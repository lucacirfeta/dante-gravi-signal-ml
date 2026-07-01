import numpy as np
import pandas as pd
from pathlib import Path
from gwpy.timeseries import TimeSeries
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

# Constants
GPS_START = 1369128960
GPS_END = 1369133056  # 4096 seconds block
CHUNK_DURATION = 32
N_CHUNKS = (GPS_END - GPS_START) // CHUNK_DURATION
N_PAIRS = 1000
FFTLENGTH = 2.0
FREQ_BOUNDS = (20, 500)
THRESHOLD = 0.6
NDS_HOST = "nds.gwosc.org"

# We have 11 channels in production
L1_CHANNELS = [
    "L1:ASC-X_TR_A_NSUM_OUT_DQ",
    "L1:CAL-PCALX_RX_PD_OUT_DQ",
    "L1:CAL-PCALY_RX_PD_OUT_DQ",
    "L1:IMC-WFS_B_I_PIT_OUT_DQ",
    "L1:OAF-IMC_WFS_B_I_PIT_PREFILT_OUT_DQ",
    "L1:PEM-EX_VMON_ETMX_ESDPOWER24_DQ",
    "L1:PEM-EY_MAINSMON_EBAY_1_DQ",
    "L1:SUS-ETMX_L1_CAL_LINE_OUT_DQ",
    "L1:SUS-ETMX_L2_CAL_LINE_OUT_DQ",
    "L1:SUS-ETMX_L3_CAL_LINE_OUT_DQ",
    "L1:SUS-PI_PROC_COMPUTE_MODE5_RMSMON",
]

