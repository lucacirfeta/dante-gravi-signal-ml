"""Independent per-candidate descriptors plus a production-veto lookup.

This command reproduces the public Kretski forum cross-check as an explicitly
independent descriptor recipe:

1. peak frequency from the raw-strain ASD of a 4 s feature window;
2. whitened, band-passed energy relative to the *mean* of adjacent windows;
3. signed normalized correlation and lag in a 4 s feature window.

It intentionally does not reuse the production coincidence preprocessing.
Independent agreement is the point of this cross-check. The optional
``--catalog-gps`` lookup places an already-computed production time-shift/null
veto result next to the descriptors without conflating the two statistics.

Example
-------
    python -m src.pipeline_v2_production.characterize_candidate \
        --detector L1 --gps 1382955232 --feature-gps 1382955253.17 \
        --band 26 42 --partner H1 --catalog-gps 1382955228

Writes ``data/production/aggregated/characterize_{detector}_{gps}.json``.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from src.core.data_loader import fetch_local_or_remote_strain
from src.core.utils import record_environment, setup_logger

logger = setup_logger(__name__)

SEGMENT_LENGTH = 32.0
FEATURE_SPAN = 4.0
WHITEN_FFT_LENGTH = 4.0
WHITEN_OVERLAP = 2.0
PEAK_FFT_LENGTH = 1.0
PEAK_OVERLAP = 0.5
DEFAULT_PAD = 8.0
DEFAULT_MAX_LAG_S = 0.012
SOURCE_GIST = (
    "https://gist.github.com/Kretski/"
    "d0f17ae69cd8fc40093cb4a4e372b7be"
)
SOURCE_REVISION = "9ea0f8e4ec998e1f41521e5265eb3cc0b07ca1a0"

AGG = Path("data/production/aggregated")
DEFAULT_COINCIDENCE_ARTIFACT = AGG / "coincidence_physical_o4a.json"
PARTNER = {"H1": "L1", "L1": "H1"}


def _fetch_raw(detector: str, start: float, end: float):
    """Fetch strain from the local mirror first, then GWOSC."""
    return fetch_local_or_remote_strain(
        detector,
        float(start),
        float(end),
        cache_raw=False,
        edge_tolerance=0.0,
    )


def _descriptor_whitened(
    detector: str,
    start: float,
    duration: float,
    *,
    pad: float = DEFAULT_PAD,
):
    """Reproduce the gist's ``whiten(4, 2)`` followed by a crop."""
    padded = _fetch_raw(detector, start - pad, start + duration + pad)
    whitened = padded.whiten(WHITEN_FFT_LENGTH, WHITEN_OVERLAP)
    return whitened.crop(start, start + duration)


def _peak_hz(raw_segment, band: tuple[float, float]) -> float:
    """Return the maximum raw-strain ASD frequency inside ``band``."""
    asd = raw_segment.asd(
        fftlength=PEAK_FFT_LENGTH,
        overlap=PEAK_OVERLAP,
    )
    frequencies = np.asarray(asd.frequencies.value, dtype=np.float64)
    values = np.asarray(asd.value, dtype=np.float64)
    in_band = (frequencies >= band[0]) & (frequencies <= band[1])
    if not np.any(in_band):
        raise ValueError(f"Band {band} does not overlap the ASD frequency grid")
    indices = np.flatnonzero(in_band)
    return float(frequencies[indices[np.argmax(values[indices])]])


def _inband_energy(whitened, band: tuple[float, float]) -> float:
    """Return squared energy after the gist's GWpy band-pass."""
    filtered = whitened.bandpass(*band)
    values = np.asarray(filtered.value, dtype=np.float64)
    return float(np.sum(values * values))


def _max_signed_corr_with_lag(
    first,
    second,
    *,
    max_lag_s: float = DEFAULT_MAX_LAG_S,
) -> tuple[float, float]:
    """Return the public gist's signed correlation maximum and lag.

    Despite prose in the gist referring to ``|corr|``, its implementation
    maximizes the signed value. We preserve the implementation and label it
    accurately. This is a descriptor, not a time-shift/null veto.
    """
    x = np.asarray(first.value, dtype=np.float64)
    y = np.asarray(second.value, dtype=np.float64)
    n = min(x.size, y.size)
    if n < 2:
        raise ValueError("Need at least two samples for cross-correlation")
    x = x[:n]
    y = y[:n]
    x = (x - x.mean()) / (x.std() + 1e-30)
    y = (y - y.mean()) / (y.std() + 1e-30)

    sample_rate = float(first.sample_rate.value)
    max_lag = int(round(max_lag_s * sample_rate))
    best_corr = -math.inf
    best_lag = 0
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            xa, ya = x[:lag], y[-lag:]
        elif lag > 0:
            xa, ya = x[lag:], y[:-lag]
        else:
            xa, ya = x, y
        corr = float(np.dot(xa, ya) / len(xa))
        if corr > best_corr:
            best_corr = corr
            best_lag = lag
    return best_corr, best_lag / sample_rate


