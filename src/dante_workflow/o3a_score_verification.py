"""Retained native calibration/rescore gates; never scoring or preflight writes."""

from __future__ import annotations

import importlib
from pathlib import Path

from . import o3a_index_verification as index_parent
from . import o3a_native_verification as parents
from .o3a_initial_verification import (
    InitialEvidenceError,
    _Evidence,
    _clean,
    _existing,
    _json,
)


def _sources(root):
    from src.dante_light.o3a_raw_download import file_sha256

    result = index_parent._sources(root)
    for name in (
        "o3a_native_calibration_cohort",
        "o3a_native_rescore",
        "o3a_native_rescore_preflight",
    ):
        module = importlib.import_module("src.dante_light." + name)
        relative = module.__name__.replace(".", "/") + ".py"
        digest = file_sha256(Path(module.__file__))
        if file_sha256(_existing(root, relative)) != digest:
            raise InitialEvidenceError(f"executed helper source mismatch: {relative}")
        result[relative] = digest
    base = Path(__file__).resolve().parents[2]
    for relative in (
        "src/dante_workflow/o3a_score_verification.py",
        "scripts/verify_dante_o3a_score_evidence.py",
    ):
        result[relative] = file_sha256(base / relative)
    return result


def _saved(evidence, name):
    reference = evidence.inputs[name]
    return _json(evidence.read(name, Path(reference["path"]), reference["sha256"]))


def _rows(evidence, name, path, sha):
    return [
        _json(line)
        for line in evidence.read(name, path, sha).splitlines()
        if line.strip()
    ]


def _frames(root, database, evidence):
    from src.dante_light import o3a_native_calibration_cohort as calibration
    from src.dante_light.o3a_raw_acquisition import INVENTORY_REL

    inventory = calibration.load_source_inventory(root=root)
    parents._loaded(evidence, root, "score_inventory", INVENTORY_REL, inventory)
    frames = {d: calibration._inventory_frames(inventory, d) for d in ("H1", "L1")}
    return frames, parents._frame_rows(database)


def _calibration_expected(root, contract, database, cohort, evidence):
    from src.dante_light import o3a_native_calibration_cohort as calibration

    reference = evidence.inputs["cohort_ledger"]
    rows = _rows(
        evidence,
        "calibration_index_ledger",
        Path(reference["path"]),
        contract["parents"]["native_cohort"]["ledger_sha256"],
    )
    frames, raw_frames = _frames(root, database, evidence)

    def sources(detector, gps):
        return calibration._source_rows_for_context(
            detector=detector,
            gps=gps,
            frames=frames[detector],
            frame_starts=[int(frame["gps_start"]) for frame in frames[detector]],
            raw_frame_rows=raw_frames,
        )

    selection = contract["selection"]
    return calibration.select_native_calibration_rows(
        parents._identity_rows(database),
        [(str(row["detector"]), int(row["gps_start"])) for row in rows],
        target_rows=int(selection["target_rows_per_detector"]),
        block_length=int(selection["block_length_rows"]),
        window_s=int(selection["window_duration_s"]),
        stride_s=int(selection["stride_s"]),
        guard_delta_s=int(selection["candidate_and_index_guard_start_delta_s"]),
        context_sources=sources,
    )


