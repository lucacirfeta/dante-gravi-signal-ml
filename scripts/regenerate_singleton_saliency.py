#!/usr/bin/env python3
"""Regenerate singleton saliency figures with corrected axes.

Before 2026-07-21 the saliency panels used ``extent = [0, w, 0, h]``
(raw pixel indices) while labelling the y-axis "Frequency (Hz)", so a
feature at pixel row 220 read as "220 Hz" when it actually sits near
1150 Hz.  The corrected ``saliency_map.py`` plots time in seconds and
keeps the y-axis in pixel units with log-spaced Hz tick labels.

This script fetches the strain from GWOSC for both singletons,
whitens, Q-transforms, loads DINOv2, computes a spatial-median
background from session-local pristine segments, and calls
``generate_saliency_map()`` with the corrected code.

Usage
-----
    python scripts/regenerate_singleton_saliency.py [--device cuda|cpu]

Outputs are written to:
  - data/production/aggregated/visual_checks/Singleton_<GPS>/
  - paper_draft/v5_15072026_arvix/img/
  - paper_draft/v5_15072026_cqg/img/
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import matplotlib.pyplot as plt
from PIL import Image
from torchvision import transforms

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.data_loader import fetch_strain_data
from src.core.preprocessor import whiten_context, extract_clean_subwindow, generate_qtransform
from src.pipeline_v2_production.saliency_map import generate_saliency_map

# ── Singletons ──────────────────────────────────────────────────────
SINGLETONS = [
    {"gps": 1382955228, "det": "L1", "session_id": 1382451712, "label": "Singleton_1382955228"},
    {"gps": 1369305276, "det": "H1", "session_id": 1368973312, "label": "Singleton_1369305276"},
]

PAPER_IMG_DIRS = [
    PROJECT_ROOT / "paper_draft" / "v5_15072026_arvix" / "img",
    PROJECT_ROOT / "paper_draft" / "v5_15072026_cqg" / "img",
]

VISUAL_CHECKS_DIR = PROJECT_ROOT / "data" / "production" / "aggregated" / "visual_checks"

# ── Background computation ──────────────────────────────────────────
# Number of pristine background windows to use for spatial median.
N_BG_WINDOWS = 20  # Enough for a representative median; keeps runtime short.
BG_OFFSET_STEP = 64  # seconds between consecutive background windows


def _load_model(device: str) -> torch.nn.Module:
    """Load DINOv2 ViT-S/14 with registers (cached in ~/.cache/torch/hub)."""
    cache_dir = os.path.expanduser("~/.cache/torch/hub/facebookresearch_dinov2_main")
    try:
        model = torch.hub.load(cache_dir, "dinov2_vits14_reg", source="local")
    except Exception:
        model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14_reg")
    model = model.to(device).eval()
    return model


def _compute_spatial_median(
    model: torch.nn.Module,
    detector: str,
    gps_center: int,
    device: str,
    n_windows: int = N_BG_WINDOWS,
) -> np.ndarray:
    """Compute per-patch spatial median from pristine background windows.

    Samples ``n_windows`` clean segments *before* the event GPS, each
    separated by BG_OFFSET_STEP seconds, encodes them through DINOv2,
    and returns the element-wise median across the N patches.
    """
    transform = transforms.Compose([
        transforms.Resize((518, 518)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    all_patches = []
    # Sample clean windows *before* the event
    for i in range(n_windows):
        t_start = gps_center - (i + 2) * BG_OFFSET_STEP  # offset to avoid event vicinity
        try:
            ts_super = fetch_strain_data(detector, t_start - 4.0, t_start + 36.0, edge_tolerance=4.0)
            ts_w, _ = whiten_context(ts_super, t_start, t_start + 32.0, pad=4.0)
            ts_clean = extract_clean_subwindow(ts_w, t_start, t_start + 32.0)
            spec = generate_qtransform(ts_clean, save_path=None, output_size=(256, 256))

            cmap_func = plt.get_cmap("cividis")
            rgb = cmap_func(spec)[:, :, :3]
            rgb_u8 = (rgb * 255.0).astype(np.uint8)
            img = Image.fromarray(rgb_u8).convert("RGB")
            tensor = transform(img).unsqueeze(0).to(device)

            with torch.inference_mode():
                feats = model.forward_features(tensor)
                patches = feats["x_norm_patchtokens"].squeeze(0)
                patches = F.normalize(patches, p=2, dim=-1)
                all_patches.append(patches.cpu().numpy())
        except Exception as e:
            print(f"  [WARN] background window t={t_start} failed: {e}")
            continue

    if len(all_patches) < 3:
        raise RuntimeError(
            f"Only {len(all_patches)} background windows succeeded — too few for a stable median."
        )

    stacked = np.array(all_patches)  # (N, 1369, 384)
    spatial_median = np.median(stacked, axis=0)  # (1369, 384)
    print(f"  Spatial median from {len(all_patches)} background windows.")
    return spatial_median


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate singleton saliency figures with corrected axes")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument(
        "--spatial-background", action="store_true",
        help="Draw the diagnostic spatial-background saliency instead of the "
             "production VQ score. The highlighted patches are then NOT the "
             "Top-k the pipeline pooled, and the figure must not be captioned "
             "as if they were.",
    )
    args = parser.parse_args()
    device = args.device

    print(f"Device: {device}")

    # Default to the production scorer: the boxes then mark the same patches
    # that produced the candidate's novelty score. The figures shipped with the
    # 2026-07-21 correction predate this and used the spatial-background
    # fallback, which is why their middle panel reads "Spatial Background".
    scorer = None
    if not args.spatial_background:
        from src.core.patch_scorer import PatchScorer
        from src.core.utils import get_reference_dir
        idx = get_reference_dir() / "patch_compressed_index_o3b.npz"
        scorer = PatchScorer(reference_index_path=str(idx), device=device)
        print(f"Production scorer loaded from {idx.name} (K={scorer.centroids.shape[0]}).")

    model = scorer.model if scorer is not None else _load_model(device)
    print("Model loaded.")

    for singleton in SINGLETONS:
        gps = singleton["gps"]
        det = singleton["det"]
        label = singleton["label"]
        print(f"\n{'='*60}")
        print(f"Processing {label} ({det} @ GPS {gps})")
        print(f"{'='*60}")

        # 1. Fetch + whiten + Q-transform the event window
        print("  Fetching strain data...")
        ts_super = fetch_strain_data(det, gps - 4.0, gps + 36.0, edge_tolerance=4.0)
        ts_w, _ = whiten_context(ts_super, gps, gps + 32.0, pad=4.0)
        ts_clean = extract_clean_subwindow(ts_w, gps, gps + 32.0)
        spec_matrix = generate_qtransform(ts_clean, save_path=None, output_size=(256, 256))
        print(f"  Spectrogram shape: {spec_matrix.shape}")

        # 2. Spatial median background — only the fallback needs it, and it
        #    costs 20 extra strain fetches.
        spatial_median = None
        if scorer is None:
            print("  Computing spatial median background...")
            spatial_median = _compute_spatial_median(model, det, gps, device)

        # 3. Generate the corrected saliency map
        out_dir = VISUAL_CHECKS_DIR / label
        out_dir.mkdir(parents=True, exist_ok=True)
        out_prefix = str(out_dir / f"saliency_{label}")

        # The output will be at: <prefix>_saliency.png / .pdf
        # But the paper expects: saliency_Singleton_<GPS>.png
        # So we use a prefix such that the file is saliency_<label>_saliency.png
        # Actually let's just output directly with the expected name
        raw_prefix = str(out_dir / label)  # -> label_saliency.png

        print("  Generating corrected saliency map...")
        result = generate_saliency_map(
            spectrogram_matrix=spec_matrix,
            background_vector=spatial_median,
            output_path_prefix=raw_prefix,
            model=model,
            k_highlight=68,
            device=device,
            segment_length=32.0,
            scorer=scorer,
        )
        print(f"  Score source: {result['score_source']}")
        print(f"  Max anomaly score: {result['max_anomaly_score']:.4f}")
        print(f"  Mean top-k score: {result['mean_topk_score']:.4f}")

        # The output file is: <raw_prefix>_saliency.png
        generated_png = Path(f"{raw_prefix}_saliency.png")
        target_name = f"saliency_{label}.png"

        # Rename in visual_checks dir to match expected naming
        final_visual = out_dir / target_name
        if generated_png.exists() and generated_png != final_visual:
            shutil.copy2(generated_png, final_visual)

        # 4. Copy to paper img directories
        for img_dir in PAPER_IMG_DIRS:
            if img_dir.exists():
                dest = img_dir / target_name
                shutil.copy2(final_visual, dest)
                print(f"  Copied to {dest}")
            else:
                print(f"  [WARN] Paper img dir not found: {img_dir}")

    print("\n✓ All saliency figures regenerated successfully.")


if __name__ == "__main__":
    main()