def _loudness_summary(
    candidate_energy: float,
    background_energies: list[float],
) -> dict[str, float | int]:
    """Summarize loudness using the public recipe's mean denominator."""
    if not background_energies:
        raise ValueError("At least one background window is required")
    bg = np.asarray(background_energies, dtype=np.float64)
    mean = float(np.mean(bg))
    median = float(np.median(bg))
    return {
        "ratio_to_background_mean": float(candidate_energy / mean),
        "ratio_to_background_median_diagnostic": float(candidate_energy / median),
        "background_mean": mean,
        "background_median": median,
        "background_min": float(np.min(bg)),
        "background_max": float(np.max(bg)),
        "n_background": int(bg.size),
    }


def _load_production_coincidence(
    detector: str,
    catalog_gps: float | None,
    *,
    artifact: Path = DEFAULT_COINCIDENCE_ARTIFACT,
) -> dict | None:
    """Load, but never recompute or reinterpret, a production-veto entry."""
    if catalog_gps is None or not artifact.exists():
        return None
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    records = payload.get("events", []) if isinstance(payload, dict) else payload
    for record in records:
        if (
            record.get("detector") == detector
            and abs(float(record.get("gps")) - float(catalog_gps)) < 1e-6
        ):
            keys = (
                "gps",
                "detector",
                "partner",
                "t_offset_s",
                "f_lo",
                "f_hi",
                "cc_onsource",
                "cc_null_mean",
                "cc_null_max",
                "n_null",
                "patch_iou",
            )
            result = {key: record.get(key) for key in keys}
            result["artifact"] = str(artifact)
            result["interpretation"] = (
                "Production time-shift/null veto; not comparable one-for-one "
                "with raw descriptor correlation."
            )
            return result
    return None


