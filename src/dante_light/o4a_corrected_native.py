"""Fail-closed detector-aware native-index reconstruction for corrected O4a.

The historical native training sidecar stored GPS centers without detector
identity.  This module never guesses that missing field.  It freezes a new,
balanced detector-aware cohort from the verified corrected primary scan before
any native embedding or score is computed.
"""

from __future__ import annotations

import bisect
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_execution import verify_primary_scan
from src.dante_light.o4a_native_provenance import (
    verify_reference_with_reconciliation,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_native_v1.json")
DEFAULT_EXTERNAL_ROOT = Path("E:/dante_cache/dante_light/o4a_corrected_native_v1")
SCHEMA_VERSION = 1


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                + "\n"
            )
    temporary.replace(path)


def validate_native_contract(
    payload: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    """Validate the frozen native reconstruction contract and every input hash."""

    value = dict(payload)
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("corrected native contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported corrected native contract schema")
    parity = value.get("historical_parity", {})
    target = int(parity.get("balanced_target_per_detector", -1))
    if target <= 0 or 2 * target != int(parity.get("source_training_total", -1)):
        raise ContractError("corrected native cohort is not exact balanced parity")
    gates = value.get("gates", {}).get("exact_cardinality_by_detector", {})
    if gates != {"H1": target, "L1": target}:
        raise ContractError("corrected native cardinality gate is inconsistent")
    cohort = value.get("cohort", {})
    if cohort.get("detectors") != ["H1", "L1"]:
        raise ContractError("corrected native detector order is not frozen")
    if cohort.get("selection_must_not_read_primary_scores") is not True:
        raise ContractError("corrected native selector is not outcome-blind")
    references: list[Mapping[str, Any]] = list(value.get("references", {}).values())
    veto_reference = value["preprocessing"]["excess_power_veto"]
    references.append(
        {
            "path": veto_reference["source_path"],
            "sha256": veto_reference["source_sha256"],
        }
    )
    references.extend(
        [
            {
                "path": parity["source_index_path"],
                "sha256": parity["source_index_sha256"],
            },
            {
                "path": parity["source_training_ledger_path"],
                "sha256": parity["source_training_ledger_sha256"],
            },
        ]
    )
    for reference in references:
        path = root / str(reference["path"])
        verify_reference_with_reconciliation(
            root=root,
            path=path,
            expected_sha256=str(reference["sha256"]),
            raw_hasher=sha256_file,
        )
    parent_path = root / value["parent_protocol"]["path"]
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    if parent.get("protocol_digest") != value["parent_protocol"]["protocol_digest"]:
        raise ContractError("corrected native parent protocol mismatch")
    return value


def load_native_contract(root: Path = ROOT) -> dict[str, Any]:
    path = root / CONTRACT_REL
    return validate_native_contract(
        json.loads(path.read_text(encoding="utf-8")), root.resolve()
    )


def _priority(seed: int, detector: str, gps_start: float) -> str:
    text = f"{int(seed)}|{detector}|{float(gps_start):.9f}"
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _within_guard(value: float, sorted_values: Sequence[float], guard: float) -> bool:
    position = bisect.bisect_left(sorted_values, value)
    return (
        (position > 0 and value - sorted_values[position - 1] < guard)
        or (
            position < len(sorted_values)
            and sorted_values[position] - value < guard
        )
    )


def select_native_proposals(
    identities: Iterable[tuple[str, float, bool]],
    *,
    candidate_times: Sequence[float],
    calibration_identities: set[tuple[str, float]],
    seed_by_detector: Mapping[str, int],
    proposal_limit_per_detector: int,
    minimum_separation_s: float,
    candidate_guard_delta_s: float,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, int]]]:
    """Pure, outcome-blind proposal selector used by the frozen cohort stage."""

    candidates = sorted(set(float(value) for value in candidate_times))
    pools: dict[str, list[dict[str, Any]]] = {"H1": [], "L1": []}
    counts = {
        detector: {
            "eligible_seen": 0,
            "direct_candidate": 0,
            "candidate_guard": 0,
            "native_calibration": 0,
            "proposal_separation": 0,
        }
        for detector in ("H1", "L1")
    }
    for detector, gps_start, is_candidate in identities:
        if detector not in pools:
            raise ContractError(f"unexpected detector in corrected scan: {detector}")
        gps = float(gps_start)
        counts[detector]["eligible_seen"] += 1
        if bool(is_candidate):
            counts[detector]["direct_candidate"] += 1
            continue
        left = bisect.bisect_left(candidates, gps - candidate_guard_delta_s)
        guarded = (
            left < len(candidates)
            and candidates[left] <= gps + candidate_guard_delta_s
        )
        if guarded:
            counts[detector]["candidate_guard"] += 1
            continue
        if (detector, gps) in calibration_identities:
            counts[detector]["native_calibration"] += 1
            continue
        pools[detector].append(
            {
                "detector": detector,
                "gps_start": gps,
                "priority": _priority(seed_by_detector[detector], detector, gps),
            }
        )
    proposals: dict[str, list[dict[str, Any]]] = {"H1": [], "L1": []}
    for detector in ("H1", "L1"):
        accepted_gps: list[float] = []
        for row in sorted(pools[detector], key=lambda item: item["priority"]):
            gps = float(row["gps_start"])
            if _within_guard(gps, accepted_gps, minimum_separation_s):
                counts[detector]["proposal_separation"] += 1
                continue
            bisect.insort(accepted_gps, gps)
            proposals[detector].append(row)
            if len(proposals[detector]) == proposal_limit_per_detector:
                break
        if len(proposals[detector]) != proposal_limit_per_detector:
            raise ContractError(
                f"corrected native {detector} proposal pool is incomplete: "
                f"{len(proposals[detector])}/{proposal_limit_per_detector}"
            )
    return proposals, counts


