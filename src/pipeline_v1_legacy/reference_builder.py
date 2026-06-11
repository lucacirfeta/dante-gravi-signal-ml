"""Build a DINOv2 embedding reference index from the Gravity Spy
training set for morphological similarity search."""

from __future__ import annotations

import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd
import requests

from src.core.encoder import DINOv2Encoder
from src.core.utils import setup_logger

logger = setup_logger(__name__)


def download_training_set_metadata(
        output_dir: Path,
        zenodo_url: str = "https://zenodo.org/records/1476551/files/trainingset_v1d1_metadata.csv",
) -> pd.DataFrame:
    """Download and load Gravity Spy training set metadata CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "trainingset_metadata.csv"

    if not csv_path.exists():
        logger.info("Downloading Gravity Spy training set metadata from %s", zenodo_url)
        response = requests.get(zenodo_url, stream=True)
        response.raise_for_status()
        with open(csv_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    else:
        logger.info("Using cached Gravity Spy metadata from %s", csv_path)

    df = pd.read_csv(csv_path)
    if "label" not in df.columns:
        if "ml_label" in df.columns:
            df.rename(columns={"ml_label": "label"}, inplace=True)

    n_samples = len(df)
    n_classes = df["label"].nunique()
    logger.info("Loaded metadata: %d samples across %d classes", n_samples, n_classes)

    return df


def extract_from_tar(
        tar_path: Path,
        output_dir: Path,
        metadata: pd.DataFrame,
        max_per_class: int = 50,
        sample_type: str = "train",
        duration: str = "1.0",
) -> tuple[list[Path], list[str]]:
    """Extracts PNG images from tar.gz directly to disk."""
    if not tar_path.exists():
        raise FileNotFoundError(f"Training set tar.gz not found: {tar_path}")

    logger.info("Extracting from tar.gz: %s (this may take a few minutes)", tar_path)

    df_filtered = metadata[metadata["sample_type"] == sample_type]
    id_to_label = dict(zip(df_filtered["gravityspy_id"], df_filtered["label"]))

    all_labels = df_filtered["label"].unique()
    class_counts = {label: 0 for label in all_labels}

    list_of_paths = []
    list_of_labels = []

    training_images_dir = output_dir / "training_images"
    training_images_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(tar_path, "r:gz") as tar:
        members_processed = 0
        for member in tar:
            members_processed += 1
            if members_processed % 500 == 0:
                logger.info("Processed %d tar members...", members_processed)

            if not member.isfile() or not member.name.endswith(".png"):
                continue

            p = PurePosixPath(member.name)
            filename = p.name

            parts = filename.replace(".png", "").split("_")
            if len(parts) >= 4 and parts[-2] == "spectrogram":
                gs_id = "_".join(parts[1:-2])
                dur = parts[-1]
            else:
                continue

            if dur != duration:
                continue

            if gs_id not in id_to_label:
                continue

            label = id_to_label[gs_id]

            if class_counts[label] >= max_per_class:
                continue

            label_dir = training_images_dir / label
            label_dir.mkdir(parents=True, exist_ok=True)
            dest_path = label_dir / filename

            try:
                f_in = tar.extractfile(member)
                if f_in:
                    with open(dest_path, "wb") as f_out:
                        f_out.write(f_in.read())
            except tarfile.TarError as e:
                logger.warning("Failed to extract %s: %s", filename, e)
                continue

            class_counts[label] += 1
            list_of_paths.append(dest_path)
            list_of_labels.append(label)

    for label, count in class_counts.items():
        if count == 0:
            logger.warning("Class %s has 0 samples after extraction.", label)

    n_images = len(list_of_paths)
    n_classes = sum(1 for count in class_counts.values() if count > 0)
    logger.info("Extracted %d images across %d classes", n_images, n_classes)

    return list_of_paths, list_of_labels


def build_reference_index_from_paths(
        image_paths: list[Path],
        labels: list[str],
        output_path: Path,
        batch_size: int = 32,
) -> dict:
    """Build a DINOv2 embedding reference index from extracted PNG paths."""
    from skimage import io
    import warnings

    logger.info("Applying crop to %d images...", len(image_paths))
    for path in image_paths:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arr = io.imread(path)
            if arr.shape[0] >= 532 and arr.shape[1] >= 671:
                if arr.ndim == 3:
                    arr = arr[66:532, 105:671, :3]
                else:
                    arr = arr[66:532, 105:671]
                io.imsave(path, arr)

    logger.info("Extracting embeddings for %d images...", len(image_paths))
    encoder = DINOv2Encoder()
    embeddings = encoder.extract_batch(image_paths, batch_size=batch_size)

    label_array = np.array(labels, dtype=str)
    path_array = np.array([str(p) for p in image_paths], dtype=str)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(output_path, embeddings=embeddings, labels=label_array, image_paths=path_array)

    unique_classes = sorted(list(set(labels)))
    meta = {
        "n_samples": len(embeddings),
        "n_classes": len(unique_classes),
        "classes": unique_classes,
        "model": "dinov2_vits14_reg",
        "embedding_dim": int(embeddings.shape[1]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(output_path.with_suffix(".json"), "w") as f:
        json.dump(meta, f, indent=2)

    return meta


def load_reference_index(index_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load reference embeddings and labels."""
    data = np.load(index_path)
    return data["embeddings"], data["labels"]
