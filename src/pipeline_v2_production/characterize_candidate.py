"""Per-candidate single-detector characterization: peak, loudness, cross-corr.

Given one 32 s analysis window ``[gps, gps + 32]`` in one detector, reports three
descriptors a reader wants for a single candidate:

1. **In-band peak frequency** — the frequency of maximum whitened ASD inside the
   requested band.
2. **In-band loudness ratio** — the window's in-band energy over the median of a
   set of adjacent 32 s windows. A plain order-of-magnitude ratio.
3. **Cross-detector max |correlation|** — the normalized cross-correlation with
   the partner detector over the physical light-travel lag. This does **not**
   reimplement the coincidence test; it calls the same
   ``coincidence_physical`` helpers, so the number here and the authoritative
   veto cannot drift apart.

Attribution
-----------
The three-descriptor cross-check recipe is adapted from an independent
reproduction by GitHub user **Kretski** (gist ``d0f17ae69cd8fc40093cb4a4e372b7be``),
contributed on the detector-characterization forum thread for the L1 singleton
at GPS 1382955253. Two caveats travel with it, and are enforced here rather than
left in prose:

* The **loudness ratio is not a significance.** Whitening self-inflates against a
  feature this loud and the adjacent-window spread is small, so a z-score built
  on it is wildly optimistic. Only the plain ratio is reported, and it is labelled
  as an order-of-magnitude descriptor.
* The **cross-correlation value is not stable to three decimals** when there is no
  real peak — the maximiser then picks noise and the lag wanders to the edge of
  the search window. A small value is *consistent with zero*, not a measurement.

Window convention: ``--gps`` is the start of the 32 s analysis window, matching
``coincidence_physical._whitened``. Catalogues before 2026-07-24 label the padded
crop, so for those pass ``gps_start + 4``.

Usage
-----
    python -m src.pipeline_v2_production.characterize_candidate \
        --detector L1 --gps 1382955232 --band 26 42

Writes ``data/production/aggregated/characterize_{detector}_{gps}.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from src.core.utils import record_environment, setup_logger
from src.pipeline_v2_production.coincidence_physical import (
    LIGHT_TRAVEL_S, LAG_MARGIN_S, SEGMENT_LENGTH, SPEC_FRANGE,
    _whitened, _bandpass, _max_normxcorr)

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
PARTNER = {"H1": "L1", "L1": "H1"}


def _peak_hz(tsw, band: tuple[float, float]) -> float:
    """Frequency of maximum whitened ASD inside the band."""
    asd = tsw.asd(fftlength=4, overlap=2)
    f = asd.frequencies.value
    m = (f >= band[0]) & (f <= band[1])
    return float(f[m][np.argmax(asd.value[m])])


def _inband_energy(tsw, band: tuple[float, float], fs: float) -> float:
    v = _bandpass(np.asarray(tsw.value, dtype=float), fs, band[0], band[1])
    return float(np.sum(v * v))


def run(detector: str, gps: float, band=SPEC_FRANGE, partner: str | None = None,
        n_background: int = 16, bg_spacing: float = 40.0) -> dict:
    partner = partner or PARTNER[detector]
    band = (float(band[0]), float(band[1]))

    tsw = _whitened(detector, gps)
    fs = float(1.0 / tsw.dt.value)

    # 1. in-band peak frequency
    peak_hz = _peak_hz(tsw, band)

    # 2. loudness ratio vs adjacent windows (PLAIN RATIO, not a significance)
    cand_e = _inband_energy(tsw, band, fs)
    half = n_background // 2
    offsets = [bg_spacing * k for k in range(-half, 0)] + \
              [bg_spacing * k for k in range(1, n_background - half + 1)]
    bg = []
    for off in offsets:
        try:
            bg.append(_inband_energy(_whitened(detector, gps + off), band, fs))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"bg window {off:+.0f}s skipped: {e}")
    bg = np.array(bg)
    loudness_ratio = float(cand_e / np.median(bg)) if len(bg) else float("nan")

    # 3. cross-detector max |corr| — REUSES the coincidence helpers, no reimpl.
    tsp = _whitened(partner, gps)
    x = _bandpass(np.asarray(tsw.value, dtype=float), fs, band[0], band[1])
    y = _bandpass(np.asarray(tsp.value, dtype=float), fs, band[0], band[1])
    cc = _max_normxcorr(x, y, fs, LIGHT_TRAVEL_S + LAG_MARGIN_S)

    out = {
        "detector": detector, "partner": partner, "gps": float(gps),
        "window": [float(gps), float(gps + SEGMENT_LENGTH)],
        "band_hz": list(band),
        "peak_frequency_hz": peak_hz,
        "loudness_ratio": loudness_ratio,
        "loudness_candidate_energy": cand_e,
        "loudness_background_median": float(np.median(bg)) if len(bg) else None,
        "loudness_background_spread": [float(bg.min()), float(bg.max())] if len(bg) else None,
        "loudness_n_background": int(len(bg)),
        "cross_detector_max_corr": float(cc),
        "cross_corr_lag_bound_s": LIGHT_TRAVEL_S + LAG_MARGIN_S,
        "caveats": {
            "loudness_ratio": (
                "Plain order-of-magnitude ratio, NOT a calibrated significance. "
                "Whitening self-inflates against a loud isolated feature and the "
                "adjacent-window spread is small; any z-score is optimistic."),
            "cross_detector_max_corr": (
                "The authoritative veto is coincidence-physical (this reuses its "
                "helpers). A small value is consistent with zero, not a "
                "measurement; do not quote to three decimals."),
        },
        "attribution": (
            "Cross-check recipe adapted from an independent reproduction by GitHub "
            "user Kretski (gist d0f17ae69cd8fc40093cb4a4e372b7be)."),
    }
    dest = AGG / f"characterize_{detector}_{int(gps)}.json"
    dest.write_text(json.dumps(out, indent=2))
    logger.info(
        f"{detector} {int(gps)} band {band}: peak {peak_hz:.1f} Hz, loudness "
        f"{loudness_ratio:.0f}x (n_bg={len(bg)}), cross-corr {cc:.3f} "
        f"(consistent-with-zero if small)")
    logger.info(f"wrote {dest}")
    record_environment(AGG, f"characterize_{detector}_{int(gps)}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--detector", required=True, choices=("H1", "L1"))
    p.add_argument("--gps", type=float, required=True,
                   help="Start of the 32 s analysis window (gps_start+4 for "
                        "catalogues before 2026-07-24).")
    p.add_argument("--band", type=float, nargs=2, default=list(SPEC_FRANGE),
                   metavar=("F_LO", "F_HI"), help="In-band frequency range (Hz).")
    p.add_argument("--partner", choices=("H1", "L1"), default=None)
    p.add_argument("--n-background", type=int, default=16,
                   help="Adjacent windows for the loudness ratio.")
    p.add_argument("--bg-spacing", type=float, default=40.0,
                   help="Spacing between adjacent loudness windows (s).")
    a = p.parse_args()
    run(a.detector, a.gps, band=a.band, partner=a.partner,
        n_background=a.n_background, bg_spacing=a.bg_spacing)


if __name__ == "__main__":
    main()
