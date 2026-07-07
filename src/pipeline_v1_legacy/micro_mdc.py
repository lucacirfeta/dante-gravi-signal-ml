import logging
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import scipy.stats as stats
from scipy.stats import genextreme
import hashlib
import os
import stat
import random
import torch
from tqdm import tqdm

from src.core.injection import SyntheticGlitchGenerator, InjectionEngine, _load_all_references
from src.core.preprocessor import whiten, bandpass, generate_qtransform
from src.pipeline_v1_legacy.novelty_detector import PatchLevelNoveltyDetector
from src.core.data_loader import fetch_strain_data
from src.core.utils import setup_logger, load_config

logger = setup_logger(__name__)

def run_micro_mdc(
    detector: PatchLevelNoveltyDetector,
    session_gps_start: int,
    session_gps_end: int,
    detector_name: str = 'L1',
    glitch_types: list[str] = ['AsymBlip', 'SpiralBurst'],
    amplitudes: np.ndarray = np.logspace(-22, -21, 8),
    n_injections: int = 20,
    k_values: list[int] = [15, 37, 68],
    seed: int = 42
) -> pd.DataFrame:
    """Executes the micro-MDC loop to evaluate the patch-level MIL novelty detector."""
    np.random.seed(seed)
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    
    EXPECTED_MD5 = "1080afa809964011e398c44fb24b73c6"
    
    index_path = "data/reference/patch_compressed_index.npz"
    if os.path.exists(index_path):
        with open(index_path, 'rb') as f:
            md5_hash = hashlib.md5(f.read()).hexdigest()
        logger.info(f"Reference Index MD5 Checksum: {md5_hash}")
        
        if md5_hash != EXPECTED_MD5:
            raise RuntimeError(f"Reference index non riproducibile o sovrascritto. Expected: {EXPECTED_MD5}, Got: {md5_hash}")
            
        # Forza in sola lettura per proteggere il reference index
        os.chmod(index_path, stat.S_IREAD)
        logger.info(f"Locked {index_path} to read-only mode.")
    else:
        logger.warning(f"Reference index {index_path} not found!")

    output_dir = Path("results/micro_mdc/final_run")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    spec_dir = output_dir / "temp_spectrograms"
    spec_dir.mkdir(parents=True, exist_ok=True)
    
    glitch_gen = SyntheticGlitchGenerator(sample_rate=4096)
    injector = InjectionEngine(sample_rate=4096)
    
    segment_length = 32
    available_starts = np.arange(session_gps_start, session_gps_end - segment_length, segment_length)
    
    results = []
    
    # Raccogli tutti i k univoci per calcolare le baseline una sola volta
    all_ks = set(k_values)
        
    baseline_cache = {}
    
    # --- Background Baseline Pass ---
    for k in sorted(list(all_ks)):
        logger.info(f"Extracting 500 NULL segments for baseline GEV fit (k={k})...")
        null_starts = np.random.choice(available_starts, size=min(500, len(available_starts)), replace=False)
        null_scores = []
        
        for seg_start in tqdm(null_starts, desc=f"Baseline pass k={k}"):
            seg_end = seg_start + segment_length
            try:
                ts_clean = fetch_strain_data(detector_name, seg_start, seg_end, cache_raw=True)
                ts_white = whiten(ts_clean)
                ts_bp = bandpass(ts_white)
                
                temp_path = spec_dir / f"null_{seg_start}.png"
                generate_qtransform(ts_bp, save_path=temp_path)
                
                res = detector.classify(temp_path, k=k, threshold=0.0) 
                null_scores.append(res['novelty_score'])
                
                if temp_path.exists():
                    temp_path.unlink()
            except Exception as e:
                logger.warning(f"Failed baseline segment {seg_start}: {e}")
                
        if not null_scores:
            raise RuntimeError(f"Failed to compute baseline scores for k={k}!")
            
        background_scores = np.array(null_scores)
        bg_mean = float(np.mean(background_scores))
        bg_std = float(np.std(background_scores))
        dynamic_threshold = float(np.percentile(background_scores, 99.0))
        
        logger.info(f"[RUN CONFIG] reference MD5: {EXPECTED_MD5}")
        logger.info(f"[RUN CONFIG] background n_samples: {len(background_scores)}")
        logger.info(f"[RUN CONFIG] threshold method: percentile_99")
        logger.info(f"[RUN CONFIG] dynamic_threshold: {dynamic_threshold:.6f}")
        logger.info(f"[RUN CONFIG] background_score mean: {bg_mean:.6f}")
        logger.info(f"[RUN CONFIG] background_score std: {bg_std:.6f}")
        logger.info(f"[RUN CONFIG] background_score p99: {dynamic_threshold:.6f}")
        
        baseline_cache[k] = {
            'null_scores': null_scores,
            'dynamic_threshold': dynamic_threshold,
            'bg_mean': bg_mean,
            'bg_p99': dynamic_threshold
        }
        
    # --- Injection Pass ---
    for gtype in glitch_types:
        current_ks = k_values
        for idx, amp in enumerate(amplitudes):
            current_n_inj = n_injections
            logger.info(f"Injecting {gtype} at amp={amp:.2e} (n={current_n_inj})")
            
            inj_starts = np.random.choice(available_starts, size=current_n_inj, replace=False)
            
            for seg_start in tqdm(inj_starts, desc=f"Injections {gtype} amp={amp:.1e}"):
                seg_end = seg_start + segment_length
                t_inject = seg_start + segment_length / 2.0
                
                try:
                    ts_clean = fetch_strain_data(detector_name, seg_start, seg_end, cache_raw=True)
                    glitch = glitch_gen.generate(gtype, amp, duration=1.0)
                    ts_injected = injector.inject(ts_clean, glitch, t_inject)
                    snr = injector.compute_snr(ts_clean, glitch)
                    
                    ts_white = whiten(ts_injected)
                    ts_bp = bandpass(ts_white)
                    temp_path = spec_dir / f"inj_{gtype}_{seg_start}.png"
                    generate_qtransform(ts_bp, save_path=temp_path)
                    
                    # Esegui il calcolo contemporaneamente per tutti i K della classe per abbattere i tempi I/O
                    for k in current_ks:
                        dyn_thresh = baseline_cache[k]['dynamic_threshold']
                        res = detector.classify(temp_path, k=k, threshold=dyn_thresh)
                        
                        patch_scores = np.array(res["patch_anomaly_scores"])
                        n_novel_patches = int(np.sum(patch_scores > dyn_thresh))
                        
                        results.append({
                            "glitch_type": gtype,
                            "amplitude": amp,
                            "snr": snr,
                            "k": k,
                            "novelty_score": res["novelty_score"],
                            "novelty_status": res["novelty_status"],
                            "dynamic_threshold": dyn_thresh,
                            "n_novel_patches": n_novel_patches,
                            "background_mean": baseline_cache[k]['bg_mean'],
                            "background_p99": baseline_cache[k]['bg_p99'],
                            "seed": seed
                        })
                        
                    if temp_path.exists():
                        temp_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed injection {gtype} at {seg_start}: {e}")

    df = pd.DataFrame(results)
    
    # 3. Integrazione Test KS (Kolmogorov-Smirnov)
    df["ks_statistic"] = np.nan
    df["ks_pvalue"] = np.nan
    
    # Raggruppa i risultati per calcolare il KS test cella per cella
    for (k, gtype, amp), group in df.groupby(["k", "glitch_type", "amplitude"]):
        bg_scores = baseline_cache[k]['null_scores']
        inj_scores = group["novelty_score"].values
        if len(inj_scores) > 0 and len(bg_scores) > 0:
            ks_res = stats.ks_2samp(bg_scores, inj_scores, alternative='greater')
            df.loc[group.index, "ks_statistic"] = ks_res.statistic
            df.loc[group.index, "ks_pvalue"] = ks_res.pvalue
            
    df.to_csv(output_dir / "micro_mdc_final_results.csv", index=False)
    
    # Calcola il summary esteso con i risultati KS
    summary = df.groupby(["k", "glitch_type", "amplitude"]).apply(
        lambda x: pd.Series({
            "snr_mean": x["snr"].mean(),
            "recall": (x["novelty_status"] == "NOVEL").mean(),
            "n_novel": (x["novelty_status"] == "NOVEL").sum(),
            "n_total": len(x),
            "ks_statistic": x["ks_statistic"].iloc[0] if not x.empty else np.nan,
            "ks_pvalue": x["ks_pvalue"].iloc[0] if not x.empty else np.nan
        })
    ).reset_index()
    summary.to_csv(output_dir / "micro_mdc_final_summary.csv", index=False)
    
    logger.info("Micro-MDC completed. Results saved to results/micro_mdc/final_run/")
    return df

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run Micro-MDC for Patch-Level Scoring")
    parser.add_argument("--start", type=int, default=1386795008, help="GPS Start Time (Default: 20260524 L1 start)")
    parser.add_argument("--end", type=int, default=1388003328, help="GPS End Time (Default: 20260524 L1 end)")
    args = parser.parse_args()
    
    cfg = load_config()
    mdc_cfg = cfg.get("micro_mdc", {})
    patch_cfg = cfg.get("patch_novelty", {})
    
    # FINAL RUN PARAMETERS
    glitch_types = ["Blip", "ScatteredLight", "AsymBlip", "SpiralBurst", "HarmonicComb"]
    n_injections = 100
    n_amplitudes = 8
    amp_min = 1e-22
    amp_max = 1e-21
    amplitudes = np.logspace(np.log10(amp_min), np.log10(amp_max), n_amplitudes)
    detector_name = "L1"
    seed = 42
    
    # Mappa K specifica per glitch (solo K=100 per l'MDC del paper)
    k_values = [100]
    device = patch_cfg.get("device", "cuda")
    
    # Initialize the patch-level novelty detector
    detector = PatchLevelNoveltyDetector(
        index_path="data/reference/patch_compressed_index.npz",
        device=device
    )
    
    # Execute the Micro-MDC
    run_micro_mdc(
        detector=detector,
        session_gps_start=args.start,
        session_gps_end=args.end,
        detector_name=detector_name,
        glitch_types=glitch_types,
        amplitudes=amplitudes,
        n_injections=n_injections,
        k_values=k_values,
        seed=seed
    )
