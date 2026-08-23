"""Frozen scientific contract for the DANTE-Light phase-aware v4 study."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from src.dante_light.contracts import ContractError, canonical_json_sha256


PROTOCOL_ID = "dante-light-l4-prefilter-v4-phase-primary"
SEED_METHOD = "sha256_canonical_json_first_64_bits_big_endian"
SEED_PURPOSES = ("cohort", "injection", "audit", "bootstrap")
PHASE_FEATURES = (
    "phase_frequency_time_spearman",
    "phase_frequency_positive_step_fraction",
    "phase_inspiral_coordinate_residual",
    "phase_cubic_circular_residual",
    "phase_valid_frame_fraction",
    "phase_accumulation_cycles",
)


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_reference(root: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError("frozen references must remain inside the repository") from exc
    digest = sha256_path(resolved)
    try:
        unchanged = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative],
            cwd=root,
            check=False,
        ).returncode == 0
        tracked = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{relative}"],
            cwd=root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        if unchanged and tracked:
            blob = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=root)
            digest = hashlib.sha256(blob).hexdigest()
    except (OSError, subprocess.SubprocessError):
        # The byte hash remains a valid fallback outside a Git checkout.
        pass
    return {"path": relative, "sha256": digest}


def derive_seed(protocol_id: str, purpose: str, parent_digests: Sequence[str]) -> int:
    """Derive a portable 64-bit seed from a canonical, unambiguous payload."""

    if purpose not in SEED_PURPOSES:
        raise ContractError(f"unregistered v4 seed purpose: {purpose}")
    digests = sorted(str(value).lower() for value in parent_digests)
    if any(len(value) != 64 for value in digests):
        raise ContractError("v4 seed parents must be SHA256 digests")
    payload = {"protocol_id": str(protocol_id), "purpose": purpose, "parent_digests": digests}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big", signed=False)


def protocol_digest(payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("protocol_digest", None)
    return canonical_json_sha256(body)


@dataclass(frozen=True)
class PrefilterProtocolV4:
    payload: dict[str, Any]
    path: Path

    @property
    def reference(self) -> dict[str, str]:
        return {"path": self.path.as_posix(), "sha256": sha256_path(self.path)}


def validate_protocol(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    if value.get("schema_version") != 4 or value.get("status") != "FROZEN_OUTCOME_BLIND":
        raise ContractError("v4 protocol is not a frozen schema-v4 contract")
    if value.get("protocol_id") != PROTOCOL_ID:
        raise ContractError("unexpected v4 protocol id")
    if value.get("protocol_digest") != protocol_digest(value):
        raise ContractError("v4 protocol digest mismatch")
    boundary = value["scientific_boundary"]
    if boundary["o4b_outcomes_allowed"] or boundary["routing_enabled"]:
        raise ContractError("v4 freeze may not open O4b or enable routing")
    if boundary["prior_v1_v3_interpretation"] != "EXPLORATORY_FOR_V4":
        raise ContractError("prior cohort interpretation is not bounded")
    if "sensitivity_to_physical_NSBH_waveforms_with_tidal_effects" not in boundary["does_not_establish"]:
        raise ContractError("v4 protocol omits the approved NSBH tidal limitation")
    counts = value["cohort_contract"]["counts_per_detector_stratum"]
    expected = {
        "background": {"development": 300, "confirmation": 0},
        "robust_candidate": {"development": 25, "confirmation": 60},
        "known_glitch": {"development": 25, "confirmation": 60},
        "injection": {"development": 35, "confirmation": 90},
    }
    if counts != expected:
        raise ContractError("v4 sample sizes differ from the approved power design")
    features = value["feature_extraction"]
    if tuple(features["features"]) != PHASE_FEATURES:
        raise ContractError("v4 primary phase feature order changed")
    if features["canonical_sequence"] != [
        "fetch_padded_strain", "whiten_context_pad_4s", "extract_clean_32s_crop", "phase_extractor"
    ]:
        raise ContractError("v4 preprocessing order changed")
    development = value["development"]
    if (
        development["cross_validation_folds"] != 5
        or development["gps_block_duration_s"] != 4096
        or development["regularization_c"] != 1.0
        or development["minimum_effective_reduction"] != 0.5
        or development["minimum_group_n_by_role"] != {
            "robust_candidate": 25, "known_glitch": 25, "injection": 35
        }
        or any(rate != 0.9 for rate in development["minimum_retention_by_role"].values())
        or any(rate != 0.8 for rate in development["minimum_wilson_lower_by_role"].values())
    ):
        raise ContractError("v4 development model or gate changed")
    confirmation = value["confirmation"]
    if confirmation["minimum_retention"] != 0.9 or confirmation["minimum_wilson_lower"] != 0.8:
        raise ContractError("v4 confirmation gate changed")
    if confirmation["gate_operator"] != "AND":
        raise ContractError("v4 point and Wilson retention gates must both pass")
    injection = value["injection_waveform_contract"]
    if (
        injection["approximant"] != "IMRPhenomD"
        or injection["sample_rate_hz"] != 4096
        or injection["window_duration_s"] != 32.0
        or injection["placement"]
        != "geocentric_merger_at_window_midpoint_plus_detector_delay"
        or injection["snr_role"] != "diagnostic_only_never_selection_or_gate"
        or injection["systems"] != {
            "BBH_30_30": {"mass_1_msun": 30.0, "mass_2_msun": 30.0, "f_low_hz": 20.0},
            "BBH_10_10": {"mass_1_msun": 10.0, "mass_2_msun": 10.0, "f_low_hz": 25.0},
            "NSBH_10_1.4": {"mass_1_msun": 10.0, "mass_2_msun": 1.4, "f_low_hz": 30.0,
                "tidal_effects_included": False, "physical_scope": "point_particle_comparability_control_only"},
        }
    ):
        raise ContractError("v4 legacy injection waveform contract changed")
    seeds = value["seed_derivation"]
    if seeds["method"] != SEED_METHOD or tuple(seeds["purposes"]) != SEED_PURPOSES:
        raise ContractError("v4 seed derivation changed")
    parents = seeds["parent_digests"]
    expected_seeds = {purpose: derive_seed(PROTOCOL_ID, purpose, parents) for purpose in SEED_PURPOSES}
    if seeds["seeds"] != expected_seeds:
        raise ContractError("v4 derived seeds do not reproduce")
    return value


def load_protocol(path: str | Path) -> PrefilterProtocolV4:
    source = Path(path)
    return PrefilterProtocolV4(validate_protocol(json.loads(source.read_text(encoding="utf-8"))), source)