def _calibration_gate(
    *,
    root,
    external_root,
    index_external_root,
    cohort_external_root,
    primary_external_root,
    evidence,
):
    from src.dante_light import o3a_native_calibration_cohort as calibration
    from src.dante_light.contracts import canonical_json_sha256

    contract = calibration.load_cohort_contract(root=root)
    parents._loaded(
        evidence, root, "calibration_contract", calibration.CONTRACT_REL, contract
    )
    index, index_dir = index_parent._index_gate(
        root=root,
        external_root=index_external_root,
        cohort_external_root=cohort_external_root,
        primary_external_root=primary_external_root,
        evidence=evidence,
    )
    scan, cohort = _saved(evidence, "scan_summary"), _saved(evidence, "cohort_summary")
    for name, value in (
        ("primary_scan", scan),
        ("native_cohort", cohort),
        ("native_index", index),
    ):
        if value["artifact_digest"] != contract["parents"][name]["artifact_digest"]:
            raise InitialEvidenceError(f"O3a calibration {name} parent changed")
    runtime = calibration.load_runtime_contract(root=root, require_current=True)
    parents._loaded(
        evidence, root, "runtime_contract", calibration.RUNTIME_REL, runtime
    )
    directory = calibration._run_dir(contract, root=root, external_root=external_root)
    _clean(directory)
    summary = evidence.sealed(
        "calibration_summary",
        _existing(directory, "native_calibration_summary.json"),
        "artifact_digest",
    )
    if (
        summary.get("status") != "PASS_FROZEN_O3A_NATIVE_CALIBRATION_COHORT"
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("run_key")
        != directory.name.removeprefix("native_calibration_cohort_")
        or summary.get("scores_or_classes_read") is not False
    ):
        raise InitialEvidenceError("O3a native-calibration summary is invalid")
    ledger = _existing(directory, summary["ledger"]["filename"])
    rows = _rows(evidence, "calibration_ledger", ledger, summary["ledger"]["sha256"])
    selection = contract["selection"]
    target = int(selection["target_rows_per_detector"])
    if (
        len(rows) != 2 * target
        or summary["ledger"]["row_total"] != len(rows)
        or summary["ledger"]["row_digest"] != canonical_json_sha256(rows)
        or summary["counts_by_detector"] != {"H1": target, "L1": target}
        or summary["bootstrap_rows_by_detector"]
        != {d: selection["bootstrap_rows_per_detector"] for d in ("H1", "L1")}
    ):
        raise InitialEvidenceError("O3a native-calibration cardinality changed")
    fields = {
        "detector",
        "gps_start",
        "gps_end",
        "context_sources",
        "context_sources_digest",
        "plan_priority_rank",
        "row_number",
        "bootstrap_block_index",
    }
    if any(set(row) - fields for row in rows):
        raise InitialEvidenceError(
            "O3a native-calibration ledger contains an outcome field"
        )
    database = Path(evidence.inputs["scan_database"]["path"])
    expected, audit = _calibration_expected(root, contract, database, cohort, evidence)
    if rows != expected or summary["selection_audit"] != audit:
        raise InitialEvidenceError("O3a native-calibration selection changed")
    return summary, directory, scan, index, index_dir


def _scoring_identities(database):
    from src.dante_light.contracts import ContractError

    with parents.immutable_database(database) as connection:
        records = connection.execute(
            "SELECT detector,gps_start,is_candidate,identity_digest,image_sha256 FROM windows ORDER BY detector,gps_start"
        ).fetchall()
    rows = {}
    for detector, gps, seed, identity, image in records:
        key = str(detector), int(gps)
        if (
            key in rows
            or key[0] not in {"H1", "L1"}
            or seed not in (0, 1)
            or not isinstance(identity, str)
            or len(identity) != 64
            or not isinstance(image, str)
            or len(image) != 64
        ):
            raise ContractError("O3a native-rescore scan identity ledger is invalid")
        rows[key] = {
            "detector": key[0],
            "gps_start": key[1],
            "is_candidate": bool(seed),
            "identity_digest": identity,
            "expected_image_sha256": image,
        }
    return rows


