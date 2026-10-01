"""Read-only deterministic threshold/classification replay; no history writes."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat

from . import o3a_score_verification as scores
from .o3a_initial_verification import (
    InitialEvidenceError,
    _Evidence,
    _existing,
    _reference,
)


def _fcntl():
    try:
        import fcntl
    except ImportError as error:
        raise InitialEvidenceError(
            "read-only persistent locks require POSIX/WSL"
        ) from error
    return fcntl


def _signature(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _stage_clean(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise InitialEvidenceError("missing or unsafe decision run directory")
    for name in ("failure.json", "failures.json", "controller.lock"):
        if (directory / name).exists() or (directory / name).is_symlink():
            raise InitialEvidenceError(f"failure/active evidence present: {name}")
    if any(
        p.name.endswith((".part", ".partial", ".tmp")) for p in directory.rglob("*")
    ):
        raise InitialEvidenceError("partial decision evidence present")


@contextmanager
def _persistent_lock(directory):
    """Hold the original flock protocol on an existing O_RDONLY regular inode."""
    fcntl = _fcntl()
    _stage_clean(directory)
    path = directory / "run.lock"
    descriptor, held = None, False
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise InitialEvidenceError("unsafe persistent lock file")
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        )
        opened = os.fstat(descriptor)
        if _signature(opened) != _signature(before) or opened.st_nlink != 1:
            raise InitialEvidenceError("persistent lock replaced during open")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held = True
        if _signature(path.lstat()) != _signature(opened):
            raise InitialEvidenceError("persistent lock replaced during acquisition")
        yield
        _stage_clean(directory)
        if (
            _signature(path.lstat()) != _signature(opened)
            or _signature(os.fstat(descriptor)) != _signature(opened)
            or os.fstat(descriptor).st_nlink != 1
        ):
            raise InitialEvidenceError("persistent lock changed during verification")
    except OSError as error:
        raise InitialEvidenceError(
            "persistent lock missing, busy or unsupported"
        ) from error
    finally:
        try:
            if held:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            if descriptor is not None:
                os.close(descriptor)


def _sources(root):
    from src.dante_light.o3a_raw_download import file_sha256

    result = scores._sources(root)
    for name in (
        "src.dante_light.o3a_native_thresholds",
        "src.dante_light.o3a_native_classification",
        "src.pipeline_v2_production.background_calibration",
    ):
        module = importlib.import_module(name)
        relative = name.replace(".", "/") + ".py"
        digest = file_sha256(Path(module.__file__))
        if file_sha256(_existing(root, relative)) != digest:
            raise InitialEvidenceError(f"executed helper source mismatch: {relative}")
        result[relative] = digest
    base = Path(__file__).resolve().parents[2]
    for relative in (
        "src/dante_workflow/o3a_decision_verification.py",
        "scripts/verify_dante_o3a_decision_evidence.py",
    ):
        result[relative] = file_sha256(base / relative)
    return result


def _contract(evidence, root, name, relative, value):
    scores.parents._loaded(evidence, root, name, relative, value)
    for field in ("references", "implementation_sources"):
        for reference, sha in value[field].items():
            evidence.read(name + ":" + reference, _existing(root, reference), sha)


def _compact(evidence, root, relative, name, summary, directory, status):
    from src.dante_light.contracts import canonical_json_sha256

    compact = evidence.sealed(name, _existing(root, relative), "artifact_digest")
    summary_path = Path(evidence.inputs[name.replace("compact", "summary")]["path"])
    if _reference(compact["external_run_dir_wsl"]) != directory.resolve():
        raise InitialEvidenceError("decision compact run reference changed")
    body = dict(summary)
    digest = body.pop("artifact_digest")
    body.update(
        status=status,
        external_run_dir_wsl=compact["external_run_dir_wsl"],
        run_artifact_digest=digest,
        summary_sha256=evidence.inputs[name.replace("compact", "summary")]["sha256"],
    )
    if compact != {**body, "artifact_digest": canonical_json_sha256(body)}:
        raise InitialEvidenceError("decision compact reconstruction changed")
    if summary_path.parent.resolve() != directory.resolve():
        raise InitialEvidenceError("decision summary directory changed")
    return compact


def _threshold_gate(*, root, external_root, parent_arguments, evidence, stack):
    from src.dante_light import o3a_native_thresholds as nt
    from src.dante_light.contracts import canonical_json_sha256

    contract = nt.load_threshold_contract(root=root)
    _contract(evidence, root, "threshold_contract", nt.CONTRACT_REL, contract)
    directory = nt._run_dir(contract, external_root)
    stack.enter_context(_persistent_lock(directory))
    evidence.read("threshold_lock", directory / "run.lock")
    saved = evidence.sealed(
        "threshold_summary",
        _existing(directory, contract["output"]["summary_filename"]),
        "artifact_digest",
    )
    from .o3a_retained_runtime import load_runtime

    runtime = load_runtime(evidence, nt.load_runtime_contract, root=root)
    scores.parents._loaded(evidence, root, "runtime_contract", nt.RUNTIME_REL, runtime)
    parent, parent_dir = scores._rescore_gate(
        root=root, evidence=evidence, **parent_arguments
    )
    declared = contract["parent_rescore"]
    if any(
        parent[k] != declared[k]
        for k in ("artifact_digest", "run_key", "contract_digest")
    ):
        raise InitialEvidenceError("threshold verified RESCORE parent changed")
    inputs, thresholds = {}, {}
    population = contract["population"]
    for detector, count in sorted(population["rows_by_detector"].items()):
        name = "native_calibration_" + detector
        meta = parent["outputs"][name]
        if meta["filename"] != name + ".jsonl":
            raise InitialEvidenceError("threshold calibration filename changed")
        path = _existing(parent_dir, meta["filename"])
        rows = scores._rows(
            evidence,
            "threshold_input:" + detector,
            path,
            declared["output_sha256"][name],
        )
        vector, audit = nt.validate_score_rows(
            rows,
            detector=detector,
            count=count,
            block_length=contract["method"]["block_length"],
            stride=population["within_block_stride_s"],
        )
        inputs[detector] = {
            **audit,
            "sha256": evidence.inputs["threshold_input:" + detector]["sha256"],
            "row_digest": meta["row_digest"],
        }
        thresholds[detector] = nt.compute_threshold(vector, method=contract["method"])
        if (
            thresholds[detector]["n_bootstrap_rows"]
            != population["bootstrap_rows_per_detector"]
        ):
            raise InitialEvidenceError("threshold bootstrap population changed")
    body = {
        "schema_version": 1,
        "status": "PASS_COMPLETE_O3A_NATIVE_THRESHOLDS",
        "contract_digest": contract["contract_digest"],
        "run_key": directory.name.removeprefix("native_thresholds_"),
        "native_rescore_artifact_digest": parent["artifact_digest"],
        "runtime_environment_digest": runtime["runtime_environment"][
            "environment_digest"
        ],
        "inputs": inputs,
        "method": contract["method"],
        "thresholds": thresholds,
        "scientific_boundary": contract["scientific_boundary"],
    }
    expected = {**body, "artifact_digest": canonical_json_sha256(body)}
    if saved != expected:
        raise InitialEvidenceError("threshold deterministic replay changed")
    compact = _compact(
        evidence,
        root,
        nt.COMPACT_REL,
        "threshold_compact",
        saved,
        directory,
        "PASS_VERIFIED_O3A_NATIVE_THRESHOLDS",
    )
    return saved, directory, compact, parent, parent_dir


def _classification_gate(
    *, root, external_root, threshold_external_root, parent_arguments, evidence, stack
):
    from src.dante_light import o3a_native_classification as nc
    from src.dante_light.contracts import canonical_json_sha256

    contract = nc.load_contract(root=root)
    _contract(evidence, root, "classification_contract", nc.CONTRACT_REL, contract)
    directory = nc._run_dir(contract, external_root)
    stack.enter_context(_persistent_lock(directory))
    evidence.read("classification_lock", directory / "run.lock")
    saved = evidence.sealed(
        "classification_summary",
        _existing(directory, contract["output"]["summary_filename"]),
        "artifact_digest",
    )
    threshold, _threshold_dir, compact, parent, parent_dir = _threshold_gate(
        root=root,
        external_root=threshold_external_root,
        parent_arguments=parent_arguments,
        evidence=evidence,
        stack=stack,
    )
    if (
        any(
            compact[k] != contract["threshold_parent"][k]
            for k in (
                "artifact_digest",
                "run_artifact_digest",
                "contract_digest",
                "run_key",
            )
        )
        or threshold["native_rescore_artifact_digest"]
        != contract["rescore_parent"]["artifact_digest"]
        or any(
            parent[k] != contract["rescore_parent"][k]
            for k in ("artifact_digest", "contract_digest", "run_key")
        )
    ):
        raise InitialEvidenceError("classification verified parent changed")
    meta = parent["outputs"]["primary_candidate"]
    if meta["filename"] != "primary_candidate.jsonl":
        raise InitialEvidenceError("classification candidate filename changed")
    source = _existing(parent_dir, meta["filename"])
    rows = scores._rows(
        evidence,
        "classification_input",
        source,
        contract["rescore_parent"]["output_sha256"]["primary_candidate"],
    )
    classified, counts = nc.classify_rows(
        rows,
        thresholds=threshold["thresholds"],
        expected_counts=contract["population"]["rows_by_detector"],
    )
    payload = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        for row in classified
    ).encode("utf-8")
    expected_sha = hashlib.sha256(payload).hexdigest()
    output = _existing(directory, contract["output"]["candidate_filename"])
    if evidence.read("classification_output", output, expected_sha) != payload:
        raise InitialEvidenceError("classification output replay changed")
    body = {
        "schema_version": 1,
        "status": "PASS_COMPLETE_O3A_NATIVE_CLASSIFICATION",
        "contract_digest": contract["contract_digest"],
        "run_key": directory.name.removeprefix("native_classification_"),
        "threshold_artifact_digest": threshold["artifact_digest"],
        "runtime_environment_digest": threshold["runtime_environment_digest"],
        "rescore_artifact_digest": contract["rescore_parent"]["artifact_digest"],
        "rule": contract["rule"],
        "row_total": len(classified),
        "counts_by_detector_and_class": counts,
        "source_sha256": evidence.inputs["classification_input"]["sha256"],
        "output_sha256": expected_sha,
        "output_row_digest": canonical_json_sha256(classified),
        "scientific_boundary": contract["scientific_boundary"],
    }
    if saved != {**body, "artifact_digest": canonical_json_sha256(body)}:
        raise InitialEvidenceError("classification deterministic replay changed")
    _compact(
        evidence,
        root,
        nc.COMPACT_REL,
        "classification_compact",
        saved,
        directory,
        "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION",
    )
    return saved, directory


def verify_decision_evidence(
    *,
    root,
    external_root,
    rescore_external_root,
    calibration_external_root,
    index_external_root,
    cohort_external_root,
    primary_external_root,
    stage,
    threshold_external_root=None,
):
    from src.dante_light.contracts import canonical_json_sha256

    if (
        stage not in {"thresholds", "classification"}
        or (stage == "classification" and threshold_external_root is None)
        or (stage == "thresholds" and threshold_external_root is not None)
    ):
        raise InitialEvidenceError("unsupported or incomplete decision evidence scope")
    _fcntl()
    root = root.resolve()
    sources_before, evidence = _sources(root), _Evidence()
    parent_arguments = {
        "external_root": rescore_external_root.resolve(),
        "calibration_external_root": calibration_external_root.resolve(),
        "index_external_root": index_external_root.resolve(),
        "cohort_external_root": cohort_external_root.resolve(),
        "primary_external_root": primary_external_root.resolve(),
    }
    with ExitStack() as stack:
        arguments = dict(
            root=root,
            external_root=external_root.resolve(),
            parent_arguments=parent_arguments,
            evidence=evidence,
            stack=stack,
        )
        if stage == "thresholds":
            summary, directory, *_ = _threshold_gate(**arguments)
        else:
            summary, directory = _classification_gate(
                **arguments, threshold_external_root=threshold_external_root.resolve()
            )
        evidence.unchanged()
        for name in (
            "scan_summary",
            "cohort_summary",
            "index_summary",
            "calibration_summary",
            "rescore_summary",
        ):
            if name in evidence.inputs:
                scores._clean(Path(evidence.inputs[name]["path"]).parent)
        for reference in evidence.inputs.values():
            if reference["path"].endswith(".sqlite"):
                scores.parents._no_journals(Path(reference["path"]))
        if _sources(root) != sources_before:
            raise InitialEvidenceError("helper sources changed during verification")
        body = {
            "schema_version": 1,
            "status": f"PASS_O3A_READ_ONLY_{stage.upper()}_DETERMINISTIC_REPLAY_ONLY",
            "verification_policy_id": "o3a-native-decision-evidence-read-only-v1",
            "verification_level": "EXISTING_FROZEN_GATE_RECONSTRUCTION",
            "observing_run": "O3a",
            "stage": stage,
            "run_dir": str(directory),
            "legacy_artifact_digest": summary["artifact_digest"],
            "historical_evidence_mutated": False,
            "raw_score_replay_executed": False,
            "encoder_executed": False,
            "preprocessing_replay_executed": False,
            "source_fetch_executed": False,
            "full_workflow_verified": False,
            "threshold_bootstrap_replay_executed": True,
            "classification_replay_executed": stage == "classification",
            "persistent_lock_policy": "EXISTING_READ_ONLY_NONBLOCKING_EXCLUSIVE_FLOCK",
            "global_upstream_quiescence_verified": False,
            "inputs": evidence.inputs,
            "source_bindings": sources_before,
        }
        result = {**body, "receipt_digest": canonical_json_sha256(body)}
    return result
