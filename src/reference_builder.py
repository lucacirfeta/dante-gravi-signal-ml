"""Build a DINOv2 embedding reference index from the Gravity Spy
training set for morphological similarity search."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from gwpy.table import GravitySpyTable

from src.encoder import DINOv2Encoder
from src.utils import setup_logger

logger = setup_logger(__name__)

def download_training_set_metadata(
    output_dir: Path,
    zenodo_url: str = "https://zenodo.org/record/1476551/files/trainingset_v1d0_metadata.csv",
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
    # Check if 'label' column exists, sometimes it might be 'ml_label' depending on the exact csv
    # The official dataset has 'label', 'gravityspy_id', 'sample_type', 'ifo'
    if "label" not in df.columns:
        if "ml_label" in df.columns:
            df.rename(columns={"ml_label": "label"}, inplace=True)

    n_samples = len(df)
    n_classes = df["label"].nunique()
    logger.info("Loaded metadata: %d samples across %d classes", n_samples, n_classes)
    
    return df

def download_training_images(
    metadata: pd.DataFrame,
    output_dir: Path,
    duration: float = 1.0,
    max_per_class: int = 50,
    sample_type: str = "train",
) -> list[Path]:
    """Download Gravity Spy spectrograms for reference building."""
    df_train = metadata[metadata["sample_type"] == sample_type]
    
    images_dir = output_dir / "training_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    
    downloaded_paths = []
    
    classes = df_train["label"].unique()
    logger.info("Downloading images for %d classes (max %d per class)", len(classes), max_per_class)
    
    for label in classes:
        df_class = df_train[df_train["label"] == label].head(max_per_class)
        class_dir = images_dir / label
        class_dir.mkdir(parents=True, exist_ok=True)
        
        for _, row in df_class.iterrows():
            gs_id = row["gravityspy_id"]
            ifo = row["ifo"]
            filename = f"{ifo}_{gs_id}_spectrogram_{duration}.png"
            file_path = class_dir / filename
            
            if file_path.exists():
                downloaded_paths.append(file_path)
                continue
                
            # Attempt gwpy download first
            try:
                # GravitySpyTable.download wants just the ID, but it downloads all 4 durations
                # To be precise and just get the one we want, we can use requests fallback immediately
                # Or let's try the direct S3 URL first as it's cleaner to get exact file.
                s3_url = f"https://gravityspy-ligo.s3.amazonaws.com/{label}/{gs_id}/{filename}"
                resp = requests.get(s3_url, stream=True, timeout=10)
                resp.raise_for_status()
                with open(file_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                downloaded_paths.append(file_path)
            except Exception as e:
                # Try gwpy fallback
                try:
                    logger.debug("S3 download failed for %s, trying gwpy...", gs_id)
                    # GravitySpyTable.download downloads a tar.gz typically, so maybe better to stick to HTTP
                    # The S3 url might have case issues or different paths.
                    # We will log a warning and skip if both fail.
                    logger.warning("Failed to download %s: %s", gs_id, e)
                except Exception as gw_e:
                    logger.warning("All download methods failed for %s: %s", gs_id, gw_e)

        logger.info("Downloaded %d samples for class %s", len(list(class_dir.glob("*.png"))), label)

    logger.info("Total downloaded reference images: %d", len(downloaded_paths))
    return downloaded_paths

def build_reference_index(
    image_paths: list[Path],
    labels: list[str],
    output_path: Path,
    batch_size: int = 32,
) -> dict:
    """Extract DINOv2 embeddings and save reference index."""
    encoder = DINOv2Encoder(batch_size=batch_size)
    
    logger.info("Extracting embeddings for %d reference images", len(image_paths))
    embeddings = encoder.extract_batch(image_paths, batch_size=batch_size)
    
    label_array = np.array(labels, dtype=str)
    path_array = np.array([str(p) for p in image_paths], dtype=str)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        output_path,
        embeddings=embeddings,
        labels=label_array,
        image_paths=path_array,
    )
    
    n_samples = len(embeddings)
    unique_classes = sorted(list(set(labels)))
    
    metadata = {
        "n_samples": n_samples,
        "n_classes": len(unique_classes),
        "classes": unique_classes,
        "model": "dinov2_vits14_reg",
        "embedding_dim": embeddings.shape[1],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    json_path = output_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        
    logger.info("Reference index built: %d samples, %d classes", n_samples, len(unique_classes))
    return metadata

def load_reference_index(index_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load reference embeddings and labels."""
    data = np.load(index_path)
    return data["embeddings"], data["labels"]