def run(
    detector: str,
    gps: float,
    feature_gps: float,
    band=(26.0, 42.0),
    partner: str | None = None,
    n_background: int = 16,
    bg_spacing: float = 40.0,
    *,
    catalog_gps: float | None = None,
    coincidence_artifact: Path = DEFAULT_COINCIDENCE_ARTIFACT,
    output_dir: Path = AGG,
    record_provenance: bool = True,
) -> dict:
    """Compute independent descriptors and persist a traceable JSON artifact."""
    partner = partner or PARTNER[detector]
    band = (float(band[0]), float(band[1]))
    if not (gps <= feature_gps <= gps + SEGMENT_LENGTH):
        raise ValueError("feature_gps must lie inside the candidate window")
    if n_background < 1:
        raise ValueError("n_background must be at least 1")

    half_feature = FEATURE_SPAN / 2.0
    raw_feature = _fetch_raw(
        detector,
        feature_gps - half_feature,
        feature_gps + half_feature,
    )
    peak_hz = _peak_hz(raw_feature, band)

    candidate = _descriptor_whitened(detector, gps, SEGMENT_LENGTH)
    candidate_energy = _inband_energy(candidate, band)

    half_background = n_background // 2
    offsets = [
        bg_spacing * index
        for index in range(-half_background, n_background - half_background + 1)
        if index != 0
    ][:n_background]
    background_energies = [
        _inband_energy(
            _descriptor_whitened(detector, gps + offset, SEGMENT_LENGTH),
            band,
        )
        for offset in offsets
    ]
    loudness = _loudness_summary(candidate_energy, background_energies)

    corr_start = feature_gps - half_feature
    first = _descriptor_whitened(detector, corr_start, FEATURE_SPAN).bandpass(*band)
    second = _descriptor_whitened(partner, corr_start, FEATURE_SPAN).bandpass(*band)
    cross_corr, cross_corr_lag_s = _max_signed_corr_with_lag(first, second)

    production_coincidence = _load_production_coincidence(
        detector,
        catalog_gps,
        artifact=coincidence_artifact,
    )

    out = {
        "detector": detector,
        "partner": partner,
        "gps": float(gps),
        "feature_gps": float(feature_gps),
        "window": [float(gps), float(gps + SEGMENT_LENGTH)],
        "band_hz": list(band),
        "descriptor_recipe": {
            "name": "kretski-independent-v1",
            "source": SOURCE_GIST,
            "source_revision": SOURCE_REVISION,
            "whitening": {
                "fftlength_s": WHITEN_FFT_LENGTH,
                "overlap_s": WHITEN_OVERLAP,
                "padding_s": DEFAULT_PAD,
            },
            "peak": {
                "input": "raw strain, 4 s centred on feature_gps",
                "asd_fftlength_s": PEAK_FFT_LENGTH,
                "asd_overlap_s": PEAK_OVERLAP,
            },
            "correlation": {
                "input": "whitened, band-passed 4 s feature window",
                "maximum": "signed",
                "max_lag_s": DEFAULT_MAX_LAG_S,
                "null_test": False,
            },
            "loudness_reference": "mean of adjacent windows",
        },
        "peak_frequency_hz": peak_hz,
        "candidate_inband_energy": candidate_energy,
        "loudness_ratio_to_background_mean": loudness[
            "ratio_to_background_mean"
        ],
        "loudness_ratio_to_background_median_diagnostic": loudness[
            "ratio_to_background_median_diagnostic"
        ],
        "background_energy_mean": loudness["background_mean"],
        "background_energy_median": loudness["background_median"],
        "background_energy_min": loudness["background_min"],
        "background_energy_max": loudness["background_max"],
        "n_background": loudness["n_background"],
        "background_spacing_s": float(bg_spacing),
        "raw_cross_detector_max_corr": float(cross_corr),
        "raw_cross_detector_best_lag_s": float(cross_corr_lag_s),
        "correlation_note": (
            "Independent descriptive statistic near zero lag. It is unstable "
            "under reasonable implementation choices and is not the production "
            "time-shift/null coincidence veto."
        ),
        "production_coincidence": production_coincidence,
        "attribution": (
            "Cross-check recipe reproduced from GitHub user Kretski, gist "
            "d0f17ae69cd8fc40093cb4a4e372b7be, revision "
            f"{SOURCE_REVISION}."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"characterize_{detector}_{int(gps)}.json"
    destination.write_text(json.dumps(out, indent=2), encoding="utf-8")
    if record_provenance:
        record_environment(output_dir, f"characterize_{detector}_{int(gps)}")
    logger.info(
        "%s %d: peak %.1f Hz, loudness %.0fx, raw corr %.3f at %.1f ms",
        detector,
        int(gps),
        peak_hz,
        out["loudness_ratio_to_background_mean"],
        cross_corr,
        1e3 * cross_corr_lag_s,
    )
    logger.info("wrote %s", destination)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detector", required=True, choices=("H1", "L1"))
    parser.add_argument(
        "--gps",
        type=float,
        required=True,
        help="Start of the 32 s descriptor window.",
    )
    parser.add_argument(
        "--feature-gps",
        type=float,
        required=True,
        help="Feature time used to centre the 4 s peak/correlation windows.",
    )
    parser.add_argument(
        "--band",
        type=float,
        nargs=2,
        default=[26.0, 42.0],
        metavar=("F_LO", "F_HI"),
    )
    parser.add_argument("--partner", choices=("H1", "L1"), default=None)
    parser.add_argument("--n-background", type=int, default=16)
    parser.add_argument("--bg-spacing", type=float, default=40.0)
    parser.add_argument(
        "--catalog-gps",
        type=float,
        help="Optional GPS key for the stored production coincidence artifact.",
    )
    parser.add_argument(
        "--coincidence-artifact",
        type=Path,
        default=DEFAULT_COINCIDENCE_ARTIFACT,
    )
    args = parser.parse_args()
    run(
        args.detector,
        args.gps,
        args.feature_gps,
        band=args.band,
        partner=args.partner,
        n_background=args.n_background,
        bg_spacing=args.bg_spacing,
        catalog_gps=args.catalog_gps,
        coincidence_artifact=args.coincidence_artifact,
    )


if __name__ == "__main__":
    main()