def _read_native_calibration_identities(
    root: Path, contract: Mapping[str, Any]
) -> set[tuple[str, float]]:
    identities: set[tuple[str, float]] = set()
    for detector in ("H1", "L1"):
        reference = contract["references"][f"native_calibration_{detector}"]
        with (root / reference["path"]).open("r", encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                row_detector = str(row["detector"])
                if row_detector != detector:
                    raise ContractError("native calibration ledger detector mismatch")
                identity = (row_detector, float(row["gps_start"]))
                if identity in identities:
                    raise ContractError("native calibration identity is duplicated")
                identities.add(identity)
    if len(identities) != 10_000:
        raise ContractError("native calibration ledgers do not contain 10,000 identities")
    return identities


_WORKER_MANIFESTS: dict[str, Any] = {}
_WORKER_RAW_ROOT: Path | None = None
_WORKER_SAMPLE_RATE = 4096
_WORKER_PAD = 4.0


def _initialize_quality_worker(
    manifest_path: str,
    raw_root: str,
    sample_rate_hz: int,
    whitening_pad_s: float,
) -> None:
    from src.core.patch_producer import load_frozen_raw_manifest

    global _WORKER_MANIFESTS, _WORKER_RAW_ROOT, _WORKER_SAMPLE_RATE, _WORKER_PAD
    _WORKER_RAW_ROOT = Path(raw_root).resolve()
    _WORKER_SAMPLE_RATE = int(sample_rate_hz)
    _WORKER_PAD = float(whitening_pad_s)
    _WORKER_MANIFESTS = {
        detector: load_frozen_raw_manifest(
            Path(manifest_path), raw_root=_WORKER_RAW_ROOT, detector=detector
        )
        for detector in ("H1", "L1")
    }


def _quality_check_proposal(row: Mapping[str, Any]) -> dict[str, Any]:
    from src.core.patch_producer import read_complete_context
    from src.core.preprocessor import extract_clean_subwindow, whiten_context
    from src.pipeline_v3_multiscale.micro_mdc_multiscale import excess_power_veto

    if _WORKER_RAW_ROOT is None:
        raise RuntimeError("corrected native quality worker is not initialized")
    detector = str(row["detector"])
    gps = float(row["gps_start"])
    manifest = _WORKER_MANIFESTS[detector]
    context = read_complete_context(
        manifest.entries,
        gps_start=gps - _WORKER_PAD,
        gps_end=gps + 32.0 + _WORKER_PAD,
        sample_rate_hz=_WORKER_SAMPLE_RATE,
        expected_sha256=manifest.expected_sha256,
    )
    whitened, pad_info = whiten_context(
        context.series, gps, gps + 32.0, pad=_WORKER_PAD
    )
    tolerance = max(1.0 / _WORKER_SAMPLE_RATE, np.finfo(np.float64).eps)
    if (
        float(pad_info["effective_left"]) < _WORKER_PAD - tolerance
        or float(pad_info["effective_right"]) < _WORKER_PAD - tolerance
    ):
        raise ContractError("corrected native whitening context is incomplete")
    clean = extract_clean_subwindow(whitened, gps, gps + 32.0)
    values = np.ascontiguousarray(clean.value)
    expected_samples = int(round(32.0 * _WORKER_SAMPLE_RATE))
    if len(values) != expected_samples or np.any(~np.isfinite(values)):
        raise ContractError("corrected native clean window is invalid")
    vetoed = bool(excess_power_veto(clean, sample_rate=_WORKER_SAMPLE_RATE))
    sources = [
        {
            "relative_path": str(source.path.resolve().relative_to(_WORKER_RAW_ROOT)).replace("\\", "/"),
            "block_interval": [float(source.block_start), float(source.block_end)],
            "used_interval": [float(source.used_start), float(source.used_end)],
            "sha256": source.sha256,
        }
        for source in context.sources
    ]
    return {
        **dict(row),
        "gps_end": gps + 32.0,
        "quality_disposition": "EXCESS_POWER_VETO" if vetoed else "PASS_CLEAN",
        "clean_window_dtype": str(values.dtype),
        "clean_window_shape": list(values.shape),
        "clean_window_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
        "context_sources": sources,
        "context_sources_digest": canonical_json_sha256(sources),
    }


def _scan_identity_rows(database_path: Path) -> list[tuple[str, float, bool]]:
    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        # Deliberately omit primary_score and every model outcome except the
        # already-frozen candidate boolean needed by anti-circularity.
        rows = connection.execute(
            "SELECT detector,gps_start,is_candidate FROM windows "
            "ORDER BY detector,gps_start"
        ).fetchall()
    finally:
        connection.close()
    return [(str(detector), float(gps), bool(candidate)) for detector, gps, candidate in rows]


def _cohort_run_key(
    contract: Mapping[str, Any], scan_summary: Mapping[str, Any]
) -> str:
    return canonical_json_sha256(
        {
            "stage": "freeze_detector_aware_native_cohort",
            "contract_digest": contract["contract_digest"],
            "primary_scan_artifact_digest": scan_summary["artifact_digest"],
            "references": contract["references"],
        }
    )


def freeze_native_cohort(
    *,
    root: Path = ROOT,
    raw_root: Path = Path("E:/o4a"),
    primary_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    workers: int = 8,
    quality_batch_size: int = 128,
) -> tuple[dict[str, Any], Path]:
    """Freeze the exact detector-aware native cohort before representation work."""

    if workers < 1 or quality_batch_size < 1:
        raise ValueError("corrected native worker parameters must be positive")
    root = root.resolve()
    raw_root = raw_root.resolve()
    external_root = external_root.resolve()
    contract = load_native_contract(root)
    scan_summary, scan_dir = verify_primary_scan(
        root=root, external_root=primary_external_root.resolve()
    )
    run_key = _cohort_run_key(contract, scan_summary)
    run_dir = external_root / f"native_cohort_{run_key}"
    identity = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "primary_scan_artifact_digest": scan_summary["artifact_digest"],
        "primary_scan_database_sha256": scan_summary["database"]["sha256"],
        "workers": int(workers),
        "quality_batch_size": int(quality_batch_size),
    }
    identity_path = run_dir / "run_identity.json"
    if identity_path.is_file():
        if json.loads(identity_path.read_text(encoding="utf-8")) != identity:
            raise ContractError("corrected native cohort run-key collision")
    else:
        _atomic_json(identity_path, identity)
    summary_path = run_dir / "native_cohort_summary.json"
    if summary_path.is_file():
        return verify_native_cohort(
            root=root,
            primary_external_root=primary_external_root,
            external_root=external_root,
        )
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError(f"corrected native cohort has a recorded failure: {failure_path}")
    database_path = scan_dir / "primary_scan.sqlite"
    if sha256_file(database_path) != scan_summary["database"]["sha256"]:
        raise ContractError("corrected primary scan database changed before native freeze")
    identities = _scan_identity_rows(database_path)
    expected_total = int(scan_summary["window_total"])
    if len(identities) != expected_total:
        raise ContractError("corrected native selector saw incomplete primary identities")
    candidate_times = [gps for _detector, gps, candidate in identities if candidate]
    calibration = _read_native_calibration_identities(root, contract)
    cohort = contract["cohort"]
    proposals, selection_counts = select_native_proposals(
        identities,
        candidate_times=candidate_times,
        calibration_identities=calibration,
        seed_by_detector=cohort["seed_by_detector"],
        proposal_limit_per_detector=int(cohort["proposal_limit_per_detector"]),
        minimum_separation_s=float(cohort["minimum_same_detector_separation_s"]),
        candidate_guard_delta_s=float(cohort["candidate_guard_window_start_delta_s"]),
    )
    preprocessing = contract["preprocessing"]
    manifest_path = root / contract["references"]["raw_manifest"]["path"]
    target = int(contract["historical_parity"]["balanced_target_per_detector"])
    selected: list[dict[str, Any]] = []
    quality_counts: dict[str, dict[str, int]] = {
        detector: {"checked": 0, "pass_clean": 0, "excess_power_veto": 0}
        for detector in ("H1", "L1")
    }
    try:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_initialize_quality_worker,
            initargs=(
                str(manifest_path),
                str(raw_root),
                int(preprocessing["sample_rate_hz"]),
                float(preprocessing["whitening_pad_s"]),
            ),
        ) as executor:
            for detector in ("H1", "L1"):
                rows = proposals[detector]
                for start in range(0, len(rows), quality_batch_size):
                    checked = list(
                        executor.map(
                            _quality_check_proposal,
                            rows[start : start + quality_batch_size],
                        )
                    )
                    quality_counts[detector]["checked"] += len(checked)
                    for row in checked:
                        if row["quality_disposition"] == "EXCESS_POWER_VETO":
                            quality_counts[detector]["excess_power_veto"] += 1
                            continue
                        quality_counts[detector]["pass_clean"] += 1
                        selected.append(row)
                        if quality_counts[detector]["pass_clean"] == target:
                            break
                    if quality_counts[detector]["pass_clean"] == target:
                        break
                if quality_counts[detector]["pass_clean"] != target:
                    raise ContractError(
                        f"corrected native {detector} clean cohort is incomplete: "
                        f"{quality_counts[detector]['pass_clean']}/{target}"
                    )
    except BaseException as exc:
        failure = {
            **identity,
            "status": "FAILED_COHORT_FREEZE",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "selection_counts": selection_counts,
            "quality_counts": quality_counts,
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        raise
    selected.sort(key=lambda row: (row["detector"], row["priority"]))
    for index, row in enumerate(selected):
        row["cohort_index"] = index
        row["identity_digest"] = canonical_json_sha256(
            {"detector": row["detector"], "gps_start": row["gps_start"]}
        )
    ledger_path = run_dir / "native_cohort.jsonl"
    _atomic_jsonl(ledger_path, selected)
    ledger_digest = canonical_json_sha256(selected)
    counts = {
        detector: sum(row["detector"] == detector for row in selected)
        for detector in ("H1", "L1")
    }
    summary_body = {
        **identity,
        "status": "PASS_FROZEN_NATIVE_COHORT",
        "ledger": {
            "filename": ledger_path.name,
            "sha256": sha256_file(ledger_path),
            "size_bytes": ledger_path.stat().st_size,
            "row_digest": ledger_digest,
        },
        "counts_by_detector": counts,
        "row_total": len(selected),
        "candidate_identity_count": len(
            {(detector, gps) for detector, gps, candidate in identities if candidate}
        ),
        "candidate_time_count": len(set(candidate_times)),
        "native_calibration_identity_count": len(calibration),
        "selection_counts": selection_counts,
        "quality_counts": quality_counts,
        "scientific_boundary": {
            "historical_detector_identity_inferred": False,
            "primary_scores_read_by_selector": False,
            "native_embeddings_or_scores_computed": False,
            "cohort_frozen_before_native_representation": True,
        },
    }
    summary = {
        **summary_body,
        "artifact_digest": canonical_json_sha256(summary_body),
    }
    _atomic_json(summary_path, summary)
    return verify_native_cohort(
        root=root,
        primary_external_root=primary_external_root,
        external_root=external_root,
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def verify_native_cohort(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], Path]:
    """Verify the frozen cohort structurally without opening native outcomes."""

    root = root.resolve()
    contract = load_native_contract(root)
    scan_summary, scan_dir = verify_primary_scan(
        root=root, external_root=primary_external_root.resolve()
    )
    run_key = _cohort_run_key(contract, scan_summary)
    run_dir = external_root.resolve() / f"native_cohort_{run_key}"
    summary_path = run_dir / "native_cohort_summary.json"
    ledger_path = run_dir / "native_cohort.jsonl"
    if not summary_path.is_file() or not ledger_path.is_file():
        raise ContractError("corrected native cohort artifacts are incomplete")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("corrected native cohort artifact digest mismatch")
    if summary.get("status") != "PASS_FROZEN_NATIVE_COHORT":
        raise ContractError("corrected native cohort is not PASS")
    if summary.get("run_key") != run_key:
        raise ContractError("corrected native cohort run key mismatch")
    if sha256_file(ledger_path) != summary["ledger"]["sha256"]:
        raise ContractError("corrected native cohort ledger SHA-256 mismatch")
    rows = _load_jsonl(ledger_path)
    if canonical_json_sha256(rows) != summary["ledger"]["row_digest"]:
        raise ContractError("corrected native cohort row digest mismatch")
    target = int(contract["historical_parity"]["balanced_target_per_detector"])
    counts = {
        detector: sum(row.get("detector") == detector for row in rows)
        for detector in ("H1", "L1")
    }
    if counts != {"H1": target, "L1": target} or len(rows) != 2 * target:
        raise ContractError("corrected native cohort cardinality gate failed")
    identities = [(str(row["detector"]), float(row["gps_start"])) for row in rows]
    if len(identities) != len(set(identities)):
        raise ContractError("corrected native cohort identities are duplicated")
    calibration = _read_native_calibration_identities(root, contract)
    if set(identities) & calibration:
        raise ContractError("corrected native cohort overlaps native calibration")
    scan_identities = _scan_identity_rows(scan_dir / "primary_scan.sqlite")
    scan_lookup = {(detector, gps): candidate for detector, gps, candidate in scan_identities}
    candidate_times = sorted(
        {gps for _detector, gps, candidate in scan_identities if candidate}
    )
    guard_delta = float(contract["cohort"]["candidate_guard_window_start_delta_s"])
    separation = float(contract["cohort"]["minimum_same_detector_separation_s"])
    for detector in ("H1", "L1"):
        detector_gps = sorted(gps for row_detector, gps in identities if row_detector == detector)
        if any(
            right - left < separation
            for left, right in zip(detector_gps, detector_gps[1:], strict=False)
        ):
            raise ContractError("corrected native cohort separation gate failed")
    for identity in identities:
        if identity not in scan_lookup or scan_lookup[identity]:
            raise ContractError("corrected native cohort contains a primary candidate")
        gps = identity[1]
        position = bisect.bisect_left(candidate_times, gps - guard_delta)
        if position < len(candidate_times) and candidate_times[position] <= gps + guard_delta:
            raise ContractError("corrected native cohort violates candidate guard")
    if any(row.get("quality_disposition") != "PASS_CLEAN" for row in rows):
        raise ContractError("corrected native cohort includes a failed quality row")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "freeze_native_cohort",
    "load_native_contract",
    "select_native_proposals",
    "validate_native_contract",
    "verify_native_cohort",
]
