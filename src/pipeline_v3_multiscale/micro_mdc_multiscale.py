import os
import json
import logging
import argparse
import numpy as np
import pandas as pd
import scipy.stats as stats
import torch
import torch.nn.functional as F
from pathlib import Path
from tqdm import tqdm
from PIL import Image
from gwosc.timeline import get_segments

from src.core.data_loader import fetch_strain_data, clear_astropy_cache, _DATA_DIRECTORIES
from src.core.preprocessor import whiten_context, extract_clean_subwindow, bandpass, generate_qtransform
from src.core.encoder import build_dinov2_transform
from src.core.utils import setup_logger

logger = setup_logger(__name__)

def excess_power_veto(ts_whitened, sample_rate=4096):
    windows_ms = [50, 100, 250]
    context_s = 16.0
    threshold_mad = 5.0
    MAD_TO_SIGMA = 1.4826
    data = ts_whitened.value
    for win_ms in windows_ms:
        win_samples = int(win_ms * sample_rate / 1000)
        stride = max(1, win_samples // 4)
        rms = np.sqrt(np.convolve(data**2, np.ones(win_samples) / win_samples, mode='valid'))
        context_samples = int(context_s * sample_rate)
        for i in range(0, len(rms), stride):
            ctx_start = max(0, i - context_samples // 2)
            ctx_end = min(len(rms), i + context_samples // 2)
            excl_start = max(ctx_start, i - win_samples)
            excl_end = min(ctx_end, i + win_samples)
            ctx_indices = np.concatenate([np.arange(ctx_start, excl_start), np.arange(excl_end, ctx_end)])
            if len(ctx_indices) < 100: continue
            ctx_values = rms[ctx_indices]
            local_median = np.median(ctx_values)
            local_mad = np.median(np.abs(ctx_values - local_median))
            local_sigma = local_mad * MAD_TO_SIGMA
            if local_sigma > 0 and (rms[i] - local_median) > threshold_mad * local_sigma:
                return True
    return False

def block_bootstrap_p99(scores, B=1000, seed=42):
    rng = np.random.default_rng(seed)
    p99_samples = []
    n = len(scores)
    for _ in range(B):
        idx = rng.integers(0, n, size=n)
        p99_samples.append(np.percentile(scores[idx], 99.0))
    return np.mean(p99_samples), np.std(p99_samples)

def run_micro_mdc_multiscale(detector="L1", n_calib=5000, seed=42):
    np.random.seed(seed)
    output_dir = Path("results/micro_mdc/multiscale")
    temp_dir = output_dir / "temp_mdc_pngs"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    scales = [0.5, 1, 2, 4, 32]
    stride = 96
    
    # Load dictionaries
    dicts = {}
    for scale in scales:
        dict_path = output_dir / f"{detector}_patch_dict_{scale}s.npz"
        if not dict_path.exists():
            raise FileNotFoundError(f"Missing dict for scale {scale}s at {dict_path}")
        data = np.load(dict_path)
        dicts[scale] = torch.tensor(data["embeddings"], dtype=torch.float32).cuda()
        
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = torch.hub.load('facebookresearch/dinov2', 'dinov2_vits14_reg').to(device)
    model.eval()
    for param in model.parameters(): param.requires_grad = False
    transform = build_dinov2_transform()
    
    # 1. Discover local blocks
    local_blocks = []
    for directory in _DATA_DIRECTORIES:
        if directory.exists():
            for file in directory.rglob(f"{detector}_*.hdf5"):
                parts = file.stem.split("_")
                if len(parts) >= 3:
                    try:
                        local_blocks.append((int(parts[1]), int(parts[2])))
                    except ValueError: pass
                        
    np.random.shuffle(local_blocks)
    
    valid_t_bgs = []
    calib_scores = {s: [] for s in scales}
    
    logger.info(f"Finding {n_calib} valid background centers for calibration...")
    pbar = tqdm(total=n_calib, desc="Calibration Extractor")
    
    for block_start, block_end in local_blocks:
        if len(valid_t_bgs) >= n_calib: break
            
        try:
            burst_segs = get_segments(f'{detector}_BURST_CAT1', block_start, block_end)
        except: continue
            
        try:
            ts_clean = fetch_strain_data(detector, block_start, block_end, cache_raw=False)
            ts_w_padded, _ = whiten_context(ts_clean, block_start, block_end, pad=4.0)
            ts_white = extract_clean_subwindow(ts_w_padded, block_start, block_end)
            ts_bp = bandpass(ts_white)
        except: continue
            
        candidate_t_bgs = np.arange(block_start + 64, block_end - 64, stride)
        
        for t_bg in candidate_t_bgs:
            if len(valid_t_bgs) >= n_calib: break
                
            win_start = t_bg - 16
            win_end = t_bg + 16
            is_dq_clean = any(s[0] <= win_start and s[1] >= win_end for s in burst_segs)
            if not is_dq_clean: continue
                
            ts_32s = ts_bp.crop(t_bg - 16, t_bg + 16)
            if excess_power_veto(ts_32s): continue
                
            scale_scores = {}
            valid_extraction = True
            
            for scale in scales:
                ts_crop = ts_bp.crop(t_bg - scale / 2.0, t_bg + scale / 2.0)
                if np.any(np.isnan(ts_crop.value)) or np.any(np.isinf(ts_crop.value)):
                    valid_extraction = False
                    break
                    
                temp_path = temp_dir / f"calib_{scale}.png"
                try:
                    generate_qtransform(ts_crop, qrange=(4, 32), save_path=temp_path)
                    
                    img = Image.open(temp_path)
                    tensor = transform(img).unsqueeze(0).to(device)
                    with torch.inference_mode():
                        features = model.forward_features(tensor)
                        patch_tokens = F.normalize(features["x_norm_patchtokens"].squeeze(0), p=2, dim=-1) # (1369, 384)
                        
                    similarities = torch.matmul(patch_tokens, dicts[scale].T)
                    max_sims, _ = similarities.max(dim=1) # (1369,)
                    anomaly_scores = 1.0 - max_sims
                    
                    top_k_scores, _ = torch.topk(anomaly_scores, k=68)
                    score = top_k_scores.mean().item()
                    scale_scores[scale] = score
                except Exception as e:
                    logger.warning(f"Error at scale {scale}s: {e}")
                    valid_extraction = False
                    break
                finally:
                    if temp_path.exists():
                        temp_path.unlink()
                        
            if not valid_extraction or len(scale_scores) != len(scales):
                continue
                
            valid_t_bgs.append(int(t_bg))
            for scale in scales:
                calib_scores[scale].append(scale_scores[scale])
                
            pbar.update(1)
            
    pbar.close()
    
    if len(valid_t_bgs) < n_calib:
        logger.warning(f"Only found {len(valid_t_bgs)} segments out of {n_calib}.")
        
    # Block Bootstrap
    thresholds = {}
    for scale in scales:
        scores_arr = np.array(calib_scores[scale])
        p99_mean, p99_std = block_bootstrap_p99(scores_arr, B=1000, seed=seed)
        logger.info(f"Scale {scale}s: P99 = {p99_mean:.6f} ± {p99_std:.6f}")
        thresholds[f"{scale}s"] = {
            "p99_mean": float(p99_mean),
            "p99_std": float(p99_std),
            "n_calib": len(scores_arr)
        }
        
    with open(output_dir / f"{detector}_calib_scores.json", "w") as f:
        json.dump(calib_scores, f)
        
    with open(output_dir / f"{detector}_thresholds.json", "w") as f:
        json.dump(thresholds, f, indent=4)
        
    logger.info("Calibration complete. Thresholds saved.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector", type=str, default="L1")
    parser.add_argument("--n_calib", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run_micro_mdc_multiscale(detector=args.detector, n_calib=args.n_calib, seed=args.seed)