def run_significance_test():
    logger.info("=== EMPIRICAL FALSE POSITIVE RATE ESTIMATION ===")
    logger.info(f"Using {N_PAIRS} time-shifted pairs (32s chunks) from block {GPS_START}-{GPS_END}")
    logger.info(f"Protocol: fftlength={FFTLENGTH}s, band={FREQ_BOUNDS}Hz, threshold={THRESHOLD}")
    
    # 1. Load Strain Data
    logger.info("Fetching 4096s of L1 strain data from GWOSC...")
    try:
        strain = TimeSeries.fetch_open_data("L1", GPS_START, GPS_END)
    except Exception as e:
        logger.error(f"Failed to fetch strain: {e}")
        return

    # Split strain into 128 chunks
    strain_chunks = []
    for i in range(N_CHUNKS):
        t0 = GPS_START + i * CHUNK_DURATION
        strain_chunks.append(strain.crop(t0, t0 + CHUNK_DURATION))
        
    # 2. Fetch Aux Data & Compute Coherence
    channel_fpr = {}
    
    # Pre-generate 1000 random non-matching indices (i, j)
    # i = strain index, j = aux index
    np.random.seed(42)
    pairs = []
    while len(pairs) < N_PAIRS:
        i = np.random.randint(0, N_CHUNKS)
        j = np.random.randint(0, N_CHUNKS)
        if abs(i - j) > 5:  # Ensure they are separated by at least 5*32 = 160 seconds to break physical correlation
            pairs.append((i, j))
            
    for ch in L1_CHANNELS:
        logger.info(f"Processing channel: {ch}")
        try:
            time.sleep(1.0) # rate limit
            aux = TimeSeries.fetch(ch, start=GPS_START, end=GPS_END, host=NDS_HOST)
            if aux.sample_rate.value >= 40:
                aux = aux.highpass(20)
        except Exception as e:
            logger.error(f"Failed to fetch {ch}: {e}")
            channel_fpr[ch] = np.nan
            continue
            
        aux_chunks = []
        for i in range(N_CHUNKS):
            t0 = GPS_START + i * CHUNK_DURATION
            aux_chunks.append(aux.crop(t0, t0 + CHUNK_DURATION))
            
        hits = 0
        for pair_idx, (i, j) in enumerate(pairs):
            st = strain_chunks[i]
            au = aux_chunks[j]
            
            # Align sample rates
            if st.sample_rate != au.sample_rate:
                target_sr = min(st.sample_rate.value, au.sample_rate.value)
                if st.sample_rate.value > target_sr:
                    st_res = st.resample(target_sr)
                else:
                    st_res = st
                if au.sample_rate.value > target_sr:
                    au_res = au.resample(target_sr)
                else:
                    au_res = au
            else:
                st_res = st
                au_res = au
                
            coh = st_res.coherence(au_res, fftlength=FFTLENGTH, overlap=FFTLENGTH/2)
            freqs = coh.frequencies.value
            mask = (freqs >= FREQ_BOUNDS[0]) & (freqs <= FREQ_BOUNDS[1])
            coh_band = coh.value[mask]
            
            if len(coh_band) > 0:
                max_coh = float(np.max(coh_band))
                if max_coh >= THRESHOLD:
                    hits += 1
                    
            if (pair_idx + 1) % 250 == 0:
                logger.info(f"  ... {pair_idx + 1}/{N_PAIRS} pairs tested ({hits} hits so far)")
                
        fpr = hits / N_PAIRS
        channel_fpr[ch] = fpr
        logger.info(f"Channel {ch} FPR: {fpr:.4f} ({hits}/{N_PAIRS} hits)")
        
    # 3. Compute Theoretical FPR & Expected False Positives
    # P(C >= 0.6) for single freq = (1 - 0.6)^(F-1)
    # F = averages. For 32s with 2s FFT and 50% overlap, segments = (32 - 2) / 1 + 1 = 31. F = 31.
    F = 31
    p_single = (1 - THRESHOLD)**(F - 1)
    N_bins = (FREQ_BOUNDS[1] - FREQ_BOUNDS[0]) / (1.0 / FFTLENGTH) # 480 / 0.5 = 960
    p_theoretical_channel = 1 - (1 - p_single)**N_bins
    
    # Empirical cumulative
    valid_fprs = [fpr for fpr in channel_fpr.values() if not np.isnan(fpr)]
    if len(valid_fprs) == 0:
        logger.error("No valid FPRs computed.")
        return
        
    p_cumulative_empirical = 1.0
    for fpr in valid_fprs:
        p_cumulative_empirical *= (1 - fpr)
    p_cumulative_empirical = 1 - p_cumulative_empirical
    
    n_candidates = 388
    n_expected_false_positives = p_cumulative_empirical * n_candidates
    
    logger.info("==================================================")
    logger.info("=== EMPIRICAL RESULTS SUMMARY ===")
    for ch, fpr in channel_fpr.items():
        logger.info(f"{ch}: FPR = {fpr:.4f}")
    logger.info("--------------------------------------------------")
    logger.info(f"Theoretical F-statistic (F={F}, bins={N_bins}):")
    logger.info(f"  Per-channel expected FPR: {p_theoretical_channel:.2e}")
    logger.info("--------------------------------------------------")
    logger.info(f"Cumulative probability (at least 1 hit across {len(valid_fprs)} channels): {p_cumulative_empirical:.4f}")
    logger.info(f"Expected false-positive candidates (out of {n_candidates}): {n_expected_false_positives:.1f}")
    logger.info("==================================================")
    
    # Save to disk
    out_dir = Path("data/production/aggregated/pem")
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(list(channel_fpr.items()), columns=["Channel", "FPR"])
    df.to_csv(out_dir / "empirical_fpr_results.csv", index=False)
    
    with open(out_dir / "fpr_summary.txt", "w") as f:
        f.write(f"Cumulative probability: {p_cumulative_empirical:.4f}\n")
        f.write(f"Expected false positives (N={n_candidates}): {n_expected_false_positives:.1f}\n")
        f.write(f"Theoretical per-channel FPR: {p_theoretical_channel:.2e}\n")

if __name__ == "__main__":
    run_significance_test()