def _rescore_gate(
    *,
    root,
    external_root,
    calibration_external_root,
    index_external_root,
    cohort_external_root,
    primary_external_root,
    evidence,
):
    from src.dante_light import o3a_native_rescore as rescore
    from src.dante_light import o3a_native_rescore_preflight as work_builder
    from src.dante_light.contracts import canonical_json_sha256

    contract = rescore.load_rescore_contract(root=root)
    parents._loaded(evidence, root, "rescore_contract", rescore.CONTRACT_REL, contract)
    calibration, calibration_dir, scan, index, _index_dir = _calibration_gate(
        root=root,
        external_root=calibration_external_root,
        index_external_root=index_external_root,
        cohort_external_root=cohort_external_root,
        primary_external_root=primary_external_root,
        evidence=evidence,
    )
    runtime = rescore.load_runtime_contract(root=root, require_current=True)
    parents._loaded(
        evidence,
        root,
        "runtime_contract",
        "config/dante_o3a_native_v1_runtime.json",
        runtime,
    )
    if (
        runtime["runtime_environment"]["environment_digest"]
        != contract["parents"]["canonical_runtime"]["environment_digest"]
    ):
        raise InitialEvidenceError("O3a native-rescore runtime changed")
    digests = {}
    for name, value in (
        ("primary_scan", scan),
        ("native_index", index),
        ("native_calibration", calibration),
    ):
        if value["artifact_digest"] != contract["parents"][name]["artifact_digest"]:
            raise InitialEvidenceError("O3a native-rescore parent changed")
        digests[name] = value["artifact_digest"]
    directory = rescore._run_dir(contract, external_root)
    _clean(directory)
    preflight = evidence.sealed(
        "rescore_preflight", _existing(directory, "preflight.json"), "preflight_digest"
    )
    manifest = _existing(directory, preflight["manifest"]["filename"])
    work = _rows(
        evidence, "rescore_manifest", manifest, preflight["manifest"]["sha256"]
    )
    database = Path(evidence.inputs["scan_database"]["path"])
    reference = evidence.inputs["calibration_ledger"]
    calibration_rows = _rows(
        evidence,
        "rescore_calibration_ledger",
        Path(reference["path"]),
        reference["sha256"],
    )
    frames, raw_frames = _frames(root, database, evidence)
    expected, audit = work_builder.assemble_work_rows(
        scan_rows=_scoring_identities(database),
        calibration_rows=calibration_rows,
        frames_by_detector=frames,
        raw_frame_rows=raw_frames,
        expected_calibration_rows_by_detector=contract["population"][
            "calibration_rows_by_detector"
        ],
        bootstrap_block_length_rows=int(
            contract["population"]["bootstrap_block_length_rows"]
        ),
    )
    ordered = sorted(
        expected, key=lambda row: (row["detector"], row["gps_start"], row["population"])
    )
    population = contract["population"]
    if (
        work != ordered
        or audit["calibration_rows_by_detector"]
        != population["calibration_rows_by_detector"]
        or audit["candidate_rows_by_detector"]
        != population["candidate_rows_by_detector"]
        or audit["row_total"] != population["exact_total_rows"]
    ):
        raise InitialEvidenceError("O3a native-rescore work population changed")
    body = {
        "schema_version": rescore.SCHEMA_VERSION,
        "status": "PASS_O3A_NATIVE_RESCORE_PREFLIGHT",
        "run_key": rescore._run_key(contract),
        "contract_digest": contract["contract_digest"],
        "parent_artifact_digests": digests,
        "manifest": {
            "filename": manifest.name,
            "sha256": preflight["manifest"]["sha256"],
            "row_digest": canonical_json_sha256(ordered),
            "row_total": len(ordered),
        },
        "audit": audit,
    }
    if preflight != {**body, "preflight_digest": canonical_json_sha256(body)}:
        raise InitialEvidenceError(
            "O3a native-rescore preflight reconstruction changed"
        )
    if rescore._load_preflight(directory, contract) != (preflight, work):
        raise InitialEvidenceError("loaded rescore preflight differs from file")
    evidence.sealed(
        "rescore_cuda_preflight",
        _existing(directory, "cuda_preflight.json"),
        "cuda_preflight_digest",
    )
    if not rescore._cuda_preflight_is_valid(directory, preflight, contract):
        raise InitialEvidenceError("O3a native-rescore CUDA preflight is missing")
    batches = rescore._batch_rows(work, int(contract["execution"]["batch_size"]))
    for position in range(len(batches)):
        path = rescore._shard_path(directory, position)
        evidence.sealed(
            f"rescore_shard:{position}",
            _existing(directory, path.relative_to(directory).as_posix()),
            "shard_digest",
        )
    scored = rescore._gather_outputs(
        run_dir=directory, batches=batches, contract=contract
    )
    groups = rescore._output_groups(scored)
    summary = evidence.sealed(
        "rescore_summary",
        _existing(directory, "native_rescore_summary.json"),
        "artifact_digest",
    )
    if (
        summary.get("status") != "PASS_COMPLETE_O3A_NATIVE_RESCORE"
        or summary.get("run_key") != rescore._run_key(contract)
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("preflight_digest") != preflight["preflight_digest"]
        or summary.get("row_total") != len(scored)
        or summary.get("gates")
        != {
            "source_frame_hash_mismatches": 0,
            "context_failures": 0,
            "image_hash_mismatches": 0,
            "encoder_failures": 0,
            "nonfinite_scores": 0,
            "old_o4a_scores_or_thresholds_read": False,
            "threshold_or_class_computed": False,
        }
    ):
        raise InitialEvidenceError("O3a native-rescore summary changed")
    for name, expected_rows in groups.items():
        output = summary["outputs"].get(name)
        if not isinstance(output, dict):
            raise InitialEvidenceError(
                "O3a native-rescore output summary is incomplete"
            )
        path = _existing(directory, output["filename"])
        rows = _rows(evidence, "rescore_output:" + name, path, output["sha256"])
        if (
            path.name != f"{name}.jsonl"
            or rows != expected_rows
            or output["row_total"] != len(expected_rows)
            or output["row_digest"] != canonical_json_sha256(expected_rows)
        ):
            raise InitialEvidenceError("O3a native-rescore output ledger changed")
    cache = directory / "transient_raw"
    if cache.exists() and any(path.is_file() for path in cache.rglob("*")):
        raise InitialEvidenceError(
            "O3a native-rescore transient raw cache is not empty"
        )
    return summary, directory


