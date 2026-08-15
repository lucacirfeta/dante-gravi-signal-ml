import os
import json
import logging
import argparse
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from pathlib import Path
from tqdm import tqdm
from PIL import Image
from sklearn.cluster import MiniBatchKMeans
from gwosc.timeline import get_segments

from src.core.data_loader import fetch_strain_data
from src.core.preprocessor import whiten_context, extract_clean_subwindow, bandpass, generate_qtransform
from src.core.encoder import build_dinov2_transform
from src.core.model_loader import load_dinov2_model
from src.core.utils import setup_logger
from src.pipeline_v3_multiscale.micro_mdc_multiscale import excess_power_veto

logger = setup_logger(__name__)

def build_o3a_dictionaries(detector="L1", n_dict=2000, seed=42):
    output_dir = Path("results/micro_mdc/multiscale_o3a")
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "temp_pngs"
    temp_dir.mkdir(exist_ok=True)
    
    scales = [0.5, 1, 2, 4]
    
    # O3a approx range
    logger.info("Fetching O3a segments from GWOSC...")
    start_o3a = 1238166018
    end_o3a = 1253977218
    import time
    for attempt in range(5):
        try:
            burst_segs = get_segments(f'{detector}_BURST_CAT1', start_o3a, end_o3a)
            data_segs = get_segments(f'{detector}_DATA', start_o3a, end_o3a)
            break
        except Exception as e:
            logger.warning(f"GWOSC API error on attempt {attempt+1}: {e}. Retrying in 5s...")
            time.sleep(5)
    
    np.random.seed(seed)
    
    valid_t_bgs = []
    logger.info(f"Finding {n_dict} valid background centers from O3a...")
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_dinov2_model(device)
    model.eval()
    for param in model.parameters(): param.requires_grad = False
    transform = build_dinov2_transform()
    
    embeddings_by_scale = {s: [] for s in scales}
    
    pbar = tqdm(total=n_dict, desc="Extracting O3a features")
    
    while len(valid_t_bgs) < n_dict:
        block_idx = np.random.randint(0, (end_o3a - start_o3a) // 4096)
        block_start = start_o3a + block_idx * 4096
        block_end = block_start + 4096
        
        candidates = np.random.randint(block_start + 64, block_end - 64, size=50)
        
        for t_bg in candidates:
            if len(valid_t_bgs) >= n_dict: break
            
            win_start = t_bg - 16
            win_end = t_bg + 16
            
            if not any(s[0] <= win_start and s[1] >= win_end for s in burst_segs): continue
            if not any(s[0] <= win_start and s[1] >= win_end for s in data_segs): continue
                
            try:
                ts_super = fetch_strain_data(detector, t_bg - 16 - 4.0, t_bg + 16 + 4.0, cache_raw=False, edge_tolerance=4.0)
                ts_w_padded, _ = whiten_context(ts_super, t_bg - 16, t_bg + 16, pad=4.0)
                ts_bp = extract_clean_subwindow(ts_w_padded, t_bg - 16, t_bg + 16)  # already whitened+bandpassed
            except Exception as e:
                continue
                
            scale_feats = {}
            valid_extraction = True
            
            for scale in scales:
                ts_crop = ts_bp.crop(t_bg - scale / 2.0, t_bg + scale / 2.0)
                if np.any(np.isnan(ts_crop.value)) or np.any(np.isinf(ts_crop.value)):
                    valid_extraction = False
                    break
                    
                # NB: nessun taper qui — il builder O4a non lo applica; un taper
                # asimmetrico tra dizionari sarebbe un confondente (audit M-5).
                temp_path = temp_dir / f"dict_{scale}.png"
                try:
                    generate_qtransform(ts_crop, qrange=(4, 32), save_path=temp_path)
                    img = Image.open(temp_path)
                    tensor = transform(img).unsqueeze(0).to(device)
                    with torch.inference_mode():
                        features = model.forward_features(tensor)
                        patch_tokens = F.normalize(features["x_norm_patchtokens"].squeeze(0), p=2, dim=-1)
                    scale_feats[scale] = patch_tokens.cpu().numpy()
                except Exception as e:
                    valid_extraction = False
                    break
                finally:
                    if temp_path.exists(): temp_path.unlink()
                    
            if valid_extraction:
                valid_t_bgs.append(int(t_bg))
                for scale in scales:
                    embeddings_by_scale[scale].append(scale_feats[scale])
                pbar.update(1)
                
    pbar.close()
    
    with open(output_dir / f"{detector}_dict_t_bg.json", "w") as f:
        json.dump(valid_t_bgs, f)
        
    for scale in scales:
        all_feats = np.concatenate(embeddings_by_scale[scale], axis=0)
        logger.info(f"Clustering {len(all_feats)} patches for scale {scale}s...")
        kmeans = MiniBatchKMeans(n_clusters=275, batch_size=4096, n_init=3, random_state=42)  # K aligned to production (audit B-5)
        kmeans.fit(all_feats)
        centroids = kmeans.cluster_centers_
        centroids_norm = centroids / np.linalg.norm(centroids, axis=1, keepdims=True)
        out_path = output_dir / f"{detector}_patch_dict_{scale}s.npz"
        np.savez_compressed(out_path, embeddings=centroids_norm, labels=np.arange(len(centroids_norm)))
        logger.info(f"Saved {out_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector", type=str, default="L1")
    parser.add_argument("--n_dict", type=int, default=2000)
    args = parser.parse_args()
    build_o3a_dictionaries(detector=args.detector, n_dict=args.n_dict)
