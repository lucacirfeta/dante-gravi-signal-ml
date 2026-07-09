import logging
import argparse
import numpy as np
from pathlib import Path
from src.core.data_loader import fetch_strain_data
from src.core.preprocessor import whiten_context, extract_clean_subwindow, bandpass, generate_qtransform
from src.core.utils import setup_logger

logger = setup_logger(__name__)

def run_qtransform_support_test(gps_start: int, num_segments: int = 20, detector: str = "L1"):
    segment_length = 32
    available_starts = np.arange(gps_start, gps_start + num_segments * segment_length, segment_length)
    
    # 20-40 Hz band (assuming 256 pixels correspond to 20-2048 Hz log scale)
    # y = log2(f/20) / log2(2048/20) * 256
    # f = 20 -> y = 0
    # f = 40 -> y = log2(2) / log2(102.4) * 256 ~= 1 / 6.67 * 256 ~= 38
    low_band_max_pixel = 38
    
    passed = True
    for start in available_starts:
        end = start + segment_length
        ts_super = fetch_strain_data(detector, start - 4.0, end + 4.0, cache_raw=True, edge_tolerance=4.0)
        ts_w_padded, _ = whiten_context(ts_super, start, end, pad=4.0)
        ts_bp = extract_clean_subwindow(ts_w_padded, start, end)  # already whitened+bandpassed
        
        # Test 4s baseline
        ts_4s = ts_bp.crop(start + 14, start + 18)
        try:
            q_4s = generate_qtransform(ts_4s, qrange=(4, 64))
        except Exception as e:
            logger.error(f"4s Q-transform failed: {e}")
            continue
            
        # Test 1s baseline
        ts_1s = ts_bp.crop(start + 15.5, start + 16.5)
        try:
            q_1s = generate_qtransform(ts_1s, qrange=(4, 64))
        except Exception as e:
            logger.error(f"1s Q-transform failed: {e}")
            passed = False
            continue
            
        # Check low band (20-40 Hz)
        low_band_4s = q_4s[:low_band_max_pixel, :]
        low_band_1s = q_1s[:low_band_max_pixel, :]
        
        if np.isnan(low_band_1s).any() or np.all(low_band_1s == 0):
            logger.warning(f"Segment {start} 1s Q-transform low-band contains NaNs or all zeros!")
            passed = False
        else:
            energy_4s = np.mean(low_band_4s)
            energy_1s = np.mean(low_band_1s)
            if energy_1s < 0.1 * energy_4s: # huge dropoff
                logger.warning(f"Segment {start} 1s Q-transform low-band energy dropped significantly! (1s: {energy_1s:.2e}, 4s: {energy_4s:.2e})")
                passed = False

    if passed:
        logger.info("Q-transform support test PASSED on [4, 64] range.")
    else:
        logger.info("Q-transform support test FAILED on [4, 64] range. Recommending [4, 32] or smaller.")
        
if __name__ == "__main__":
    run_qtransform_support_test(1386795008, num_segments=20)
