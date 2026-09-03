"""Fail-closed normalized v1-versus-corrected O4a comparison."""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import adjusted_rand_score

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_rescore import _atomic_json, _atomic_jsonl
from src.dante_light.o4a_corrected_native_rescore_v2 import _load_jsonl
from src.dante_light.prefilter_v5_protocol import sha256_path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_final_comparison_v2.json")
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_final_comparison_v2"
)
SCHEMA_VERSION = 1

Identity = tuple[str, float]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _platform_path(value: str | Path) -> Path:
    text = str(value).replace("\\", "/")
    if os.name != "nt" and len(text) >= 3 and text[1:3] == ":/":
        return Path("/mnt") / text[0].lower() / text[3:]
    return Path(value)


def _identity(row: Mapping[str, Any], *, gps_field: str = "gps_start") -> Identity:
    detector = str(row.get("detector", ""))
    gps = float(row.get(gps_field, np.nan))
    if detector not in {"H1", "L1"} or not np.isfinite(gps):
        raise ContractError("invalid detector+GPS identity")
    return detector, gps


def _identity_object(identity: Identity) -> dict[str, Any]:
    return {"detector": identity[0], "gps_start": identity[1]}


def _unique_index(
    rows: Sequence[Mapping[str, Any]], *, gps_field: str = "gps_start"
) -> dict[Identity, Mapping[str, Any]]:
    result: dict[Identity, Mapping[str, Any]] = {}
    for row in rows:
        identity = _identity(row, gps_field=gps_field)
        if identity in result:
            raise ContractError(f"duplicate detector+GPS identity: {identity}")
        result[identity] = row
    return result


def _shift_gps_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    offset_s: float,
    gps_field: str = "gps_start",
) -> list[dict[str, Any]]:
    if not np.isfinite(offset_s):
        raise ContractError("historical GPS normalization offset is invalid")
    shifted = []
    for row in rows:
        identity = _identity(row, gps_field=gps_field)
        value = dict(row)
        value[gps_field] = identity[1] + float(offset_s)
        shifted.append(value)
    return shifted


def _require_historical_candidate_subset(
    rows: Sequence[Mapping[str, Any]],
    candidate_identities: set[Identity],
    *,
    gps_field: str = "gps_start",
    population: str,
) -> None:
    identities = set(_unique_index(rows, gps_field=gps_field))
    outside = identities - candidate_identities
    if outside:
        raise ContractError(
            f"historical {population} contains identities outside the frozen "
            "candidate catalogue"
        )


def _repo_reference(root: Path, reference: Mapping[str, Any]) -> Path:
    path = (root / str(reference["path"])).resolve()
    if not path.is_file() or sha256_path(path) != str(reference["sha256"]):
        raise ContractError(f"final-comparison reference changed: {path}")
    return path


