"""Classify corrected O4a candidates with frozen native detector thresholds."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_rescore import (
    _atomic_json,
    _atomic_jsonl,
    _float32_hex,
)
from src.dante_light.o4a_corrected_native_rescore_v2 import _load_jsonl
from src.dante_light.o4a_corrected_native_thresholds import verify_native_thresholds
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.dante_light.prefilter_v5_protocol import sha256_path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_native_classification_v1.json")
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_native_classification_v1"
)
SCHEMA_VERSION = 1
CLASS_LABELS = ("BACKGROUND", "AMBIGUOUS", "ROBUST")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def validate_native_classification_contract(
    contract: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(contract))
    digest = value.pop("contract_digest", None)
    if digest != canonical_json_sha256(value):
        raise ContractError("corrected native-classification contract digest mismatch")
    if int(value.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ContractError("corrected native-classification schema changed")
    if value.get("classification") != {
        "rule": (
            "BACKGROUND if score < ci_lower; ROBUST if score > ci_upper; "
            "AMBIGUOUS otherwise"
        ),
        "lower_boundary_class": "AMBIGUOUS",
        "upper_boundary_class": "AMBIGUOUS",
        "score_field": "native_score",
        "output_field": "native_class",
    }:
        raise ContractError("corrected native-classification rule changed")
    if value.get("scientific_boundary") != {
        "candidate_population_changed": False,
        "native_scores_changed": False,
        "native_thresholds_changed": False,
        "deterministic_classes_only": True,
        "taxonomy_performed_in_this_stage": False,
        "coincidence_performed_in_this_stage": False,
        "pem_performed_in_this_stage": False,
        "historical_artifacts_immutable": True,
    }:
        raise ContractError("corrected native-classification boundary changed")
    references = value.get("references", {})
    for reference in references.values():
        path = (root / str(reference["path"])).resolve()
        if not path.is_file() or sha256_path(path) != reference["sha256"]:
            raise ContractError(
                f"corrected native-classification reference changed: {path}"
            )
    threshold_artifact = _read_json(root / str(references["native_thresholds"]["path"]))
    rescore_artifact = _read_json(root / str(references["native_rescore_v2"]["path"]))
    if value.get("parent_native_thresholds") != {
        "compact_artifact_digest": threshold_artifact.get("artifact_digest"),
        "run_artifact_digest": threshold_artifact.get("external_artifact_digest"),
        "contract_digest": threshold_artifact.get("contract_digest"),
        "run_key": threshold_artifact.get("external_run", {}).get("run_key"),
        "summary_sha256": threshold_artifact.get("external_run", {}).get(
            "summary_sha256"
        ),
    }:
        raise ContractError("corrected native-classification threshold parent changed")
    if value.get("parent_native_rescore") != {
        "compact_artifact_digest": rescore_artifact.get("artifact_digest"),
        "run_artifact_digest": threshold_artifact.get("native_rescore_artifact_digest"),
        "contract_digest": rescore_artifact.get("contract_digest"),
        "run_key": rescore_artifact.get("run_key"),
        "candidate_sha256": rescore_artifact.get("outputs", {})
        .get("primary_candidate", {})
        .get("sha256"),
        "candidate_row_digest": rescore_artifact.get("outputs", {})
        .get("primary_candidate", {})
        .get("row_digest"),
    }:
        raise ContractError("corrected native-classification rescore parent changed")
    gates = value.get("gates", {})
    expected_candidate_counts = {
        "H1": int(rescore_artifact["input_counts"]["primary_candidate"]["H1"]),
        "L1": int(rescore_artifact["input_counts"]["primary_candidate"]["L1"]),
    }
    if (
        gates.get("exact_rows_by_detector") != expected_candidate_counts
        or int(gates.get("exact_total_rows", -1))
        != sum(expected_candidate_counts.values())
        or int(gates.get("first_input_index", -1))
        != sum(
            int(count)
            for count in rescore_artifact["input_counts"]["native_calibration"].values()
        )
        or any(
            gates.get(name) is not True
            for name in (
                "fail_closed",
                "zero_duplicate_detector_gps",
                "zero_nonfinite_scores",
                "zero_prior_class_taxonomy_or_disposition_use",
            )
        )
    ):
        raise ContractError("corrected native-classification cardinality changed")
    return {"contract_digest": digest, **value}


def load_native_classification_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_native_classification_contract(
        _read_json(root / CONTRACT_REL), root=root
    )


def classify_native_score(score: float, *, lower: float, upper: float) -> str:
    values = np.asarray([score, lower, upper], dtype=np.float64)
    if not np.isfinite(values).all() or lower > upper:
        raise ContractError("corrected native-classification values are invalid")
    if score < lower:
        return "BACKGROUND"
    if score > upper:
        return "ROBUST"
    return "AMBIGUOUS"


def classify_candidate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    thresholds: Mapping[str, Mapping[str, float]],
    expected_counts: Mapping[str, int],
    expected_first_input_index: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    forbidden = {
        "native_class",
        "class",
        "robustness_class",
        "taxonomy",
        "taxonomy_family",
        "disposition",
    }
    identities: set[tuple[str, float]] = set()
    classified: list[dict[str, Any]] = []
    counts: dict[str, Counter[str]] = {
        detector: Counter() for detector in sorted(expected_counts)
    }
    for expected_index, source in enumerate(rows):
        detector = str(source.get("detector"))
        gps = float(source.get("gps_start", np.nan))
        score = float(source.get("native_score", np.nan))
        identity = (detector, gps)
        if (
            forbidden & set(source)
            or source.get("population") != "primary_candidate"
            or int(source.get("input_index", -1))
            != expected_first_input_index + expected_index
            or detector not in expected_counts
            or identity in identities
            or not np.isfinite(gps)
            or not np.isfinite(score)
            or source.get("score_float32_hex") != _float32_hex(score)
        ):
            raise ContractError("corrected native-classification input row changed")
        limit = thresholds[detector]
        label = classify_native_score(
            score,
            lower=float(limit["ci_lower"]),
            upper=float(limit["ci_upper"]),
        )
        row = {
            **dict(source),
            "native_class": label,
            "native_threshold_ci_lower": float(limit["ci_lower"]),
            "native_threshold_p99": float(limit["p99"]),
            "native_threshold_ci_upper": float(limit["ci_upper"]),
        }
        identities.add(identity)
        counts[detector][label] += 1
        classified.append(row)
    observed_by_detector = Counter(row["detector"] for row in classified)
    if observed_by_detector != Counter(
        {detector: int(count) for detector, count in expected_counts.items()}
    ):
        raise ContractError("corrected native-classification population changed")
    return classified, {
        detector: {label: int(counts[detector][label]) for label in CLASS_LABELS}
        for detector in sorted(counts)
    }


def _run_key(
    contract: Mapping[str, Any],
    *,
    threshold_summary: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> str:
    return canonical_json_sha256(
        {
            "stage": "native_classification_v1",
            "contract_digest": contract["contract_digest"],
            "native_threshold_artifact_digest": threshold_summary["artifact_digest"],
            "native_rescore_artifact_digest": threshold_summary[
                "native_rescore_artifact_digest"
            ],
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
    threshold_external_root: Path,
    device: str,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    threshold_summary, _threshold_dir = verify_native_thresholds(
        root=root,
        primary_external_root=primary_external_root,
        native_external_root=native_external_root,
        calibration_external_root=calibration_external_root,
        index_external_root=index_external_root,
        rescore_external_root=rescore_external_root,
        external_root=threshold_external_root,
        device=device,
    )
    runtime = load_canonical_runtime_contract(
        root=root, require_current=True, device=device
    )
    return threshold_summary, rescore_external_root.resolve(), runtime


def _candidate_path(
    *, contract: Mapping[str, Any], rescore_external_root: Path
) -> Path:
    return (
        rescore_external_root
        / f"native_rescore_{contract['parent_native_rescore']['run_key']}"
        / "native_candidates.jsonl"
    )


def run_native_classification(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    native_external_root: Path,
    calibration_external_root: Path,
    index_external_root: Path,
    rescore_external_root: Path,
    threshold_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_classification_contract(root)
    thresholds, rescore_root, runtime = _verified_parent(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        native_external_root=native_external_root.resolve(),
        calibration_external_root=calibration_external_root.resolve(),
        index_external_root=index_external_root.resolve(),
        rescore_external_root=rescore_external_root.resolve(),
        threshold_external_root=threshold_external_root.resolve(),
        device=device,
    )
    if (
        thresholds["artifact_digest"]
        != contract["parent_native_thresholds"]["run_artifact_digest"]
        or thresholds["native_rescore_artifact_digest"]
        != contract["parent_native_rescore"]["run_artifact_digest"]
    ):
        raise ContractError("corrected native-classification parent changed")
    run_key = _run_key(contract, threshold_summary=thresholds, runtime=runtime)
    run_dir = external_root.resolve() / f"native_classification_{run_key}"
    failure_path = run_dir / "failure.json"
    summary_path = run_dir / str(contract["output"]["summary_filename"])
    output_path = run_dir / str(contract["output"]["candidate_filename"])
    if failure_path.is_file():
        raise ContractError(
            "corrected native-classification failure artifact is present"
        )
    if summary_path.is_file():
        return verify_native_classification(
            root=root,
            primary_external_root=primary_external_root,
            native_external_root=native_external_root,
            calibration_external_root=calibration_external_root,
            index_external_root=index_external_root,
            rescore_external_root=rescore_external_root,
            threshold_external_root=threshold_external_root,
            external_root=external_root,
            device=device,
        )
    try:
        source_path = _candidate_path(
            contract=contract, rescore_external_root=rescore_root
        )
        if (
            not source_path.is_file()
            or sha256_file(source_path)
            != contract["parent_native_rescore"]["candidate_sha256"]
        ):
            raise ContractError("corrected native-classification source hash changed")
        source_rows = _load_jsonl(source_path)
        if (
            canonical_json_sha256(source_rows)
            != contract["parent_native_rescore"]["candidate_row_digest"]
        ):
            raise ContractError("corrected native-classification source rows changed")
        classified, counts = classify_candidate_rows(
            source_rows,
            thresholds=thresholds["thresholds"],
            expected_counts=contract["gates"]["exact_rows_by_detector"],
            expected_first_input_index=int(contract["gates"]["first_input_index"]),
        )
        _atomic_jsonl(output_path, classified)
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_COMPLETE_NATIVE_CLASSIFICATION_V1",
            "contract_digest": contract["contract_digest"],
            "run_key": run_key,
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
            "native_threshold_artifact_digest": thresholds["artifact_digest"],
            "native_rescore_artifact_digest": thresholds[
                "native_rescore_artifact_digest"
            ],
            "classification": contract["classification"],
            "scientific_boundary": contract["scientific_boundary"],
            "row_total": len(classified),
            "counts_by_detector_and_class": counts,
            "source": {
                "filename": source_path.name,
                "sha256": sha256_file(source_path),
                "row_digest": canonical_json_sha256(source_rows),
            },
            "output": {
                "filename": output_path.name,
                "sha256": sha256_file(output_path),
                "row_digest": canonical_json_sha256(classified),
                "size_bytes": output_path.stat().st_size,
            },
            "gates": {
                "duplicate_detector_gps": 0,
                "nonfinite_scores": 0,
                "class_labels": list(CLASS_LABELS),
                "historical_classes_read": False,
                "taxonomy_read": False,
                "disposition_read": False,
            },
        }
        summary = {**body, "artifact_digest": canonical_json_sha256(body)}
        _atomic_json(summary_path, summary)
        return summary, run_dir
    except BaseException as exc:
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAILED_NATIVE_CLASSIFICATION_V1",
            "contract_digest": contract["contract_digest"],
            "run_key": run_key,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        raise


def verify_native_classification(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    native_external_root: Path,
    calibration_external_root: Path,
    index_external_root: Path,
    rescore_external_root: Path,
    threshold_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_classification_contract(root)
    thresholds, rescore_root, runtime = _verified_parent(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        native_external_root=native_external_root.resolve(),
        calibration_external_root=calibration_external_root.resolve(),
        index_external_root=index_external_root.resolve(),
        rescore_external_root=rescore_external_root.resolve(),
        threshold_external_root=threshold_external_root.resolve(),
        device=device,
    )
    run_key = _run_key(contract, threshold_summary=thresholds, runtime=runtime)
    run_dir = external_root.resolve() / f"native_classification_{run_key}"
    if (run_dir / "failure.json").is_file():
        raise ContractError(
            "corrected native-classification failure artifact is present"
        )
    summary_path = run_dir / str(contract["output"]["summary_filename"])
    output_path = run_dir / str(contract["output"]["candidate_filename"])
    if not summary_path.is_file() or not output_path.is_file():
        raise ContractError("corrected native-classification output is missing")
    summary = _read_json(summary_path)
    body = dict(summary)
    digest = body.pop("artifact_digest", None)
    if (
        digest != canonical_json_sha256(body)
        or summary.get("status") != "PASS_COMPLETE_NATIVE_CLASSIFICATION_V1"
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("run_key") != run_key
        or summary.get("classification") != contract["classification"]
        or summary.get("scientific_boundary") != contract["scientific_boundary"]
    ):
        raise ContractError("corrected native-classification summary changed")
    source_path = _candidate_path(contract=contract, rescore_external_root=rescore_root)
    source_rows = _load_jsonl(source_path)
    expected_rows, expected_counts = classify_candidate_rows(
        source_rows,
        thresholds=thresholds["thresholds"],
        expected_counts=contract["gates"]["exact_rows_by_detector"],
        expected_first_input_index=int(contract["gates"]["first_input_index"]),
    )
    observed_rows = _load_jsonl(output_path)
    if (
        observed_rows != expected_rows
        or summary.get("row_total") != len(expected_rows)
        or summary.get("counts_by_detector_and_class") != expected_counts
        or summary.get("output", {}).get("sha256") != sha256_file(output_path)
        or summary.get("output", {}).get("row_digest")
        != canonical_json_sha256(observed_rows)
    ):
        raise ContractError("corrected native-classification replay changed")
    expected_gates = {
        "duplicate_detector_gps": 0,
        "nonfinite_scores": 0,
        "class_labels": list(CLASS_LABELS),
        "historical_classes_read": False,
        "taxonomy_read": False,
        "disposition_read": False,
    }
    if summary.get("gates") != expected_gates:
        raise ContractError("corrected native-classification gates changed")
    return summary, run_dir


__all__ = [
    "CLASS_LABELS",
    "DEFAULT_EXTERNAL_ROOT",
    "classify_candidate_rows",
    "classify_native_score",
    "load_native_classification_contract",
    "run_native_classification",
    "validate_native_classification_contract",
    "verify_native_classification",
]