def verify_score_evidence(
    *,
    root,
    external_root,
    index_external_root,
    cohort_external_root,
    primary_external_root,
    stage,
    calibration_external_root=None,
):
    from src.dante_light.contracts import canonical_json_sha256

    if stage not in {"calibration", "rescore"} or (
        stage == "rescore" and calibration_external_root is None
    ):
        raise InitialEvidenceError(
            "unsupported or incomplete native score evidence scope"
        )
    if stage == "calibration" and calibration_external_root is not None:
        raise InitialEvidenceError(
            "calibration scope does not accept an extra calibration root"
        )
    root = root.resolve()
    evidence, sources = _Evidence(), _sources(root)
    arguments = dict(
        root=root,
        external_root=external_root.resolve(),
        index_external_root=index_external_root.resolve(),
        cohort_external_root=cohort_external_root.resolve(),
        primary_external_root=primary_external_root.resolve(),
        evidence=evidence,
    )
    if stage == "calibration":
        summary, directory, *_ = _calibration_gate(**arguments)
    else:
        summary, directory = _rescore_gate(
            **arguments, calibration_external_root=calibration_external_root.resolve()
        )
    evidence.unchanged()
    for reference in evidence.inputs.values():
        if reference["path"].endswith(".sqlite"):
            parents._no_journals(Path(reference["path"]))
    for name in (
        "scan_summary",
        "cohort_summary",
        "index_summary",
        "calibration_summary",
        "rescore_summary",
    ):
        if name in evidence.inputs:
            _clean(Path(evidence.inputs[name]["path"]).parent)
    _clean(directory)
    if _sources(root) != sources:
        raise InitialEvidenceError("helper sources changed during verification")
    body = {
        "schema_version": 1,
        "status": f"PASS_O3A_READ_ONLY_{stage.upper()}_STORED_VALIDATION_ONLY",
        "verification_policy_id": "o3a-native-score-evidence-read-only-v1",
        "verification_level": "EXISTING_FROZEN_GATE_RECONSTRUCTION",
        "observing_run": "O3a",
        "stage": stage,
        "run_dir": str(directory),
        "legacy_artifact_digest": summary["artifact_digest"],
        "historical_evidence_mutated": False,
        "raw_score_replay_executed": False,
        "encoder_executed": False,
        "preprocessing_replay_executed": False,
        "threshold_fit_executed": False,
        "source_fetch_executed": False,
        "full_workflow_verified": False,
        "calibration_selection_reconstructed": True,
        "rescore_manifest_reconstructed": stage == "rescore",
        "stored_score_shards_checked": stage == "rescore",
        "stored_cuda_preflight_checked": stage == "rescore",
        "inputs": evidence.inputs,
        "source_bindings": sources,
    }
    return {**body, "receipt_digest": canonical_json_sha256(body)}