def validate_final_comparison_contract(
    contract: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(contract))
    digest = value.pop("contract_digest", None)
    if digest != canonical_json_sha256(value):
        raise ContractError("final-comparison contract digest mismatch")
    if int(value.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ContractError("final-comparison schema changed")
    if value.get("contract_id") != "dante-o4a-corrected-final-comparison-v2":
        raise ContractError("final-comparison contract identity changed")
    if value.get("status") != "FROZEN_BEFORE_FINAL_COMPARISON":
        raise ContractError("final-comparison freeze status changed")
    identity_contract = value.get("identity")
    if identity_contract != {
        "comparison_fields": ["detector", "gps_start"],
        "gps_equality": "exact_float_value_after_declared_normalization",
        "cross_detector_matching": False,
        "corrected_semantics": "analysis_window_start",
        "historical_normalization": {
            "source_semantics": "padded_context_start",
            "target_semantics": "analysis_window_start",
            "offset_s": 4.0,
            "scope": "frozen_candidate_catalogue_and_verified_downstream_subsets",
            "historical_expected_total": 10429,
            "calibration_identities_in_scope": False,
            "downstream_subset_membership_required": [
                "coincidence_events",
                "pem_targets",
                "pem_verdicts",
            ],
        },
    }:
        raise ContractError("final-comparison identity changed")
    if value.get("candidate_comparison") != {
        "population": "exact_detector_normalized_analysis_gps_union",
        "historical_expected_total": 10429,
        "corrected_expected_total": 10942,
        "score_delta": {
            "direction": "corrected_minus_historical",
            "historical_field": "native_score_idxq4_64_queryq4_64",
            "corrected_field": "native_score",
            "population": "exact_shared_normalized_identities",
            "descriptive_only": True,
            "equivalence_claim": False,
        },
        "class_transition": {
            "historical_field": "robustness_class_idxq4_64_queryq4_64",
            "corrected_field": "native_class",
            "labels": ["BACKGROUND", "AMBIGUOUS", "ROBUST"],
            "population": "exact_shared_normalized_identities",
        },
    }:
        raise ContractError("final-comparison candidate method changed")
    if value.get("taxonomy_comparison") != {
        "metric": "adjusted_rand_score",
        "metric_source": "sklearn.metrics.adjusted_rand_score",
        "permutation_invariant": True,
        "population": "exact_shared_normalized_identities",
        "historical_field": "global_family_id",
        "corrected_field": "global_family_id",
        "singletons_included": True,
        "physical_coincidence_interpretation": False,
    }:
        raise ContractError("final-comparison taxonomy method changed")
    if value.get("coincidence_comparison") != {
        "mode": "identity_set_accounting_only",
        "historical_exceeder_rule": "cc_onsource_strictly_greater_than_recorded_cc_null_max_p99",
        "corrected_exceeder_field": "exceeds_primary_threshold",
        "statistic_delta_per_event": False,
        "threshold_equivalence_claim": False,
        "global_significance_claim": False,
        "reason": "candidate populations, localization, and pooled null thresholds differ",
    }:
        raise ContractError("final-comparison coincidence boundary changed")
    if value.get("pem_comparison") != {
        "mode": "exact_identity_overlap_then_fail_closed",
        "aggregate_verdict_rate_comparison_when_disjoint": False,
        "astrophysical_confirmation_claim": False,
    }:
        raise ContractError("final-comparison PEM boundary changed")
    if value.get("historical_singletons") != [
        {
            "name": "historical_h1_singleton",
            "historical_catalog_identity": {
                "detector": "H1",
                "gps_start": 1369305276.0,
            },
            "expected_analysis_identity": {
                "detector": "H1",
                "gps_start": 1369305280.0,
            },
        },
        {
            "name": "historical_l1_forum_singleton",
            "historical_catalog_identity": {
                "detector": "L1",
                "gps_start": 1382955228.0,
            },
            "expected_analysis_identity": {
                "detector": "L1",
                "gps_start": 1382955232.0,
            },
            "localized_feature_gps": 1382955253.17,
        },
    ]:
        raise ContractError("final-comparison singleton identities changed")
    if value.get("scientific_boundary") != {
        "historical_artifacts_immutable": True,
        "corrected_artifacts_immutable": True,
        "no_cross_null_statistic_comparison": True,
        "no_post_hoc_candidate_pairing": True,
        "historical_gps_normalization_predeclared": True,
        "calibration_identities_excluded_from_gps_normalization": True,
        "no_global_significance_claim": True,
        "pem_is_not_astrophysical_confirmation": True,
        "future_full_pipeline_time_slide_null_required": True,
        "operational_validation_claim": False,
    }:
        raise ContractError("final-comparison scientific boundary changed")
    if value.get("output") != {
        "root": "E:/dante_cache/dante_light/o4a_corrected_final_comparison_v2",
        "summary_filename": "final_comparison_summary.json",
        "shared_filename": "shared_candidate_transitions.jsonl",
        "removed_filename": "historical_only_candidates.jsonl",
        "new_filename": "corrected_only_candidates.jsonl",
        "singletons_filename": "historical_singleton_rechecks.json",
        "historical_artifacts_overwritten": False,
        "large_outputs_committed_to_git": False,
    }:
        raise ContractError("final-comparison output changed")
    for reference in value.get("references", {}).values():
        _repo_reference(root, reference)
    audit = _read_json(
        _repo_reference(root, value["references"]["gps_identity_audit"])
    )
    if (
        audit.get("status")
        != "PASS_SCOPED_CANDIDATE_PLUS4_WITH_CALIBRATION_EDGE_EXCEPTION"
        or audit.get("candidate_catalogue", {}).get("rows") != 10429
        or audit.get("candidate_catalogue", {}).get("offset_counts_s")
        != {"4.0": 10429}
        or audit.get("candidate_catalogue", {}).get("edge_rows") != 169
        or audit.get("candidate_catalogue", {}).get("edge_offset_counts_s")
        != {"4.0": 169}
        or audit.get("primary_calibration", {}).get("offset_counts_s")
        != {"0.0": 331, "4.0": 39640}
        or audit.get("scientific_boundary", {}).get(
            "candidate_transform_may_not_be_reused_for_calibration"
        )
        is not True
    ):
        raise ContractError("GPS identity audit no longer authorizes scoped +4 s")
    return {"contract_digest": digest, **value}


def load_final_comparison_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_final_comparison_contract(
        _read_json(root / CONTRACT_REL), root=root
    )


def compare_candidate_catalogues(
    historical_rows: Sequence[Mapping[str, Any]],
    corrected_rows: Sequence[Mapping[str, Any]],
    historical_taxonomy_rows: Sequence[Mapping[str, Any]],
    corrected_taxonomy_rows: Sequence[Mapping[str, Any]],
    *,
    historical_gps_offset_s: float = 0.0,
) -> tuple[
    dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    historical_shifted = _shift_gps_rows(
        historical_rows, offset_s=historical_gps_offset_s
    )
    historical_taxonomy_shifted = _shift_gps_rows(
        historical_taxonomy_rows, offset_s=historical_gps_offset_s
    )
    historical = _unique_index(historical_shifted)
    corrected = _unique_index(corrected_rows)
    historical_taxonomy = _unique_index(historical_taxonomy_shifted)
    corrected_taxonomy = _unique_index(corrected_taxonomy_rows)
    if set(historical) != set(historical_taxonomy):
        raise ContractError("historical score/taxonomy identities differ")
    if set(corrected) != set(corrected_taxonomy):
        raise ContractError("corrected classification/taxonomy identities differ")

    shared_keys = sorted(
        set(historical) & set(corrected), key=lambda item: (item[1], item[0])
    )
    removed_keys = sorted(
        set(historical) - set(corrected), key=lambda item: (item[1], item[0])
    )
    new_keys = sorted(
        set(corrected) - set(historical), key=lambda item: (item[1], item[0])
    )
    labels = ("BACKGROUND", "AMBIGUOUS", "ROBUST")
    transitions = {old: {new: 0 for new in labels} for old in labels}
    shared: list[dict[str, Any]] = []
    deltas: list[float] = []
    historical_families: list[str] = []
    corrected_families: list[str] = []
    for identity in shared_keys:
        old = historical[identity]
        new = corrected[identity]
        old_class = str(old["robustness_class_idxq4_64_queryq4_64"])
        new_class = str(new["native_class"])
        if old_class not in labels or new_class not in labels:
            raise ContractError("unexpected native class")
        old_score = float(old["native_score_idxq4_64_queryq4_64"])
        new_score = float(new["native_score"])
        if not np.isfinite([old_score, new_score]).all():
            raise ContractError("non-finite shared score")
        delta = new_score - old_score
        transitions[old_class][new_class] += 1
        deltas.append(delta)
        old_family = str(historical_taxonomy[identity]["global_family_id"])
        new_family = str(corrected_taxonomy[identity]["global_family_id"])
        historical_families.append(old_family)
        corrected_families.append(new_family)
        shared.append(
            {
                **_identity_object(identity),
                "historical_catalog_gps_start": identity[1]
                - float(historical_gps_offset_s),
                "historical_score": old_score,
                "corrected_score": new_score,
                "score_delta_corrected_minus_historical": delta,
                "historical_class": old_class,
                "corrected_class": new_class,
                "historical_family": old_family,
                "corrected_family": new_family,
            }
        )
    delta_array = np.asarray(deltas, dtype=np.float64)
    score_summary = {
        "count": len(deltas),
        "minimum": float(delta_array.min()) if len(delta_array) else None,
        "q25": float(np.quantile(delta_array, 0.25)) if len(delta_array) else None,
        "median": float(np.median(delta_array)) if len(delta_array) else None,
        "mean": float(delta_array.mean()) if len(delta_array) else None,
        "q75": float(np.quantile(delta_array, 0.75)) if len(delta_array) else None,
        "maximum": float(delta_array.max()) if len(delta_array) else None,
        "maximum_absolute": float(np.abs(delta_array).max())
        if len(delta_array)
        else None,
        "descriptive_only": True,
    }
    family_sizes_historical = Counter(
        str(row["global_family_id"]) for row in historical_taxonomy_rows
    )
    family_sizes_corrected = Counter(
        str(row["global_family_id"]) for row in corrected_taxonomy_rows
    )
    metrics = {
        "historical_total": len(historical),
        "corrected_total": len(corrected),
        "shared_total": len(shared_keys),
        "historical_only_total": len(removed_keys),
        "corrected_only_total": len(new_keys),
        "union_total": len(set(historical) | set(corrected)),
        "score_delta": score_summary,
        "class_transitions": transitions,
        "class_changed_total": sum(
            count
            for old, row in transitions.items()
            for new, count in row.items()
            if old != new
        ),
        "taxonomy": {
            "population": "exact_shared_normalized_identities",
            "shared_total": len(shared_keys),
            "adjusted_rand_index": float(
                adjusted_rand_score(historical_families, corrected_families)
            )
            if shared_keys
            else None,
            "historical_family_count_all": len(family_sizes_historical),
            "historical_largest_family_all": max(family_sizes_historical.values()),
            "historical_singleton_count_all": sum(
                size == 1 for size in family_sizes_historical.values()
            ),
            "corrected_family_count_all": len(family_sizes_corrected),
            "corrected_largest_family_all": max(family_sizes_corrected.values()),
            "corrected_singleton_count_all": sum(
                size == 1 for size in family_sizes_corrected.values()
            ),
            "physical_coincidence_interpretation": False,
        },
    }
    removed = [
        {
            **_identity_object(identity),
            "historical_catalog_gps_start": identity[1]
            - float(historical_gps_offset_s),
        }
        for identity in removed_keys
    ]
    added = [_identity_object(identity) for identity in new_keys]
    return metrics, shared, removed, added


def compare_coincidence_sets(
    historical: Mapping[str, Any],
    corrected_rows: Sequence[Mapping[str, Any]],
    *,
    historical_candidate_identities: set[Identity] | None = None,
    historical_gps_offset_s: float = 0.0,
) -> dict[str, Any]:
    events = list(historical.get("events", []))
    if historical_candidate_identities is not None:
        _require_historical_candidate_subset(
            events,
            historical_candidate_identities,
            gps_field="gps",
            population="coincidence events",
        )
    shifted_events = _shift_gps_rows(
        events, offset_s=historical_gps_offset_s, gps_field="gps"
    )
    hist_measured = _unique_index(shifted_events, gps_field="gps")
    threshold = float(historical["summary"]["cc_null_max_p99"])
    hist_exceeders = {
        identity
        for identity, row in hist_measured.items()
        if float(row["cc_onsource"]) > threshold
    }
    corr_measured: set[Identity] = set()
    corr_exceeders: set[Identity] = set()
    all_corrected = _unique_index(corrected_rows)
    for identity, row in all_corrected.items():
        if row.get("measurement_status") == "MEASURED":
            corr_measured.add(identity)
            if row.get("exceeds_primary_threshold") is True:
                corr_exceeders.add(identity)
    return {
        "mode": "identity_set_accounting_only",
        "historical": {
            "catalogue_total": int(historical["summary"]["n_catalogue"]),
            "measured_total": len(hist_measured),
            "recorded_null_max_p99": threshold,
            "threshold_exceeder_total": len(hist_exceeders),
        },
        "corrected": {
            "seed_total": len(all_corrected),
            "measured_total": len(corr_measured),
            "threshold_exceeder_total": len(corr_exceeders),
        },
        "measured_identity_overlap": len(set(hist_measured) & corr_measured),
        "threshold_exceeder_identity_overlap": len(hist_exceeders & corr_exceeders),
        "historical_gps_normalization_offset_s": float(historical_gps_offset_s),
        "threshold_equivalence_claim": False,
        "global_significance_claim": False,
    }


def compare_pem_sets(
    historical_targets: Sequence[Mapping[str, Any]],
    historical_verdicts: Sequence[Mapping[str, Any]],
    corrected_targets: Sequence[Mapping[str, Any]],
    *,
    historical_candidate_identities: set[Identity] | None = None,
    historical_gps_offset_s: float = 0.0,
) -> dict[str, Any]:
    if historical_candidate_identities is not None:
        _require_historical_candidate_subset(
            historical_targets,
            historical_candidate_identities,
            population="PEM targets",
        )
        _require_historical_candidate_subset(
            historical_verdicts,
            historical_candidate_identities,
            population="PEM verdicts",
        )
    old_targets = set(
        _unique_index(
            _shift_gps_rows(
                historical_targets, offset_s=historical_gps_offset_s
            )
        )
    )
    old_verdicts = set(
        _unique_index(
            _shift_gps_rows(
                historical_verdicts, offset_s=historical_gps_offset_s
            )
        )
    )
    new_targets = set(_unique_index(corrected_targets))
    overlap = old_targets & new_targets
    return {
        "historical_target_total": len(old_targets),
        "historical_verdict_total": len(old_verdicts),
        "corrected_target_total": len(new_targets),
        "detector_gps_overlap": len(overlap),
        "outcome_comparison_performed": False,
        "disposition": (
            "IDENTITY_OVERLAP_PRESENT_OUTCOMES_NOT_CROSS_CONTRACT_COMPARABLE"
            if overlap
            else "NOT_COMPARABLE_DISJOINT_TARGET_POPULATIONS"
        ),
        "aggregate_verdict_rate_comparison_performed": False,
        "historical_gps_normalization_offset_s": float(historical_gps_offset_s),
    }


def recheck_historical_singletons(
    cases: Sequence[Mapping[str, Any]],
    historical_rows: Sequence[Mapping[str, Any]],
    corrected_rows: Sequence[Mapping[str, Any]],
    historical_taxonomy_rows: Sequence[Mapping[str, Any]],
    corrected_taxonomy_rows: Sequence[Mapping[str, Any]],
    corrected_coincidence_rows: Sequence[Mapping[str, Any]],
    corrected_pem_rows: Sequence[Mapping[str, Any]],
    *,
    historical_gps_offset_s: float = 0.0,
) -> list[dict[str, Any]]:
    historical = _unique_index(historical_rows)
    corrected = _unique_index(corrected_rows)
    historical_taxonomy = _unique_index(historical_taxonomy_rows)
    corrected_taxonomy = _unique_index(corrected_taxonomy_rows)
    coincidence = _unique_index(corrected_coincidence_rows)
    normalized_pem_rows: list[dict[str, Any]] = []
    for result in corrected_pem_rows:
        target = result.get("target")
        if not isinstance(target, Mapping):
            raise ContractError(
                "corrected PEM result is missing nested target identity"
            )
        normalized_pem_rows.append(
            {
                "detector": target.get("detector"),
                "gps_start": target.get("gps_start"),
                "population": target.get("population"),
                "verdict_tier": result.get("verdict_tier"),
            }
        )
    pem = _unique_index(normalized_pem_rows)
    output: list[dict[str, Any]] = []
    for case in cases:
        historical_catalog_identity = (
            str(case["historical_catalog_identity"]["detector"]),
            float(case["historical_catalog_identity"]["gps_start"]),
        )
        normalized_identity = (
            historical_catalog_identity[0],
            historical_catalog_identity[1] + float(historical_gps_offset_s),
        )
        expected_identity = (
            str(case["expected_analysis_identity"]["detector"]),
            float(case["expected_analysis_identity"]["gps_start"]),
        )
        if normalized_identity != expected_identity:
            raise ContractError("historical singleton normalization mismatch")
        old = historical.get(historical_catalog_identity)
        if old is None:
            raise ContractError("frozen historical singleton missing from v1")
        old_taxonomy = historical_taxonomy[historical_catalog_identity]
        corrected_matches = (
            [normalized_identity] if normalized_identity in corrected else []
        )
        match_rows = []
        for identity in corrected_matches:
            row = corrected[identity]
            tax = corrected_taxonomy[identity]
            coincidence_row = coincidence.get(identity)
            pem_row = pem.get(identity)
            match_rows.append(
                {
                    **_identity_object(identity),
                    "match_role": "exact_normalized_analysis_identity",
                    "native_class": str(row["native_class"]),
                    "native_score": float(row["native_score"]),
                    "global_family_id": str(tax["global_family_id"]),
                    "coincidence": None
                    if coincidence_row is None
                    else {
                        "measurement_status": coincidence_row.get("measurement_status"),
                        "exceeds_primary_threshold": coincidence_row.get(
                            "exceeds_primary_threshold"
                        ),
                        "population": coincidence_row.get("population"),
                    },
                    "pem": None
                    if pem_row is None
                    else {
                        "population": pem_row.get("population"),
                        "verdict_tier": pem_row.get("verdict_tier"),
                    },
                }
            )
        output.append(
            {
                "name": str(case["name"]),
                "historical_catalog_identity": _identity_object(
                    historical_catalog_identity
                ),
                "normalized_analysis_identity": _identity_object(normalized_identity),
                "localized_feature_gps": case.get("localized_feature_gps"),
                "historical": {
                    "native_class": str(old["robustness_class_idxq4_64_queryq4_64"]),
                    "native_score": float(old["native_score_idxq4_64_queryq4_64"]),
                    "global_family_id": str(old_taxonomy["global_family_id"]),
                },
                "corrected_normalized_identity_present": (
                    normalized_identity in corrected
                ),
                "corrected_matches": match_rows,
            }
        )
    return output


def _load_and_verify_jsonl(path: Path, spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _load_jsonl(path)
    if (
        sha256_file(path) != str(spec["sha256"])
        or canonical_json_sha256(rows) != str(spec["row_digest"])
        or len(rows) != int(spec["row_total"])
    ):
        raise ContractError(f"final-comparison JSONL changed: {path}")
    return rows


def _validate_historical_score_consistency(
    taxonomy_rows: Sequence[Mapping[str, Any]],
    score_rows: Sequence[Mapping[str, Any]],
) -> None:
    taxonomy = _unique_index(taxonomy_rows)
    scores = _unique_index(score_rows)
    if set(taxonomy) != set(scores):
        raise ContractError("historical taxonomy/DSD score identities differ")
    for identity in taxonomy:
        taxonomy_row = taxonomy[identity]
        score_row = scores[identity]
        if str(taxonomy_row["robustness_class_idxq4_64_queryq4_64"]) != str(
            score_row["class"]
        ) or float(taxonomy_row["native_score_idxq4_64_queryq4_64"]) != float(
            score_row["score"]
        ):
            raise ContractError("historical taxonomy/DSD score payload differs")


def _external_run_dir(root: Path, prefix: str, run_key: str) -> Path:
    return root.resolve() / f"{prefix}_{run_key}"


def _load_inputs(root: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    refs = contract["references"]
    historical_taxonomy = _read_csv(root / refs["historical_taxonomy"]["path"])
    historical_scores = _read_csv(root / refs["historical_scores"]["path"])
    historical_coincidence = _read_json(root / refs["historical_coincidence"]["path"])
    historical_pem_targets = _read_csv(root / refs["historical_pem_targets"]["path"])
    historical_pem_verdicts = _read_csv(root / refs["historical_pem_verdicts"]["path"])
    _validate_historical_score_consistency(historical_taxonomy, historical_scores)

    corrected_classification_artifact = _read_json(
        root / refs["corrected_classification"]["path"]
    )
    corrected_taxonomy_artifact = _read_json(root / refs["corrected_taxonomy"]["path"])
    corrected_coincidence_artifact = _read_json(
        root / refs["corrected_coincidence"]["path"]
    )
    corrected_pem_artifact = _read_json(root / refs["corrected_pem"]["path"])

    external = {
        name: _platform_path(path) for name, path in contract["external_roots"].items()
    }
    class_dir = _external_run_dir(
        external["classification"],
        "native_classification",
        corrected_classification_artifact["external_run"]["run_key"],
    )
    taxonomy_dir = _external_run_dir(
        external["taxonomy"],
        "native_taxonomy",
        corrected_taxonomy_artifact["external_run"]["run_key"],
    )
    coincidence_dir = _external_run_dir(
        external["coincidence"],
        "native_coincidence",
        corrected_coincidence_artifact["external_run"]["run_key"],
    )
    pem_dir = _external_run_dir(
        external["pem"],
        "native_pem",
        corrected_pem_artifact["external_run"]["run_key"],
    )
    corrected_classification = _load_and_verify_jsonl(
        class_dir / corrected_classification_artifact["output"]["filename"],
        corrected_classification_artifact["output"],
    )
    corrected_taxonomy = _load_and_verify_jsonl(
        taxonomy_dir / corrected_taxonomy_artifact["output"]["filename"],
        corrected_taxonomy_artifact["output"],
    )
    corrected_coincidence = []
    for population in ("primary", "diagnostic"):
        spec = corrected_coincidence_artifact["outputs"][population]
        corrected_coincidence.extend(
            _load_and_verify_jsonl(coincidence_dir / spec["filename"], spec)
        )
    corrected_pem_targets = _load_and_verify_jsonl(
        pem_dir / corrected_pem_artifact["outputs"]["targets"]["filename"],
        corrected_pem_artifact["outputs"]["targets"],
    )
    corrected_pem = []
    for population in ("primary", "diagnostic"):
        spec = corrected_pem_artifact["outputs"][population]
        corrected_pem.extend(_load_and_verify_jsonl(pem_dir / spec["filename"], spec))
    return {
        "historical_taxonomy": historical_taxonomy,
        "historical_scores": historical_scores,
        "historical_coincidence": historical_coincidence,
        "historical_pem_targets": historical_pem_targets,
        "historical_pem_verdicts": historical_pem_verdicts,
        "corrected_classification": corrected_classification,
        "corrected_taxonomy": corrected_taxonomy,
        "corrected_coincidence": corrected_coincidence,
        "corrected_pem_targets": corrected_pem_targets,
        "corrected_pem": corrected_pem,
    }


def _build_comparison(
    *, root: Path, contract: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    data = _load_inputs(root, contract)
    historical_gps_offset_s = float(
        contract["identity"]["historical_normalization"]["offset_s"]
    )
    historical_candidate_identities = set(
        _unique_index(data["historical_taxonomy"])
    )
    candidate_metrics, shared, removed, added = compare_candidate_catalogues(
        data["historical_taxonomy"],
        data["corrected_classification"],
        data["historical_taxonomy"],
        data["corrected_taxonomy"],
        historical_gps_offset_s=historical_gps_offset_s,
    )
    expected = contract["candidate_comparison"]
    if candidate_metrics["historical_total"] != expected["historical_expected_total"]:
        raise ContractError("historical candidate total changed")
    if candidate_metrics["corrected_total"] != expected["corrected_expected_total"]:
        raise ContractError("corrected candidate total changed")
    coincidence = compare_coincidence_sets(
        data["historical_coincidence"],
        data["corrected_coincidence"],
        historical_candidate_identities=historical_candidate_identities,
        historical_gps_offset_s=historical_gps_offset_s,
    )
    pem = compare_pem_sets(
        data["historical_pem_targets"],
        data["historical_pem_verdicts"],
        data["corrected_pem_targets"],
        historical_candidate_identities=historical_candidate_identities,
        historical_gps_offset_s=historical_gps_offset_s,
    )
    singletons = recheck_historical_singletons(
        contract["historical_singletons"],
        data["historical_taxonomy"],
        data["corrected_classification"],
        data["historical_taxonomy"],
        data["corrected_taxonomy"],
        data["corrected_coincidence"],
        data["corrected_pem"],
        historical_gps_offset_s=historical_gps_offset_s,
    )
    metrics = {
        "identity_normalization": {
            "historical_gps_offset_s": historical_gps_offset_s,
            "scope": "frozen_candidate_catalogue_and_verified_downstream_subsets",
            "historical_candidate_total": len(historical_candidate_identities),
            "historical_coincidence_event_total": len(
                data["historical_coincidence"].get("events", [])
            ),
            "historical_pem_target_total": len(data["historical_pem_targets"]),
            "historical_pem_verdict_total": len(data["historical_pem_verdicts"]),
            "downstream_subset_membership_verified": True,
            "calibration_identities_transformed": 0,
            "gps_identity_audit_sha256": contract["references"][
                "gps_identity_audit"
            ]["sha256"],
        },
        "candidates": candidate_metrics,
        "coincidence": coincidence,
        "pem": pem,
    }
    return metrics, {"shared": shared, "removed": removed, "new": added}, singletons


def _run_key(contract: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": contract["runtime_environment_digest"],
            "source_hashes": {
                name: reference["sha256"]
                for name, reference in sorted(contract["references"].items())
            },
        }
    )


def run_final_comparison(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> tuple[dict[str, Any], Path]:
    contract = load_final_comparison_contract(root)
    run_key = _run_key(contract)
    run_dir = _platform_path(external_root).resolve() / f"final_comparison_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics, rows, singletons = _build_comparison(root=root, contract=contract)
    output = contract["output"]
    paths = {
        "shared": run_dir / output["shared_filename"],
        "removed": run_dir / output["removed_filename"],
        "new": run_dir / output["new_filename"],
    }
    for name, path in paths.items():
        _atomic_jsonl(path, rows[name])
    singleton_path = run_dir / output["singletons_filename"]
    _atomic_json(singleton_path, {"singletons": singletons})
    outputs = {
        name: {
            "filename": path.name,
            "row_total": len(rows[name]),
            "sha256": sha256_file(path),
            "row_digest": canonical_json_sha256(rows[name]),
        }
        for name, path in paths.items()
    }
    outputs["singletons"] = {
        "filename": singleton_path.name,
        "sha256": sha256_file(singleton_path),
        "digest": canonical_json_sha256({"singletons": singletons}),
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_COMPLETE_O4A_FINAL_COMPARISON_V2",
        "contract_digest": contract["contract_digest"],
        "runtime_environment_digest": contract["runtime_environment_digest"],
        "run_key": run_key,
        "metrics": metrics,
        "historical_singletons": singletons,
        "outputs": outputs,
        "scientific_boundary": contract["scientific_boundary"],
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / output["summary_filename"], summary)
    return summary, run_dir


def verify_final_comparison(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> tuple[dict[str, Any], Path]:
    contract = load_final_comparison_contract(root)
    run_key = _run_key(contract)
    run_dir = _platform_path(external_root).resolve() / f"final_comparison_{run_key}"
    summary_path = run_dir / contract["output"]["summary_filename"]
    summary = _read_json(summary_path)
    body = dict(summary)
    digest = body.pop("artifact_digest", None)
    if digest != canonical_json_sha256(body) or summary.get("run_key") != run_key:
        raise ContractError("final-comparison summary digest mismatch")
    metrics, rows, singletons = _build_comparison(root=root, contract=contract)
    if (
        summary.get("metrics") != metrics
        or summary.get("historical_singletons") != singletons
    ):
        raise ContractError("final-comparison metric replay mismatch")
    for name in ("shared", "removed", "new"):
        spec = summary["outputs"][name]
        path = run_dir / spec["filename"]
        observed = _load_jsonl(path)
        if (
            observed != rows[name]
            or sha256_file(path) != spec["sha256"]
            or canonical_json_sha256(observed) != spec["row_digest"]
        ):
            raise ContractError(f"final-comparison {name} output mismatch")
    singleton_spec = summary["outputs"]["singletons"]
    singleton_value = _read_json(run_dir / singleton_spec["filename"])
    if (
        singleton_value != {"singletons": singletons}
        or canonical_json_sha256(singleton_value) != singleton_spec["digest"]
        or sha256_file(run_dir / singleton_spec["filename"]) != singleton_spec["sha256"]
    ):
        raise ContractError("final-comparison singleton output mismatch")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "ROOT",
    "compare_candidate_catalogues",
    "compare_coincidence_sets",
    "compare_pem_sets",
    "load_final_comparison_contract",
    "recheck_historical_singletons",
    "run_final_comparison",
    "validate_final_comparison_contract",
    "verify_final_comparison",
]
