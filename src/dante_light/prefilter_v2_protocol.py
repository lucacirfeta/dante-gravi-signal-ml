"""Frozen scientific contract for the research-only L4 v2 prefilter."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL_V2_PATH = ROOT / "config" / "dante_light_prefilter_protocol_v2.json"
SCHEMA_VERSION = 2
CONTROL_ROLES = ("robust_candidate", "known_glitch", "injection")
FEATURE_FAMILIES = (
    "temporal_energy",
    "tf_cluster",
    "spectral_evolution",
    "wavelet_sparse",
)


@dataclass(frozen=True)
class PrefilterProtocolV2:
    path: Path
    payload: Mapping[str, Any]
    sha256: str

    @property
    def reference(self) -> dict[str, str]:
        return {
            "file_name": self.path.name,
            "sha256": self.sha256,
            "protocol_id": str(self.payload["protocol_id"]),
            "protocol_digest": str(self.payload["protocol_digest"]),
        }


def _fraction(value: Any, label: str, *, positive: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ContractError(f"{label} must be a finite fraction")
    if positive and result <= 0.0:
        raise ContractError(f"{label} must be positive")
    return result


def _positive(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ContractError(f"{label} must be finite and positive")
    return result


def _positive_int(value: Any, label: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{label} must be an integer >= {minimum}")
    return value


def _exact_mapping(value: Any, label: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ContractError(f"{label} must define exactly {sorted(keys)}")
    return value


def _validate_gate(block: Any, label: str, *, development: bool) -> None:
    common = {
        "wilson_confidence",
        "minimum_retention_by_role",
        "minimum_wilson_lower_by_role",
        "minimum_group_n_by_role",
    }
    required = common | (
        {
            "cross_validation_folds",
            "cross_validation_method",
            "gps_block_duration_s",
            "model",
            "regularization_c",
            "maximum_iterations",
            "class_weighting",
            "candidate_feature_sets",
            "selection_metric",
            "selection_tie_break",
            "minimum_effective_reduction",
            "minimum_background_per_detector",
        }
        if development
        else {"minimum_compute_reduction", "minimum_exact_escalates"}
    )
    block = _exact_mapping(block, label, required)
    _fraction(block["wilson_confidence"], f"{label}.wilson_confidence", positive=True)
    for field in ("minimum_retention_by_role", "minimum_wilson_lower_by_role"):
        mapping = _exact_mapping(block[field], f"{label}.{field}", set(CONTROL_ROLES))
        for role, value in mapping.items():
            _fraction(value, f"{label}.{field}.{role}")
    sizes = _exact_mapping(
        block["minimum_group_n_by_role"],
        f"{label}.minimum_group_n_by_role",
        set(CONTROL_ROLES),
    )
    for role, value in sizes.items():
        _positive_int(value, f"{label}.minimum_group_n_by_role.{role}")
    if development:
        _positive_int(block["cross_validation_folds"], f"{label}.cross_validation_folds", minimum=2)
        if block["cross_validation_method"] != "shuffled_group_k_fold":
            raise ContractError("development.cross_validation_method is unsupported")
        _positive_int(block["gps_block_duration_s"], f"{label}.gps_block_duration_s")
        _positive(block["regularization_c"], f"{label}.regularization_c")
        _positive_int(block["maximum_iterations"], f"{label}.maximum_iterations")
        _fraction(block["minimum_effective_reduction"], f"{label}.minimum_effective_reduction")
        _positive_int(block["minimum_background_per_detector"], f"{label}.minimum_background_per_detector")
        if block["model"] != "l2_logistic_regression":
            raise ContractError("development.model is unsupported")
        if block["class_weighting"] != "equal_background_and_positive_strata":
            raise ContractError("development.class_weighting is unsupported")
        if block["selection_metric"] != "oof_effective_development_call_reduction":
            raise ContractError("development.selection_metric is unsupported")
        if block["selection_tie_break"] != [
            "higher_reduction",
            "fewer_features",
            "feature_set_lexicographic",
        ]:
            raise ContractError("development.selection_tie_break is unsupported")
        if block["candidate_feature_sets"] != [*FEATURE_FAMILIES, "all"]:
            raise ContractError("development candidate feature sets are not frozen")
    else:
        _fraction(block["minimum_compute_reduction"], f"{label}.minimum_compute_reduction")
        _positive_int(block["minimum_exact_escalates"], f"{label}.minimum_exact_escalates")


def validate_prefilter_v2_protocol(payload: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "status",
        "protocol_id",
        "parent_protocol",
        "scientific_boundary",
        "cohort_split_seed",
        "required_detectors",
        "required_morphologies_by_role",
        "cohort_augmentation",
        "audit",
        "feature_extraction",
        "development",
        "evaluation",
        "protocol_digest",
    }
    if set(payload) != required:
        raise ContractError("prefilter v2 protocol fields are incomplete or unexpected")
    body = dict(payload)
    declared = body.pop("protocol_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("prefilter v2 protocol digest mismatch")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ContractError("unsupported prefilter v2 protocol schema")
    if payload["status"] != "frozen" or not payload["protocol_id"]:
        raise ContractError("prefilter v2 protocol must be frozen and identified")
    _positive_int(payload["cohort_split_seed"], "cohort_split_seed", minimum=0)

    parent = _exact_mapping(payload["parent_protocol"], "parent_protocol", {"path", "sha256", "result"})
    if parent["result"] != "NOT_READY" or len(str(parent["sha256"])) != 64:
        raise ContractError("prefilter v2 parent protocol is invalid")
    boundary = _exact_mapping(
        payload["scientific_boundary"],
        "scientific_boundary",
        {
            "primary_development_run",
            "external_known_glitch_run",
            "prospective_evaluation_run",
            "o4b_outcomes_allowed_during_development",
            "routing_enabled",
        },
    )
    if boundary != {
        "primary_development_run": "O4A",
        "external_known_glitch_run": "O3B",
        "prospective_evaluation_run": "O4B",
        "o4b_outcomes_allowed_during_development": False,
        "routing_enabled": False,
    }:
        raise ContractError("prefilter v2 scientific boundary changed")
    if payload["required_detectors"] != ["H1", "L1"]:
        raise ContractError("prefilter v2 requires H1/L1")
    morphologies = _exact_mapping(
        payload["required_morphologies_by_role"],
        "required_morphologies_by_role",
        {"known_glitch", "injection"},
    )
    for role, values in morphologies.items():
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise ContractError(f"invalid morphology grid for {role}")

    augmentation = _exact_mapping(
        payload["cohort_augmentation"],
        "cohort_augmentation",
        {"base_split", "robust_candidate", "known_glitch", "availability_preflight"},
    )
    base = _exact_mapping(augmentation["base_split"], "cohort_augmentation.base_split", {"path", "sha256", "entries_sha256"})
    if any(len(str(base[field])) != 64 for field in ("sha256", "entries_sha256")):
        raise ContractError("base split hashes are invalid")
    robust = _exact_mapping(
        augmentation["robust_candidate"],
        "cohort_augmentation.robust_candidate",
        {"additional_development_per_detector", "source_path", "source_sha256", "required_class"},
    )
    _positive_int(robust["additional_development_per_detector"], "robust augmentation")
    if robust["required_class"] != "ROBUST" or len(str(robust["source_sha256"])) != 64:
        raise ContractError("robust augmentation source is invalid")
    known = _exact_mapping(
        augmentation["known_glitch"],
        "cohort_augmentation.known_glitch",
        {
            "additional_development_per_stratum",
            "availability_reserve_per_stratum",
            "catalog_zenodo_record",
            "catalog_paths",
            "catalog_sha256",
            "minimum_ml_confidence",
            "minimum_snr",
            "separation_guard_s",
        },
    )
    _positive_int(known["additional_development_per_stratum"], "known augmentation")
    _positive_int(known["availability_reserve_per_stratum"], "known reserve")
    if known["availability_reserve_per_stratum"] < known["additional_development_per_stratum"]:
        raise ContractError("known-glitch reserve is smaller than its quota")
    for field in ("catalog_paths", "catalog_sha256"):
        _exact_mapping(known[field], f"known_glitch.{field}", {"H1", "L1"})
    if any(len(str(value)) != 64 for value in known["catalog_sha256"].values()):
        raise ContractError("known-glitch catalog hash is invalid")
    _fraction(known["minimum_ml_confidence"], "known minimum confidence", positive=True)
    _positive(known["minimum_snr"], "known minimum SNR")
    _positive(known["separation_guard_s"], "known separation guard")
    preflight = _exact_mapping(
        augmentation["availability_preflight"],
        "availability_preflight",
        {"whitening_context_pad_s", "workers", "selection_uses_feature_values", "selection_uses_exact_scores"},
    )
    _positive(preflight["whitening_context_pad_s"], "preflight whitening pad")
    _positive_int(preflight["workers"], "preflight workers")
    if preflight["selection_uses_feature_values"] is not False or preflight["selection_uses_exact_scores"] is not False:
        raise ContractError("availability preflight must be outcome blind")

    audit = _exact_mapping(payload["audit"], "audit", {"fraction", "seed"})
    _fraction(audit["fraction"], "audit.fraction", positive=True)
    _positive_int(audit["seed"], "audit.seed", minimum=0)
    features = _exact_mapping(
        payload["feature_extraction"],
        "feature_extraction",
        {
            "feature_version",
            "sample_rate_hz",
            "analysis_band_hz",
            "temporal_block_durations_s",
            "temporal_overlap_fraction",
            "temporal_top_fraction",
            "stft_frame_duration_s",
            "stft_overlap_fraction",
            "robust_z_threshold",
            "dyadic_levels",
            "wavelet_tail_quantile",
            "families",
        },
    )
    if features["feature_version"] != "prefilter-v2" or features["families"] != list(FEATURE_FAMILIES):
        raise ContractError("prefilter v2 feature families changed")
    _positive_int(features["sample_rate_hz"], "feature sample rate")
    band = features["analysis_band_hz"]
    if not isinstance(band, list) or len(band) != 2 or not 0 < float(band[0]) < float(band[1]):
        raise ContractError("invalid feature analysis band")
    durations = features["temporal_block_durations_s"]
    if not isinstance(durations, list) or not durations or any(_positive(value, "temporal duration") <= 0 for value in durations):
        raise ContractError("invalid temporal block durations")
    for field in ("temporal_overlap_fraction", "temporal_top_fraction", "stft_overlap_fraction", "wavelet_tail_quantile"):
        _fraction(features[field], f"feature_extraction.{field}", positive=True)
    _positive(features["stft_frame_duration_s"], "STFT frame duration")
    _positive(features["robust_z_threshold"], "robust z threshold")
    _positive_int(features["dyadic_levels"], "dyadic levels")

    _validate_gate(payload["development"], "development", development=True)
    _validate_gate(payload["evaluation"], "evaluation", development=False)
    for role in CONTROL_ROLES:
        if payload["development"]["minimum_retention_by_role"][role] != payload["evaluation"]["minimum_retention_by_role"][role]:
            raise ContractError(f"development/evaluation point-retention mismatch for {role}")
        if payload["development"]["minimum_wilson_lower_by_role"][role] != payload["evaluation"]["minimum_wilson_lower_by_role"][role]:
            raise ContractError(f"development/evaluation Wilson mismatch for {role}")
    if payload["development"]["wilson_confidence"] != payload["evaluation"]["wilson_confidence"]:
        raise ContractError("development/evaluation Wilson confidence mismatch")


def load_prefilter_v2_protocol(
    path: str | Path = DEFAULT_PROTOCOL_V2_PATH,
) -> PrefilterProtocolV2:
    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid prefilter v2 protocol {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("prefilter v2 protocol root must be an object")
    validate_prefilter_v2_protocol(payload)
    return PrefilterProtocolV2(
        path=source,
        payload=payload,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
