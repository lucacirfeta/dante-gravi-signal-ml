"""Freeze detector-aware native thresholds from calibration-v2 scores only."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_rescore import _atomic_json, _float32_hex
from src.dante_light.o4a_corrected_native_rescore_v2 import verify_native_rescore_v2
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.dante_light.prefilter_v5_protocol import sha256_path
from src.pipeline_v2_production.background_calibration import block_bootstrap_p99_ci


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_native_thresholds_v1.json")
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_native_thresholds_v1"
)
SCHEMA_VERSION = 1


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_native_threshold_contract(
    contract: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(contract))
    digest = value.pop("contract_digest", None)
    if digest != canonical_json_sha256(value):
        raise ContractError("corrected native-threshold contract digest mismatch")
    if int(value.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ContractError("corrected native-threshold schema changed")
    if value.get("scientific_boundary") != {
        "detector_specific": True,
        "calibration_v2_scores_only": True,
        "candidate_scores_used": False,
        "historical_scores_used": False,
        "historical_thresholds_used": False,
        "point_estimate_uses_all_calibration_rows": True,
        "bootstrap_uses_complete_non_overlapping_blocks": True,
        "classification_performed_in_this_stage": False,
        "historical_artifacts_immutable": True,
    }:
        raise ContractError("corrected native-threshold scientific boundary changed")

    references = value.get("references", {})
    for reference in references.values():
        path = (root / str(reference["path"])).resolve()
        if not path.is_file() or sha256_path(path) != reference["sha256"]:
            raise ContractError(f"corrected native-threshold reference changed: {path}")

    calibration = _read_json(
        root / str(references["native_calibration_v2_contract"]["path"])
    )
    rescore = _read_json(root / str(references["native_rescore_v2"]["path"]))
    method = value.get("method", {})
    future = calibration.get("future_threshold_contract", {})
    if (
        method.get("name") != future.get("method")
        or method.get("detector_specific") != future.get("detector_specific")
        or method.get("point_percentile_uses_all_rows")
        != future.get("point_percentile_uses_all_5000_rows")
        or method.get("bootstrap_uses_first_complete_blocks")
        != future.get("bootstrap_uses_first_4998_rows_as_294_complete_blocks")
        or int(method.get("block_length", -1))
        != int(calibration["population"]["temporal_block_length"])
        or int(method.get("bootstrap_replicates", -1))
        != int(future.get("bootstrap_replicates", -2))
        or int(method.get("bootstrap_seed", -1))
        != int(future.get("bootstrap_seed", -2))
        or int(method.get("bootstrap_chunk_size", -1))
        != int(future.get("bootstrap_chunk_size", -2))
        or float(method.get("percentile", -1)) != float(future.get("percentile", -2))
        or method.get("confidence_percentiles")
        != future.get("confidence_percentiles")
    ):
        raise ContractError("corrected native-threshold method changed")
    if value.get("parent_native_rescore") != {
        "artifact_digest": rescore.get("artifact_digest"),
        "contract_digest": rescore.get("contract_digest"),
        "run_key": rescore.get("run_key"),
    }:
        raise ContractError("corrected native-threshold parent changed")
    expected_counts = rescore.get("input_counts", {}).get("native_calibration", {})
    if value.get("gates", {}).get("exact_rows_by_detector") != expected_counts:
        raise ContractError("corrected native-threshold cardinality changed")
    return {"contract_digest": digest, **value}


def load_native_threshold_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_native_threshold_contract(
        _read_json(root / CONTRACT_REL), root=root
    )


def validate_calibration_score_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    detector: str,
    expected_count: int,
    block_length: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    if len(rows) != expected_count:
        raise ContractError("corrected native-threshold calibration count changed")
    identities: set[tuple[str, float]] = set()
    scores: list[float] = []
    identity_rows: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows):
        identity = (str(row.get("detector")), float(row.get("gps_start", np.nan)))
        score = float(row.get("native_score", np.nan))
        if (
            identity[0] != detector
            or identity in identities
            or row.get("population") != "native_calibration"
            or int(row.get("ledger_row_number", -1)) != row_number
            or int(row.get("bootstrap_block_index", -1)) != row_number // block_length
            or not np.isfinite(identity[1])
            or not np.isfinite(score)
            or row.get("score_float32_hex") != _float32_hex(score)
        ):
            raise ContractError("corrected native-threshold calibration row changed")
        identities.add(identity)
        scores.append(score)
        identity_rows.append(
            {
                "detector": identity[0],
                "gps_start": identity[1],
                "identity_digest": str(row.get("identity_digest")),
                "score_float32_hex": str(row.get("score_float32_hex")),
            }
        )
    score_array = np.asarray(scores, dtype=np.float64)
    return score_array, {
        "row_total": len(rows),
        "identity_score_digest": canonical_json_sha256(identity_rows),
        "score_vector_float64_sha256": hashlib.sha256(score_array.tobytes()).hexdigest(),
    }


def compute_detector_threshold(
    scores: np.ndarray, *, method: Mapping[str, Any]
) -> dict[str, float | int]:
    result = block_bootstrap_p99_ci(
        np.asarray(scores, dtype=np.float64),
        B=int(method["bootstrap_replicates"]),
        seed=int(method["bootstrap_seed"]),
        chunk_size=int(method["bootstrap_chunk_size"]),
        block_length=int(method["block_length"]),
    )
    values = [float(result[name]) for name in ("p99", "ci_lower", "ci_upper")]
    if not np.isfinite(values).all() or not values[1] <= values[0] <= values[2]:
        raise ContractError("corrected native-threshold interval is invalid")
    return result


def _run_key(
    contract: Mapping[str, Any],
    *,
    rescore_summary: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> str:
    return canonical_json_sha256(
        {
            "stage": "native_thresholds_v1",
            "contract_digest": contract["contract_digest"],
            "native_rescore_artifact_digest": rescore_summary["artifact_digest"],
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
        }
    )


def _verified_parent(
    *,
    root: Path,
    primary_external_root: Path,
    native_external_root: Path,
    calibration_external_root: Path,
    index_external_root: Path,
    rescore_external_root: Path,
    device: str,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    summary, run_dir = verify_native_rescore_v2(
        root=root,
        primary_external_root=primary_external_root,
        native_external_root=native_external_root,
        calibration_external_root=calibration_external_root,
        index_external_root=index_external_root,
        external_root=rescore_external_root,
        device=device,
    )
    runtime = load_canonical_runtime_contract(
        root=root, require_current=True, device=device
    )
    return summary, run_dir, runtime


def run_native_thresholds(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    native_external_root: Path,
    calibration_external_root: Path,
    index_external_root: Path,
    rescore_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_threshold_contract(root)
    rescore, rescore_dir, runtime = _verified_parent(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        native_external_root=native_external_root.resolve(),
        calibration_external_root=calibration_external_root.resolve(),
        index_external_root=index_external_root.resolve(),
        rescore_external_root=rescore_external_root.resolve(),
        device=device,
    )
    if rescore["artifact_digest"] != contract["parent_native_rescore"]["artifact_digest"]:
        raise ContractError("corrected native-threshold rescore artifact changed")
    run_key = _run_key(contract, rescore_summary=rescore, runtime=runtime)
    run_dir = external_root.resolve() / f"native_thresholds_{run_key}"
    failure_path = run_dir / "failure.json"
    summary_path = run_dir / str(contract["output"]["summary_filename"])
    if failure_path.is_file():
        raise ContractError("corrected native-threshold failure artifact is present")
    if summary_path.is_file():
        return verify_native_thresholds(
            root=root,
            primary_external_root=primary_external_root,
            native_external_root=native_external_root,
            calibration_external_root=calibration_external_root,
            index_external_root=index_external_root,
            rescore_external_root=rescore_external_root,
            external_root=external_root,
            device=device,
        )
    try:
        method = contract["method"]
        thresholds: dict[str, Any] = {}
        inputs: dict[str, Any] = {}
        counts = Counter()
        for detector, expected_count in sorted(
            contract["gates"]["exact_rows_by_detector"].items()
        ):
            metadata = rescore["outputs"][f"native_calibration_{detector}"]
            path = rescore_dir / str(metadata["filename"])
            if not path.is_file() or sha256_file(path) != metadata["sha256"]:
                raise ContractError("corrected native-threshold input hash changed")
            rows = _read_jsonl(path)
            scores, audit = validate_calibration_score_rows(
                rows,
                detector=detector,
                expected_count=int(expected_count),
                block_length=int(method["block_length"]),
            )
            counts[detector] = len(scores)
            inputs[detector] = {
                **audit,
                "filename": str(metadata["filename"]),
                "sha256": str(metadata["sha256"]),
                "row_digest": str(metadata["row_digest"]),
            }
            threshold = compute_detector_threshold(scores, method=method)
            thresholds[detector] = {
                **threshold,
                "n_calibration_scores": len(scores),
                "bootstrap_rows_used": int(threshold["n_complete_blocks"])
                * int(threshold["block_length"]),
                "bootstrap_tail_rows_excluded": len(scores)
                - int(threshold["n_complete_blocks"])
                * int(threshold["block_length"]),
            }
        if counts != Counter(
            {
                detector: int(count)
                for detector, count in contract["gates"][
                    "exact_rows_by_detector"
                ].items()
            }
        ):
            raise ContractError("corrected native-threshold detector counts changed")
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_COMPLETE_NATIVE_THRESHOLDS_V1",
            "contract_digest": contract["contract_digest"],
            "run_key": run_key,
            "native_rescore_artifact_digest": rescore["artifact_digest"],
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
            "method": method,
            "inputs": inputs,
            "thresholds": thresholds,
            "scientific_boundary": contract["scientific_boundary"],
            "gates": {
                "exact_rows_by_detector": dict(sorted(counts.items())),
                "nonfinite_scores": 0,
                "candidate_scores_used": False,
                "historical_scores_used": False,
                "historical_thresholds_used": False,
            },
        }
        summary = {**body, "artifact_digest": canonical_json_sha256(body)}
        _atomic_json(summary_path, summary)
        return summary, run_dir
    except BaseException as exc:
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAILED_NATIVE_THRESHOLDS_V1",
            "contract_digest": contract["contract_digest"],
            "run_key": run_key,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        raise


def verify_native_thresholds(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    native_external_root: Path,
    calibration_external_root: Path,
    index_external_root: Path,
    rescore_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_threshold_contract(root)
    rescore, rescore_dir, runtime = _verified_parent(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        native_external_root=native_external_root.resolve(),
        calibration_external_root=calibration_external_root.resolve(),
        index_external_root=index_external_root.resolve(),
        rescore_external_root=rescore_external_root.resolve(),
        device=device,
    )
    run_key = _run_key(contract, rescore_summary=rescore, runtime=runtime)
    run_dir = external_root.resolve() / f"native_thresholds_{run_key}"
    if (run_dir / "failure.json").is_file():
        raise ContractError("corrected native-threshold failure artifact is present")
    summary_path = run_dir / str(contract["output"]["summary_filename"])
    if not summary_path.is_file():
        raise ContractError("corrected native-threshold summary is missing")
    summary = _read_json(summary_path)
    body = dict(summary)
    digest = body.pop("artifact_digest", None)
    if (
        digest != canonical_json_sha256(body)
        or summary.get("status") != "PASS_COMPLETE_NATIVE_THRESHOLDS_V1"
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("run_key") != run_key
        or summary.get("native_rescore_artifact_digest")
        != rescore["artifact_digest"]
        or summary.get("scientific_boundary") != contract["scientific_boundary"]
        or summary.get("method") != contract["method"]
    ):
        raise ContractError("corrected native-threshold summary boundary changed")
    recomputed: dict[str, Any] = {}
    for detector, expected_count in sorted(
        contract["gates"]["exact_rows_by_detector"].items()
    ):
        metadata = rescore["outputs"][f"native_calibration_{detector}"]
        path = rescore_dir / str(metadata["filename"])
        rows = _read_jsonl(path)
        scores, audit = validate_calibration_score_rows(
            rows,
            detector=detector,
            expected_count=int(expected_count),
            block_length=int(contract["method"]["block_length"]),
        )
        threshold = compute_detector_threshold(scores, method=contract["method"])
        expected_input = summary["inputs"][detector]
        if (
            expected_input["identity_score_digest"]
            != audit["identity_score_digest"]
            or expected_input["score_vector_float64_sha256"]
            != audit["score_vector_float64_sha256"]
            or expected_input["sha256"] != sha256_file(path)
        ):
            raise ContractError("corrected native-threshold input replay changed")
        recomputed[detector] = {
            **threshold,
            "n_calibration_scores": len(scores),
            "bootstrap_rows_used": int(threshold["n_complete_blocks"])
            * int(threshold["block_length"]),
            "bootstrap_tail_rows_excluded": len(scores)
            - int(threshold["n_complete_blocks"])
            * int(threshold["block_length"]),
        }
    if recomputed != summary.get("thresholds"):
        raise ContractError("corrected native-threshold replay changed")
    expected_gates = {
        "exact_rows_by_detector": contract["gates"]["exact_rows_by_detector"],
        "nonfinite_scores": 0,
        "candidate_scores_used": False,
        "historical_scores_used": False,
        "historical_thresholds_used": False,
    }
    if summary.get("gates") != expected_gates:
        raise ContractError("corrected native-threshold gates changed")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "compute_detector_threshold",
    "load_native_threshold_contract",
    "run_native_thresholds",
    "validate_calibration_score_rows",
    "validate_native_threshold_contract",
    "verify_native_thresholds",
]
