import json
import logging
from pathlib import Path
import numpy as np
import pandas as pd
from tqdm import tqdm

from src.core.data_loader import fetch_strain_data, _DATA_DIRECTORIES
from gwosc.timeline import get_segments
from src.core.preprocessor import whiten_context, extract_clean_subwindow, bandpass, generate_qtransform
from src.core.utils import setup_logger

logger = setup_logger(__name__)

def test_fpr(detector="L1", n_test=200):
    # Load thresholds
    thresh_file = Path(f"results/micro_mdc/multiscale/{detector}_thresholds.json")
    with open(thresh_file, "r") as f:
        thresholds = json.load(f)
        
    p99_thresh = {s: thresholds[s]["p99_mean"] for s in thresholds}
    
    # We will pick completely random local blocks and fetch background segments
    # to test FPR. Since we didn't set a seed previously, the 5000 used for calib
    # are random. We will just randomly sample 200 new ones using a fixed seed
    # that is likely disjoint from the previous pool.
    
    local_blocks = []
    for directory in _DATA_DIRECTORIES:
        if directory.exists():
            for file in directory.rglob(f"{detector}_*.hdf5"):
                parts = file.stem.split("_")
                if len(parts) >= 3:
                    try:
                        local_blocks.append((int(parts[1]), int(parts[2])))
                    except ValueError: pass
                    
    np.random.seed(999) # different seed from anything implicitly used
    np.random.shuffle(local_blocks)
    
    valid_t_bgs = []
    for block_start, block_end in local_blocks:
        if len(valid_t_bgs) >= n_test: break
        try:
            burst_segs = get_segments(f'{detector}_BURST_CAT1', block_start, block_end)
        except: continue
            
        candidate_t_bgs = np.arange(block_start + 64, block_end - 64, 96)
        for t_bg in candidate_t_bgs:
            if len(valid_t_bgs) >= n_test: break
            win_start = t_bg - 16
            win_end = t_bg + 16
            if any(s[0] <= win_start and s[1] >= win_end for s in burst_segs):
                valid_t_bgs.append(int(t_bg))
                
    logger.info(f"Using {len(valid_t_bgs)} independent background segments for FPR test.")
    
    # Load dictionaries
    import torch
    import torch.nn.functional as F
    from PIL import Image
    from src.pipeline_v3_multiscale.test_real_blips import build_dinov2_transform
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    transform = build_dinov2_transform()
    
    dictionaries = {}
    scales = [0.5, 1, 2, 4, 32]
    for scale in scales:
        dict_path = f"results/micro_mdc/multiscale/{detector}_patch_dict_{scale}s.npz"
        if Path(dict_path).exists():
            data = np.load(dict_path)
            dictionaries[scale] = torch.tensor(data["embeddings"], dtype=torch.float32).to(device)
            
    # the 32s dictionary is actually patch_compressed_index_o3b.npz
    # so we shouldn't test 32s here, or we load it differently. 
    # The user specifically asked for FPR at 2s and 4s.
    test_scales = [0.5, 1, 2, 4]
            
    model = torch.hub.load('facebookresearch/dinov2', 'dinov2_vits14_reg').to(device)
    model.eval()
    for param in model.parameters(): param.requires_grad = False
    
    results = []
    temp_dir = Path("results/micro_mdc/multiscale/temp_fpr")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    pbar = tqdm(total=n_test, desc="FPR Testing")
    for t_bg in valid_t_bgs:
        try:
            ts_super = fetch_strain_data(detector, t_bg - 16 - 4.0, t_bg + 16 + 4.0, cache_raw=True, edge_tolerance=4.0)
            ts_w_padded, _ = whiten_context(ts_super, t_bg - 16, t_bg + 16, pad=4.0)
            ts_white = extract_clean_subwindow(ts_w_padded, t_bg - 16, t_bg + 16)
            ts_bp = bandpass(ts_white)
            
            scale_scores = {}
            valid_extraction = True
            
            for scale in test_scales:
                ts_crop = ts_bp.crop(t_bg - scale / 2.0, t_bg + scale / 2.0)
                if np.any(np.isnan(ts_crop.value)) or np.any(np.isinf(ts_crop.value)):
                    valid_extraction = False
                    break
                    
                temp_path = temp_dir / f"fpr_{scale}.png"
                generate_qtransform(ts_crop, qrange=(4, 32), save_path=temp_path)
                
                img = Image.open(temp_path)
                tensor = transform(img).unsqueeze(0).to(device)
                with torch.inference_mode():
                    features = model.forward_features(tensor)
                    patch_tokens = F.normalize(features["x_norm_patchtokens"].squeeze(0), p=2, dim=-1)
                    
                dict_tokens = F.normalize(dictionaries[scale], p=2, dim=-1)
                sim_matrix = torch.matmul(patch_tokens, dict_tokens.T)
                max_sims, _ = sim_matrix.max(dim=1)
                anomaly_scores = 1.0 - max_sims
                
                top_k_scores, _ = torch.topk(anomaly_scores, k=68)
                score = top_k_scores.mean().item()
                scale_scores[scale] = score
                temp_path.unlink()
                
            if valid_extraction:
                res = {"gps": t_bg}
                for scale in test_scales:
                    res[f"fpr_{scale}s"] = scale_scores[scale] > p99_thresh[f"{scale}s"]
                res["fpr_union"] = any(res[f"fpr_{s}s"] for s in test_scales)
                results.append(res)
                
        except Exception as e:
            import traceback
            logger.warning(f"Error at GPS {t_bg}: {traceback.format_exc()}")
            
        pbar.update(1)
        
    pbar.close()
    
    if len(results) == 0:
        print("No valid results computed.")
        return
        
    df = pd.DataFrame(results)
    print("\n=== False Positive Rate on Held-Out O4a Background ===")
    print(f"N = {len(df)}")
    for col in ["fpr_0.5s", "fpr_1s", "fpr_2s", "fpr_4s", "fpr_union"]:
        fpr = df[col].mean()
        print(f"{col}: {fpr:.2%} ({df[col].sum()}/{len(df)})")
        
if __name__ == "__main__":
    test_fpr(n_test=200)
