"""Family-wise empirical null calibration for the PEM coherence veto.

Replaces BOTH the raw per-channel threshold (C >= 0.6, measured FPR 23%
per channel on time-shift surrogates) and the quasi-Gaussian analytic
p-value ((1-C)^(n_d-1), falsified by ~7 orders of magnitude at C=0.6)
with a threshold read off the EMPIRICAL null distribution of the
event-level max-statistic:

    Cmax_null = max over the event's m tested channels and the 20-500 Hz
                band of the coherence between time-shifted strain and
                UN-shifted auxiliary channels.

Design (adapted POT-style, same philosophy as calibrate_tau_coh):
- One background block of `block_s` seconds (default 4 h) per event,
  chosen inside {DET}_BURST_CAT1 segments, excluding +/-96 s around every
  taxonomy candidate (anti-circularity, as in build_native_index).
- 32 s windows on a 96 s stride (>= 64 s guard between windows).
- Surrogates = all ordered pairs (strain window i, aux window j) with
  |t_i - t_j| >= 64 s. The SAME shift is applied against all m channels
  simultaneously, so the cross-channel correlation structure (e.g. the
  three SUS-ETMX_L1/L2/L3 actuator stages) is preserved by construction:
  channels are never resampled independently.
- Family-wise threshold = (1-alpha) quantile of the Cmax_null sample
  (alpha = 0.01 default). Pairs sharing a window are not independent;
  the threshold uncertainty is therefore quantified with a block
  bootstrap over WINDOW indices (not over pairs) and reported as a CI.

Outputs one JSON per event:
    data/production/aggregated/pem/null_calibration_{det}_{gps}.json
and, via `apply_family_wise_verdicts`, a consolidated
    data/production/aggregated/pem/pem_family_wise_verdicts.csv
consumed by the aggregate report ledger.

The analytic p-value is kept ONLY as a secondary diagnostic column; it
must never decide COUPLED/NO_CORRELATION.
"""

from __future__ import annotations

import argparse
import json
import numpy as np
import pandas as pd
from pathlib import Path

from gwosc.timeline import get_segments
from gwpy.timeseries import TimeSeries

from src.core.utils import setup_logger
from src.core.data_loader import fetch_strain_data

logger = setup_logger(__name__)

PEM_DIR = Path("data/production/aggregated/pem")

# Deliberately OUTSIDE the artifacts directory. This is re-downloadable
# auxiliary strain, ~0.5 GB per event, and it used to sit inside
# aggregated/pem/ where it made up 9.1 GB of a 9.6 GB "results" folder --
# large enough to dominate any archive or upload of that directory. The
# results are the JSONs; this is scratch.
NULL_CACHE = Path("data/cache/pem_null")

WINDOW_S = 32.0
STRIDE_S = 96.0          # >= 64 s guard between window starts
GUARD_S = 64.0
FFTLENGTH_S = 2.0
OVERLAP_S = 1.0
N_WELCH = 31             # segments per 32 s window at 2 s / 1 s overlap
F_LOW, F_HIGH = 20.0, 500.0
CANDIDATE_EXCLUSION_S = 96.0


def _candidate_gps(run: str) -> np.ndarray:
    tax = Path(f"data/production/aggregated/Master_Taxonomy_{run}.csv")
    if not tax.exists():
        logger.warning(f"{tax} missing: no candidate exclusion applied.")
        return np.array([])
    df = pd.read_csv(tax)
    return pd.to_numeric(df["gps_start"], errors="coerce").dropna().values


