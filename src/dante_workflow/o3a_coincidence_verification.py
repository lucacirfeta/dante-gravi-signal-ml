"""Frozen retained coincidence ledgers, read-only; never a raw correlation replay."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import importlib
import json
from pathlib import Path

from . import o3a_taxonomy_verification as taxonomy
from .o3a_retained_runtime import load_runtime, new_evidence, receipt_fields
from .o3a_locking import clean_native_parent
from .o3a_scan_copy_admission import scan_database_filename
from .o3a_initial_verification import (
    InitialEvidenceError,
    _existing,
    _reference,
)

decisions = taxonomy.decisions


def _sources(root):
    from src.dante_light.o3a_raw_download import file_sha256

    result = taxonomy._sources(root)
    for name in (
        "src.dante_light.o3a_native_coincidence",
        "src.dante_light.o4a_corrected_native_coincidence",
        "src.pipeline_v2_production.coincidence_physical",
    ):
        module = importlib.import_module(name)
        relative = name.replace(".", "/") + ".py"
        digest = file_sha256(Path(module.__file__))
        if file_sha256(_existing(root, relative)) != digest:
            raise InitialEvidenceError(f"executed helper source mismatch: {relative}")
        result[relative] = digest
    base = Path(__file__).resolve().parents[2]
    for relative in (
        "src/dante_workflow/o3a_coincidence_verification.py",
        "scripts/verify_dante_o3a_coincidence_evidence.py",
    ):
        result[relative] = file_sha256(base / relative)
    return result


def _empty_cache(directory):
    if any(
        p.is_file() or p.is_symlink() for p in (directory / "transient_raw").rglob("*")
    ):
        raise InitialEvidenceError("coincidence transient raw cache is not empty")
    if (directory / "transient_raw").is_symlink():
        raise InitialEvidenceError("unsafe coincidence transient cache")


def _preflight(root, contract, evidence):
    from src.dante_light import o3a_native_classification as nc
    from src.dante_light import o3a_native_coincidence as coincidence
    from src.dante_light.contracts import canonical_json_sha256

    classified = decisions.scores._saved(evidence, "classification_summary")
    primary = decisions.scores._saved(evidence, "scan_summary")
    class_contract = nc.load_contract(root=root)
    decisions._contract(
        evidence, root, "classification_contract", nc.CONTRACT_REL, class_contract
    )
    class_directory = Path(evidence.inputs["classification_summary"]["path"]).parent
    rows = decisions.scores._rows(
        evidence,
        "coincidence_classified_input",
        _existing(class_directory, class_contract["output"]["candidate_filename"]),
        classified["output_sha256"],
    )
    if canonical_json_sha256(rows) != classified["output_row_digest"]:
        raise InitialEvidenceError("coincidence classified row digest changed")
    primary_seeds, diagnostic_seeds = coincidence.split_seed_populations(
        rows, contract=contract
    )
    seeds = coincidence._ordered_measurement_seeds(primary_seeds, diagnostic_seeds)
    database = Path(evidence.inputs["scan_database"]["path"])
    if (
        scan_database_filename(evidence, database) != primary["database"]["filename"]
        or evidence.inputs["scan_database"]["sha256"] != primary["database"]["sha256"]
    ):
        raise InitialEvidenceError("coincidence database binding changed")
    frames, ledger = decisions.scores._frames(root, database, evidence)
    inventory = decisions.scores._saved(evidence, "score_inventory")
    measurement = contract["measurement"]
    plans, audit = coincidence.plan_sources(
        seeds,
        frames_by_detector=frames,
        raw_frame_ledger=ledger,
        pad=int(measurement["whitening_pad_s"]),
        duration=int(measurement["segment_duration_s"]),
    )
    body = {
        "schema_version": 2,
        "status": "PASS_O3A_COINCIDENCE_SOURCE_PREFLIGHT",
        "contract_digest": contract["contract_digest"],
        "source_classification_sha256": classified["output_sha256"],
        "source_scan_database_sha256": primary["database"]["sha256"],
        "source_inventory_digest": inventory["inventory_digest"],
        "seed_population_digest": canonical_json_sha256(seeds),
        "source_plan_digest": canonical_json_sha256(plans),
        "source_audit": audit,
    }
    return {**body, "preflight_digest": canonical_json_sha256(body)}, plans, seeds


def _coincidence_gate(
    *,
    root,
    external_root,
    taxonomy_external_root,
    classification_external_root,
    threshold_external_root,
    parent_arguments,
    evidence,
    stack,
):
    from src.dante_light import o3a_native_coincidence as coincidence
    from src.dante_light.contracts import canonical_json_sha256

    contract = coincidence.load_contract(root=root)
    decisions.scores.parents._loaded(
        evidence, root, "coincidence_contract", coincidence.CONTRACT_REL, contract
    )
    for name, binding in contract["parents"].items():
        evidence.read(
            "coincidence_parent:" + name,
            _existing(root, binding["path"]),
            binding["sha256"],
        )
        if "artifact_digest" in binding:
            value = evidence.sealed(
                "coincidence_parent:" + name,
                _existing(root, binding["path"]),
                "artifact_digest",
                binding["sha256"],
            )
            if value["artifact_digest"] != binding["artifact_digest"]:
                raise InitialEvidenceError("coincidence parent seal changed")
    for path, digest in contract["implementation_sources"].items():
        evidence.read("coincidence_source:" + path, _existing(root, path), digest)
    runtime = load_runtime(evidence, coincidence.load_runtime_contract, root=root)
    decisions.scores.parents._loaded(
        evidence, root, "runtime_contract", coincidence.RUNTIME_REL, runtime
    )
    if (
        runtime["runtime_environment"]["environment_digest"]
        != contract["runtime_environment_digest"]
    ):
        raise InitialEvidenceError("coincidence canonical runtime changed")
    # Parent gate acquires taxonomy/classification/threshold locks before exposing
    # retained rows. No legacy productive verifier is called.
    taxonomy._taxonomy_gate(
        root=root,
        external_root=taxonomy_external_root,
        classification_external_root=classification_external_root,
        threshold_external_root=threshold_external_root,
        parent_arguments=parent_arguments,
        evidence=evidence,
        stack=stack,
    )
    preflight, plans, seeds = _preflight(root, contract, evidence)
    key = coincidence._run_key(contract, preflight)
    directory = external_root / ("native_coincidence_" + key)
    stack.enter_context(decisions._persistent_lock(directory))
    evidence.read("coincidence_lock", directory / "run.lock")
    if (
        evidence.sealed(
            "coincidence_preflight",
            _existing(directory, "preflight.json"),
            "preflight_digest",
        )
        != preflight
    ):
        raise InitialEvidenceError("coincidence preflight replay changed")
    evidence.sealed(
        "coincidence_new_sources",
        _existing(directory, "new_source_frame_receipt.json"),
        "receipt_digest",
    )
    new_source = coincidence._pin_new_frames(
        plans, run_dir=directory, contract=contract, allow_download=False
    )
    _empty_cache(directory)
    batches = coincidence._batch_seed_rows(
        seeds, int(contract["execution"]["batch_size"])
    )
    plan_map = {(p["detector"], p["gps_start"]): p for p in plans}
    plan_batches = [coincidence._batch_plan_rows(batch, plan_map) for batch in batches]
    last_use, sources = coincidence._frame_dependency_order(plan_batches)
    cache_plan = coincidence._cache_plan(
        plan_batches=plan_batches,
        last_use=last_use,
        sources=sources,
        initially_cached={tuple(k.split("|", 1)) for k in new_source["frames"]},
        contract=contract,
        source_plan_pinned_digest=canonical_json_sha256(plans),
        ordered_seed_digest=preflight["seed_population_digest"],
    )
    if (
        cache_plan["status"] != "PASS_O3A_COINCIDENCE_CACHE_PLAN"
        or evidence.sealed(
            "coincidence_cache_plan",
            _existing(directory, "cache_plan.json"),
            "cache_plan_digest",
        )
        != cache_plan
    ):
        raise InitialEvidenceError("coincidence cache plan replay changed")
    for number in range(len(batches)):
        evidence.sealed(
            "coincidence_shard:" + str(number),
            _existing(directory, f"event_shards/batch_{number:05d}.json"),
            "shard_digest",
        )
    primary, diagnostic = coincidence._aggregate_shards(
        run_dir=directory, seed_batches=batches, contract=contract, run_key=key
    )
    events, primary, diagnostic = coincidence._event_summary(
        primary, diagnostic, contract
    )
    raw_receipt = coincidence._raw_receipt(plans)
    outputs = {}
    for name, rows, filename in (
        ("primary", primary, "native_coincidence_robust.jsonl"),
        ("diagnostic", diagnostic, "native_coincidence_ambiguous.jsonl"),
        ("raw_source_receipt", raw_receipt, "raw_source_receipt.jsonl"),
    ):
        payload = "".join(
            json.dumps(r, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for r in rows
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        if (
            evidence.read(
                "coincidence_output:" + name, _existing(directory, filename), digest
            )
            != payload
        ):
            raise InitialEvidenceError("coincidence output replay changed")
        outputs[name] = {
            "filename": filename,
            "row_total": len(rows),
            "sha256": digest,
            "row_digest": canonical_json_sha256(rows),
        }
    body = {
        "schema_version": 2,
        "status": "PASS_COMPLETE_O3A_NATIVE_COINCIDENCE",
        "run_key": key,
        "contract_digest": contract["contract_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "source_plan_pinned_digest": canonical_json_sha256(plans),
        "cache_plan_digest": cache_plan["cache_plan_digest"],
        "runtime_environment_digest": contract["runtime_environment_digest"],
        "population": contract["population"],
        "measurement": contract["measurement"],
        "pre_registered_limitation": contract["pre_registered_limitation"],
        "event_summary": events,
        "outputs": outputs,
        "gates": {
            "duplicate_seed_detector_gps": 0,
            "partner_class_reads": 0,
            "background_measurements": 0,
            "seed_image_or_score_mismatches": 0,
            "unaccounted_seeds": 0,
            "transient_cache_empty": True,
        },
    }
    saved = evidence.sealed(
        "coincidence_summary",
        _existing(directory, "native_coincidence_summary.json"),
        "artifact_digest",
    )
    if saved != {**body, "artifact_digest": canonical_json_sha256(body)}:
        raise InitialEvidenceError("coincidence full summary replay changed")
    compact = evidence.sealed(
        "coincidence_compact",
        _existing(root, coincidence.COMPACT_REL),
        "artifact_digest",
    )
    if _reference(compact["external_run_dir_wsl"]) != directory.resolve():
        raise InitialEvidenceError("coincidence compact run reference changed")
    body = {
        "schema_version": 2,
        "status": "PASS_VERIFIED_O3A_NATIVE_COINCIDENCE",
        "contract_digest": contract["contract_digest"],
        "run_key": key,
        "run_artifact_digest": saved["artifact_digest"],
        "cache_plan_digest": cache_plan["cache_plan_digest"],
        "summary_sha256": evidence.inputs["coincidence_summary"]["sha256"],
        "external_run_dir_wsl": compact["external_run_dir_wsl"],
        "event_summary": events,
        "outputs": outputs,
        "scientific_boundary": contract["scientific_boundary"],
        "pre_registered_limitation": contract["pre_registered_limitation"],
    }
    if compact != {**body, "artifact_digest": canonical_json_sha256(body)}:
        raise InitialEvidenceError("coincidence compact replay changed")
    return saved, directory


def verify_coincidence_evidence(
    *,
    root,
    external_root,
    taxonomy_external_root,
    classification_external_root,
    threshold_external_root,
    rescore_external_root,
    calibration_external_root,
    index_external_root,
    cohort_external_root,
    primary_external_root,
    allow_retained_driver_drift=False,
    scan_copy_dir=None,
    expected_scan_copy_receipt_sha256=None,
):
    from src.dante_light.contracts import canonical_json_sha256

    decisions._fcntl()
    root = root.resolve()
    sources_before = _sources(root)
    evidence = new_evidence(
        root,
        allow_retained_driver_drift=allow_retained_driver_drift,
        scan_copy_dir=scan_copy_dir,
        expected_scan_copy_receipt_sha256=expected_scan_copy_receipt_sha256,
    )
    parent_arguments = {
        "external_root": rescore_external_root.resolve(),
        "calibration_external_root": calibration_external_root.resolve(),
        "index_external_root": index_external_root.resolve(),
        "cohort_external_root": cohort_external_root.resolve(),
        "primary_external_root": primary_external_root.resolve(),
    }
    with ExitStack() as stack:
        summary, directory = _coincidence_gate(
            root=root,
            external_root=external_root.resolve(),
            taxonomy_external_root=taxonomy_external_root.resolve(),
            classification_external_root=classification_external_root.resolve(),
            threshold_external_root=threshold_external_root.resolve(),
            parent_arguments=parent_arguments,
            evidence=evidence,
            stack=stack,
        )
        evidence.unchanged()
        _empty_cache(directory)
        for name in (
            "scan_summary",
            "cohort_summary",
            "index_summary",
            "calibration_summary",
            "rescore_summary",
        ):
            if name in evidence.inputs:
                clean_native_parent(
                    Path(evidence.inputs[name]["path"]).parent, stack=stack
                )
        for reference in evidence.inputs.values():
            if reference["path"].endswith(".sqlite"):
                decisions.scores.parents._no_journals(Path(reference["path"]))
        if _sources(root) != sources_before:
            raise InitialEvidenceError("helper sources changed during verification")
        body = {
            "schema_version": 1,
            "status": "PASS_O3A_READ_ONLY_COINCIDENCE_RETAINED_LEDGER_REPLAY_ONLY",
            "verification_policy_id": "o3a-native-coincidence-evidence-read-only-v1",
            "verification_level": "EXISTING_FROZEN_GATE_RECONSTRUCTION",
            "observing_run": "O3a",
            "stage": "coincidence",
            "run_dir": str(directory),
            "legacy_artifact_digest": summary["artifact_digest"],
            "historical_evidence_mutated": False,
            "raw_score_replay_executed": False,
            "raw_correlation_replay_executed": False,
            "encoder_executed": False,
            "preprocessing_replay_executed": False,
            "source_fetch_executed": False,
            "full_workflow_verified": False,
            "global_upstream_quiescence_verified": False,
            "threshold_bootstrap_replay_executed": True,
            "classification_replay_executed": True,
            "taxonomy_replay_executed": True,
            "retained_null_ledger_replay_executed": True,
            "persistent_lock_policy": "EXISTING_READ_ONLY_NONBLOCKING_EXCLUSIVE_FLOCK",
            "inputs": evidence.inputs,
            "source_bindings": sources_before,
            **receipt_fields(evidence),
        }
        result = {**body, "receipt_digest": canonical_json_sha256(body)}
    return result
