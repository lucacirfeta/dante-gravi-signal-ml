import os
import argparse
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from pathlib import Path
from tqdm import tqdm
from PIL import Image

from src.core.data_loader import fetch_strain_data, clear_astropy_cache
from src.core.preprocessor import whiten, bandpass, generate_qtransform
from src.core.encoder import build_dinov2_transform
from src.core.utils import setup_logger

logger = setup_logger(__name__)

def test_real_blips(detector: str = "L1", n_test: int = -1):
    output_dir = Path("results/micro_mdc/multiscale")
    temp_dir = output_dir / "temp_real_blips"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    scales = [0.5, 1, 2, 4, 32]
    
    dicts = {}
    for scale in scales:
        dict_path = output_dir / f"{detector}_patch_dict_{scale}s.npz"
        if not dict_path.exists():
            raise FileNotFoundError(f"Missing dict {dict_path}")
        data = np.load(dict_path)
        dicts[scale] = torch.tensor(data["embeddings"], dtype=torch.float32).cuda()
        
    # Load thresholds
    try:
        import json
        with open(output_dir / f"{detector}_thresholds.json", "r") as f:
            thresholds_info = json.load(f)
            thresholds = {float(k.replace('s', '')): v["p99_mean"] for k, v in thresholds_info.items()}
    except Exception as e:
        raise RuntimeError(f"Could not load thresholds: {e}")
        
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = torch.hub.load('facebookresearch/dinov2', 'dinov2_vits14_reg').to(device)
    model.eval()
    for param in model.parameters(): param.requires_grad = False
    transform = build_dinov2_transform()
    
    # Load Zenodo O3a
    zenodo_url = f"https://zenodo.org/api/records/5649212/files/{detector}_O3a.csv/content"
    logger.info(f"Downloading O3a metadata for {detector} from {zenodo_url}...")
    df = pd.read_csv(zenodo_url)
    
    # Filter ml_confidence >= 0.90
    df_blip = df[(df["ml_label"].isin(["Blip", "Blip_Low_Frequency"])) & (df["ml_confidence"] >= 0.90)]
    
    if len(df_blip) == 0:
        logger.error(f"No Blips found for detector {detector} with confidence >= 0.90.")
        return
        
    actual_n_test = len(df_blip) if n_test == -1 else min(n_test, len(df_blip))
    df_sample = df_blip.sample(n=actual_n_test, random_state=42)
    
    blips_to_test = []
    for _, row in df_sample.iterrows():
        # Using Omega metadata since Omicron is not in the public CSV
        blips_to_test.append({
            "gps": row["peak_time"],
            "class": row["ml_label"],
            "ml_confidence": row["ml_confidence"],
            "duration": row["duration"],
            "snr": row["snr"],
            "central_freq": row["central_freq"],
            "bandwidth": row["bandwidth"]
        })
        
    logger.info(f"Selected {len(blips_to_test)} high-confidence real Blips.")
    
    segment_length = 32
    results = []
    
    pbar = tqdm(total=len(blips_to_test), desc="Scoring Blips")
    
    for item in blips_to_test:
        start_center = item["gps"]
        
        start = start_center - segment_length / 2.0
        end = start_center + segment_length / 2.0
        
        try:
            ts_context = fetch_strain_data(detector, start - 4.0, end + 4.0, cache_raw=True)
            from src.core.preprocessor import whiten_context, extract_clean_subwindow, bandpass
            ts_white_full, _, _ = whiten_context(ts_context, start, end, pad=4.0)
            ts_bp = bandpass(ts_white_full)
            
            blip_res = item.copy()
            
            for scale in scales:
                ts_crop = ts_bp.crop(start_center - scale / 2.0, start_center + scale / 2.0)
                generate_qtransform(ts_crop, qrange=(4, 32), save_path=temp_dir / f"blip_{scale}.png")
                
                img = Image.open(temp_dir / f"blip_{scale}.png")
                tensor = transform(img).unsqueeze(0).to(device)
                
                with torch.inference_mode():
                    features = model.forward_features(tensor)
                    patch_tokens = F.normalize(features["x_norm_patchtokens"].squeeze(0), p=2, dim=-1)
                    
                similarities = torch.matmul(patch_tokens, dicts[scale].T)
                max_sims, _ = similarities.max(dim=1)
                anomaly_scores = 1.0 - max_sims
                
                top_k_scores, _ = torch.topk(anomaly_scores, k=68)
                score = top_k_scores.mean().item()
                
                thresh = thresholds[scale]
                is_novel = score > thresh
                
                if scale == 32:
                    blip_res["score_32s_native"] = score
                    blip_res["novel_native"] = is_novel
                else:
                    blip_res[f"score_{scale}s"] = score
                    blip_res[f"novel_{scale}s"] = is_novel
            
            # Compute Union
            union_novel = any([blip_res[f"novel_{s}s"] for s in [0.5, 1, 2, 4]])
            blip_res["novel_union"] = union_novel
            blip_res["K"] = 68
            
            results.append(blip_res)
            
        except Exception as e:
            logger.warning(f"Failed to process real Blip at GPS {start_center}: {e}")
            
        pbar.update(1)
        
    pbar.close()
    
    if results:
        out_df = pd.DataFrame(results)
        out_path = output_dir / f"{detector}_real_blips_scoring_results_{actual_n_test}.csv"
        out_df.to_csv(out_path, index=False)
        logger.info(f"Saved automated scoring results to {out_path}")
        
    clear_astropy_cache()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector", type=str, default="L1")
    parser.add_argument("--n_test", type=int, default=-1)
    args = parser.parse_args()
    test_real_blips(detector=args.detector, n_test=args.n_test)
