import os
import json
import logging
import argparse
import numpy as np
import torch
import torch.nn.functional as F
from pathlib import Path
from tqdm import tqdm
from PIL import Image
import matplotlib.pyplot as plt
from sklearn.cluster import MiniBatchKMeans
from gwosc.timeline import get_segments

from src.core.data_loader import fetch_strain_data, clear_astropy_cache, _DATA_DIRECTORIES
from src.core.preprocessor import whiten, bandpass, generate_qtransform
from src.core.encoder import DINOv2Encoder, build_dinov2_transform
from src.core.utils import setup_logger

logger = setup_logger(__name__)

def excess_power_veto(ts_whitened, sample_rate=4096):
    """Returns True if segment should be REJECTED.
    
    Multi-resolution excess power with robust statistics (median + MAD)
    and leave-one-out context estimation.
    """
    windows_ms = [50, 100, 250]
    context_s = 16.0
    threshold_mad = 5.0
    MAD_TO_SIGMA = 1.4826
    
    data = ts_whitened.value
    
    for win_ms in windows_ms:
        win_samples = int(win_ms * sample_rate / 1000)
        stride = max(1, win_samples // 4)
        
        rms = np.sqrt(
            np.convolve(data**2, np.ones(win_samples) / win_samples, mode='valid')
        )
        
        context_samples = int(context_s * sample_rate)
        
        for i in range(0, len(rms), stride):
            # Leave-one-out context: exclude the test block [i-win_samples, i+win_samples]
            ctx_start = max(0, i - context_samples // 2)
            ctx_end = min(len(rms), i + context_samples // 2)
            excl_start = max(ctx_start, i - win_samples)
            excl_end = min(ctx_end, i + win_samples)
            
            ctx_indices = np.concatenate([
                np.arange(ctx_start, excl_start),
                np.arange(excl_end, ctx_end)
            ])
            
            if len(ctx_indices) < 100:  # gap di contesto (bordo), documentato
                continue
                
            ctx_values = rms[ctx_indices]
            local_median = np.median(ctx_values)
            local_mad = np.median(np.abs(ctx_values - local_median))
            local_sigma = local_mad * MAD_TO_SIGMA
            
            if local_sigma > 0 and (rms[i] - local_median) > threshold_mad * local_sigma:
                return True  # Rigetta
    
    return False

def build_multiscale_dictionaries(
    detector: str = "L1",
    n_dict: int = 500,
    seed: int = 42
):
    np.random.seed(seed)
    output_dir = Path("results/micro_mdc/multiscale")
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "temp_pngs"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    scales = [0.5, 1, 2, 4, 32]
    stride = max(scales) + 64  # 96s
    
    # 1. Discover local blocks
    local_blocks = []
    logger.info(f"Scanning local directories for {detector} blocks (72 sessions pool)...")
    for directory in _DATA_DIRECTORIES:
        if directory.exists():
            for file in directory.rglob(f"{detector}_*.hdf5"):
                parts = file.stem.split("_")
                if len(parts) >= 3:
                    try:
                        f_start = int(parts[1])
                        f_end = int(parts[2])
                        local_blocks.append((f_start, f_end))
                    except ValueError:
                        pass
                        
    if len(local_blocks) == 0:
        raise ValueError("No local data found. Pilot must run on the existing 72-session pool.")
        
    np.random.shuffle(local_blocks)
    
    # 2. Extract valid t_bg centers
    valid_t_bgs = []
    logger.info(f"Finding {n_dict} valid background centers...")
    
    # Init encoder
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # We load DINOv2 to extract patch tokens
    model = torch.hub.load('facebookresearch/dinov2', 'dinov2_vits14_reg').to(device)
    model.eval()
    for param in model.parameters():
        param.requires_grad = False
    transform = build_dinov2_transform()
    
    embeddings_by_scale = {s: [] for s in scales}
    
    pbar = tqdm(total=n_dict, desc="Validating & Extracting t_bg")
    
    for block_start, block_end in local_blocks:
        if len(valid_t_bgs) >= n_dict:
            break
            
        try:
            # Check GWOSC API for BURST_CAT1
            burst_segs = get_segments(f'{detector}_BURST_CAT1', block_start, block_end)
        except Exception as e:
            logger.warning(f"Could not fetch GWOSC BURST_CAT1 for {block_start}-{block_end}: {e}")
            continue
            
        try:
            # Use raw data fetching, assume it's cached locally
            ts_clean = fetch_strain_data(detector, block_start, block_end, cache_raw=False)
            ts_white = whiten(ts_clean)
            ts_bp = bandpass(ts_white)
        except Exception as e:
            logger.warning(f"Failed to load block {block_start}: {e}")
            continue
            
        # Scan block with stride=96s
        # Leave 64s margin at edges
        candidate_t_bgs = np.arange(block_start + 64, block_end - 64, stride)
        
        for t_bg in candidate_t_bgs:
            if len(valid_t_bgs) >= n_dict:
                break
                
            # Livello 1: DQ Veto
            # Check if [t_bg - 16, t_bg + 16] is entirely inside ANY burst segment
            win_start = t_bg - 16
            win_end = t_bg + 16
            is_dq_clean = any(s[0] <= win_start and s[1] >= win_end for s in burst_segs)
            if not is_dq_clean:
                continue
                
            # Livello 2: Excess Power Veto
            # Crop exactly 32s around t_bg
            ts_32s = ts_bp.crop(t_bg - 16, t_bg + 16)
            if excess_power_veto(ts_32s, sample_rate=4096):
                continue
                
            scale_patches = {}
            valid_extraction = True
            
            for scale in scales:
                ts_crop = ts_bp.crop(t_bg - scale / 2.0, t_bg + scale / 2.0)
                if np.any(np.isnan(ts_crop.value)) or np.any(np.isinf(ts_crop.value)):
                    logger.warning(f"NaN/Inf found in strain at {t_bg}")
                    valid_extraction = False
                    break
                    
                qrange = (4, 32)
                temp_path = temp_dir / f"dict_{t_bg}_{scale}s.png"
                
                try:
                    generate_qtransform(ts_crop, qrange=qrange, save_path=temp_path)
                    
                    # Extract Patch Tokens
                    img = Image.open(temp_path)
                    tensor = transform(img).unsqueeze(0).to(device)
                    
                    with torch.inference_mode():
                        features = model.forward_features(tensor)
                        patch_tokens = features["x_norm_patchtokens"] # (1, 1369, 384)
                        patch_tokens = patch_tokens.squeeze(0).cpu().numpy().astype(np.float32)
                        
                    scale_patches[scale] = patch_tokens
                except Exception as e:
                    logger.warning(f"Q-transform/extraction failed at {t_bg}: {e}")
                    valid_extraction = False
                    break
                finally:
                    if temp_path.exists():
                        temp_path.unlink()
                        
            if not valid_extraction or len(scale_patches) != len(scales):
                continue
                
            # Both veti passed and all scales extracted successfully. Valid center!
            valid_t_bgs.append(int(t_bg))
            for scale in scales:
                embeddings_by_scale[scale].append(scale_patches[scale])
                
            pbar.update(1)
            
    pbar.close()
    
    if len(valid_t_bgs) < n_dict:
        raise RuntimeError(f"Could only find {len(valid_t_bgs)} valid background centers. Needed {n_dict}.")
        
    with open(output_dir / f"{detector}_dict_t_bg.json", "w") as f:
        json.dump(valid_t_bgs, f, indent=4)
        
    # 3. Compress with MiniBatchKMeans (CPU)
    k_clusters = 281
    logger.info(f"Running MiniBatchKMeans with K={k_clusters} on patch tokens...")
    
    for scale in scales:
        # Concatenate all patch tokens for this scale
        # Each is (1369, 384), we have 500 of them -> (500*1369, 384)
        embs = np.vstack(embeddings_by_scale[scale])
        logger.info(f"Scale {scale}s: {embs.shape[0]} patch tokens extracted.")
        
        kmeans = MiniBatchKMeans(
            n_clusters=k_clusters,
            batch_size=4096,
            compute_labels=False,
            random_state=seed,
            n_init="auto"
        )
        kmeans.fit(embs)
        centroids = kmeans.cluster_centers_
        
        # L2-normalize centroids
        centroids_tensor = torch.tensor(centroids, dtype=torch.float32)
        centroids_tensor = F.normalize(centroids_tensor, p=2, dim=-1)
        centroids_normalized = centroids_tensor.numpy()
        
        labels = np.array([f"BG_{scale}s"] * k_clusters)
        
        out_path = output_dir / f"{detector}_patch_dict_{scale}s.npz"
        np.savez_compressed(out_path, embeddings=centroids_normalized, labels=labels)
        logger.info(f"Saved {scale}s dictionary to {out_path}")
        
    logger.info("Multiscale dictionary building complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Multiscale Patch Dictionaries")
    parser.add_argument("--detector", type=str, default="L1", help="Detector")
    parser.add_argument("--n_dict", type=int, default=500, help="Number of background segments to build dictionary")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()
    
    build_multiscale_dictionaries(
        detector=args.detector,
        n_dict=args.n_dict,
        seed=args.seed
    )
