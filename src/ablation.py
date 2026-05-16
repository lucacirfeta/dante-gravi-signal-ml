"""Ablation study module — tests robustness of clustering against image perturbations."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps
from sklearn.metrics import adjusted_rand_score
from tqdm import tqdm

from src.clustering import run_full_pipeline
from src.encoder import DINOv2Encoder
from src.utils import setup_logger

logger: logging.Logger = setup_logger(__name__)


def apply_perturbation(img: Image.Image, method: str) -> Image.Image:
    """Apply a perturbation to an image.
    
    Args:
        img: Input PIL Image.
        method: Perturbation method ('grayscale', 'inverted', 'shuffled-intensity').
        
    Returns:
        Perturbed PIL Image.
    """
    if method == "grayscale":
        # Convert to grayscale L mode, then back to RGB to remove colormap info.
        return img.convert("L").convert("RGB")
    elif method == "inverted":
        # Invert pixel intensities.
        img_rgb = img.convert("RGB")
        return ImageOps.invert(img_rgb)
    elif method == "shuffled-intensity":
        # Multiply by a random scalar between 0.5 and 1.5 per image.
        img_rgb = img.convert("RGB")
        arr = np.array(img_rgb).astype(np.float32)
        factor = np.random.uniform(0.5, 1.5)
        arr = np.clip(arr * factor, 0, 255).astype(np.uint8)
        return Image.fromarray(arr, mode="RGB")
    else:
        raise ValueError(f"Unknown perturbation method: {method}")


def extract_perturbed_embeddings(
    encoder: DINOv2Encoder,
    image_paths: list[Path],
    method: str,
    batch_size: int = 32,
) -> np.ndarray:
    """Extract DINOv2 embeddings for perturbed images."""
    all_embeddings = []
    
    for start in tqdm(
        range(0, len(image_paths), batch_size),
        desc=f"Extracting '{method}' embeddings",
    ):
        batch_paths = image_paths[start : start + batch_size]
        tensors = []
        for p in batch_paths:
            img = Image.open(p)
            perturbed_img = apply_perturbation(img, method)
            # The encoder transform already ensures it's RGB and normalizes it.
            tensors.append(encoder.transform(perturbed_img))
            
        tensors_stack = torch.stack(tensors).to(encoder.device)
        
        try:
            with torch.no_grad():
                cls_tokens = encoder.model(tensors_stack)
                # L2 normalize
                cls_tokens = torch.nn.functional.normalize(cls_tokens, p=2, dim=1)
                all_embeddings.append(cls_tokens.cpu().numpy().astype(np.float32))
        except RuntimeError as exc:
            if "out of memory" not in str(exc):
                raise
            raise RuntimeError(
                f"OOM during ablation '{method}'. Reduce batch size."
            ) from exc
            
    return np.concatenate(all_embeddings, axis=0)


def run_ablation_study(
    original_labels: np.ndarray,
    image_paths: list[Path],
    encoder: DINOv2Encoder,
    cluster_cfg: dict,
    output_dir: Path,
    session_id: str,
    detector: str = "H1",
) -> None:
    """Run ablation study across different conditions and compare with baseline.
    
    Args:
        original_labels: HDBSCAN labels of the original embeddings.
        image_paths: List of paths to the original spectrogram PNGs.
        encoder: Initialized DINOv2Encoder instance.
        cluster_cfg: Dictionary with clustering configuration.
        output_dir: Directory to save the ablation report.
        session_id: Session identifier.
        detector: Detector identifier (e.g. H1).
    """
    conditions = ["grayscale", "inverted", "shuffled-intensity", "random-baseline"]
    
    n_samples = len(image_paths)
    
    report = {
        "session_id": session_id,
        "detector": detector,
        "n_samples": n_samples,
        "original_n_clusters": len(set(original_labels)) - (1 if -1 in original_labels else 0),
        "results": {}
    }
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for method in conditions:
        logger.info("--- Ablation Condition: %s ---", method)
        
        if method == "random-baseline":
            # Generate random standard normal embeddings, and normalize them like DINOv2
            random_emb = np.random.normal(loc=0.0, scale=1.0, size=(n_samples, 384)).astype(np.float32)
            norms = np.linalg.norm(random_emb, axis=1, keepdims=True)
            embeddings = random_emb / np.maximum(norms, 1e-8)
        else:
            embeddings = extract_perturbed_embeddings(
                encoder=encoder,
                image_paths=image_paths,
                method=method,
                batch_size=encoder.batch_size,
            )
            
        # Run full clustering pipeline
        logger.info("Clustering '%s' embeddings...", method)
        result = run_full_pipeline(embeddings, cluster_cfg)
        new_labels = result["labels"]
        
        # Calculate Adjusted Rand Index
        ari = float(adjusted_rand_score(original_labels, new_labels))
        n_clusters = result["hdbscan_stats"]["n_clusters"]
        
        logger.info("Condition '%s': ARI = %.3f, clusters = %d", method, ari, n_clusters)
        
        report["results"][method] = {
            "ari": ari,
            "n_clusters": n_clusters,
            "hdbscan_stats": result["hdbscan_stats"]
        }
    
    # Interpretation
    ari_gray = report["results"].get("grayscale", {}).get("ari", 0.0)
    if ari_gray < 0.4:
        interpretation = (
            "WARNING: preprocessing-dominant. Clusters rely heavily on rendering "
            "statistics (colormap/intensity) rather than physical morphology."
        )
    else:
        interpretation = "OK: Clusters seem reasonably robust to rendering statistics."
        
    report["interpretation"] = interpretation
    
    # Save report
    report_path = output_dir / f"ablation_report_{detector}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        
    logger.info("Ablation complete. Report saved to %s", report_path)
    print(f"\nAblation Complete. Report saved to {report_path}")
    print(f"Interpretation: {interpretation}")
    for method, data in report["results"].items():
        print(f"  {method:<20s}: ARI = {data['ari']:.3f} | Clusters = {data['n_clusters']}")
