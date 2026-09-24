"""Frozen detector-local native p99 fitting; no candidate classification."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_calibration_cohort import (
    CONTRACT_REL as COHORT_CONTRACT_REL,
    _atomic_json,
    load_cohort_contract,
)
from src.dante_light.o3a_native_contract import ROOT, RUNTIME_REL, load_runtime_contract
from src.dante_light.o3a_native_rescore import (
    CONTRACT_REL as RESCORE_CONTRACT_REL,
    DEFAULT_EXTERNAL_ROOT,
    _float32_hex,
    load_rescore_contract,
    verify_native_rescore,
)
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_light.o3a_scale_adequacy import STAGE_CONTRACT_REL, load_stage_contract
from src.pipeline_v2_production.background_calibration import block_bootstrap_p99_ci

CONTRACT_REL = "config/dante_o3a_native_thresholds_v1.json"
RESCORE_REL = "artifacts/dante_light/o3a_native_v1/native_rescore.json"
COMPACT_REL = "artifacts/dante_light/o3a_native_v1/native_thresholds.json"
METHOD_REL = "config/dante_o4a_corrected_native_thresholds_v1.json"
SOURCE_PATHS = (
    "src/dante_light/o3a_native_thresholds.py",
    "scripts/run_dante_o3a_native_thresholds.py",
    "tests/test_dante_o3a_native_thresholds.py",
    "src/pipeline_v2_production/background_calibration.py",
    "src/dante_light/contracts.py",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _sealed(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    body = dict(value)
    if body.pop(field, None) != canonical_json_sha256(body):
        raise ContractError(f"native threshold parent {field} mismatch")
    return body


def build_threshold_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Freeze from approved metadata only, without opening score ledgers."""
    stage = load_stage_contract(root=root)
    rescore_contract = load_rescore_contract(root=root)
    cohort = load_cohort_contract(root=root)
    receipt = _read_json(root / RESCORE_REL)
    _sealed(receipt, "compact_digest")
    if (
        receipt.get("status") != "PASS_VERIFIED_O3A_NATIVE_RESCORE"
        or receipt.get("contract_digest") != rescore_contract["contract_digest"]
        or receipt.get("row_total")
        != rescore_contract["population"]["exact_total_rows"]
        or receipt.get("native_threshold_or_class_computed") is not False
    ):
        raise ContractError("native threshold rescore receipt is not verified")
    approved = stage["author_decisions"]["native_threshold_statistics"]
    method = {
        "name": "non_overlapping_block_bootstrap_p99",
        "detector_specific": approved["detector_specific"],
        "percentile": approved["score_percentile"],
        "point_percentile_uses_all_rows": approved["point_percentile_uses_all_rows"],
        "bootstrap_uses_first_complete_blocks": True,
        "block_length": approved["block_length_rows"],
        "bootstrap_replicates": approved["bootstrap_replicates"],
        "bootstrap_seed": approved["bootstrap_seed"],
        "bootstrap_chunk_size": approved["bootstrap_chunk_size"],
        "confidence_percentiles": approved["confidence_percentiles"],
    }
    o4a_method = _read_json(root / METHOD_REL)
    _sealed(o4a_method, "contract_digest")
    if method != o4a_method["method"]:
        raise ContractError("native threshold approved O3a/O4a methods differ")
    # The shared helper implements precisely these percentiles, not arbitrary ones.
    if method["percentile"] != 99 or method["confidence_percentiles"] != [2.5, 97.5]:
        raise ContractError("native threshold helper does not implement this method")
    selection = cohort["selection"]
    counts = rescore_contract["population"]["calibration_rows_by_detector"]
    if (
        not method["detector_specific"]
        or not method["point_percentile_uses_all_rows"]
        or method["block_length"] != selection["block_length_rows"]
        or set(counts) != set(selection["detectors"])
        or any(
            n != approved["native_calibration_rows_per_detector"]
            for n in counts.values()
        )
        or any(
            n // method["block_length"] * method["block_length"]
            != selection["bootstrap_rows_per_detector"]
            for n in counts.values()
        )
    ):
        raise ContractError("native threshold population/block contract differs")
    relatives = (
        STAGE_CONTRACT_REL,
        COHORT_CONTRACT_REL,
        RESCORE_CONTRACT_REL,
        RESCORE_REL,
        RUNTIME_REL,
        METHOD_REL,
    )
    body = {
        "schema_version": 1,
        "status": "FROZEN_O3A_NATIVE_THRESHOLDS_V1",
        "run": "O3A",
        "method": method,
        "population": {
            "rows_by_detector": counts,
            "bootstrap_rows_per_detector": selection["bootstrap_rows_per_detector"],
            "within_block_stride_s": selection["stride_s"],
        },
        "parent_rescore": {
            key: receipt[key]
            for key in (
                "run_key",
                "artifact_digest",
                "contract_digest",
                "output_sha256",
            )
        },
        "references": {p: file_sha256(root / p) for p in relatives},
        "implementation_sources": {p: file_sha256(root / p) for p in SOURCE_PATHS},
        "scientific_boundary": {
            "candidate_scores_used_for_fitting": False,
            "o4a_scores_or_thresholds_used": False,
            "detector_pooling": False,
            "classification_performed": False,
            "interval_width_reported_without_post_hoc_cutoff": True,
        },
        "output": {"summary_filename": "native_thresholds_summary.json"},
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def load_threshold_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = _read_json(root / CONTRACT_REL)
    if value != build_threshold_contract(root=root):
        raise ContractError("native threshold frozen contract or source changed")
    return value


def freeze_threshold_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_threshold_contract(root=root)
    _atomic_json(root / CONTRACT_REL, value)
    return value


def validate_score_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    detector: str,
    count: int,
    block_length: int,
    stride: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    if len(rows) != count:
        raise ContractError("native threshold calibration count changed")
    seen: set[float] = set()
    scores = []
    identities = []
    previous = None
    for k, row in enumerate(rows):
        gps = float(row.get("gps_start", np.nan))
        score = float(row.get("native_score", np.nan))
        if (
            row.get("detector") != detector
            or row.get("population") != "native_calibration"
            or row.get("calibration_row_number") != k
            or row.get("bootstrap_block_index") != k // block_length
            or not np.isfinite(gps)
            or gps <= 0
            or gps in seen
            or not np.isfinite(score)
            or row.get("score_float32_hex") != _float32_hex(score)
            or (previous is not None and gps <= previous)
            or (
                k < count // block_length * block_length
                and k % block_length != 0
                and gps - previous != stride
            )
        ):
            raise ContractError(
                "native threshold calibration identity/order/score changed"
            )
        seen.add(gps)
        previous = gps
        scores.append(score)
        identities.append(
            {
                key: row[key]
                for key in (
                    "detector",
                    "gps_start",
                    "identity_digest",
                    "score_float32_hex",
                )
            }
        )
    values = np.asarray(scores, dtype=np.float64)
    return values, {
        "row_total": len(rows),
        "identity_score_digest": canonical_json_sha256(identities),
        "score_vector_float64_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
    }


def compute_threshold(
    scores: np.ndarray, *, method: Mapping[str, Any]
) -> dict[str, Any]:
    value = block_bootstrap_p99_ci(
        scores,
        B=int(method["bootstrap_replicates"]),
        seed=int(method["bootstrap_seed"]),
        chunk_size=int(method["bootstrap_chunk_size"]),
        block_length=int(method["block_length"]),
    )
    point, low, high = (float(value[k]) for k in ("p99", "ci_lower", "ci_upper"))
    if not np.isfinite([point, low, high]).all() or not low <= point <= high:
        raise ContractError("native threshold interval invalid")
    used = int(value["block_length"]) * int(value["n_complete_blocks"])
    return {
        **value,
        "n_point_rows": len(scores),
        "n_bootstrap_rows": used,
        "point_only_tail_rows": len(scores) - used,
        "ci_width": high - low,
        "ci_width_fraction_of_p99": (high - low) / abs(point) if point != 0 else None,
    }


def _run_dir(contract: Mapping[str, Any], external_root: Path) -> Path:
    key = canonical_json_sha256(
        {
            "stage": "o3a_native_thresholds_v1",
            "contract_digest": contract["contract_digest"],
        }
    )
    return external_root.resolve() / f"native_thresholds_{key}"


@contextmanager
def _lock(run_dir: Path):
    import fcntl  # Canonical execution is WSL, including verification.

    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "run.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ContractError("native threshold run already active") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _calculate(
    contract: Mapping[str, Any], *, root: Path, external_root: Path
) -> dict[str, Any]:
    runtime = load_runtime_contract(root=root, require_current=True)
    # Parent verification may read candidate bytes for integrity; never for fitting.
    summary, parent_dir = verify_native_rescore(root=root, external_root=external_root)
    parent = contract["parent_rescore"]
    if any(
        summary[k] != parent[k]
        for k in ("artifact_digest", "run_key", "contract_digest")
    ):
        raise ContractError("native threshold verified rescore parent changed")
    inputs, thresholds = {}, {}
    population = contract["population"]
    for detector, count in sorted(population["rows_by_detector"].items()):
        name = f"native_calibration_{detector}"
        meta = summary["outputs"][name]
        path = parent_dir / meta["filename"]
        if (
            meta["filename"] != name + ".jsonl"
            or file_sha256(path) != parent["output_sha256"][name]
        ):
            raise ContractError("native threshold calibration input changed")
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        scores, audit = validate_score_rows(
            rows,
            detector=detector,
            count=count,
            block_length=contract["method"]["block_length"],
            stride=population["within_block_stride_s"],
        )
        inputs[detector] = {
            **audit,
            "sha256": file_sha256(path),
            "row_digest": meta["row_digest"],
        }
        thresholds[detector] = compute_threshold(scores, method=contract["method"])
        if (
            thresholds[detector]["n_bootstrap_rows"]
            != population["bootstrap_rows_per_detector"]
        ):
            raise ContractError("native threshold bootstrap population changed")
    body = {
        "schema_version": 1,
        "status": "PASS_COMPLETE_O3A_NATIVE_THRESHOLDS",
        "contract_digest": contract["contract_digest"],
        "run_key": _run_dir(contract, external_root).name.removeprefix(
            "native_thresholds_"
        ),
        "native_rescore_artifact_digest": summary["artifact_digest"],
        "runtime_environment_digest": runtime["runtime_environment"][
            "environment_digest"
        ],
        "inputs": inputs,
        "method": contract["method"],
        "thresholds": thresholds,
        "scientific_boundary": contract["scientific_boundary"],
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def execute_thresholds(
    *,
    root: Path = ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    verify: bool = False,
) -> tuple[dict[str, Any], Path]:
    contract = load_threshold_contract(root=root)
    run_dir = _run_dir(contract, external_root)
    with _lock(run_dir):
        failure = run_dir / "failure.json"
        if failure.exists():
            raise ContractError("native threshold failure requires review")
        path = run_dir / contract["output"]["summary_filename"]
        if verify and not path.exists():
            raise ContractError("native threshold summary missing")
        try:
            result = _calculate(contract, root=root, external_root=external_root)
            if path.exists():
                if _read_json(path) != result:
                    raise ContractError("native threshold deterministic replay changed")
            else:
                _atomic_json(path, result)
            if verify:
                body = {
                    **result,
                    "status": "PASS_VERIFIED_O3A_NATIVE_THRESHOLDS",
                    "external_run_dir_wsl": str(run_dir),
                    "summary_sha256": file_sha256(path),
                }
                body.pop("artifact_digest")
                body["run_artifact_digest"] = result["artifact_digest"]
                _atomic_json(
                    root / COMPACT_REL,
                    {**body, "artifact_digest": canonical_json_sha256(body)},
                )
            return result, run_dir
        except BaseException as exc:
            body = {
                "status": "FAILED_O3A_NATIVE_THRESHOLDS",
                "run_key": run_dir.name.removeprefix("native_thresholds_"),
                "contract_digest": contract["contract_digest"],
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            _atomic_json(
                failure, {**body, "artifact_digest": canonical_json_sha256(body)}
            )
            raise