def _pick_background_span(detector: str, event_gps: float, block_s: float,
                          run: str,
                          min_clean_windows: int = 60) -> tuple[int, int, np.ndarray]:
    """Nearest CAT1-clean span of block_s seconds with enough clean windows.

    Candidate exclusion is applied per-WINDOW (drop 32 s windows within
    +/-96 s of the event or of any taxonomy candidate), not per-span: with
    ~10^4 candidates in the run, no multi-hour span is candidate-free, but
    plenty of individual windows are. Returns (start, end, window_starts).
    """
    cands = _candidate_gps(run)
    search_half = 7 * 86400
    segs = get_segments(f"{detector}_BURST_CAT1",
                        int(event_gps - search_half),
                        int(event_gps + search_half))
    best = None
    for s0, s1 in segs:
        s0, s1 = float(s0), float(s1)
        start = s0
        while start + block_s <= s1:
            end = start + block_s
            wstarts = np.arange(start, end - WINDOW_S, STRIDE_S)
            centers = wstarts + WINDOW_S / 2
            clean = np.abs(centers - event_gps) > (
                WINDOW_S / 2 + CANDIDATE_EXCLUSION_S)
            if len(cands):
                dmin = np.min(np.abs(centers[:, None] - cands[None, :]),
                              axis=1)
                clean &= dmin > (WINDOW_S / 2 + CANDIDATE_EXCLUSION_S)
            n_clean = int(clean.sum())
            if n_clean >= min_clean_windows:
                dist = abs(start - event_gps)
                if best is None or dist < best[0]:
                    best = (dist, int(start), int(end), wstarts[clean])
            start += block_s / 2
    if best is None:
        raise RuntimeError(
            f"No {block_s:.0f}s background span with >= {min_clean_windows} "
            f"candidate-free windows found for {detector} around GPS "
            f"{event_gps} — cannot calibrate a family-wise null.")
    return best[1], best[2], best[3]


def _fetch_aux_block(channel: str, start: int, end: int,
                     nds_host: str, max_fs: float | None = None) -> TimeSeries:
    """Fetch (and cache) one background block of an auxiliary channel.

    ``max_fs`` caps the cached sample rate. Pass the strain rate: the
    coherence below already resamples every channel to ``min(fs_strain,
    fs_aux)``, so decimating at fetch time is the same operation moved
    earlier — while cutting the 16384 Hz channels, which dominate the cache
    at ~800 MB per 4 h block, by 4x. Measured effect on the window FFTs:
    1.6e-6 relative, from doing the float32 cast after the decimation
    instead of before, against a threshold CI of order 0.03.
    """
    NULL_CACHE.mkdir(parents=True, exist_ok=True)
    safe = channel.replace(":", "_")
    cache = NULL_CACHE / f"{safe}_{start}_{end}.npz"
    if cache.exists():
        d = np.load(cache)
        return TimeSeries(d["data"], t0=start, sample_rate=float(d["fs"]),
                          name=channel)
    ts = TimeSeries.fetch(channel, start=start, end=end, host=nds_host)
    if max_fs is not None and float(ts.sample_rate.value) > max_fs:
        ts = ts.resample(max_fs)
    np.savez_compressed(cache, data=ts.value.astype(np.float32),
                        fs=float(ts.sample_rate.value))
    return ts


def _purge_span_cache(channels: list[str], start: int, end: int) -> float:
    """Delete one background block from the cache. Returns the GB freed.

    Each event needs ~0.5 GB of auxiliary background even after decimation,
    and spans rarely repeat across events, so a 60-event batch would otherwise
    leave ~30 GB behind for no reuse.
    """
    freed = 0
    for ch in channels:
        p = NULL_CACHE / f"{ch.replace(':', '_')}_{start}_{end}.npz"
        if p.exists():
            freed += p.stat().st_size
            try:
                p.unlink()
            except OSError as e:
                logger.warning(f"Could not purge {p.name}: {e}")
    return freed / 1e9


