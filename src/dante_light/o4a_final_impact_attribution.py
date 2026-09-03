"""Post-hoc attribution audit for the corrected O4a final comparison."""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_final_impact_attribution_v1.json")
SCHEMA_VERSION = 1
SCORE_ATOL = 2e-7

Identity = tuple[str, float]


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


def _platform_path(value: str | Path) -> Path:
    text = str(value).replace("\\", "/")
    if os.name != "nt" and len(text) >= 3 and text[1:3] == ":/":
        return Path("/mnt") / text[0].lower() / text[3:]
    return Path(value)


def _identity(row: Mapping[str, Any], gps_field: str = "gps_start") -> Identity:
    detector = str(row.get("detector", ""))
    gps = float(row.get(gps_field, "nan"))
    if detector not in {"H1", "L1"}:
        raise ContractError("invalid detector identity")
    return detector, gps


def _unique(rows: Sequence[Mapping[str, Any]]) -> dict[Identity, Mapping[str, Any]]:
    output: dict[Identity, Mapping[str, Any]] = {}
    for row in rows:
        identity = _identity(row)
        if identity in output:
            raise ContractError(f"duplicate detector+GPS identity: {identity}")
        output[identity] = row
    return output


def _verify_file(path: Path, expected_sha256: str) -> Path:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ContractError(f"impact-attribution reference changed: {path}")
    return path


def validate_contract(
    contract: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(contract))
    digest = value.pop("contract_digest", None)
    if digest != canonical_json_sha256(value):
        raise ContractError("impact-attribution contract digest mismatch")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("impact-attribution schema changed")
    if value.get("contract_id") != "dante-o4a-final-impact-attribution-v1":
        raise ContractError("impact-attribution identity changed")
    if value.get("status") != "FROZEN_POSTHOC_AFTER_EXPLORATORY_PREFLIGHT":
        raise ContractError("impact-attribution disclosure changed")
    if value.get("method") != {
        "identity": ["detector", "analysis_gps_start"],
        "historical_catalogue_gps_offset_s": 4.0,
        "direct_padding_effect": (
            "complete_context_score_with_historical_index_and_historical_thresholds"
        ),
        "final_churn_partition": "membership_in_frozen_169_edge_cohort",
        "corrected_only_edge_geometry": (
            "any_source_block_end_equals_analysis_gps_start_plus_32s"
        ),
        "pem_membership": "exact_detector_analysis_gps_identity",
        "score_change_tolerance": SCORE_ATOL,
    }:
        raise ContractError("impact-attribution method changed")
    if value.get("scientific_boundary") != {
        "posthoc_after_final_comparison": True,
        "outcome_blind": False,
        "controlled_padding_replay_is_direct_causal_evidence": True,
        "final_churn_is_descriptive_not_causal": True,
        "new_index_and_new_thresholds_are_jointly_changed": True,
        "nonedge_churn_may_not_be_called_threshold_only": True,
        "corrected_only_membership_may_not_be_called_padding_false_negative": True,
        "pem_is_not_astrophysical_confirmation": True,
        "global_significance_claim": False,
    }:
        raise ContractError("impact-attribution scientific boundary changed")
    for reference in value["references"].values():
        _verify_file(root / reference["path"], reference["sha256"])
    for reference in value["external_files"].values():
        _verify_file(_platform_path(reference["path"]), reference["sha256"])
    return {"contract_digest": digest, **value}


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_contract(_read_json(root / CONTRACT_REL), root=root)


def _classify(score: float, thresholds: Mapping[str, Any]) -> str:
    if score < float(thresholds["ci_lower"]):
        return "BACKGROUND"
    if score > float(thresholds["ci_upper"]):
        return "ROBUST"
    return "AMBIGUOUS"


def _right_edge_geometry(row: Mapping[str, Any]) -> bool:
    analysis_end = float(row["gps_start"]) + 32.0
    return any(
        float(source["block_interval"][1]) == analysis_end
        for source in row["context_sources"]
    )


