"""Where in the time-frequency plane is DANTE blind? An empirical map.

Both manuscripts show an *analytic* blind-spot boundary, T = Q_max/f (Figure 14):
DANTE's primary Q-transform uses a bounded quality factor (Qrange 4-64), so a transient
that is simultaneously short and narrowband cannot be concentrated by any tile
and its morphology degrades. The boundary has never been validated empirically --
"no measurement of what actually happens near it" is a standing reviewer point.

This maps it directly. The probe is a sine-Gaussian burst, the standard
unmodelled-burst waveform, because its two parameters set exactly the axes of the
blind spot:

    h(t) = sin(2*pi*f0*(t-t0)) * exp(-(t-t0)^2 / (2*tau^2)),   tau = Q / (2*pi*f0)

so central frequency f0 and quality factor Q give duration ~ Q/f0 and fractional
bandwidth df/f = 1/Q. Sweeping (f0, Q) traverses the (duration, bandwidth) plane
and crosses the Q_max=64 boundary.

Each cell is injected into real vetoed O4a background at a fixed matched-filter
SNR -- fixed, so a non-detection is a statement about morphology, not loudness --
scored against the frozen O3b dictionary (K=275) exactly as production flags, and
compared to the SAME segment scored without the injection (paired control). The
cell's signal is the score *excess* over its own clean baseline and the flag rate
against the 0.3783 threshold; the blind spot is where both collapse.

Requires the O3b reference index. Single detector (L1, the vetted one): the blind
spot is a property of one detector's morphology pathway, not of coincidence.

Usage
-----
    python -m src.pipeline_v2_production.blind_spot_map --pilot
    python -m src.pipeline_v2_production.blind_spot_map --n-realizations 6

Writes
``data/production/aggregated/blind_spot_map_centered_q64_v3_{run}.json``.
The invalid pre-audit artifact is never overwritten.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from src.core.utils import record_environment, setup_logger

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
SEGMENT_LENGTH = 32.0
SAMPLE_RATE = 4096
FLAG_THRESHOLD = 0.3783          # O3b session flagging threshold
# Upper bound of the PRIMARY flag path's Q-transform (config.yaml preprocessing
# qrange = [4, 64], used by generate_qtransform). NOT the V3 multiscale Q=32; the
# scoring here goes through the primary O3b path, so 64 is the boundary that
# applies. A sine-Gaussian with Q > Q_MAX cannot be concentrated by any tile.
Q_MAX = 64.0
TARGET_SNR = 20.0                # loud enough that a miss is morphological
ANALYSIS_VERSION = "centered_q64_v3"
QRANGE = (4, 64)

# Grid: f0 across the analysis band (log-spaced), Q from broadband to very
# narrowband, straddling Q_MAX so the analytic boundary sits inside the map.
DEFAULT_F0 = (35.0, 60.0, 100.0, 170.0, 300.0)
DEFAULT_Q = (2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0)


def _sine_gaussian(f0: float, q: float) -> np.ndarray:
    """Unit-amplitude sine-Gaussian at SAMPLE_RATE, truncated at +-4 tau."""
    tau = q / (2.0 * np.pi * f0)
    half = max(4.0 * tau, 3.0 / f0)          # cover the envelope and a few cycles
    t = np.arange(-half, half, 1.0 / SAMPLE_RATE)
    return np.sin(2.0 * np.pi * f0 * t) * np.exp(-t * t / (2.0 * tau * tau))


def _injection_center(gps: float) -> float:
    """GPS time at which InjectionEngine must place the waveform centre."""
    return float(gps) + SEGMENT_LENGTH / 2.0


def _score(rgb, scorers: dict) -> dict:
    return {name: float(sc.score_spectrogram([rgb], threshold=0.0)[0]["novelty_score"])
            for name, sc in scorers.items()}


def _cell(f0: float, q: float, times, rng, scorers, n_real: int) -> dict:
    """Inject the (f0, Q) sine-Gaussian into n_real segments; paired clean control."""
    import warnings
    import matplotlib

    from src.core.data_loader import fetch_local_or_remote_strain
    from src.core.injection import InjectionEngine
    from src.core.preprocessor import (whiten_context, extract_clean_subwindow,
                                       generate_qtransform)

    eng = InjectionEngine(sample_rate=SAMPLE_RATE)
    sg = _sine_gaussian(f0, q)
    inj_o3b, clean_o3b, inj_nat, snrs = [], [], [], []
    used = 0
    for gps in times:
        if used >= n_real:
            break
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ts = fetch_local_or_remote_strain(
                    "L1", gps - 4.0, gps + SEGMENT_LENGTH + 4.0, edge_tolerance=4.0)
                if not np.isfinite(np.asarray(ts.value)).all():
                    continue
                # clean baseline: same segment, no injection
                tw0, _ = whiten_context(ts, gps, gps + SEGMENT_LENGTH, pad=4.0)
                spec0 = generate_qtransform(extract_clean_subwindow(
                    tw0, gps, gps + SEGMENT_LENGTH),
                    save_path=None,
                    cmap="cividis",
                    qrange=QRANGE,
                )
                rgb0 = (matplotlib.colormaps["cividis"](spec0)[:, :, :3] * 255).astype(np.uint8)

                # scale the burst to a fixed matched-filter SNR, then inject at centre
                snr_unit = eng.compute_snr(ts.crop(gps, gps + SEGMENT_LENGTH), sg)
                if not np.isfinite(snr_unit) or snr_unit <= 0:
                    continue
                h = sg * (TARGET_SNR / snr_unit)
                # InjectionEngine interprets t_inject as the waveform centre.
                # Do not subtract half the waveform duration here.
                t_place = _injection_center(gps)
                tsi = eng.inject(ts, h, t_place)
                twi, _ = whiten_context(tsi, gps, gps + SEGMENT_LENGTH, pad=4.0)
                speci = generate_qtransform(extract_clean_subwindow(
                    twi, gps, gps + SEGMENT_LENGTH),
                    save_path=None,
                    cmap="cividis",
                    qrange=QRANGE,
                )
                rgbi = (matplotlib.colormaps["cividis"](speci)[:, :, :3] * 255).astype(np.uint8)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"cell f0={f0} Q={q} gps={gps} failed: {e}")
            continue
        c, i = _score(rgb0, scorers), _score(rgbi, scorers)
        clean_o3b.append(c["o3b"]); inj_o3b.append(i["o3b"])
        inj_nat.append(i["native"]); snrs.append(TARGET_SNR)
        used += 1

    if used == 0:
        return {"f0": f0, "q": q, "n": 0}
    inj_o3b, clean_o3b = np.array(inj_o3b), np.array(clean_o3b)
    tau = q / (2.0 * np.pi * f0)
    return {
        "f0": f0, "q": q, "n": used,
        "duration_s": float(2.355 * tau),          # FWHM of the Gaussian envelope
        "bandwidth_hz": float(f0 / q),
        "clean_o3b_mean": float(clean_o3b.mean()),
        "inj_o3b_mean": float(inj_o3b.mean()),
        "excess_o3b_mean": float((inj_o3b - clean_o3b).mean()),
        "flag_rate": float((inj_o3b > FLAG_THRESHOLD).mean()),
        "inj_native_mean": float(np.mean(inj_nat)),
        "q_gt_qmax": bool(q > Q_MAX),               # analytic-boundary side
    }


def run(run_name: str = "O4a", f0_values=DEFAULT_F0, q_values=DEFAULT_Q,
        n_realizations: int = 6, seed: int = 42) -> dict:
    from src.core.patch_scorer import PatchScorer
    from src.core.index_contract import (
        load_index_contract,
        taxonomy_representation,
    )
    from src.core.utils import get_reference_dir
    from src.pipeline_v3_multiscale.norm_leakage.common import iter_clean_segments

    rng = np.random.default_rng(seed)
    ref = get_reference_dir()
    native_index = ref / "patch_compressed_index_o4a_q4-64_ex.npz"
    native_contract = load_index_contract(native_index)
    representation = taxonomy_representation(QRANGE, QRANGE)
    scorers = {
        "o3b": PatchScorer(reference_index_path=str(ref / "patch_compressed_index_o3b.npz"),
                           verify_md5=True),
        "native": PatchScorer(reference_index_path=str(native_index),
                              verify_md5=False),
    }
    # A pool of vetted L1 times, reused across every grid cell so the map differs
    # only in the injected morphology, not in which background it landed on.
    need = n_realizations + 12
    times = [int(s.t_bg - SEGMENT_LENGTH / 2)
             for s in iter_clean_segments(run_name.lower(), "L1", need, seed=seed)]
    logger.info(f"{len(times)} vetted L1 background times; grid "
                f"{len(f0_values)}x{len(q_values)} at SNR {TARGET_SNR}")

    cells = []
    for f0 in f0_values:
        for q in q_values:
            cell = _cell(f0, q, times, rng, scorers, n_realizations)
            cells.append(cell)
            if cell.get("n", 0):
                logger.info(
                    f"f0={f0:6.1f} Q={q:6.1f} (T={cell['duration_s']*1e3:5.0f}ms "
                    f"df={cell['bandwidth_hz']:5.1f}Hz) excess {cell['excess_o3b_mean']:+.3f} "
                    f"flag {cell['flag_rate']:.2f}")

    valid = [c for c in cells if c.get("n", 0)]
    # Blind = injection fails to lift the score to a flag on average.
    blind = [c for c in valid if c["flag_rate"] < 0.5]
    # Does the empirical blind set align with the analytic Q>Q_max boundary?
    narrow = [c for c in valid if c["q_gt_qmax"]]
    wide = [c for c in valid if not c["q_gt_qmax"]]
    out = {
        "run": run_name, "seed": seed, "target_snr": TARGET_SNR,
        "flag_threshold": FLAG_THRESHOLD, "q_max": Q_MAX,
        "qrange": list(QRANGE),
        "native_representation": representation,
        "native_index_path": str(native_index),
        "native_index_sha256": native_contract.sha256,
        "n_realizations": n_realizations,
        "injection_time_semantics": "waveform_center_at_analysis_window_center",
        "f0_values": list(f0_values), "q_values": list(q_values),
        "cells": cells,
        "mean_flag_rate_Q_le_Qmax": float(np.mean([c["flag_rate"] for c in wide])) if wide else None,
        "mean_flag_rate_Q_gt_Qmax": float(np.mean([c["flag_rate"] for c in narrow])) if narrow else None,
        "blind_cells": [{"f0": c["f0"], "q": c["q"], "flag_rate": c["flag_rate"],
                         "excess_o3b_mean": c["excess_o3b_mean"]} for c in blind],
        "interpretation_note": (
            "Cells with flag_rate<0.5 at fixed SNR 20 are where the morphology, "
            "not the loudness, keeps DANTE from flagging. Compare "
            "mean_flag_rate_Q_le_Qmax vs _Q_gt_Qmax: if flagging drops sharply for "
            f"Q>Q_max={Q_MAX:g}, the analytic T=Q_max/f boundary is empirically real; if it "
            "drops elsewhere, the true blind spot differs from the drawn boundary."),
    }
    dest = AGG / (
        f"blind_spot_map_{ANALYSIS_VERSION}_{run_name.lower()}.json"
    )
    if dest.exists():
        raise FileExistsError(
            f"Refusing to overwrite blind-spot artifact {dest}"
        )
    dest.write_text(json.dumps(out, indent=2))
    logger.info(
        f"mean flag rate: Q<=Qmax {out['mean_flag_rate_Q_le_Qmax']} vs "
        f"Q>Qmax {out['mean_flag_rate_Q_gt_Qmax']}; {len(blind)} blind cells")
    logger.info(f"wrote {dest}")
    record_environment(
        AGG,
        f"blind_spot_map_{ANALYSIS_VERSION}_{run_name.lower()}",
    )
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--n-realizations", type=int, default=6,
                   help="Background segments injected per grid cell.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pilot", action="store_true",
                   help="Fast machinery check on a coarse 2x3 grid.")
    a = p.parse_args()
    if a.pilot:
        run(a.run, f0_values=(60.0, 200.0), q_values=(4.0, 32.0, 128.0),
            n_realizations=2, seed=a.seed)
    else:
        run(a.run, n_realizations=a.n_realizations, seed=a.seed)


if __name__ == "__main__":
    main()
