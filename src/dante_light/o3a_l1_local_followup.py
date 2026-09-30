"""Candidate localized PEM design: synthetic kernel and metadata feasibility.

There is deliberately no real measurement runner. Metadata preflight opens
sealed JSON/JSONL, never strain or auxiliary sample arrays. The reference-tail
score below is an exploratory screen, not a calibrated false-alarm probability.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import coherence, get_window

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_o4a_common_pem_acquisition import sealed_json
from src.dante_light.o3a_o4a_common_pem_contract import _host_path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = "config/dante_o3a_l1_local_followup_v1.json"


def load_design(root: Path = ROOT) -> dict[str, Any]:
    value = json.loads((root / CONFIG_PATH).read_text(encoding="utf-8"))
    if (
        value.get("status") != "CANDIDATE_GATE_B_METHOD_NO_REAL_MEASUREMENTS"
        or value.get("execution", {}).get("gate_c_enabled") is not False
        or value["decision"]["family_target_count"] != len(value["targets"])
        or len({(r["detector"], r["gps_start"]) for r in value["targets"]})
        != len(value["targets"])
        or any(r["detector"] != "L1" for r in value["targets"])
    ):
        raise ContractError("local follow-up scope/execution gate changed")
    for ref in value["parents"].values():
        path = _host_path(root, ref["path"])
        if sha256_file(path) != ref["sha256"]:
            raise ContractError(f"local follow-up parent hash changed: {path}")
    required = (
        math.ceil(
            value["decision"]["family_target_count"]
            / value["decision"]["screen_cutoff"]
        )
        - 1
    )
    if value["controls"]["minimum_reference_blocks"] < required:
        raise ContractError("reference blocks cannot resolve the fixed cutoff")
    return value


def local_coherence_max(
    strain: np.ndarray,
    auxiliary: Mapping[str, np.ndarray],
    *,
    channels: Sequence[str],
    band: tuple[float, float],
    measurement: Mapping[str, Any],
) -> float:
    """Pure kernel for already aligned/preprocessed local arrays (synthetic only).

    Fixed zero lag. A numeric low PSD/constant input is unavailable, rather
    than negative. Cropping/filtering is outside this kernel and Gate C.
    """
    fs = float(measurement["sample_rate_hz"])
    nperseg = int(fs * float(measurement["fftlength_s"]))
    noverlap = int(fs * float(measurement["overlap_s"]))
    x = np.asarray(strain, dtype=np.float64)
    if (
        set(auxiliary) != set(channels)
        or len(channels) != len(set(channels))
        or not channels
        or any(not name.startswith("L1:") for name in channels)
        or measurement["window"] != "hann_periodic"
        or measurement["lag_s"] != 0
        or not 0 < band[0] < band[1] < fs / 2
        or nperseg <= noverlap
        or x.ndim != 1
        or not np.isfinite(x).all()
        or np.var(x) == 0
    ):
        raise ContractError("local coherence channel/coverage/band invalid")
    segments = 1 + (x.size - nperseg) // (nperseg - noverlap)
    if (
        segments < measurement["minimum_welch_segments"]
        or band[0] * measurement["fftlength_s"]
        < measurement["minimum_cycles_at_band_low"]
    ):
        raise ContractError("local coherence time/frequency resolution insufficient")
    window = get_window("hann", nperseg, fftbins=True)
    maxima = []
    for channel in channels:
        y = np.asarray(auxiliary[channel], dtype=np.float64)
        if y.shape != x.shape or not np.isfinite(y).all() or np.var(y) == 0:
            raise ContractError("local coherence auxiliary unavailable")
        frequencies, values = coherence(
            x,
            y,
            fs=fs,
            window=window,
            nperseg=nperseg,
            noverlap=noverlap,
            detrend=measurement["detrend"],
        )
        mask = (frequencies >= band[0]) & (frequencies <= band[1])
        if not mask.any() or not np.isfinite(values[mask]).all():
            raise ContractError("local coherence spectral bins unavailable")
        maxima.append(float(values[mask].max()))
    return max(maxima)


def reference_screen(
    event_value: float,
    block_maxima: Sequence[float],
    design: Mapping[str, Any],
) -> dict[str, Any]:
    """Conservative ties and target multiplicity; unavailable never negative."""
    values = np.asarray(block_maxima, dtype=float)
    if (
        not np.isfinite(event_value)
        or not 0 <= event_value <= 1
        or values.ndim != 1
        or not np.isfinite(values).all()
        or np.any((values < 0) | (values > 1))
    ):
        raise ContractError("reference screen statistic invalid")
    if values.size < design["controls"]["minimum_reference_blocks"]:
        return {"status": "INCONCLUSIVE", "reason": "REFERENCE_TAIL_UNRESOLVED"}
    score = min(
        1.0,
        design["decision"]["family_target_count"]
        * (1 + int(np.count_nonzero(values >= event_value)))
        / (1 + values.size),
    )
    verdict = (
        design["decision"]["screen_positive"]
        if score <= design["decision"]["screen_cutoff"]
        else design["decision"]["screen_negative"]
    )
    return {"status": verdict, "corrected_reference_tail_fraction": score}


def control_blocks(
    segment: Sequence[int],
    candidate_gps: Sequence[int],
    controls: Mapping[str, Any],
) -> list[list[int]]:
    """Complete chronological blocks; no stitching or outcome-dependent choice."""
    left, right = map(int, segment)
    duration = int(controls["context_duration_s"])
    stride = int(controls["context_stride_s"])
    block_s = int(controls["chronological_block_s"])
    guard = int(controls["candidate_exclusion_s"])
    count = int(controls["contexts_per_block"])
    if right <= left or stride != duration or block_s != count * duration:
        raise ContractError("control block geometry invalid")
    blocks = []
    for start in range(left, right - block_s + 1, block_s):
        end = start + block_s
        if any(
            start < gps + duration + guard and end > gps - guard
            for gps in candidate_gps
        ):
            continue
        blocks.append([start + j * stride for j in range(count)])
    return blocks


def _ledger(root: Path, receipt: Mapping[str, Any], filename: str, digest: str) -> list:
    wsl_root = receipt["external_run_dir_wsl"]
    value = wsl_root.replace("/mnt/e/", "E:/", 1)
    path = _host_path(root, value) / filename
    if sha256_file(path) != digest:
        raise ContractError("local follow-up ledger bytes changed")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def metadata_preflight(root: Path = ROOT) -> dict[str, Any]:
    """Report feasibility upper bounds, without DQ queries or sample reads."""
    design = load_design(root)
    parents = {
        key: json.loads((root / ref["path"]).read_text(encoding="utf-8"))
        for key, ref in design["parents"].items()
    }
    receipt = parents["coincidence"]
    rows = _ledger(
        root,
        receipt,
        receipt["outputs"]["primary"]["filename"],
        receipt["outputs"]["primary"]["sha256"],
    )
    classified = _ledger(
        root,
        parents["classification"],
        "native_classified_candidates.jsonl",
        parents["classification"]["output_sha256"],
    )
    if len(classified) != parents["classification"]["row_total"]:
        raise ContractError("local exclusion ledger incomplete")
    coincidence_config = parents["coincidence_contract"]
    if coincidence_config["contract_digest"] != receipt["contract_digest"]:
        raise ContractError("local region parent contract changed")
    half = coincidence_config["measurement"]["half_window_s"]
    aux_root = _host_path(
        root, parents["common_inputs"]["input_roots"]["auxiliary_samples"]
    )
    aux_plan = sealed_json(aux_root / "plan.json")
    channels = parents["common_method"]["method"]["channels"]["L1"]
    targets = []
    for spec in design["targets"]:
        gps = spec["gps_start"]
        matching = [r for r in rows if r["detector"] == "L1" and r["gps_start"] == gps]
        segments = [
            s
            for s in parents["cat1"]["segments"]["L1"]
            if s[0] <= gps and gps + design["controls"]["context_duration_s"] <= s[1]
        ]
        if len(matching) != 1 or len(segments) != 1:
            raise ContractError("local target/segment identity missing or duplicated")
        row, segment = matching[0], segments[0]
        candidates = [r["gps_start"] for r in classified]
        blocks = control_blocks(segment, candidates, design["controls"])
        coverage = [
            r
            for r in aux_plan["series"]
            if r["run"] == "O3a"
            and r["detector"] == "L1"
            and r["channel"] in channels
            and any(
                u["target_gps"] == gps and u["role"] == "background" for u in r["uses"]
            )
        ]
        required = design["controls"]["minimum_reference_blocks"]
        targets.append(
            {
                **spec,
                "same_cat1_segment_gps": segment,
                "identity_digest": row["seed_identity_digest"],
                "local_offset_interval_s": [
                    row["t_offset_s"] - half,
                    row["t_offset_s"] + half,
                ],
                "frequency_band_hz": [row["f_lo_hz"], row["f_hi_hz"]],
                "maximum_blocks_before_exclusions": (segment[1] - segment[0])
                // design["controls"]["chronological_block_s"],
                "candidate_clean_blocks_before_cat2_cat3": len(blocks),
                "minimum_reference_blocks": required,
                "best_possible_corrected_tail_fraction": design["decision"][
                    "family_target_count"
                ]
                / (1 + len(blocks)),
                "tail_resolution_possible": len(blocks) >= required,
                "cached_background_in_same_segment": len(coverage) == len(channels)
                and all(
                    segment[0]
                    <= r["interval_gps"][0]
                    < r["interval_gps"][1]
                    <= segment[1]
                    for r in coverage
                ),
                "cat2_cat3_and_channel_safety": "NOT_YET_PREFLIGHTED",
            }
        )
    body = {
        "status": "CANDIDATE_METADATA_PREFLIGHT_ONLY",
        "design_digest": canonical_json_sha256(design),
        "targets": targets,
        "real_sample_arrays_opened": False,
        "new_outcomes_computed": False,
        "gate_c_enabled": False,
    }
    return {**body, "receipt_digest": canonical_json_sha256(body)}