def build_attribution(
    *, root: Path = ROOT, contract: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    frozen = dict(contract or load_contract(root))
    refs = frozen["references"]
    external = frozen["external_files"]
    edge_audit = _read_json(root / refs["edge_padding_audit"]["path"])
    final = _read_json(root / refs["final_comparison"]["path"])
    classification = _read_json(root / refs["corrected_classification"]["path"])
    pem = _read_json(root / refs["corrected_pem"]["path"])
    thresholds = _read_json(root / refs["historical_thresholds"]["path"])[
        "thresholds"
    ]
    edge_rows = _read_jsonl(root / refs["historical_edge_identities"]["path"])

    shared = _read_jsonl(_platform_path(external["final_shared"]["path"]))
    removed = _read_jsonl(_platform_path(external["final_historical_only"]["path"]))
    added = _read_jsonl(_platform_path(external["final_corrected_only"]["path"]))
    replay = _read_jsonl(_platform_path(external["historical_complete_context_replay"]["path"]))
    corrected_rows = _read_jsonl(
        _platform_path(external["corrected_classification_rows"]["path"])
    )
    pem_targets = _read_jsonl(_platform_path(external["pem_targets"]["path"]))
    pem_primary = _read_jsonl(_platform_path(external["pem_primary"]["path"]))

    expected = frozen["expected_source_counts"]
    observed_counts = {
        "shared": len(shared),
        "historical_only": len(removed),
        "corrected_only": len(added),
        "historical_edges": len(edge_rows),
        "historical_replay": len(replay),
        "corrected_classification": len(corrected_rows),
        "pem_targets": len(pem_targets),
        "pem_primary": len(pem_primary),
    }
    if observed_counts != expected:
        raise ContractError("impact-attribution source population changed")
    if (
        edge_audit.get("changed_class_count") != 120
        or edge_audit.get("changed_route_count") != 97
        or final.get("candidate_comparison", {}).get("class_changed_total") != 1626
        or classification.get("output", {}).get("row_total") != len(corrected_rows)
        or pem.get("event_summary", {}).get("primary", {}).get("total")
        != len(pem_primary)
    ):
        raise ContractError("impact-attribution parent metric changed")

    edge_by_case = {str(row["case_id"]): row for row in edge_rows}
    edge_identities = {
        _identity(row["window"]): str(row["case_id"]) for row in edge_rows
    }
    replay_by_case = {
        str(row["evidence"]["case_id"]): row
        for row in replay
        if str(row.get("evidence", {}).get("case_id")) in edge_by_case
    }
    if set(replay_by_case) != set(edge_by_case):
        raise ContractError("historical edge replay is incomplete")

    direct_changed: set[Identity] = set()
    direct_transitions: Counter[str] = Counter()
    for case_id, edge_row in edge_by_case.items():
        detector = str(edge_row["window"]["detector"])
        old_class = str(edge_row["published_offline_class"])
        corrected_score = float(replay_by_case[case_id]["scores"]["native"])
        corrected_class = _classify(corrected_score, thresholds[detector])
        if corrected_class != old_class:
            identity = _identity(edge_row["window"])
            direct_changed.add(identity)
            direct_transitions[f"{old_class}->{corrected_class}"] += 1

    shared_index = _unique(shared)
    shared_identities = set(shared_index)
    removed_identities = set(_unique(removed))
    added_identities = set(_unique(added))
    final_changed = {
        identity
        for identity, row in shared_index.items()
        if row["historical_class"] != row["corrected_class"]
    }
    edge_set = set(edge_identities)
    edge_final_changed = edge_set & final_changed
    nonedge_final_changed = final_changed - edge_set
    score_changed = {
        identity
        for identity, row in shared_index.items()
        if abs(float(row["score_delta_corrected_minus_historical"])) > SCORE_ATOL
    }

    corrected_index = _unique(corrected_rows)
    if added_identities - set(corrected_index):
        raise ContractError("corrected-only identity missing from classification")
    corrected_only_rows = [corrected_index[identity] for identity in added_identities]
    corrected_only_edge = {
        _identity(row) for row in corrected_only_rows if _right_edge_geometry(row)
    }

    targets_by_population: dict[str, set[Identity]] = {}
    target_index = _unique(pem_targets)
    for identity, row in target_index.items():
        targets_by_population.setdefault(str(row["population"]), set()).add(identity)
    primary_results = {
        _identity(row["target"]): row for row in pem_primary
    }
    primary_new = added_identities & targets_by_population.get("primary", set())
    diagnostic_new = added_identities & targets_by_population.get(
        "diagnostic", set()
    )
    primary_new_details = []
    for identity in sorted(primary_new):
        row = target_index[identity]
        result = primary_results[identity]
        primary_new_details.append(
            {
                "detector": identity[0],
                "gps_start": identity[1],
                "native_class": row["native_class"],
                "native_score": float(row["native_score"]),
                "coincidence_primary_threshold_exceeded": bool(
                    row["coincidence_primary_threshold_exceeded"]
                ),
                "right_edge_geometry": _right_edge_geometry(row),
                "pem_verdict_tier": result["verdict_tier"],
                "pem_top_channel": result["top_channel"],
                "pem_is_astrophysical_confirmation": False,
            }
        )

    forum = next(
        row
        for row in final["historical_singletons"]
        if row["detector"] == "L1"
        and float(row["normalized_analysis_gps_start"]) == 1382955232.0
    )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_POSTHOC_FINAL_IMPACT_ATTRIBUTION_V1",
        "contract_digest": frozen["contract_digest"],
        "source_counts": observed_counts,
        "controlled_direct_padding_effect": {
            "historical_edge_candidates": len(edge_set),
            "class_changed": len(direct_changed),
            "route_changed": int(edge_audit["changed_route_count"]),
            "class_transitions": dict(sorted(direct_transitions.items())),
            "representation": "historical_index",
            "thresholds": "historical_detector_specific",
            "complete_symmetric_context": True,
        },
        "final_shared_class_churn": {
            "shared_total": len(shared_identities),
            "class_changed_total": len(final_changed),
            "edge_shared_total": len(edge_set & shared_identities),
            "edge_class_changed": len(edge_final_changed),
            "nonedge_class_changed": len(nonedge_final_changed),
            "edge_historical_only": len(edge_set & removed_identities),
            "direct_padding_changed_and_final_changed": len(
                direct_changed & final_changed
            ),
            "direct_padding_changed_but_historical_only": len(
                direct_changed & removed_identities
            ),
            "final_edge_changed_outside_controlled_padding_120": len(
                edge_final_changed - direct_changed
            ),
            "shared_score_delta_gt_2e7": len(score_changed),
            "nonedge_shared_score_delta_gt_2e7": len(
                score_changed - edge_set
            ),
            "causal_decomposition": "NOT_IDENTIFIABLE_FROM_FINAL_COMPARISON",
            "reason": (
                "the detector-aware index and detector-specific thresholds both "
                "changed; cross-representation threshold substitution is invalid"
            ),
        },
        "corrected_only_followup": {
            "corrected_only_total": len(added_identities),
            "historical_right_edge_geometry_total": len(corrected_only_edge),
            "right_edge_causality_established": False,
            "primary_pem_total": len(targets_by_population.get("primary", set())),
            "primary_pem_from_corrected_only": len(primary_new),
            "primary_pem_from_corrected_only_details": primary_new_details,
            "diagnostic_pem_total": len(
                targets_by_population.get("diagnostic", set())
            ),
            "diagnostic_pem_from_corrected_only": len(diagnostic_new),
            "primary_new_candidates_at_right_edge": len(
                primary_new & corrected_only_edge
            ),
            "padding_false_negative_claim": False,
        },
        "forum_candidate": {
            "detector": forum["detector"],
            "analysis_gps_start": forum["normalized_analysis_gps_start"],
            "localized_feature_gps": forum["localized_feature_gps"],
            "corrected_class": forum["corrected_class"],
            "corrected_score": forum["corrected_score"],
            "coincidence_exceeds_primary_threshold": forum[
                "coincidence_exceeds_primary_threshold"
            ],
            "included_in_pem_shortlist": forum["pem_population"] is not None,
            "interpretation": (
                "single-detector anomaly without corrected pooled-null "
                "coincidence support; instrumental origin remains an inference"
            ),
        },
        "scientific_boundary": frozen["scientific_boundary"],
        "references": {
            name: {"path": ref["path"], "sha256": ref["sha256"]}
            for name, ref in {**refs, **external}.items()
        },
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


__all__ = ["ROOT", "build_attribution", "load_contract", "validate_contract"]
