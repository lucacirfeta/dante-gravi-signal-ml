"""Post-hoc diagnostics for the closed DANTE-Light L4 v4 development result.

The diagnostics in this module are descriptive and hypothesis-generating.
They cannot change the frozen v4 decision, authorize confirmation access, or
inspect O4b outcomes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from scipy import stats
from sklearn.metrics import roc_auc_score

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_protocol import PHASE_FEATURES, repository_reference
from src.dante_light.prefilter_v4_screening import (
    _load_development_ledger,
    _portable_numbers,
    load_screening_result,
)


REQUIRED_ROLES = ("background", "robust_candidate", "known_glitch", "injection")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_digest_artifact(path: Path, digest_field: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid diagnostic dependency {path}: {exc}") from exc
    body = dict(payload)
    declared = body.pop(digest_field, None)
    if declared != canonical_json_sha256(body):
        raise ContractError(f"diagnostic dependency digest mismatch: {path}")
    return payload


def _distribution(values: np.ndarray) -> dict[str, float | int]:
    if values.ndim != 1 or values.size == 0 or not np.all(np.isfinite(values)):
        raise ContractError("v4 diagnostic distribution is invalid")
    q25, median, q75 = np.quantile(values, [0.25, 0.5, 0.75])
    return {
        "n": int(values.size),
        "median": float(median),
        "q25": float(q25),
        "q75": float(q75),
        "iqr": float(q75 - q25),
        "unique_value_count": int(np.unique(values).size),
    }


def _feature_values(rows: list[dict[str, Any]], feature: str) -> np.ndarray:
    try:
        values = np.asarray(
            [float(row["features"]["values"][feature]) for row in rows],
            dtype=np.float64,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError(f"invalid v4 diagnostic feature: {feature}") from exc
    if values.size != len(rows) or not np.all(np.isfinite(values)):
        raise ContractError(f"non-finite v4 diagnostic feature: {feature}")
    return values


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    coefficient = float(stats.spearmanr(left, right).statistic)
    if not np.isfinite(coefficient):
        raise ContractError("v4 diagnostic Spearman coefficient is non-finite")
    return coefficient


def _candidate(records: list[Mapping[str, Any]], feature_set: str) -> Mapping[str, Any]:
    matches = [record for record in records if record.get("feature_set") == feature_set]
    if len(matches) != 1:
        raise ContractError(f"expected exactly one {feature_set} diagnostic candidate")
    return matches[0]


def analyze_v4_development_diagnostics(
    *,
    root: Path,
    ledgers: Mapping[str, str | Path],
    screening_path: str | Path,
    feasibility_path: str | Path,
    v2_diagnostics_path: str | Path,
    v3_summary_path: str | Path,
) -> dict[str, Any]:
    """Build a sealed, non-gating diagnostic from development-only evidence."""

    if set(ledgers) != set(REQUIRED_ROLES):
        raise ContractError("v4 diagnostics require exactly four development ledgers")
    resolved_root = root.resolve()
    all_rows: list[dict[str, Any]] = []
    source_ledgers: list[dict[str, Any]] = []
    for role in REQUIRED_ROLES:
        path = Path(ledgers[role]).resolve()
        ledger, rows = _load_development_ledger(path)
        if ledger.get("role") != role or any(row.get("roles") != [role] for row in rows):
            raise ContractError(f"v4 diagnostic role mismatch: {role}")
        all_rows.extend(rows)
        source_ledgers.append(
            {
                "role": role,
                "ledger": repository_reference(resolved_root, path),
                "rows_sha256": ledger["rows_sha256"],
                "row_count": len(rows),
            }
        )

    screening_source = Path(screening_path).resolve()
    screening = load_screening_result(screening_source)
    if screening.get("status") != "V4_NOT_READY":
        raise ContractError("v4 post-hoc diagnostics require a closed negative screen")
    feasibility_source = Path(feasibility_path).resolve()
    try:
        feasibility = json.loads(feasibility_source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v4 feasibility summary: {exc}") from exc
    if feasibility.get("outcome_access") != {
        "development_labels": False,
        "o4b": False,
        "reserved_confirmation": False,
    }:
        raise ContractError("v4 feasibility outcome boundary mismatch")
    v2_source = Path(v2_diagnostics_path).resolve()
    v2 = _load_digest_artifact(v2_source, "artifact_digest")
    v3_source = Path(v3_summary_path).resolve()
    v3 = _load_digest_artifact(v3_source, "summary_digest")
    if v2.get("eligible_for_pass_fail_gate") is not False or v2.get("o4b_outcomes_used") != []:
        raise ContractError("v2 comparison source violates its diagnostic boundary")
    if v3.get("sealed_boundaries", {}).get("o4b_outcomes_used") != []:
        raise ContractError("v3 comparison source violates its sealed boundary")

    background = [row for row in all_rows if row["roles"] == ["background"]]
    protected = [row for row in all_rows if row["roles"] != ["background"]]
    if len(background) + len(protected) != len(all_rows):
        raise ContractError("v4 diagnostic role partition is incomplete")
    target = np.asarray(
        [0 if row["roles"] == ["background"] else 1 for row in all_rows],
        dtype=np.int8,
    )

    univariate: dict[str, Any] = {}
    for feature in PHASE_FEATURES:
        values = _feature_values(all_rows, feature)
        raw_auc = float(roc_auc_score(target, values))
        univariate[feature] = {
            "raw_roc_auc": raw_auc,
            "orientation_free_roc_auc": max(raw_auc, 1.0 - raw_auc),
            "all_unique_value_count": int(np.unique(values).size),
            "background": _distribution(_feature_values(background, feature)),
            "protected": _distribution(_feature_values(protected, feature)),
        }

    strata: dict[str, Any] = {}
    for role, morphology in sorted(
        {(str(row["roles"][0]), str(row["morphology"])) for row in all_rows}
    ):
        rows = [
            row
            for row in all_rows
            if row["roles"] == [role] and row["morphology"] == morphology
        ]
        strata[f"{role}/{morphology}"] = {
            "n": len(rows),
            "phase_frequency_time_spearman_median": float(
                np.median(_feature_values(rows, "phase_frequency_time_spearman"))
            ),
            "phase_cubic_circular_residual_median": float(
                np.median(_feature_values(rows, "phase_cubic_circular_residual"))
            ),
            "phase_inspiral_coordinate_residual_median": float(
                np.median(_feature_values(rows, "phase_inspiral_coordinate_residual"))
            ),
        }

    injection_rows = [row for row in all_rows if row["roles"] == ["injection"]]
    injection_snr: dict[str, Any] = {}
    for morphology in sorted({str(row["morphology"]) for row in injection_rows}):
        rows = [row for row in injection_rows if row["morphology"] == morphology]
        try:
            snr = np.asarray(
                [row["preparation_metadata"]["measured_snr_diagnostic_only"] for row in rows],
                dtype=np.float64,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("v4 injection SNR diagnostic metadata is invalid") from exc
        residual = _feature_values(rows, "phase_inspiral_coordinate_residual")
        injection_snr[morphology] = {
            "snr": _distribution(snr),
            "inspiral_residual_snr_spearman": _spearman(residual, snr),
        }

    phase_probe = feasibility["phase_probe"]
    v2_spectral = _candidate(v2["auc_by_candidate"], "spectral_evolution")
    v3_primary = v3["candidate_results"]["signed_plus_ridge"]
    v4_primary = screening["screening"]["candidate"]
    result: dict[str, Any] = {
        "schema_version": 4,
        "status": "POSTHOC_DIAGNOSTIC_ONLY",
        "scientific_mode": "closed_v4_development_hypothesis_generating",
        "eligible_for_pass_fail_gate": False,
        "updates_frozen_screening": False,
        "routing_enabled": False,
        "confirmation_values_used": [],
        "o4b_outcomes_used": [],
        "source_screening": {
            **repository_reference(resolved_root, screening_source),
            "artifact_digest": screening["artifact_digest"],
        },
        "source_feasibility": repository_reference(resolved_root, feasibility_source),
        "source_ledgers": source_ledgers,
        "development_counts": {
            "background": len(background),
            "protected": len(protected),
            "total": len(all_rows),
        },
        "synthetic_to_real": {
            "ideal_ordered_chirp": {
                "phase_frequency_time_spearman": phase_probe["ordered_chirp_spearman"],
                "phase_cubic_circular_residual": phase_probe["ordered_chirp_cubic_residual"],
            },
            "phase_scrambled_controls": {
                "phase_frequency_time_spearman_p95": phase_probe["scrambled_spearman_p95"],
                "phase_cubic_circular_residual_median": phase_probe[
                    "scrambled_cubic_residual_median"
                ],
            },
            "real_development_background": {
                "phase_frequency_time_spearman_median": univariate[
                    "phase_frequency_time_spearman"
                ]["background"]["median"],
                "phase_cubic_circular_residual_median": univariate[
                    "phase_cubic_circular_residual"
                ]["background"]["median"],
            },
            "real_development_protected": {
                "phase_frequency_time_spearman_median": univariate[
                    "phase_frequency_time_spearman"
                ]["protected"]["median"],
                "phase_cubic_circular_residual_median": univariate[
                    "phase_cubic_circular_residual"
                ]["protected"]["median"],
            },
        },
        "univariate_feature_diagnostics": univariate,
        "stratum_phase_summaries": strata,
        "injection_snr_diagnostics": injection_snr,
        "cross_protocol_descriptive_comparison": {
            "controlled_head_to_head": False,
            "comparability_warning": (
                "v2 and v3 share 962 development windows; v4 uses a fresh 1010-window "
                "development cohort, so differences cannot be attributed only to representation"
            ),
            "v2_spectral_baseline": {
                "development_n": int(v2["development_n"]),
                "overall_roc_auc": v2_spectral["roc_auc"]["overall"],
                "effective_background_call_reduction": v2_spectral[
                    "frozen_constrained_context"
                ]["oof_effective_development_call_reduction"],
                "source": repository_reference(resolved_root, v2_source),
            },
            "v3_signed_plus_ridge_primary": {
                "development_n": int(v3["development_counts"]["total"]),
                "overall_roc_auc": v3_primary["overall_roc_auc"],
                "effective_background_call_reduction": v3_primary[
                    "oof_development_background_call_reduction"
                ],
                "source": repository_reference(resolved_root, v3_source),
            },
            "v4_phase_primary": {
                "development_n": len(all_rows),
                "overall_roc_auc": v4_primary["auc_diagnostics"]["overall"]["auc"],
                "effective_background_call_reduction": v4_primary[
                    "oof_development_background_call_reduction"
                ],
                "source": repository_reference(resolved_root, screening_source),
            },
        },
        "interpretation_boundary": {
            "supported": (
                "the frozen global analytic-phase summaries did not transfer the ideal "
                "synthetic phase-ordering response into safe real-strain routing separation"
            ),
            "plausible_not_established": (
                "broadband non-Gaussian non-stationary strain and global 32-second phase "
                "summaries may destabilize or dilute analytic instantaneous phase"
            ),
            "does_not_establish": [
                "phase information is generally useless",
                "all phase-aware representations fail",
                "the cross-protocol performance difference is caused only by representation",
                "confirmation or O4b performance",
            ],
        },
        "analyzer": repository_reference(
            resolved_root, resolved_root / "src/dante_light/prefilter_v4_diagnostics.py"
        ),
    }
    result = _portable_numbers(result)
    result["artifact_digest"] = canonical_json_sha256(result)
    return result


def write_v4_development_diagnostics(result: Mapping[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def verify_v4_development_diagnostics(
    saved_path: str | Path,
    **analysis_arguments: Any,
) -> dict[str, Any]:
    source = Path(saved_path)
    try:
        saved = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v4 diagnostic artifact: {exc}") from exc
    body = dict(saved)
    if body.pop("artifact_digest", None) != canonical_json_sha256(body):
        raise ContractError("v4 diagnostic artifact digest mismatch")
    recomputed = analyze_v4_development_diagnostics(**analysis_arguments)
    if saved != recomputed:
        raise ContractError("v4 diagnostic artifact does not match exact recomputation")
    return {
        "status": "PASS",
        "scientific_status": saved["status"],
        "eligible_for_pass_fail_gate": False,
        "confirmation_values_used": [],
        "o4b_outcomes_used": [],
        "artifact_digest": saved["artifact_digest"],
    }
