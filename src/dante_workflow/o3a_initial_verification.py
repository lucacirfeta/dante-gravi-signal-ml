"""Read-only historical O3a input checks; never a raw/encoder score replay.

The existing acceptance/threshold contracts anchor historical evidence. These
checks are intentionally not registered as scientific workflow stage verifiers.
They return scoped receipts only; callers own any NEW workflow output storage.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
from typing import Any


class InitialEvidenceError(ValueError):
    """Missing, divergent or unsafe historical evidence (no repair attempted)."""


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise InitialEvidenceError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _json(payload: bytes) -> dict:
    def invalid(value):
        raise InitialEvidenceError(f"non-finite JSON: {value}")

    value = json.loads(payload, object_pairs_hook=_object, parse_constant=invalid)
    if not isinstance(value, dict):
        raise InitialEvidenceError("evidence must be a JSON object")
    return value


def _existing(base: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise InitialEvidenceError("empty evidence path")
    portable = PureWindowsPath(relative)
    path = Path(relative)
    if portable.drive or portable.is_absolute() or path.is_absolute():
        raise InitialEvidenceError("expected relative evidence path")
    if ".." in portable.parts or "\\" in relative:
        raise InitialEvidenceError("unsafe evidence path")
    base = base.resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise InitialEvidenceError(f"missing or escaping evidence: {relative}")
    return target


def _reference(value: str) -> Path:
    """Translate drive/mount syntax only, never rebase a sealed reference."""
    if not isinstance(value, str):
        raise InitialEvidenceError("invalid absolute reference")
    if re.match(r"^[A-Za-z]:[/\\]", value):
        path = PureWindowsPath(value)
        if os.name == "nt":
            return Path(path).resolve()
        return (Path("/mnt") / path.drive[0].lower() / Path(*path.parts[1:])).resolve()
    mount = re.fullmatch(r"/mnt/([a-zA-Z])/(.*)", value)
    if mount and os.name == "nt":
        return Path(f"{mount[1]}:/" + mount[2]).resolve()
    path = Path(value)
    if not path.is_absolute():
        raise InitialEvidenceError("sealed reference must be absolute")
    return path.resolve()


class _Evidence:
    def __init__(self):
        self.inputs: dict[str, dict[str, str]] = {}

    def read(self, name: str, path: Path, sha256: str | None = None) -> bytes:
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if sha256 is not None and digest != sha256:
            raise InitialEvidenceError(f"evidence hash mismatch: {name}")
        self.inputs[name] = {"path": str(path), "sha256": digest}
        return payload

    def sealed(self, name: str, path: Path, seal: str, sha256=None) -> dict:
        from src.dante_light.contracts import canonical_json_sha256

        value = _json(self.read(name, path, sha256))
        body = dict(value)
        declared = body.pop(seal, None)
        if declared != canonical_json_sha256(body):
            raise InitialEvidenceError(f"evidence seal mismatch: {name}")
        return value

    def unchanged(self):
        from src.dante_light.o3a_raw_download import file_sha256

        for name, reference in self.inputs.items():
            if file_sha256(Path(reference["path"])) != reference["sha256"]:
                raise InitialEvidenceError(
                    f"evidence changed during verification: {name}"
                )


def _clean(directory: Path):
    if not directory.is_dir():
        raise InitialEvidenceError("historical run directory missing")
    for name in ("failure.json", "failures.json", "controller.lock", "run.lock"):
        if (directory / name).exists():
            raise InitialEvidenceError(f"failure/lock evidence present: {name}")
    if any(
        p.name.endswith((".part", ".partial", ".tmp")) for p in directory.rglob("*")
    ):
        raise InitialEvidenceError("partial evidence present")


def _sources(root: Path) -> dict[str, str]:
    from src.dante_light import (
        contracts,
        o3a_initial_calibration,
        o3a_initial_thresholds,
    )
    from src.dante_light import o3a_initial_calibration_acceptance, o3a_raw_acquisition
    from src.dante_light import o3a_raw_download
    from src.dante_light import (
        o3a_native_contract,
        o3a_population_geometry,
        o3a_scale_adequacy,
    )

    sources = {}
    for module in (
        contracts,
        o3a_initial_calibration,
        o3a_initial_thresholds,
        o3a_initial_calibration_acceptance,
        o3a_raw_acquisition,
        o3a_raw_download,
        o3a_native_contract,
        o3a_population_geometry,
        o3a_scale_adequacy,
    ):
        relative = module.__name__.replace(".", "/") + ".py"
        digest = o3a_raw_download.file_sha256(Path(module.__file__))
        if o3a_raw_download.file_sha256(_existing(root, relative)) != digest:
            raise InitialEvidenceError(f"executed helper source mismatch: {relative}")
        sources[relative] = digest
    sources["src/dante_workflow/o3a_initial_verification.py"] = (
        o3a_raw_download.file_sha256(Path(__file__))
    )
    entry = (
        Path(__file__).resolve().parents[2]
        / "scripts/verify_dante_o3a_initial_evidence.py"
    )
    sources["scripts/verify_dante_o3a_initial_evidence.py"] = (
        o3a_raw_download.file_sha256(entry)
    )
    return sources


def _loaded(evidence: _Evidence, root: Path, name: str, relative: str, value: dict):
    if _json(evidence.read(name, _existing(root, relative))) != value:
        raise InitialEvidenceError(f"loaded contract differs from file: {name}")


def _raw_context(root: Path, raw_root: Path, evidence: _Evidence):
    from src.dante_light import o3a_initial_calibration_acceptance as acceptance
    from src.dante_light import o3a_raw_download as raw

    contract = acceptance.load_acceptance_contract(root=root)
    _loaded(evidence, root, "acceptance_contract", acceptance.CONTRACT_REL, contract)
    plan = raw.load_acquisition_plan(root=root)
    _loaded(evidence, root, "acquisition_plan", raw.ACQUISITION_REL, plan)
    key = raw._run_key(plan, root)
    directory = raw_root / "runs" / f"raw_download_{key}"
    _clean(directory)
    parent = contract["verified_raw_input"]
    summary_path = _existing(directory, "summary.json")
    if (
        _reference(parent["download_summary_path"]) != summary_path
        or parent["download_run_key"] != key
    ):
        raise InitialEvidenceError("raw parent path/run identity mismatch")
    summary = evidence.sealed(
        "raw_summary",
        summary_path,
        "artifact_digest",
        parent["download_summary_sha256"],
    )
    if summary["artifact_digest"] != parent["download_artifact_digest"]:
        raise InitialEvidenceError("raw parent artifact mismatch")
    preflight = evidence.sealed(
        "raw_preflight", _existing(directory, "preflight.json"), "preflight_digest"
    )
    frames = raw._all_frames(plan)
    if (
        preflight.get("status") != "PASS_O3A_RAW_DOWNLOAD_PREFLIGHT"
        or preflight.get("run_key") != key
        or preflight.get("acquisition_digest") != plan["acquisition_digest"]
        or preflight.get("acquisition_file_sha256")
        != evidence.inputs["acquisition_plan"]["sha256"]
        or preflight.get("implementation_sources") != raw._source_hashes(root)
        or _reference(preflight["raw_root"]) != raw_root
        or preflight.get("expected_file_count") != len(frames)
    ):
        raise InitialEvidenceError("raw preflight identity mismatch")
    sizes = {
        (row["detector"], row["filename"]): int(row["content_length_bytes"])
        for row in preflight["source_metadata"]
    }
    if len(sizes) != len(preflight["source_metadata"]) or set(sizes) != {
        (r["detector"], r["filename"]) for r in frames
    }:
        raise InitialEvidenceError("raw preflight source population mismatch")
    if any(size <= 0 for size in sizes.values()) or preflight[
        "expected_download_bytes"
    ] != sum(sizes.values()):
        raise InitialEvidenceError("raw preflight size mismatch")
    ledger_path = _existing(directory, "verified_files.jsonl")
    manifest_path = _existing(raw_root, parent["manifest_relative_to_raw_root"])
    for path, declaration in (
        (ledger_path, summary["verified_ledger"]),
        (manifest_path, summary["raw_manifest"]),
    ):
        if _reference(declaration["path"]) != path:
            raise InitialEvidenceError("raw ledger/manifest path mismatch")
    records = [
        _json(line)
        for line in evidence.read(
            "raw_ledger", ledger_path, summary["verified_ledger"]["sha256"]
        ).splitlines()
        if line
    ]
    manifest = evidence.read("raw_manifest", manifest_path, parent["manifest_sha256"])
    if evidence.inputs["raw_manifest"]["sha256"] != summary["raw_manifest"]["sha256"]:
        raise InitialEvidenceError("raw manifest parent mismatch")
    if len(records) != len(frames) or parent["verified_file_count"] != len(frames):
        raise InitialEvidenceError("raw ledger cardinality mismatch")
    for item, record in zip(frames, records):
        digest = record.get("sha256", "")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise InitialEvidenceError("raw file digest invalid")
        expected = {
            **raw._record_base(item),
            "sample_rate_hz": contract["method_parity"]["sample_rate_hz"],
            "sample_count": int(item["duration_s"])
            * int(contract["method_parity"]["sample_rate_hz"]),
            "metadata_only_validation": True,
            "size_bytes": sizes[item["detector"], item["filename"]],
            "sha256": digest,
        }
        if record != expected:
            raise InitialEvidenceError("raw record identity/metadata mismatch")
    if manifest != _jsonl_bytes(raw.build_raw_manifest_rows(records)):
        raise InitialEvidenceError("raw manifest reconstruction mismatch")
    body = {
        "schema_version": raw.SCHEMA_VERSION,
        "status": "PASS_VERIFIED_RAW_DOWNLOAD",
        "run_key": key,
        "acquisition_digest": plan["acquisition_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "expected_file_count": len(frames),
        "verified_file_count": len(records),
        "failure_count": 0,
        "failures": [],
        "verified_ledger": summary["verified_ledger"],
        "raw_manifest": summary["raw_manifest"],
        "strain_values_inspected": False,
        "scoring_executed": False,
    }
    from src.dante_light.contracts import canonical_json_sha256

    if summary != {**body, "artifact_digest": canonical_json_sha256(body)}:
        raise InitialEvidenceError("raw summary reconstruction mismatch")
    return contract, records, frames, summary


def _jsonl_bytes(rows: list[dict]) -> bytes:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        for row in rows
    ).encode()


def _receipt(stage, level, evidence, sources, **details):
    from src.dante_light.contracts import canonical_json_sha256

    evidence.unchanged()
    body = {
        "schema_version": 1,
        "status": f"PASS_O3A_INITIAL_{stage}_{level}_ONLY",
        "verification_policy_id": "o3a-initial-evidence-read-only-v1",
        "observing_run": "O3a",
        "verification_level": level,
        "historical_evidence_mutated": False,
        "raw_score_replay_executed": False,
        "encoder_executed": False,
        "threshold_fit_executed": False,
        "source_fetch_executed": False,
        "full_workflow_verified": False,
        "inputs": evidence.inputs,
        "executed_sources": sources,
        **details,
    }
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def verify_raw_evidence(*, root: Path, raw_root: Path) -> dict[str, Any]:
    """Check actual local raw file bytes against frozen historical evidence."""
    from src.dante_light import o3a_raw_download as raw

    root, raw_root = root.resolve(), raw_root.resolve()
    sources, evidence = _sources(root), _Evidence()
    _, records, frames, _ = _raw_context(root, raw_root, evidence)
    files = []
    for item, record in zip(frames, records):
        target = _existing(raw_root, item["target_relative_path"])
        if target.with_suffix(target.suffix + ".part").exists():
            raise InitialEvidenceError("partial raw file present")
        if target.stat().st_size != record["size_bytes"]:
            raise InitialEvidenceError("raw file size mismatch")
        metadata = raw.validate_hdf5_metadata(target, item)
        if any(record.get(key) != value for key, value in metadata.items()):
            raise InitialEvidenceError("raw HDF5 metadata mismatch")
        digest = raw.file_sha256(target)
        if digest != record["sha256"]:
            raise InitialEvidenceError("raw file hash mismatch")
        files.append({"path": str(target), "sha256": digest})
    return _receipt(
        "RAW",
        "INTEGRITY",
        evidence,
        sources,
        raw_files=files,
        verified_file_count=len(files),
        stored_score_values_read=False,
        strain_samples_evaluated=False,
    )


def verify_acceptance_evidence(
    *, root: Path, raw_root: Path, external_root: Path
) -> dict[str, Any]:
    """Reconstruct stored acceptance evidence, without evaluating raw scores."""
    from src.dante_light import o3a_initial_calibration_acceptance as acceptance
    from src.dante_light import o3a_initial_thresholds as thresholds

    root, raw_root, external_root = (
        root.resolve(),
        raw_root.resolve(),
        external_root.resolve(),
    )
    sources, evidence = _sources(root), _Evidence()
    contract, _, _, raw_summary = _raw_context(root, raw_root, evidence)
    threshold_contract = thresholds.load_threshold_contract(root=root)
    _loaded(
        evidence,
        root,
        "initial_threshold_contract",
        thresholds.CONTRACT_REL,
        threshold_contract,
    )
    plan = acceptance.load_initial_calibration_plan(root=root)
    _loaded(
        evidence,
        root,
        "initial_calibration_plan",
        acceptance.CALIBRATION_PLAN_REL,
        plan,
    )
    key = acceptance._run_key(contract)
    directory = external_root / f"initial_calibration_acceptance_{key}"
    _clean(directory)
    parent = threshold_contract["parents"]["acceptance_run"]
    summary_path = _existing(directory, "summary.json")
    ledger_path = _existing(directory, "initial_calibration_accepted.jsonl")
    if (
        _reference(parent["summary_path"]) != summary_path
        or _reference(parent["ledger_path"]) != ledger_path
        or parent["run_key"] != key
    ):
        raise InitialEvidenceError("acceptance parent path/run identity mismatch")
    summary = evidence.sealed(
        "acceptance_summary", summary_path, "artifact_digest", parent["summary_sha256"]
    )
    if summary["artifact_digest"] != parent["artifact_digest"]:
        raise InitialEvidenceError("acceptance parent artifact mismatch")
    if (
        _reference(summary["accepted_ledger"]["path"]) != ledger_path
        or summary["accepted_ledger"]["sha256"] != parent["ledger_sha256"]
    ):
        raise InitialEvidenceError("acceptance ledger parent mismatch")
    ledger = evidence.read("acceptance_ledger", ledger_path, parent["ledger_sha256"])
    population = contract["population"]
    block_length = int(population["candidate_rows_per_block"])
    bootstrap_blocks = int(population["bootstrap_rows_per_detector"]) // block_length
    rows, names = [], set()
    counts = {detector: 0 for detector in plan["detectors"]}
    bootstrap_counts = dict(counts)
    for detector in plan["detectors"]:
        for block in plan["detector_plans"][detector]["selected_blocks"]:
            identity = acceptance._block_identity(
                detector, block, int(plan["selection"]["window_stride_s"])
            )
            name = f"{detector}_stratum_{int(block['stratum_index']):03d}.json"
            if name in names:
                raise InitialEvidenceError("duplicate acceptance block")
            names.add(name)
            shard = evidence.sealed(
                name, _existing(directory, "shards/" + name), "shard_digest"
            )
            acceptance.validate_block_shard(shard, run_key=key, identity=identity)
            if (
                shard["status"] != "PASS_BLOCK_ATOMIC_ACCEPTANCE"
                or shard.get("score_value_or_class_used_for_acceptance") is not False
                or shard.get("threshold_fitted") is not False
            ):
                raise InitialEvidenceError("acceptance block failure/boundary mismatch")
            for index, row in enumerate(
                shard["rows"][: int(identity["output_row_count"])]
            ):
                eligible = int(block["stratum_index"]) < bootstrap_blocks
                rows.append(
                    {
                        **row,
                        "stratum_index": int(block["stratum_index"]),
                        "block_selection_priority_sha256": identity[
                            "selection_priority_sha256"
                        ],
                        "bootstrap_eligible": eligible,
                        "point_only_tail": int(block["stratum_index"])
                        == bootstrap_blocks
                        and index
                        < int(population["point_only_tail_rows_per_detector"]),
                    }
                )
                counts[detector] += 1
                bootstrap_counts[detector] += int(eligible)
    if (
        names != {p.name for p in (directory / "shards").glob("*.json")}
        or len(names) != population["provisional_block_count"]
    ):
        raise InitialEvidenceError("acceptance shard population mismatch")
    if counts != {
        d: population["point_estimate_rows_per_detector"] for d in counts
    } or bootstrap_counts != {
        d: population["bootstrap_rows_per_detector"] for d in counts
    }:
        raise InitialEvidenceError("acceptance row cardinality mismatch")
    if ledger != _jsonl_bytes(rows):
        raise InitialEvidenceError("acceptance ledger reconstruction mismatch")
    body = {
        "schema_version": acceptance.SCHEMA_VERSION,
        "status": "PASS_VERIFIED_O3A_INITIAL_CALIBRATION_ACCEPTANCE",
        "run_key": key,
        "contract_digest": contract["contract_digest"],
        "raw_manifest_sha256": contract["verified_raw_input"]["manifest_sha256"],
        "total_blocks": len(names),
        "passed_blocks": len(names),
        "failed_block_count": 0,
        "accepted_point_rows_by_detector": counts,
        "accepted_bootstrap_rows_by_detector": bootstrap_counts,
        "accepted_ledger": summary["accepted_ledger"],
        "threshold_fitted": False,
        "classification_executed": False,
        "candidate_outcomes_reviewed": False,
        "score_value_or_class_used_for_acceptance": False,
    }
    from src.dante_light.contracts import canonical_json_sha256

    if summary != {**body, "artifact_digest": canonical_json_sha256(body)}:
        raise InitialEvidenceError("acceptance summary reconstruction mismatch")
    return _receipt(
        "ACCEPTANCE",
        "RECONSTRUCTION",
        evidence,
        sources,
        counts_by_detector=counts,
        bootstrap_rows_by_detector=bootstrap_counts,
        shard_count=len(names),
        stored_score_values_read=True,
        parent_raw_artifact_digest=raw_summary["artifact_digest"],
        parent_raw_file_bytes_replayed=False,
    )