def _window_segment_ffts(ts: TimeSeries, block_start: int,
                         window_starts: np.ndarray,
                         band: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """FFTs of the N_WELCH Hann segments of every 32 s window.

    Returns (ffts[W, N_WELCH, F] complex64, freqs[F]) restricted to `band`.
    """
    fs = float(ts.sample_rate.value)
    nfft = int(FFTLENGTH_S * fs)
    hop = int((FFTLENGTH_S - OVERLAP_S) * fs)
    win = np.hanning(nfft).astype(np.float32)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    fmask = (freqs >= band[0]) & (freqs <= band[1])
    # Coherence is scale-invariant: z-score the whole block so |FFT|^2
    # stays O(1). Raw strain is ~1e-19, whose float32 power (~1e-38)
    # underflows AND is swallowed by any additive eps in the denominator
    # — this exact failure produced threshold_fw=0.003 on real data.
    raw = ts.value.astype(np.float64)
    std = raw.std()
    if std == 0:
        raise RuntimeError(f"Constant time series in block for {ts.name}")
    data = ((raw - raw.mean()) / std).astype(np.float32)
    out = np.empty((len(window_starts), N_WELCH, int(fmask.sum())),
                   dtype=np.complex64)
    for wi, wstart in enumerate(window_starts):
        off0 = int((wstart - block_start) * fs)
        for k in range(N_WELCH):
            seg = data[off0 + k * hop: off0 + k * hop + nfft]
            out[wi, k] = np.fft.rfft(seg * win)[fmask]
    return out, freqs[fmask]


def calibrate_event(detector: str, event_gps: float, channels: list[str],
                    run: str = "O4a", block_s: float = 14400.0,
                    alpha: float = 0.01, nds_host: str = "nds.gwosc.org",
                    n_boot: int = 200, seed: int = 42,
                    purge_cache: bool = False) -> dict:
    """Empirical family-wise null for one event. Writes and returns the JSON."""
    rng = np.random.default_rng(seed)
    bstart, bend, window_starts = _pick_background_span(
        detector, event_gps, block_s, run)
    W = len(window_starts)
    logger.info(f"[{detector} {event_gps:.0f}] background span "
                f"[{bstart}, {bend}] ({(bend-bstart)/3600:.1f} h, "
                f"{W} candidate-free windows)")

    strain = fetch_strain_data(detector, bstart, bend)

    # Per-channel coherence max over band for every (i, j) pair.
    # The same strain shift i faces every channel's aux window j: the
    # max over channels is taken per (i, j), preserving inter-channel
    # correlation.
    fs_strain = float(strain.sample_rate.value)
    cmax_per_channel = []
    used_channels = []
    for ch in channels:
        try:
            aux = _fetch_aux_block(ch, bstart, bend, nds_host,
                                   max_fs=fs_strain)
        except Exception as e:
            logger.warning(f"Aux fetch failed for {ch}: {e} — channel "
                           "dropped from the null (and must then be "
                           "dropped from the observed max too).")
            continue
        fs = min(fs_strain, float(aux.sample_rate.value))
        st = strain.resample(fs) if fs_strain > fs else strain
        ax = aux.resample(fs) if float(aux.sample_rate.value) > fs else aux
        band = (F_LOW, min(F_HIGH, 0.9 * fs / 2))
        X, _ = _window_segment_ffts(st, bstart, window_starts, band)
        Y, _ = _window_segment_ffts(ax, bstart, window_starts, band)
        Px = np.sum(np.abs(X) ** 2, axis=1)          # (W, F)
        Py = np.sum(np.abs(Y) ** 2, axis=1)
        # C[i, j, f] = |sum_k X[i,k,f] conj(Y[j,k,f])|^2 / (Px[i,f] Py[j,f])
        cross = np.einsum("ikf,jkf->ijf", X, np.conj(Y), optimize=True)
        coh = (np.abs(cross) ** 2) / (Px[:, None, :] * Py[None, :, :] + 1e-30)
        cmax_per_channel.append(coh.max(axis=2))     # (W, W)
        used_channels.append(ch)
        del X, Y, cross, coh

    if not used_channels:
        raise RuntimeError("No auxiliary channel could be fetched: "
                           "family-wise null impossible for this event.")

    stack = np.stack(cmax_per_channel)                 # (m, W, W)
    cmax = np.max(stack, axis=0)                       # (W, W) over channels
    argmax_ch = np.argmax(stack, axis=0)               # (W, W)
    ii, jj = np.meshgrid(np.arange(W), np.arange(W), indexing="ij")
    valid = np.abs(window_starts[ii] - window_starts[jj]) >= GUARD_S
    null_sample = cmax[valid]
    n_pairs = int(valid.sum())
    threshold = float(np.quantile(null_sample, 1.0 - alpha))

    # Per-channel diagnostics: which channel drags the family-wise
    # quantile? A single channel with a persistent spectral line shows
    # (a) a high per-channel null quantile, (b) a large share of the
    # argmax among surrogate pairs, (c) high zero-lag (i==j) coherence
    # inside the background block (deterministic line signature).
    per_channel = {}
    argmax_valid = argmax_ch[valid]
    for ci, ch in enumerate(used_channels):
        ch_null = stack[ci][valid]
        per_channel[ch] = {
            "null_q": float(np.quantile(ch_null, 1.0 - alpha)),
            "null_median": float(np.median(ch_null)),
            "argmax_fraction": float(np.mean(argmax_valid == ci)),
            "zero_lag_median": float(np.median(np.diag(stack[ci]))),
        }
    # ZERO-LAG CONTROL. The null above is built from time-shifted pairs, but
    # the observed statistic is measured at zero lag, where persistent spectral
    # lines make strain and auxiliary channels coherent at *every* time. Without
    # this control a high observed C_max cannot be told apart from "this
    # detector is simply like that", and the COUPLED fraction is uninterpretable.
    #
    # The diagonal of the (W, W) coherence matrix is exactly that: zero-lag
    # C_max on quiet, candidate-free background windows. Persist its
    # distribution, not only the per-channel median, so the fraction of quiet
    # windows exceeding the veto threshold can be quoted directly.
    zero_lag_cmax = np.diag(cmax)
    zero_lag = {
        "n_windows": int(len(zero_lag_cmax)),
        "median": float(np.median(zero_lag_cmax)),
        "q90": float(np.quantile(zero_lag_cmax, 0.90)),
        "q99": float(np.quantile(zero_lag_cmax, 1.0 - alpha)),
        "max": float(zero_lag_cmax.max()),
        # The number that matters: how often does an ordinary quiet window
        # already fire the veto? If this is not small, the veto is measuring
        # the detector, not the candidate.
        "fraction_above_threshold": float(np.mean(zero_lag_cmax > threshold)),
        "values": [float(x) for x in zero_lag_cmax],
    }

    hist_counts, hist_edges = np.histogram(null_sample, bins=50,
                                           range=(0.0, 1.0))

    # Threshold uncertainty: bootstrap over WINDOW indices, because pairs
    # sharing a window are dependent — pair-level bootstrap would be
    # spuriously tight.
    boot_thr = np.empty(n_boot)
    for b in range(n_boot):
        wsel = rng.integers(0, W, size=W)
        sub = cmax[np.ix_(wsel, wsel)]
        vsub = np.abs(window_starts[wsel][:, None]
                      - window_starts[wsel][None, :]) >= GUARD_S
        vals = sub[vsub]
        boot_thr[b] = np.quantile(vals, 1.0 - alpha) if len(vals) else np.nan
    ci = (float(np.nanpercentile(boot_thr, 2.5)),
          float(np.nanpercentile(boot_thr, 97.5)))

    result = {
        "detector": detector,
        "event_gps": float(event_gps),
        "run": run,
        "channels": used_channels,
        "m_channels": len(used_channels),
        "background_span": [bstart, bend],
        "n_windows": W,
        "n_surrogate_pairs": n_pairs,
        "alpha_family_wise": alpha,
        "threshold_fw": threshold,
        "threshold_fw_ci95": ci,
        "per_channel_null": per_channel,
        "zero_lag_control": zero_lag,
        "dominant_null_channel": max(per_channel,
                                     key=lambda c: per_channel[c]["argmax_fraction"]),
        "null_histogram": {"bin_edges": hist_edges.tolist(),
                           "counts": hist_counts.tolist()},
        "method": ("empirical max-statistic over m channels, strain "
                   "time-shift pairs (32s windows, 96s stride, 64s guard), "
                   "channel correlation preserved (single shift vs all "
                   "channels), window-level bootstrap CI"),
    }
    PEM_DIR.mkdir(parents=True, exist_ok=True)
    out = PEM_DIR / f"null_calibration_{detector}_{int(event_gps)}.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"[{detector} {event_gps:.0f}] m={len(used_channels)} "
                f"N_pairs={n_pairs} threshold_fw={threshold:.3f} "
                f"CI95=({ci[0]:.3f}, {ci[1]:.3f}) -> {out}")

    if purge_cache:
        freed = _purge_span_cache(used_channels, bstart, bend)
        logger.info(f"[{detector} {event_gps:.0f}] purged {freed:.2f} GB of "
                    "auxiliary background cache.")
    return result


