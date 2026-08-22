"""Frozen scientific contract for the research-only DANTE-Light L4 v3 screen."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_splits import load_prefilter_splits


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL_V3_PATH = ROOT / "config" / "dante_light_prefilter_protocol_v3.json"
SCHEMA_VERSION = 3
CONTROL_ROLES = ("robust_candidate", "known_glitch", "injection")
ABLATIONS = (
    "signed_ordering",
    "ridge_consistency",
    "signed_plus_ridge",
    "spectral_v2_baseline",
)


@dataclass(frozen=True)
class PrefilterProtocolV3:
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _exact_mapping(value: Any, label: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ContractError(f"{label} must define exactly {sorted(keys)}")
    return value


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


def _hash_reference(
    value: Any,
    label: str,
    *,
    extra: frozenset[str] = frozenset(),
) -> Mapping[str, Any]:
    record = _exact_mapping(value, label, {"path", "sha256", *extra})
    if not str(record["path"]) or len(str(record["sha256"])) != 64:
        raise ContractError(f"{label} is not a valid file/hash reference")
    return record


def _validate_retention_gate(value: Any, label: str) -> Mapping[str, Any]:
    required = {
        "wilson_confidence",
        "minimum_retention_by_role",
        "minimum_wilson_lower_by_role",
        "minimum_group_n_by_role",
    }
    gate = _exact_mapping(value, label, required)
    _fraction(gate["wilson_confidence"], f"{label}.wilson_confidence", positive=True)
    for field in ("minimum_retention_by_role", "minimum_wilson_lower_by_role"):
        mapping = _exact_mapping(gate[field], f"{label}.{field}", set(CONTROL_ROLES))
        for role, raw in mapping.items():
            _fraction(raw, f"{label}.{field}.{role}")
    sizes = _exact_mapping(
        gate["minimum_group_n_by_role"],
        f"{label}.minimum_group_n_by_role",
        set(CONTROL_ROLES),
    )
    for role, raw in sizes.items():
        _positive_int(raw, f"{label}.minimum_group_n_by_role.{role}")
    return gate


def validate_prefilter_v3_protocol(payload: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "status",
        "protocol_id",
        "parent_v2",
        "design_basis",
        "scientific_boundary",
        "required_detectors",
        "required_morphologies_by_role",
        "cohort_contract",
        "audit",
        "feature_extraction",
        "development",
        "confirmation",
        "uncertainty",
        "evaluation",
        "protocol_digest",
    }
    if set(payload) != required:
        raise ContractError("prefilter v3 protocol fields are incomplete or unexpected")
    body = dict(payload)
    declared = body.pop("protocol_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("prefilter v3 protocol digest mismatch")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ContractError("unsupported prefilter v3 protocol schema")
    if payload["status"] != "frozen" or payload["protocol_id"] != "dante-light-l4-prefilter-v3-ab":
        raise ContractError("prefilter v3 protocol must be the frozen A+B design")

    parent = _exact_mapping(
        payload["parent_v2"],
        "parent_v2",
        {"protocol", "split", "screening", "diagnostics"},
    )
    _hash_reference(parent["protocol"], "parent_v2.protocol")
    split_ref = _hash_reference(
        parent["split"],
        "parent_v2.split",
        extra=frozenset({"entries_path", "entries_sha256", "artifact_digest", "role_split_sha256"}),
    )
    for field in ("entries_sha256", "artifact_digest"):
        if len(str(split_ref[field])) != 64:
            raise ContractError(f"parent_v2.split.{field} is invalid")
    role_hashes = _exact_mapping(
        split_ref["role_split_sha256"],
        "parent_v2.split.role_split_sha256",
        {"background", *CONTROL_ROLES},
    )
    if any(len(str(value)) != 64 for value in role_hashes.values()):
        raise ContractError("parent v2 role split hash is invalid")
    screening_ref = _hash_reference(
        parent["screening"], "parent_v2.screening", extra=frozenset({"required_status"})
    )
    diagnostic_ref = _hash_reference(
        parent["diagnostics"], "parent_v2.diagnostics", extra=frozenset({"required_status"})
    )
    if screening_ref["required_status"] != "NOT_READY":
        raise ContractError("v3 must descend from a NOT_READY v2 screen")
    if diagnostic_ref["required_status"] != "COMPLETE_DIAGNOSTIC_ONLY":
        raise ContractError("v3 diagnostic parent status changed")
    _hash_reference(payload["design_basis"], "design_basis")

    boundary = _exact_mapping(
        payload["scientific_boundary"],
        "scientific_boundary",
        {
            "primary_development_run",
            "external_known_glitch_run",
            "prospective_evaluation_run",
            "v2_development_ablation_interpretation",
            "reserved_positive_confirmation_endpoint",
            "o4b_outcomes_allowed_before_confirmation_pass",
            "routing_enabled",
        },
    )
    expected_boundary = {
        "primary_development_run": "O4A",
        "external_known_glitch_run": "O3B",
        "prospective_evaluation_run": "O4B",
        "v2_development_ablation_interpretation": "exploratory_only",
        "reserved_positive_confirmation_endpoint": "protected_stratum_retention_only",
        "o4b_outcomes_allowed_before_confirmation_pass": False,
        "routing_enabled": False,
    }
    if boundary != expected_boundary:
        raise ContractError("prefilter v3 scientific boundary changed")
    if payload["required_detectors"] != ["H1", "L1"]:
        raise ContractError("prefilter v3 requires H1/L1")
    morphologies = _exact_mapping(
        payload["required_morphologies_by_role"],
        "required_morphologies_by_role",
        {"known_glitch", "injection"},
    )
    if morphologies["known_glitch"] != ["Blip", "KoiFish", "ScatteredLight"]:
        raise ContractError("prefilter v3 known-glitch morphologies changed")
    if morphologies["injection"] != ["BBH_30_30", "BBH_10_10", "NSBH_10_1.4"]:
        raise ContractError("prefilter v3 injection morphologies changed")

    cohort = _exact_mapping(
        payload["cohort_contract"],
        "cohort_contract",
        {
            "development_partition",
            "development_interpretation",
            "confirmation_partition",
            "confirmation_feature_values_inspected_before_freeze",
            "require_zero_window_overlap",
            "invalidate_confirmation_on_pre_freeze_access",
            "required_confirmation_n_by_role",
            "nsbh_confirmation_per_detector",
            "nsbh_confirmation_per_distance",
            "nsbh_distances_mpc",
        },
    )
    if (
        cohort["development_partition"] != "development"
        or cohort["development_interpretation"] != "hypothesis_generating_exploratory"
        or cohort["confirmation_partition"] != "evaluation"
        or cohort["confirmation_feature_values_inspected_before_freeze"] != []
        or cohort["require_zero_window_overlap"] is not True
        or cohort["invalidate_confirmation_on_pre_freeze_access"] is not True
    ):
        raise ContractError("prefilter v3 anti-circularity contract changed")
    expected_counts = {"robust_candidate": 20, "known_glitch": 18, "injection": 90}
    if cohort["required_confirmation_n_by_role"] != expected_counts:
        raise ContractError("prefilter v3 confirmation counts changed")
    if cohort["nsbh_confirmation_per_detector"] != 90 or cohort["nsbh_confirmation_per_distance"] != 18:
        raise ContractError("prefilter v3 NSBH confirmation counts changed")
    if cohort["nsbh_distances_mpc"] != [100.0, 200.0, 400.0, 800.0, 1600.0]:
        raise ContractError("prefilter v3 NSBH distance grid changed")

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
            "whitening_context_pad_s",
            "stft_frame_duration_s",
            "stft_overlap_fraction",
            "signed_ordering",
            "ridge_consistency",
            "families",
        },
    )
    if features["feature_version"] != "prefilter-v3-ab":
        raise ContractError("prefilter v3 feature version changed")
    if features["families"] != ["signed_ordering", "ridge_consistency", "spectral_v2_baseline"]:
        raise ContractError("prefilter v3 feature families changed")
    _positive_int(features["sample_rate_hz"], "feature sample rate")
    band = features["analysis_band_hz"]
    if not isinstance(band, list) or len(band) != 2 or not 0 < float(band[0]) < float(band[1]):
        raise ContractError("invalid prefilter v3 analysis band")
    if float(features["whitening_context_pad_s"]) != 4.0:
        raise ContractError("prefilter v3 requires the canonical four-second whitening pad")
    _positive(features["stft_frame_duration_s"], "STFT frame duration")
    _fraction(features["stft_overlap_fraction"], "STFT overlap", positive=True)
    signed = _exact_mapping(
        features["signed_ordering"],
        "signed_ordering",
        {"log_frequency_band_count", "energy_arrival_quantile", "features"},
    )
    if signed["log_frequency_band_count"] != 3:
        raise ContractError("prefilter v3 requires three log-frequency bands")
    _fraction(signed["energy_arrival_quantile"], "energy arrival quantile", positive=True)
    if signed["features"] != [
        "signed_centroid_slope",
        "centroid_time_spearman",
        "centroid_positive_step_fraction",
        "low_band_arrival_time",
        "mid_band_arrival_time",
        "high_band_arrival_time",
        "high_minus_low_arrival_time",
    ]:
        raise ContractError("signed-ordering feature schema changed")
    ridge = _exact_mapping(
        features["ridge_consistency"],
        "ridge_consistency",
        {"ridge_method", "inspiral_coordinate_power", "features"},
    )
    if ridge["ridge_method"] != "per_frame_maximum_power":
        raise ContractError("unsupported prefilter v3 ridge method")
    if not math.isclose(float(ridge["inspiral_coordinate_power"]), -8.0 / 3.0):
        raise ContractError("prefilter v3 inspiral coordinate changed")
    if ridge["features"] != [
        "ridge_signed_slope",
        "ridge_time_spearman",
        "ridge_positive_step_fraction",
        "ridge_energy_fraction",
        "ridge_linear_residual",
        "ridge_inspiral_residual",
    ]:
        raise ContractError("ridge-consistency feature schema changed")

    development_required = {
        "cross_validation_folds",
        "cross_validation_method",
        "gps_block_duration_s",
        "model",
        "regularization_c",
        "maximum_iterations",
        "class_weighting",
        "final_calibration_method",
        "primary_feature_set",
        "ablation_feature_sets",
        "ablation_eligible_for_selection",
        "selection_metric",
        "minimum_effective_reduction",
        "minimum_background_per_detector",
        "wilson_confidence",
        "minimum_retention_by_role",
        "minimum_wilson_lower_by_role",
        "minimum_group_n_by_role",
    }
    development = _exact_mapping(payload["development"], "development", development_required)
    if (
        development["cross_validation_method"] != "shuffled_group_k_fold"
        or development["model"] != "l2_logistic_regression"
        or development["class_weighting"] != "equal_background_and_positive_strata"
        or development["final_calibration_method"]
        != "full_development_model_threshold_on_full_development"
        or development["primary_feature_set"] != "signed_plus_ridge"
        or development["ablation_feature_sets"] != list(ABLATIONS)
        or development["ablation_eligible_for_selection"] is not False
        or development["selection_metric"] != "oof_effective_development_call_reduction"
    ):
        raise ContractError("prefilter v3 development design changed")
    _positive_int(development["cross_validation_folds"], "development folds", minimum=2)
    _positive_int(development["gps_block_duration_s"], "development GPS block")
    _positive(development["regularization_c"], "development regularization")
    _positive_int(development["maximum_iterations"], "development iterations")
    _fraction(development["minimum_effective_reduction"], "development reduction")
    _positive_int(development["minimum_background_per_detector"], "development background")
    development_gate = _validate_retention_gate(
        {key: development[key] for key in (
            "wilson_confidence",
            "minimum_retention_by_role",
            "minimum_wilson_lower_by_role",
            "minimum_group_n_by_role",
        )},
        "development retention",
    )

    confirmation_required = {
        "open_only_after_development_ready",
        "endpoint",
        "wilson_confidence",
        "minimum_retention_by_role",
        "minimum_wilson_lower_by_role",
        "minimum_group_n_by_role",
        "can_authorize_operational_pass",
    }
    confirmation = _exact_mapping(payload["confirmation"], "confirmation", confirmation_required)
    if (
        confirmation["open_only_after_development_ready"] is not True
        or confirmation["endpoint"] != "protected_stratum_retention_only"
        or confirmation["can_authorize_operational_pass"] is not False
    ):
        raise ContractError("prefilter v3 confirmation boundary changed")
    confirmation_gate = _validate_retention_gate(
        {key: confirmation[key] for key in (
            "wilson_confidence",
            "minimum_retention_by_role",
            "minimum_wilson_lower_by_role",
            "minimum_group_n_by_role",
        )},
        "confirmation retention",
    )

    uncertainty = _exact_mapping(
        payload["uncertainty"],
        "uncertainty",
        {"method", "gps_block_duration_s", "n_resamples", "confidence", "eligible_for_gate", "seed"},
    )
    if uncertainty["method"] != "detector_gps_block_bootstrap" or uncertainty["eligible_for_gate"] is not False:
        raise ContractError("prefilter v3 uncertainty must be informational block bootstrap")
    _positive_int(uncertainty["gps_block_duration_s"], "uncertainty GPS block")
    _positive_int(uncertainty["n_resamples"], "uncertainty resamples")
    _fraction(uncertainty["confidence"], "uncertainty confidence", positive=True)
    _positive_int(uncertainty["seed"], "uncertainty seed", minimum=0)

    evaluation_required = {
        "minimum_compute_reduction",
        "minimum_exact_escalates",
        "wilson_confidence",
        "minimum_retention_by_role",
        "minimum_wilson_lower_by_role",
        "minimum_group_n_by_role",
    }
    evaluation = _exact_mapping(payload["evaluation"], "evaluation", evaluation_required)
    _fraction(evaluation["minimum_compute_reduction"], "evaluation reduction")
    _positive_int(evaluation["minimum_exact_escalates"], "minimum exact escalates")
    evaluation_gate = _validate_retention_gate(
        {key: evaluation[key] for key in (
            "wilson_confidence",
            "minimum_retention_by_role",
            "minimum_wilson_lower_by_role",
            "minimum_group_n_by_role",
        )},
        "evaluation retention",
    )
    for role in CONTROL_ROLES:
        for field in ("minimum_retention_by_role", "minimum_wilson_lower_by_role"):
            if not (
                development_gate[field][role]
                == confirmation_gate[field][role]
                == evaluation_gate[field][role]
            ):
                raise ContractError(f"v3 retention criteria differ across stages for {role}")
    if not (
        development_gate["wilson_confidence"]
        == confirmation_gate["wilson_confidence"]
        == evaluation_gate["wilson_confidence"]
    ):
        raise ContractError("v3 Wilson confidence differs across stages")


def verify_prefilter_v3_sources(
    protocol: PrefilterProtocolV3,
    *,
    root: str | Path = ROOT,
) -> dict[str, Any]:
    """Verify frozen v2 ancestry and the unused confirmation partition."""

    root = Path(root).resolve()
    parent = protocol.payload["parent_v2"]
    references = [
        parent["protocol"],
        parent["split"],
        {"path": parent["split"]["entries_path"], "sha256": parent["split"]["entries_sha256"]},
        parent["screening"],
        parent["diagnostics"],
        protocol.payload["design_basis"],
    ]
    for reference in references:
        path = root / str(reference["path"])
        if not path.is_file() or _sha256(path) != str(reference["sha256"]):
            raise ContractError(f"prefilter v3 source provenance mismatch: {reference['path']}")

    screening = json.loads((root / parent["screening"]["path"]).read_text(encoding="utf-8"))
    if (
        screening.get("status") != parent["screening"]["required_status"]
        or screening.get("routing_enabled") is not False
        or screening.get("o4b_outcomes_used") != []
    ):
        raise ContractError("prefilter v3 parent screening boundary changed")
    diagnostics = json.loads((root / parent["diagnostics"]["path"]).read_text(encoding="utf-8"))
    if (
        diagnostics.get("status") != parent["diagnostics"]["required_status"]
        or diagnostics.get("eligible_for_pass_fail_gate") is not False
        or diagnostics.get("o4b_outcomes_used") != []
    ):
        raise ContractError("prefilter v3 parent diagnostic boundary changed")

    split = load_prefilter_splits(root / parent["split"]["path"])
    if split.get("artifact_digest") != parent["split"]["artifact_digest"]:
        raise ContractError("prefilter v3 parent split digest changed")
    for role, expected in parent["split"]["role_split_sha256"].items():
        if split["cohorts"][role]["split_sha256"] != expected:
            raise ContractError(f"prefilter v3 {role} split hash changed")

    development_ids = {
        row["window"]["window_id"]
        for cohort in split["cohorts"].values()
        for row in cohort["rows"]
        if row["partition"] == protocol.payload["cohort_contract"]["development_partition"]
    }
    confirmation_ids = {
        row["window"]["window_id"]
        for role in CONTROL_ROLES
        for row in split["cohorts"][role]["rows"]
        if row["partition"] == protocol.payload["cohort_contract"]["confirmation_partition"]
    }
    if development_ids & confirmation_ids:
        raise ContractError("prefilter v3 development/confirmation window overlap")

    cohort = protocol.payload["cohort_contract"]
    detectors = protocol.payload["required_detectors"]
    morphologies = protocol.payload["required_morphologies_by_role"]
    required_groups = [
        ("robust_candidate", "unknown"),
        *(("known_glitch", value) for value in morphologies["known_glitch"]),
        *(("injection", value) for value in morphologies["injection"]),
    ]
    group_counts: dict[str, int] = {}
    for detector in detectors:
        for role, morphology in required_groups:
            count = sum(
                row["partition"] == cohort["confirmation_partition"]
                and row["detector"] == detector
                and row["morphology"] == morphology
                for row in split["cohorts"][role]["rows"]
            )
            expected = int(cohort["required_confirmation_n_by_role"][role])
            if count != expected:
                raise ContractError(
                    f"prefilter v3 confirmation count mismatch for {role}/{detector}/{morphology}: "
                    f"{count}/{expected}"
                )
            group_counts[f"{role}/{detector}/{morphology}"] = count

    nsbh_rows = [
        row
        for row in split["cohorts"]["injection"]["rows"]
        if row["partition"] == cohort["confirmation_partition"]
        and row["morphology"] == "NSBH_10_1.4"
    ]
    for detector in detectors:
        selected = [row for row in nsbh_rows if row["detector"] == detector]
        if len(selected) != int(cohort["nsbh_confirmation_per_detector"]):
            raise ContractError(f"prefilter v3 NSBH count changed for {detector}")
        for distance in cohort["nsbh_distances_mpc"]:
            count = sum(math.isclose(float(row["distance_mpc"]), float(distance)) for row in selected)
            if count != int(cohort["nsbh_confirmation_per_distance"]):
                raise ContractError(f"prefilter v3 NSBH distance count changed for {detector}/{distance}")

    return {
        "status": "PASS",
        "development_window_n": len(development_ids),
        "confirmation_window_n": len(confirmation_ids),
        "overlap_n": 0,
        "confirmation_group_counts": group_counts,
        "nsbh_confirmation_n": len(nsbh_rows),
        "o4b_outcomes_used": [],
    }


def load_prefilter_v3_protocol(
    path: str | Path = DEFAULT_PROTOCOL_V3_PATH,
) -> PrefilterProtocolV3:
    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid prefilter v3 protocol {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("prefilter v3 protocol root must be an object")
    validate_prefilter_v3_protocol(payload)
    return PrefilterProtocolV3(
        path=source,
        payload=payload,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
