"""Build an in-domain DINOv2 reference index from Gravity Spy labeled
glitches, using our own preprocessing pipeline to eliminate domain gap.

Phase 3.3 revealed that using Gravity Spy's pre-rendered training images
creates a systematic domain gap: different Q-transform parameters, color
normalization, and image dimensions cause DINOv2 to see two different
"image styles" (all similarities < 0.85, GW150914 → Wandering_Line@0.670).

Solution: download labeled GPS timestamps from Zenodo, fetch raw strain
from GWOSC, and process with OUR pipeline (whiten → bandpass → Q-transform).
Reference and query spectrograms are then in identical domain.

Data source: Zenodo DOI 10.5281/zenodo.5649212
  Glanzer et al. (2023) — "Data quality up to the third observing run
  of Advanced LIGO: Gravity Spy glitch classifications"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from tqdm import tqdm

from src.core.data_loader import fetch_strain_data
from src.core.encoder import DINOv2Encoder
from src.core.preprocessor import bandpass, generate_qtransform, whiten
from src.core.utils import setup_logger

logger: logging.Logger = setup_logger(__name__)

# -----------------------------------------------------------------------
# Zenodo URL patterns (filenames vary across versions)
# -----------------------------------------------------------------------

_ZENODO_RECORD = "5649212"
_URL_PATTERNS = [
    "https://zenodo.org/records/{record}/files/{detector}_{run}.csv",
]


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------


def download_gs_classifications_csv(
        output_dir: Path,
        run: str = "O3b",
        detector: str = "H1",
        local_csv: Path | None = None,
) -> Path:
    """Download the Gravity Spy ML classifications CSV from Zenodo.

    Tries multiple URL patterns (Zenodo filenames vary by version).
    Caches the file locally to avoid re-downloading.
    If download fails and `local_csv` is provided, copies the local file.

    Args:
        output_dir: Directory to save the downloaded CSV.
        run: Observing run identifier (e.g. ``"O3b"``).
        detector: Detector identifier (e.g. ``"H1"``).
        local_csv: Optional local path to fallback to if download fails.

    Returns:
        Path to the downloaded (or cached) CSV file.

    Raises:
        FileNotFoundError: If all download attempts fail and no valid local_csv is provided.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"gs_classifications_{run}_{detector}.csv"

    if csv_path.exists():
        logger.info("Using cached Gravity Spy classifications: %s", csv_path)
        df = pd.read_csv(csv_path)
        logger.info("Downloaded %d classified glitches from Zenodo", len(df))
        return csv_path

    # Try each URL pattern in order
    last_error: Exception | None = None
    for pattern in _URL_PATTERNS:
        url = pattern.format(record=_ZENODO_RECORD, run=run, detector=detector)
        logger.info("Trying download: %s", url)

        try:
            response = requests.get(url, stream=True, timeout=120)
            response.raise_for_status()

            with open(csv_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            df = pd.read_csv(csv_path)
            logger.info("Downloaded %d classified glitches from Zenodo", len(df))
            return csv_path

        except (requests.RequestException, Exception) as exc:
            logger.warning("Download failed for %s: %s", url, exc)
            last_error = exc
            # Clean up partial download
            if csv_path.exists():
                csv_path.unlink()

    if local_csv is not None:
        local_csv_path = Path(local_csv)
        if local_csv_path.exists():
            import shutil
            logger.info("Download failed. Using local CSV fallback: %s", local_csv_path)
            shutil.copy(local_csv_path, csv_path)
            df = pd.read_csv(csv_path)
            logger.info("Loaded %d classified glitches from local fallback", len(df))
            return csv_path
        else:
            logger.warning("Local CSV fallback specified but not found: %s", local_csv_path)

    raise FileNotFoundError(
        f"Download failed. Please manually download the CSV from:\n"
        f"  https://zenodo.org/records/{_ZENODO_RECORD}\n"
        f"and save it to {csv_path}"
    ) from last_error


def select_reference_events(
        csv_path: Path,
        detector: str = "H1",
        min_confidence: float = 0.95,
        max_per_class: int = 30,
        excluded_labels: list[str] | None = None,
) -> pd.DataFrame:
    """Load the classifications CSV, apply quality filters, and sample per class.

    Args:
        csv_path: Path to the Gravity Spy ML classifications CSV.
        detector: Detector to filter on (e.g. ``"H1"``).
        min_confidence: Minimum ``ml_confidence`` threshold.
        max_per_class: Maximum samples per class (for manageable index size).
        excluded_labels: Label names to exclude (default:
            ``["None_of_the_Above"]``).

    Returns:
        Filtered DataFrame with columns:
        ``event_time``, ``ifo``, ``ml_label``, ``ml_confidence``,
        ``peak_frequency``, ``snr``.
    """
    if excluded_labels is None:
        excluded_labels = ["None_of_the_Above"]

    df = pd.read_csv(csv_path)

    # ---- Apply filters ----
    # Detector
    if "ifo" in df.columns:
        df = df[df["ifo"] == detector]

    # Confidence
    if "ml_confidence" in df.columns:
        df = df[df["ml_confidence"] >= min_confidence]

    # Excluded labels
    if "ml_label" in df.columns:
        df = df[~df["ml_label"].isin(excluded_labels)]

    # SNR threshold (Omicron standard)
    if "snr" in df.columns:
        df = df[df["snr"] >= 7.5]

    # ---- Sample per class ----
    sampled_dfs: list[pd.DataFrame] = []
    for label, group in df.groupby("ml_label"):
        n_sample = min(len(group), max_per_class)
        sampled_dfs.append(group.sample(n=n_sample, random_state=42))

    if not sampled_dfs:
        logger.warning("No events passed filters — check CSV columns and values.")
        return pd.DataFrame()

    result = pd.concat(sampled_dfs, ignore_index=True)

    # Log class distribution
    class_dist = result["ml_label"].value_counts().to_dict()
    logger.info(
        "Selected %d events: %s",
        len(result),
        json.dumps(class_dist, indent=None),
    )

    return result


def build_indomain_reference(
        events_df: pd.DataFrame,
        output_path: Path,
        segment_duration: float = 32.0,
        batch_size: int = 32,
        workers: int = 1,
) -> dict:
    """Build an in-domain reference index by fetching and preprocessing each event.

    For each labeled event:
      1. Compute GPS window centered on event_time
      2. Fetch strain from GWOSC
      3. Preprocess with our pipeline (whiten → bandpass → Q-transform)
      4. Save PNG spectrogram
      5. On failure: log warning and skip (never crash)

    After all downloads, extract DINOv2 embeddings and save the reference
    ``.npz`` + companion ``.json`` metadata.

    Args:
        events_df: DataFrame from :func:`select_reference_events`.
        output_path: Path for the output ``.npz`` reference index.
        segment_duration: Duration of each strain segment in seconds.
        batch_size: Batch size for DINOv2 embedding extraction.
        workers: Number of parallel workers (reserved for future use).

    Returns:
        Summary dict with keys: ``n_samples``, ``n_classes``, ``classes``,
        ``class_distribution``, ``model``, ``source``, ``timestamp``.
    """

    output_path = Path(output_path)
    # Isolate temporary images by run/detector using the filename stem
    images_dir = output_path.parent / "build" / output_path.stem.replace("indomain_", "")
    images_dir.mkdir(parents=True, exist_ok=True)

    half_dur = segment_duration / 2.0
    image_paths: list[Path] = []
    labels: list[str] = []
    gps_times: list[float] = []
    partial_pads: list[bool] = []
    effective_pads: list[float] = []
    skipped = 0

    for idx, row in tqdm(
            events_df.iterrows(),
            total=len(events_df),
            desc="Building in-domain reference",
    ):
        event_time = float(row["event_time"])
        label = str(row["ml_label"])
        detector = str(row["ifo"]) if "ifo" in row.index else "H1"

        gps_start = int(event_time - half_dur)
        gps_end = int(event_time + half_dur)

        # Create class-specific subdirectory
        label_dir = images_dir / label
        label_dir.mkdir(parents=True, exist_ok=True)
        save_path = label_dir / f"{event_time:.1f}.png"

        # Skip if already processed (resume support)
        if save_path.exists():
            image_paths.append(save_path)
            labels.append(label)
            gps_times.append(event_time)
            partial_pads.append(False) # Assume False for cached if missing
            effective_pads.append(4.0)
            continue

        try:
            # Fetch → Whiten (with context padding) → Bandpass → Q-transform → PNG
            ts_context = fetch_strain_data(detector, gps_start - 4.0, gps_end + 4.0)
            from src.core.preprocessor import whiten_context, extract_clean_subwindow
            ts_w_context, p_pad, e_pad = whiten_context(ts_context, gps_start, gps_end, pad=4.0)
            ts_clean = extract_clean_subwindow(ts_w_context, gps_start, gps_end)
            generate_qtransform(ts_clean, save_path=save_path)

            image_paths.append(save_path)
            labels.append(label)
            gps_times.append(event_time)
            partial_pads.append(p_pad)
            effective_pads.append(e_pad)

        except Exception as exc:
            logger.warning(
                "Skipping event %.1f (%s): %s",
                event_time,
                label,
                exc,
            )
            skipped += 1

        # Log progress every 10 events
        if (idx + 1) % 10 == 0:
            logger.info(
                "Progress: %d/%d processed, %d skipped",
                len(image_paths),
                idx + 1,
                skipped,
            )

    if not image_paths:
        raise RuntimeError(
            "No spectrograms were generated. Check network connectivity "
            "and GWOSC data availability."
        )

    logger.info(
        "Spectrogram generation complete: %d saved, %d skipped",
        len(image_paths),
        skipped,
    )

    # ---- Extract DINOv2 embeddings ----
    logger.info("Extracting DINOv2 embeddings for %d in-domain images...", len(image_paths))
    encoder = DINOv2Encoder()
    embeddings = encoder.extract_batch(image_paths, batch_size=batch_size)

    # ---- Save reference .npz ----
    label_array = np.array(labels, dtype=str)
    gps_array = np.array(gps_times, dtype=np.float64)
    path_array = np.array([str(p) for p in image_paths], dtype=str)
    partial_pad_array = np.array(partial_pads, dtype=bool)
    effective_pad_array = np.array(effective_pads, dtype=np.float64)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        output_path,
        embeddings=embeddings,
        labels=label_array,
        gps_times=gps_array,
        paths=path_array,
        partial_pads=partial_pad_array,
        effective_pads=effective_pad_array,
    )

    # ---- Save companion .json metadata ----
    unique_classes = sorted(set(labels))
    class_distribution = {}
    for lbl in labels:
        class_distribution[lbl] = class_distribution.get(lbl, 0) + 1

    meta = {
        "n_samples": len(embeddings),
        "n_classes": len(unique_classes),
        "classes": unique_classes,
        "model": "dinov2_vits14_reg",
        "embedding_dim": int(embeddings.shape[1]),
        "source": f"Zenodo {_ZENODO_RECORD} (in-domain, our pipeline)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "class_distribution": class_distribution,
    }
    json_path = output_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info(
        "In-domain reference built: %d samples, %d classes → %s",
        meta["n_samples"],
        meta["n_classes"],
        output_path,
    )

    return meta