def apply_family_wise_verdicts(run: str = "O4a") -> Path:
    """Join coherence_report.csv with the per-event calibrations.

    Writes pem_family_wise_verdicts.csv: one row per event with m, N,
    threshold, observed Cmax and the verdict. Events without a
    calibration JSON are marked UNCALIBRATED — never silently classified.
    """
    rep = pd.read_csv(PEM_DIR / "coherence_report.csv")
    rows = []
    for (det, gps), grp in rep.groupby(["detector", "gps_start"]):
        tested = grp[grp["data_available"] & grp["max_coherence"].notna()]
        cal_path = PEM_DIR / f"null_calibration_{det}_{int(gps)}.json"
        if not cal_path.exists():
            rows.append({"detector": det, "gps_start": gps,
                         "family": grp["family"].iloc[0],
                         "m_channels": len(tested), "n_surrogate_pairs": None,
                         "threshold_fw": None, "cmax_observed":
                         tested["max_coherence"].max() if len(tested) else None,
                         "top_channel": None, "verdict": "UNCALIBRATED"})
            continue
        cal = json.loads(cal_path.read_text())
        n_windows = cal.get("n_windows")
        # Observed max restricted to the channels present in the null:
        # a channel dropped from the null must not contribute to the max.
        obs = tested[tested["aux_channel"].isin(cal["channels"])]
        if len(obs) == 0:
            rows.append({"detector": det, "gps_start": gps,
                         "family": grp["family"].iloc[0],
                         "m_channels": cal["m_channels"],
                         "n_surrogate_pairs": cal["n_surrogate_pairs"],
                         "threshold_fw": cal["threshold_fw"],
                         "cmax_observed": None, "top_channel": None,
                         "verdict": "UNCALIBRATED"})
            continue
        top = obs.sort_values("max_coherence", ascending=False).iloc[0]
        cmax_obs = float(top["max_coherence"])
        verdict = "COUPLED" if cmax_obs > cal["threshold_fw"] else "NO_CORRELATION"
        rows.append({"detector": det, "gps_start": gps,
                     "family": grp["family"].iloc[0],
                     "m_channels": cal["m_channels"],
                     "n_windows": n_windows,
                     "n_surrogate_pairs": cal["n_surrogate_pairs"],
                     "threshold_fw": cal["threshold_fw"],
                     "cmax_observed": cmax_obs,
                     "top_channel": top["aux_channel"],
                     "verdict": verdict})
    out = PEM_DIR / "pem_family_wise_verdicts.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    logger.info(f"Wrote {out} ({len(rows)} events)")
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=str, default="O4a")
    p.add_argument("--alpha", type=float, default=0.01)
    p.add_argument("--block-hours", type=float, default=4.0)
    p.add_argument("--nds-host", type=str, default="nds.gwosc.org")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--apply-only", action="store_true",
                   help="Skip calibration; only regenerate the verdicts CSV.")
    p.add_argument("--purge-cache", action="store_true",
                   help="Delete each event's auxiliary background block once "
                        "its null is computed. Spans rarely repeat across "
                        "events, so a large batch otherwise leaves tens of GB "
                        "on disk for no reuse.")
    args = p.parse_args()

    if not args.apply_only:
        from src.pipeline_v2_production.pem_coherence_analysis import require_nds2
        if not require_nds2():
            raise SystemExit(
                "Aborting: without the NDS2 client every channel would be "
                "dropped from the null and each event would fail with "
                "'No auxiliary channel could be fetched', which is a missing "
                "package, not a property of the data."
            )
        rep = pd.read_csv(PEM_DIR / "coherence_report.csv")
        for (det, gps), grp in rep.groupby(["detector", "gps_start"]):
            tested = grp[grp["data_available"] & grp["max_coherence"].notna()]
            if len(tested) == 0:
                logger.warning(f"{det} {gps}: no tested channels, skipped.")
                continue
            out = PEM_DIR / f"null_calibration_{det}_{int(gps)}.json"
            if out.exists():
                logger.info(f"{det} {gps}: calibration exists, skipped "
                            "(delete the JSON to redo).")
                continue
            try:
                calibrate_event(det, float(gps),
                                tested["aux_channel"].tolist(),
                                run=args.run,
                                block_s=args.block_hours * 3600,
                                alpha=args.alpha, nds_host=args.nds_host,
                                seed=args.seed, purge_cache=args.purge_cache)
            except Exception as e:
                # One transient failure (e.g. GWOSC HTTP 500) must not kill
                # the whole batch: the event stays UNCALIBRATED (explicit
                # in the verdicts CSV) and can be retried by re-running.
                logger.error(f"{det} {gps}: calibration failed: {e}")
    apply_family_wise_verdicts(args.run)


if __name__ == "__main__":
    main()
