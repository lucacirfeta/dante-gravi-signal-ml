import json
import logging
from pathlib import Path
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
import matplotlib.pyplot as plt
from PIL import Image
import torchvision.transforms as T
from gwosc.timeline import get_segments
from tenacity import retry, wait_exponential, stop_after_attempt

from src.core.data_loader import fetch_strain_data
from src.core.preprocessor import whiten, bandpass, generate_qtransform
from src.pipeline_v3_multiscale.micro_mdc_multiscale import excess_power_veto
from src.core.utils import setup_logger

logger = setup_logger(__name__)

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(5))
def get_segments_retry(flag, start, end):
    return get_segments(flag, start, end)

def test_saliency_and_veto(detector="L1", n_test=50, seed=42):
    np.random.seed(seed)
    torch.manual_seed(seed)
    
    thresh_file = Path(f"results/micro_mdc/multiscale/{detector}_thresholds.json")
    with open(thresh_file, "r") as f:
        p99_thresh = json.load(f)
        
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14_reg")
    model = model.to(device)
    model.eval()
    
    transform = T.Compose([
        T.Resize((518, 518), interpolation=T.InterpolationMode.BICUBIC),
        T.ToTensor(),
        T.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    ])
    
    test_scales = [0.5, 1, 2, 4]
    dictionaries = {}
    for scale in test_scales:
        dict_path = f"results/micro_mdc/multiscale/{detector}_patch_dict_{scale}s.npz"
        data = np.load(dict_path)
        dictionaries[scale] = torch.tensor(data["embeddings"], dtype=torch.float32).to(device)
        
    burst_segs = get_segments_retry(f'{detector}_BURST_CAT1', 1238166018, 1253977218)
    data_segs = get_segments_retry(f'{detector}_DATA', 1238166018, 1253977218)
    
    temp_dir = Path("results/micro_mdc/multiscale/temp_fpr_o3a")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    saliency_dir = Path("results/micro_mdc/multiscale/saliency_o3a")
    saliency_dir.mkdir(parents=True, exist_ok=True)
    
    results = []
    
    # We will search for O3a background segments
    # We will apply excess_power_veto
    # If they pass the veto, but fail the FPR threshold at 2s or 4s, we plot the saliency map.
    
    block_size = 4096
    start_time = 1238166018
    
    fps_found = 0
    
    for block_start in range(start_time, 1253977218, block_size):
        if fps_found >= 10: # We just want a sample of 10 false positives
            break
            
        block_end = block_start + block_size
        if not any(s[0] <= block_start and s[1] >= block_end for s in data_segs):
            continue
            
        try:
            logger.info(f"Downloading/loading 4096s block: {block_start}-{block_end}")
            ts_block = fetch_strain_data(detector, block_start, block_end)
        except Exception as e:
            continue
            
        attempts = 0
        block_results = 0
        
        while attempts < 50 and fps_found < 10:
            attempts += 1
            t_bg = np.random.randint(block_start + 64, block_end - 64)
            win_start, win_end = t_bg - 16, t_bg + 16
            
            if not any(s[0] <= win_start and s[1] >= win_end for s in burst_segs): continue
            
            try:
                ts_clean = ts_block.crop(win_start, win_end)
                
                # IMPORTANT: Apply excess_power_veto!
                if excess_power_veto(ts_clean, sample_rate=4096):
                    logger.debug(f"Segment {t_bg} rejected by excess_power_veto.")
                    continue
                
                ts_white = whiten(ts_clean)
                ts_bp = bandpass(ts_white)
                
                is_fp = False
                
                for scale in test_scales:
                    ts_crop = ts_bp.crop(t_bg - scale / 2.0, t_bg + scale / 2.0)
                    temp_path = temp_dir / f"fpr_o3a_{scale}.png"
                    generate_qtransform(ts_crop, qrange=(4, 32), save_path=temp_path)
                    
                    img = Image.open(temp_path).convert('RGB')
                    tensor = transform(img).unsqueeze(0).to(device)
                    with torch.inference_mode():
                        features = model.forward_features(tensor)
                        patch_tokens = F.normalize(features["x_norm_patchtokens"].squeeze(0), p=2, dim=-1)
                        
                    dict_tokens = F.normalize(dictionaries[scale], p=2, dim=-1)
                    sim_matrix = torch.matmul(patch_tokens, dict_tokens.T)
                    anomaly_scores = 1.0 - sim_matrix.max(dim=1)[0]
                    score = torch.topk(anomaly_scores, k=68)[0].mean().item()
                    threshold = p99_thresh[f"{scale}s"]["p99_mean"]
                    if score > threshold:
                        logger.info(f"Found False Positive at {scale}s! Score: {score:.4f} > {threshold:.4f}")
                        is_fp = True
                        
                        # Generate Saliency Map
                        # Anomaly scores shape: (1369,)
                        saliency = anomaly_scores.cpu().numpy().reshape(37, 37)
                        
                        fig, axes = plt.subplots(1, 2, figsize=(10, 5))
                        axes[0].imshow(img)
                        axes[0].set_title(f"Spectrogram ({scale}s)")
                        axes[0].axis('off')
                        
                        # Plot saliency overlaid
                        im = axes[1].imshow(saliency, cmap='hot', interpolation='nearest')
                        axes[1].set_title("Anomaly Saliency Map")
                        axes[1].axis('off')
                        
                        # Calculate band concentration
                        # DINOv2 patches are 14x14 pixels. 518/14 = 37 patches.
                        # The y-axis corresponds to frequency (log scale).
                        # Bottom rows (high y-index) = low frequency.
                        # Top rows (low y-index) = high frequency.
                        
                        # Calculate mass in bottom 12 rows (~ lower 3rd of frequencies)
                        low_freq_mass = np.sum(saliency[-12:, :]) / np.sum(saliency)
                        axes[1].text(0, 39, f"Low-Freq Mass: {low_freq_mass:.2%}", color='red', fontsize=12)
                        
                        plt.tight_layout()
                        plt.savefig(saliency_dir / f"saliency_fp_{t_bg}_{scale}s.png")
                        plt.close()
                        
                    temp_path.unlink()
                
                if is_fp:
                    fps_found += 1
                
            except Exception as e:
                import traceback
                logger.error(f"Error at {t_bg}: {traceback.format_exc()}")
                pass

if __name__ == "__main__":
    test_saliency_and_veto()
