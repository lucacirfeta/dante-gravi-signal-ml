import json
import logging
from pathlib import Path
import numpy as np
import pandas as pd
from tqdm import tqdm
import scipy.stats as stats

from src.core.data_loader import fetch_strain_data
from gwosc.timeline import get_segments
from tenacity import retry, wait_exponential, stop_after_attempt
from src.core.preprocessor import whiten_context, extract_clean_subwindow, bandpass, generate_qtransform
from src.core.utils import setup_logger

logger = setup_logger(__name__)

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(5))
def get_segments_retry(flag, start, end):
    return get_segments(flag, start, end)

def test_fpr_o3a(detector="L1", n_test=500, seed=42):
    thresh_file = Path(f"results/micro_mdc/multiscale/{detector}_thresholds.json")
    with open(thresh_file, "r") as f:
        thresholds = json.load(f)
    # This script is the cross-run MEASUREMENT: O4a thresholds on O3a data
    # is the quantity under study, hence allow_cross_run=True.
    from src.pipeline_v3_multiscale.sampling import assert_threshold_run
    assert_threshold_run(thresholds, "O3a", allow_cross_run=True)
    p99_thresh = {s: thresholds[s]["p99_mean"] for s in thresholds
                  if isinstance(thresholds[s], dict) and "p99_mean" in thresholds[s]}
    
    logger.info("Fetching O3a segments (full run window, audit fix M-4)...")
    # Full O3a range: the previous window [1238166018, 1240166018] covered only
    # the first ~23 days, silently discarding blocks sampled outside it.
    start_time = 1238166018
    end_time = 1253977218
    burst_segs = get_segments_retry(f'{detector}_BURST_CAT1', start_time, end_time)
    data_segs = get_segments_retry(f'{detector}_DATA', start_time, end_time)
    
    np.random.seed(seed)
    
    # We want 500 segments. We will sample 15 blocks of 4096 seconds, 
    # and extract valid 32s windows from them.
    n_blocks = 15
    block_duration = 4096
    
    # Pre-select block centers
    block_centers = np.random.randint(1238166018 + block_duration, 1253977218 - block_duration, size=n_blocks*5)
    valid_blocks = []
    
    for c in block_centers:
        if len(valid_blocks) >= n_blocks: break
        # Check if this block has good overlap with DATA and BURST
        if any(s[0] <= c and s[1] >= c for s in data_segs):
            valid_blocks.append((c - block_duration//2, c + block_duration//2))
            
    import torch
    import torch.nn.functional as F
    from PIL import Image
    from src.core.encoder import build_dinov2_transform
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    transform = build_dinov2_transform()
    
    dictionaries = {}
    scales = [0.5, 1, 2, 4, 32]
    for scale in scales:
        dict_path = f"results/micro_mdc/multiscale/{detector}_patch_dict_{scale}s.npz"
        if Path(dict_path).exists():
            data = np.load(dict_path)
            dictionaries[scale] = torch.tensor(data["embeddings"], dtype=torch.float32).to(device)
            
    test_scales = [0.5, 1, 2, 4]
    model = torch.hub.load('facebookresearch/dinov2', 'dinov2_vits14_reg').to(device)
    model.eval()
    for param in model.parameters(): param.requires_grad = False
    
    results = []
    temp_dir = Path("results/micro_mdc/multiscale/temp_fpr_o3a")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    pbar = tqdm(total=n_test, desc="O3a FPR Testing")
    
    for block_start, block_end in valid_blocks:
        if len(results) >= n_test: break
        
        logger.info(f"Downloading/loading 4096s block: {block_start}-{block_end}")
        try:
            ts_block = fetch_strain_data(detector, block_start, block_end, cache_raw=True)
        except Exception as e:
            logger.warning(f"Skipping block due to error: {e}")
            continue
            
        # Sample 50 valid points from this block
        attempts = 0
        block_results = 0
        
        while block_results < 40 and attempts < 200 and len(results) < n_test:
            attempts += 1
            t_bg = np.random.randint(block_start + 64, block_end - 64)
            # Guard-time B-4: centers must be pairwise separated by >= 96 s
            # (max(scales) + 64), otherwise overlapping ViT receptive fields
            # correlate the FPR samples and the guard-time fix is inactive
            # exactly on the path that measures the FPR.
            from src.pipeline_v3_multiscale.sampling import respects_guard
            if not respects_guard(t_bg, [r["gps"] for r in results]):
                continue
            win_start, win_end = t_bg - 16, t_bg + 16
            
            if not any(s[0] <= win_start and s[1] >= win_end for s in burst_segs): continue
            if not any(s[0] <= win_start and s[1] >= win_end for s in data_segs): continue
            
            try:
                ts_super = ts_block.crop(win_start - 4.0, win_end + 4.0)
                ts_w_padded, _ = whiten_context(ts_super, win_start, win_end, pad=4.0)
                ts_bp = extract_clean_subwindow(ts_w_padded, win_start, win_end)  # already whitened+bandpassed
                
                scale_scores = {}
                valid_extraction = True
                for scale in test_scales:
                    ts_crop = ts_bp.crop(t_bg - scale / 2.0, t_bg + scale / 2.0)
                    temp_path = temp_dir / f"fpr_o3a_{scale}.png"
                    generate_qtransform(ts_crop, qrange=(4, 32), save_path=temp_path)
                    
                    img = Image.open(temp_path)
                    tensor = transform(img).unsqueeze(0).to(device)
                    with torch.inference_mode():
                        features = model.forward_features(tensor)
                        patch_tokens = F.normalize(features["x_norm_patchtokens"].squeeze(0), p=2, dim=-1)
                        
                    dict_tokens = F.normalize(dictionaries[scale], p=2, dim=-1)
                    sim_matrix = torch.matmul(patch_tokens, dict_tokens.T)
                    anomaly_scores = 1.0 - sim_matrix.max(dim=1)[0]
                    score = torch.topk(anomaly_scores, k=68)[0].mean().item()
                    scale_scores[scale] = score
                    temp_path.unlink()
                    
                res = {"gps": t_bg}
                for scale in test_scales:
                    res[f"fpr_{scale}s"] = scale_scores[scale] > p99_thresh[f"{scale}s"]
                res["fpr_union"] = any(res[f"fpr_{s}s"] for s in test_scales)
                results.append(res)
                block_results += 1
                pbar.update(1)
            except Exception as e:
                pass
                
    pbar.close()
    
    df = pd.DataFrame(results)
    print("\n=== False Positive Rate of O4a Dictionaries on O3a Background ===")
    print(f"N = {len(df)}")
    
    print("\nTest Binomiale esatto contro H0: p = 0.01")
    for col in ["fpr_0.5s", "fpr_1s", "fpr_2s", "fpr_4s", "fpr_union"]:
        if col in df.columns:
            k = df[col].sum()
            n = len(df)
            fpr = df[col].mean()
            pval = stats.binomtest(k, n, p=0.01, alternative='greater').pvalue
            print(f"  {col}: FPR = {fpr:.2%} ({k}/{n}) | p-value (p>0.01) = {pval:.4e}")
            
    df.to_csv(f"results/micro_mdc/multiscale/{detector}_fpr_o3a_results.csv", index=False)

if __name__ == "__main__":
    test_fpr_o3a(n_test=500)
