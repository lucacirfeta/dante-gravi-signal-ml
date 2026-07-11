"""Signal preprocessing pipeline for gravitational-wave strain data.

Provides whitening, bandpass filtering, Q-transform spectrogram
generation, and batch processing for large-scale O4a data scanning.
All functions operate on :class:`gwpy.timeseries.TimeSeries` objects
and return either processed time series or 2-D numpy arrays.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from gwpy.timeseries import TimeSeries
from tqdm import tqdm

from src.core.data_loader import fetch_strain_data
from src.core.utils import load_config, normalize_spectrogram, setup_logger

matplotlib.use("Agg")  # Non-interactive backend for batch jobs

logger: logging.Logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_CFG = load_config()
_PREPROC = _CFG["preprocessing"]


# ---------------------------------------------------------------------------
# Core preprocessing functions
# ---------------------------------------------------------------------------


import warnings

def _whiten_raw_unsafe(ts: TimeSeries) -> TimeSeries:
    """Whiten a strain time series to flatten the noise power spectrum.
    Internal use only. Use `whiten_context` instead to avoid edge artifacts.
    """
    duration = float(ts.duration.value)
    if duration < 1.0:
        raise ValueError(
            f"Time series too short for whitening: {duration:.2f} s "
            f"(minimum 1.0 s required)."
        )

    logger.debug("Whitening %.1f s of %s data", duration, ts.channel)
    return ts.whiten()

def whiten(ts: TimeSeries) -> TimeSeries:
    """
    DEPRECATED: Apply standard whitening without padding.
    Raises a RuntimeError due to Gibbs Ringing/Signal Dilution Barrier at boundaries.
    Use `whiten_context` instead.
    """
    raise RuntimeError(
        "whiten() diretto è vietato per rischio di artefatti ai bordi. "
        "Usa whiten_context() per includere il padding necessario."
    )



def bandpass(
        ts: TimeSeries,
        f_low: float = _PREPROC["f_low"],
        f_high: float = _PREPROC["f_high"],
) -> TimeSeries:
    """Apply a Butterworth bandpass filter to isolate the sensitive band.

    The default band (20–2000 Hz) covers the most sensitive frequency
    range of the LIGO/Virgo interferometers while rejecting seismic
    noise below ~20 Hz and shot noise above ~2 kHz.

    Args:
        ts: Input strain time series.
        f_low: Lower cutoff frequency in Hz.
        f_high: Upper cutoff frequency in Hz.

    Returns:
        Band-limited :class:`TimeSeries`.
    """
    sample_rate = float(ts.sample_rate.value)
    nyquist = sample_rate / 2.0

    # Ensure f_high is safely below Nyquist to prevent gwpy/scipy
    # boundary issues (stopband = f_high * 1.5 must be < Nyquist)
    f_high = min(f_high, nyquist * 0.9)

    # Compute explicit stopband edges to stay below Nyquist
    fstop_low = max(f_low * 2 / 3, 0.1)
    fstop_high = min(f_high * 1.5, nyquist * 0.99)

    logger.debug(
        "Bandpass filtering: [%.1f, %.1f] Hz (fstop=[%.1f, %.1f])",
        f_low, f_high, fstop_low, fstop_high,
    )
    return ts.bandpass(f_low, f_high, fstop=(fstop_low, fstop_high))


def whiten_context(
    ts_full: TimeSeries,
    context_start: float,
    context_end: float,
    pad: float = 4.0
) -> tuple[TimeSeries, dict]:
    """Whiten un blocco di contesto ampio UNA VOLTA (pad extra su entrambi i lati, scartato dopo).
    
    Ritorna la TimeSeries whitenata+bandpassata, pulita, pronta
    per essere croppata a qualsiasi sotto-finestra (32s, 4s, 2s, 1s, 0.5s) senza
    richiedere un nuovo whitening per ciascuna scala.

    Args:
        ts_full: Il blocco grezzo grande in memoria.
        context_start: L'inizio del contesto logico richiesto (senza pad).
        context_end: La fine del contesto logico richiesto (senza pad).
        pad: Padding addizionale ai lati in secondi (default: 4.0).

    Returns:
        ts_bp: La TimeSeries whitenata e bandpassata, comprensiva di pad (se disponibile).
        pad_info: Dizionario con {'left': bool, 'right': bool, 'effective_left': float, 'effective_right': float}.
    """
    t0 = float(ts_full.t0.value)
    t1 = t0 + float(ts_full.duration.value)

    pad_start = max(t0, context_start - pad)
    pad_end = min(t1, context_end + pad)

    actual_left_pad = context_start - pad_start
    actual_right_pad = pad_end - context_end
    
    pad_info = {
        'left': actual_left_pad < pad,
        'right': actual_right_pad < pad,
        'effective_left': actual_left_pad,
        'effective_right': actual_right_pad
    }

    ts_padded = ts_full.crop(pad_start, pad_end)

    # Whiten & Bandpass
    logger.debug("Whitening context [%.1f, %.1f] (pad_L=%.1f, pad_R=%.1f)", 
                 pad_start, pad_end, actual_left_pad, actual_right_pad)
    ts_w = ts_padded.whiten()
    ts_bp = bandpass(ts_w)

    return ts_bp, pad_info


def extract_clean_subwindow(
    ts_context_whitened: TimeSeries,
    seg_start: float,
    seg_end: float
) -> TimeSeries:
    """Crop esatto della sotto-finestra di analisi dal contesto già whitenato+bandpassato.
    Nessun nuovo whitening qui.

    Args:
        ts_context_whitened: La TimeSeries di contesto già filtrata (con o senza pad ai margini).
        seg_start: Inizio esatto della finestra desiderata.
        seg_end: Fine esatta della finestra desiderata.
        
    Returns:
        La TimeSeries tagliata esattamente ai margini richiesti.
    """
    return ts_context_whitened.crop(seg_start, seg_end)



def generate_qtransform(
        ts: TimeSeries,
        qrange: tuple[int, int] = tuple(_PREPROC["qrange"]),  # type: ignore[arg-type]
        frange: tuple[int, int] = tuple(_PREPROC["frange"]),  # type: ignore[arg-type]
        output_size: tuple[int, int] = tuple(_PREPROC["output_size"]),  # type: ignore[arg-type]
        save_path: Path | None = None,
        cmap: str | None = None,
        normalizer=None,
) -> np.ndarray:
    """Compute a constant-Q transform spectrogram from a time series.

    The Q-transform decomposes the signal into a time-frequency
    representation with logarithmic frequency resolution — ideal for
    visualizing compact binary coalescences and glitch morphologies.

    Args:
        ts: Input (ideally whitened + bandpassed) time series.
        qrange: Range of quality factors ``(Q_min, Q_max)``.
        frange: Frequency range ``(f_min, f_max)`` in Hz.
        output_size: Output array shape ``(height, width)`` in pixels.
        save_path: If provided, save a PNG rendering to this path.
        cmap: Matplotlib colormap name.  If ``None``, reads from
            ``config.yaml`` → ``preprocessing.colormap`` (default:
            ``"cividis"``).

    Returns:
        Normalized 2-D :class:`numpy.ndarray` with shape *output_size*
        and values in [0, 1].
    """
    if cmap is None:
        cmap = _PREPROC.get("colormap", "cividis")

    logger.debug(
        "Q-transform: qrange=%s, frange=%s, output=%s, cmap=%s",
        qrange,
        frange,
        output_size,
        cmap,
    )

    # Compute the Q-transform spectrogram via gwpy
    q_gram = ts.q_transform(
        qrange=qrange,
        frange=frange,
        logf=True,
        whiten=False,
    )

    # Convert to a 2-D numpy array and resize to the target output size
    spectrogram = np.array(q_gram.value, dtype=np.float64)

    # Resize to target output dimensions using scipy zoom
    from scipy.ndimage import zoom

    zoom_factors = (
        output_size[0] / spectrogram.shape[0],
        output_size[1] / spectrogram.shape[1],
    )
    spectrogram = zoom(spectrogram, zoom_factors, order=1)

    # Normalize to [0, 1]. Default: per-image min-max (production behavior).
    # `normalizer` allows the norm-leakage experiment to inject the fixed
    # run-independent scheme without forking this function.
    if normalizer is None:
        normalizer = normalize_spectrogram
    spectrogram = normalizer(spectrogram)

    # Optionally save as PNG
    if save_path is not None:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        fig, ax = plt.subplots(figsize=(6, 6), dpi=72)
        ax.imshow(
            spectrogram,
            origin="lower",
            aspect="auto",
            cmap=cmap,
            interpolation="bilinear",
        )
        ax.set_xlabel("Time")
        ax.set_ylabel("Frequency (Hz)")
        ax.set_title(f"Q-Transform Spectrogram")
        fig.tight_layout()
        fig.savefig(save_path, dpi=72, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved spectrogram -> %s", save_path)

    return spectrogram


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------


def batch_process(
        segment_list: list[tuple[int, int]],
        detector: str,
        output_dir: Path,
) -> list[Path]:
    """Run the full preprocessing pipeline on a list of O4a segments.

    For each segment: fetch → whiten → bandpass → Q-transform → save PNG.
    Segments that fail are logged and skipped — the batch never crashes.

    Args:
        segment_list: List of ``(gps_start, gps_end)`` tuples.
        detector: Detector identifier (``"H1"``, ``"L1"``, ``"V1"``).
        output_dir: Directory to save PNG spectrograms.

    Returns:
        List of :class:`Path` objects for successfully saved spectrograms.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    skipped = 0

    logger.info(
        "Batch processing %d segments for %s -> %s",
        len(segment_list),
        detector,
        output_dir,
    )

    for gps_start, gps_end in tqdm(
            segment_list, desc=f"Processing {detector}", unit="seg"
    ):
        try:
            segment_duration = gps_end - gps_start
            chunk_size = 32

            # 1. Fetch strain data with padding
            ts_super = fetch_strain_data(detector, gps_start - 4.0, gps_end + 4.0, edge_tolerance=4.0)

            if segment_duration > chunk_size:
                # Slice into chunks (e.g. 128 chunks for 4096s)
                for chunk_start in range(gps_start, gps_end, chunk_size):
                    chunk_end = chunk_start + chunk_size
                    filename = f"{detector}_{chunk_start}_{chunk_end}.png"
                    save_path = output_dir / filename

                    if save_path.exists():
                        logger.info("Skipping existing spectrogram: %s", filename)
                        saved.append(save_path)
                        continue

                    try:
                        crop_start = max(ts_super.t0.value, chunk_start - 4.0)
                        crop_end = min(ts_super.t0.value + ts_super.duration.value, chunk_end + 4.0)
                        ts_chunk_super = ts_super.crop(crop_start, crop_end)
                        ts_w_padded, _ = whiten_context(ts_chunk_super, chunk_start, chunk_end, pad=4.0)
                        ts_bp = extract_clean_subwindow(ts_w_padded, chunk_start, chunk_end)  # already whitened+bandpassed

                        if not np.isfinite(ts_bp.value).all():
                            logger.warning("Skipping chunk [%d, %d]: contains NaN/Inf", chunk_start, chunk_end)
                            skipped += 1
                            continue

                        generate_qtransform(ts_bp, save_path=save_path)
                        saved.append(save_path)
                    except Exception:
                        logger.warning("Skipping chunk [%d, %d]: processing failed", chunk_start, chunk_end,
                                       exc_info=True)
                        skipped += 1
            else:
                filename = f"{detector}_{gps_start}_{gps_end}.png"
                save_path = output_dir / filename

                # Skip existing spectrograms (resumable pipeline)
                if save_path.exists():
                    logger.info("Skipping existing spectrogram: %s", filename)
                    saved.append(save_path)
                    continue

                # 2. Whiten
                crop_start = max(ts_super.t0.value, gps_start - 4.0)
                crop_end = min(ts_super.t0.value + ts_super.duration.value, gps_end + 4.0)
                ts_super_cropped = ts_super.crop(crop_start, crop_end)
                ts_w_padded, _ = whiten_context(ts_super_cropped, gps_start, gps_end, pad=4.0)
                ts_bp = extract_clean_subwindow(ts_w_padded, gps_start, gps_end)  # already whitened+bandpassed

                # Check for NaN/Inf after filtering
                if not np.isfinite(ts_bp.value).all():
                    logger.warning(
                        "Skipping segment [%d, %d]: contains NaN/Inf after processing",
                        gps_start,
                        gps_end,
                    )
                    skipped += 1
                    continue

                # 4. Q-transform → PNG
                generate_qtransform(ts_bp, save_path=save_path)

                saved.append(save_path)

        except Exception:
            logger.warning(
                "Skipping segment [%d, %d]: fetch or global processing failed",
                gps_start,
                gps_end,
                exc_info=True,
            )
            skipped += 1

    logger.info(
        "Batch complete: %d saved, %d skipped, %d total segments",
        len(saved),
        skipped,
        len(segment_list),
    )
    return saved
