"""Synthetic glitch generation and injection engine for MDC."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.interpolate import interp1d
from gwpy.timeseries import TimeSeries
import pandas as pd
from tqdm import tqdm

from src.core.utils import setup_logger, load_config
from src.core.preprocessor import whiten, bandpass, generate_qtransform
from src.core.encoder import DINOv2Encoder
from src.pipeline_v1_legacy.similarity_checker import cosine_knn_search, assess_novelty, assess_novelty_dynamic, compute_baseline_stats
from src.core.utils import discover_references

logger = setup_logger(__name__)

class SyntheticGlitchGenerator:
    """Generates synthetic time-domain glitches for Mock Data Challenge."""

    def __init__(self, sample_rate: int = 4096):
        self.sample_rate = sample_rate

    def generate(
        self,
        glitch_type: str,
        amplitude: float,
        duration: float = 1.0,
        f_low: float = 20.0,
        f_high: float = 1000.0,
    ) -> np.ndarray:
        """Generate a synthetic glitch."""
        if not (0.5 <= duration <= 2.0):
            logger.warning(f"Duration {duration} outside recommended 0.5s - 2.0s range.")
            
        t = np.linspace(0, duration, int(self.sample_rate * duration), endpoint=False)
        
        if glitch_type == "ZSweep":
            sig = self._generate_zsweep(t, f_low, f_high)
        elif glitch_type == "SpiralBurst":
            sig = self._generate_spiral_burst(t, f_low, f_high)
        elif glitch_type == "StepLadder":
            sig = self._generate_step_ladder(t, f_low, f_high)
        elif glitch_type == "Butterfly":
            sig = self._generate_butterfly(t, f_low, f_high)
        elif glitch_type == "NoiseBlob":
            sig = self._generate_noise_blob(t)
        elif glitch_type == "NarrowChirp":
            sig = self._generate_narrow_chirp(t)
        elif glitch_type == "HarmonicComb":
            sig = self._generate_harmonic_comb(t)
        elif glitch_type == "AsymBlip":
            sig = self._generate_asym_blip(t)
        elif glitch_type == "Blip":
            sig = self._generate_blip(t)
        elif glitch_type == "ScatteredLight":
            sig = self._generate_scattered_light(t)
        else:
            raise ValueError(f"Unknown glitch_type: {glitch_type}")
            
        # Normalize to maximum amplitude 1, then scale by requested amplitude
        if np.max(np.abs(sig)) > 0:
            sig = (sig / np.max(np.abs(sig))) * amplitude
            
        return sig

    def _generate_zsweep(self, t: np.ndarray, f_low: float, f_high: float) -> np.ndarray:
        """Chirp concatenated f1->f2, f2->f1, f1->f2."""
        duration = t[-1]
        t_seg = duration / 3.0
        
        mask1 = (t < t_seg)
        mask2 = (t >= t_seg) & (t < 2 * t_seg)
        mask3 = (t >= 2 * t_seg)
        
        # We need continuous phase.
        # chirp function from scipy can do segment by segment if we track phase,
        # but simpler is to use a custom frequency profile and integrate.
        
        f = np.zeros_like(t)
        f[mask1] = np.linspace(f_low, f_high, mask1.sum())
        f[mask2] = np.linspace(f_high, f_low, mask2.sum())
        f[mask3] = np.linspace(f_low, f_high, mask3.sum())
        
        phase = 2 * np.pi * np.cumsum(f) / self.sample_rate
        sig = np.sin(phase)
        
        # Tukey window to prevent edge artifacts
        window = signal.windows.tukey(len(sig), alpha=0.1)
        return sig * window

    def _generate_spiral_burst(self, t: np.ndarray, f_low: float, f_high: float) -> np.ndarray:
        """Logarithmic chirp with gaussian envelope."""
        # Log chirp
        duration = t[-1]
        f = np.geomspace(f_low, f_high, len(t))
        phase = 2 * np.pi * np.cumsum(f) / self.sample_rate
        sig = np.sin(phase)
        
        # Gaussian envelope centered at duration/2
        t_center = duration / 2
        sigma = duration / 6
        envelope = np.exp(-0.5 * ((t - t_center) / sigma) ** 2)
        
        return sig * envelope

    def _generate_step_ladder(self, t: np.ndarray, f_low: float, f_high: float, steps: int = 5) -> np.ndarray:
        """N steps in frequency."""
        duration = t[-1]
        step_duration = duration / steps
        f_steps = np.geomspace(f_low, f_high, steps)
        
        f = np.zeros_like(t)
        for i in range(steps):
            mask = (t >= i * step_duration) & (t < (i + 1) * step_duration)
            f[mask] = f_steps[i]
            
        phase = 2 * np.pi * np.cumsum(f) / self.sample_rate
        sig = np.sin(phase)
        
        window = signal.windows.tukey(len(sig), alpha=0.2)
        return sig * window

    def _generate_butterfly(self, t: np.ndarray, f_low: float, f_high: float) -> np.ndarray:
        """Two ZSweep mirrored and superposed."""
        z1 = self._generate_zsweep(t, f_low, f_high)
        # Mirror is f_high->f_low, f_low->f_high, f_high->f_low
        duration = t[-1]
        t_seg = duration / 3.0
        
        mask1 = (t < t_seg)
        mask2 = (t >= t_seg) & (t < 2 * t_seg)
        mask3 = (t >= 2 * t_seg)
        
        f = np.zeros_like(t)
        f[mask1] = np.linspace(f_high, f_low, mask1.sum())
        f[mask2] = np.linspace(f_low, f_high, mask2.sum())
        f[mask3] = np.linspace(f_high, f_low, mask3.sum())
        
        phase = 2 * np.pi * np.cumsum(f) / self.sample_rate
        z2 = np.sin(phase)
        
        window = signal.windows.tukey(len(z2), alpha=0.1)
        z2 = z2 * window
        
        return z1 + z2

    def _generate_noise_blob(self, t: np.ndarray, alpha: float = 1.0) -> np.ndarray:
        """Colored noise (power-law PSD) with Tukey window."""
        n = len(t)
        white_noise = np.random.randn(n)
        
        # FFT, scale by f^(-alpha/2), IFFT
        freqs = np.fft.rfftfreq(n, d=1.0/self.sample_rate)
        fft_noise = np.fft.rfft(white_noise)
        
        # Avoid division by zero at freq=0
        freqs[0] = freqs[1]
        scaling = freqs ** (-alpha / 2.0)
        
        fft_noise = fft_noise * scaling
        colored_noise = np.fft.irfft(fft_noise, n=n)
        
        window = signal.windows.tukey(n, alpha=0.5)
        return colored_noise * window

    def _generate_narrow_chirp(self, t: np.ndarray) -> np.ndarray:
        """Narrow-band chirp: 150→300 Hz in 0.5s (simulates scattered light velocity).

        Physically motivated: a scattering arm length change drives a frequency-velocity
        coupling that sweeps a narrowband feature across this range at optical frequencies.
        The short sweep duration (0.5s) makes it visible even in 32s windows at high SNR.
        """
        duration = t[-1]
        f_start, f_end = 150.0, 300.0
        # Only chirp for 0.5s, centered in the duration
        t_center = duration / 2.0
        t_chirp_start = t_center - 0.25
        t_chirp_end   = t_center + 0.25

        f = np.where(
            (t >= t_chirp_start) & (t <= t_chirp_end),
            np.interp(t, [t_chirp_start, t_chirp_end], [f_start, f_end]),
            0.0,
        )
        phase = 2 * np.pi * np.cumsum(f) / self.sample_rate
        sig = np.sin(phase) * (f > 0)

        # Smooth onset/offset
        window = signal.windows.tukey(len(sig), alpha=0.3)
        return sig * window

    def _generate_harmonic_comb(self, t: np.ndarray, f0: float = 100.0, n_harmonics: int = 7) -> np.ndarray:
        """Harmonic comb at f0, 2f0, ..., n_harmonics*f0 (simulates violin mode coupling).

        Physically motivated: a mirror suspension violin mode at 100 Hz creates a ladder
        of coupled harmonics across the detector band, visible in the Q-transform as a
        multi-line comb pattern persistent over the full 32s window.
        """
        sig = np.zeros_like(t)
        for k in range(1, n_harmonics + 1):
            fk = k * f0
            if fk < self.sample_rate / 2.0:
                # Slight random phase per harmonic for realism
                phi = np.random.uniform(0, 2 * np.pi)
                # Amplitude falls off with harmonic number
                ak = 1.0 / k
                sig += ak * np.sin(2 * np.pi * fk * t + phi)

        window = signal.windows.tukey(len(sig), alpha=0.05)
        return sig * window

    def _generate_asym_blip(self, t: np.ndarray) -> np.ndarray:
        """Asymmetric blip: fast rise (10 ms) slow decay (300 ms), broadband (simulates impulsive noise).

        Physically motivated: mechanical impulsive noise (e.g., scattered-light scattering off
        a fast-moving optic) generates broadband transients with sub-millisecond onset and
        a decaying ring-down determined by the Q-factor of the mechanical resonance.
        """
        duration = t[-1]
        t_peak = duration / 2.0
        tau_rise = 0.010   # 10 ms
        tau_decay = 0.300  # 300 ms

        envelope = np.where(
            t <= t_peak,
            np.exp(-((t - t_peak) ** 2) / (2 * tau_rise ** 2)),
            np.exp(-(t - t_peak) / tau_decay),
        )

        # Broadband carrier: white noise under the envelope
        carrier = np.random.randn(len(t))
        sig = carrier * envelope

        return sig

    def _generate_blip(self, t: np.ndarray) -> np.ndarray:
        """Pure Blip: symmetric Gaussian envelope, extremely short duration (10-50 ms)."""
        duration = t[-1]
        t_peak = duration / 2.0
        sigma = 0.015  # 15 ms std dev -> ~40 ms effective width
        
        envelope = np.exp(-0.5 * ((t - t_peak) / sigma) ** 2)
        
        # Broadband carrier: white noise bandpassed to typical blip frequencies (100-300 Hz)
        carrier = np.random.randn(len(t))
        freqs = np.fft.rfftfreq(len(carrier), d=1.0/self.sample_rate)
        fft_carrier = np.fft.rfft(carrier)
        mask = (freqs >= 100) & (freqs <= 300)
        fft_carrier[~mask] = 0
        carrier = np.fft.irfft(fft_carrier, n=len(carrier))
        
        return carrier * envelope

    def _generate_scattered_light(self, t: np.ndarray) -> np.ndarray:
        """Scattered Light Arch: Parabolic frequency sweep over 1-2 seconds."""
        duration = t[-1]
        t_peak = duration / 2.0
        
        f_max = 60.0
        f_min = 10.0
        arch_duration = 1.5
        
        a = (f_max - f_min) / (arch_duration / 2.0)**2
        
        f = f_max - a * (t - t_peak)**2
        f[f < f_min] = 0
        
        phase = 2 * np.pi * np.cumsum(f) / self.sample_rate
        sig = np.sin(phase) * (f > f_min)
        
        window = signal.windows.tukey(len(sig), alpha=0.1)
        return sig * window


class InjectionEngine:
    def __init__(self, sample_rate: int = 4096):
        self.sample_rate = sample_rate

    def inject(self, strain_timeseries: TimeSeries, glitch_signal: np.ndarray, t_inject: float) -> TimeSeries:
        """Inject synthetic glitch into real strain data at specified GPS time.
        
        Args:
            strain_timeseries: Background strain data
            glitch_signal: Synthetic glitch array
            t_inject: GPS time at which the glitch center should be placed
        """
        # Create a copy
        injected = strain_timeseries.copy()
        
        # Find index for t_inject
        t0 = float(injected.t0.value)
        dt = float(injected.dt.value)
        
        if t_inject < t0 or t_inject > t0 + injected.duration.value:
            logger.warning(f"t_inject {t_inject} is outside the time series window [{t0}, {t0 + injected.duration.value}]")
            return injected
            
        idx_center = int((t_inject - t0) / dt)
        
        glitch_len = len(glitch_signal)
        half_len = glitch_len // 2
        
        start_idx = idx_center - half_len
        end_idx = start_idx + glitch_len
        
        # Handle boundaries
        g_start = 0
        g_end = glitch_len
        
        if start_idx < 0:
            g_start = -start_idx
            start_idx = 0
        if end_idx > len(injected):
            g_end = glitch_len - (end_idx - len(injected))
            end_idx = len(injected)
            
        if start_idx < end_idx:
            # Modify the underlying numpy array
            injected.value[start_idx:end_idx] += glitch_signal[g_start:g_end]
            
        return injected

    def compute_snr(
        self, 
        strain_clean: TimeSeries, 
        glitch_signal: np.ndarray, 
        psd=None, 
        f_low: float = 20.0, 
        f_high: float = 2000.0
    ) -> float:
        """Compute matched-filter SNR of the injected signal.
        
        rho = sqrt(4 * integral_{f_low}^{f_high} |h(f)|^2/S(f) df)
        """
        if psd is None:
            # Calculate PSD from clean strain
            psd = strain_clean.psd(fftlength=min(4, float(strain_clean.duration.value)))
            
        # Ensure we have appropriate frequency resolution
        delta_f = float(psd.df.value)
        
        # Compute FFT of the glitch signal
        n = len(glitch_signal)
        h_f = np.fft.rfft(glitch_signal) / self.sample_rate
        freqs = np.fft.rfftfreq(n, d=1.0/self.sample_rate)
        
        # Interpolate PSD to match FFT frequencies
        psd_freqs = psd.frequencies.value
        psd_vals = psd.value
        
        # Create interpolation function for PSD
        # Use log-log interpolation for better behavior
        valid_psd = psd_vals > 0
        if np.any(valid_psd):
            interp_func = interp1d(
                psd_freqs[valid_psd], 
                np.log(psd_vals[valid_psd]), 
                kind='linear', 
                bounds_error=False, 
                fill_value="extrapolate"
            )
            S_f = np.exp(interp_func(freqs))
        else:
            S_f = np.ones_like(freqs) * 1e-46 # Fallback
            
        # Calculate integrand: |h(f)|^2 / S(f)
        integrand = np.abs(h_f)**2 / S_f
        
        # Apply frequency mask
        mask = (freqs >= f_low) & (freqs <= f_high)
        
        # Integrate
        # df for the FFT is freqs[1] - freqs[0]
        df_fft = freqs[1] - freqs[0]
        integral = np.sum(integrand[mask]) * df_fft
        
        rho_sq = 4 * integral
        if rho_sq > 0:
            return np.sqrt(rho_sq)
        return 0.0

def _load_all_references() -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Load and merge all reference indices from data/reference."""
    from src.pipeline_v1_legacy.reference_builder import load_reference_index
    
    reference_files = discover_references(Path("data/reference"))
    if not reference_files:
        raise RuntimeError("No reference files found in data/reference/")
        
    all_emb = []
    all_labels = []
    
    for ref_file in reference_files:
        try:
            emb, lbl = load_reference_index(ref_file)
            all_emb.append(emb)
            all_labels.append(lbl)
            logger.info(f"Loaded reference {ref_file.name} with {len(lbl)} entries")
        except Exception as e:
            logger.warning(f"Could not load reference {ref_file}: {e}")
            
    if not all_emb:
        raise RuntimeError("Failed to load any valid reference files")
        
    merged_emb = np.vstack(all_emb)
    merged_labels = np.concatenate(all_labels)
    
    return merged_emb, merged_labels, [p.name for p in reference_files]


def run_mdc(
    session_gps_start: int,
    session_gps_end: int,
    detector: str,
    glitch_types: list[str],
    n_injections_per_type: int = 50,
    amplitude_grid: np.ndarray = None,
    output_dir: Path = Path("results/mdc"),
    seed: int = 42,
    novelty_threshold_override: float | None = None,
    use_dynamic_override: bool | None = None,
) -> pd.DataFrame:
    """Run the Mock Data Challenge.

    The pipeline performs two passes over the data:

    1. **NULL pass**: Injects no signal into randomly selected 32s strain
       segments and records the top-1 cosine similarity against the
       in-domain reference index.  These similarities define the
       *session-local noise floor* of the DINOv2 embedding space.

    2. **Injection pass**: Injects synthetic glitches, whitens the strain,
       crops the spectrogram, and evaluates novelty using the
       *dynamic threshold* derived from the null baseline::

           novelty_score = baseline_mean - max_similarity
           NOVEL if novelty_score > k_sigma * baseline_std

    This replaces the static global threshold (0.85) which was always
    exceeded by the noise floor (~0.94 on L1 O4a), causing Recall=0.00
    for all synthetic glitch types.
    """
    np.random.seed(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize components
    glitch_gen = SyntheticGlitchGenerator(sample_rate=4096)
    injector = InjectionEngine(sample_rate=4096)
    encoder = DINOv2Encoder()
    
    # Load references
    ref_emb, ref_labels, ref_sources = _load_all_references()
    logger.info(f"Loaded {len(ref_labels)} reference samples from {len(ref_sources)} files")
    
    cfg = load_config()
    sim_cfg = cfg.get("similarity", {})
    dyn_cfg = sim_cfg.get("dynamic_threshold", {})
    use_dynamic = dyn_cfg.get("enabled", True)
    k_sigma = float(dyn_cfg.get("k_sigma", 2.5))
    cons_thresh = sim_cfg.get("consensus_threshold", 0.6)
    nov_thresh = sim_cfg.get("novelty_threshold", 0.85)  # legacy fallback

    # Allow caller to override threshold and dynamic mode directly
    if novelty_threshold_override is not None:
        nov_thresh = novelty_threshold_override
        logger.info(f"novelty_threshold overridden by caller: {nov_thresh}")
    if use_dynamic_override is not None:
        use_dynamic = use_dynamic_override
        logger.info(f"use_dynamic overridden by caller: {use_dynamic}")

    # Empirical fallback baseline (measured L1 O4a, 2026-06-04)
    det_upper = detector.upper()
    empirical_mean = dyn_cfg.get(f"empirical_mean_{det_upper.lower()}") or 0.940
    empirical_std = dyn_cfg.get(f"empirical_std_{det_upper.lower()}") or 0.021
    fallback_baseline = {"mean": empirical_mean, "std": empirical_std, "n_samples": 0}
    
    # Segment selection (32s segments)
    segment_length = 32
    available_starts = np.arange(session_gps_start, session_gps_end - segment_length, segment_length)
    
    total_injections = len(glitch_types) * len(amplitude_grid) * n_injections_per_type + 10 # 10 nulls
    if len(available_starts) < total_injections:
        logger.warning(f"Not enough segments ({len(available_starts)}) for {total_injections} injections. Reusing segments.")
        # We will sample with replacement if necessary
        
    results = []
    
    # Create spectrograms dir
    spec_dir = output_dir / "injected_spectrograms"
    spec_dir.mkdir(exist_ok=True)
    
    from src.core.data_loader import fetch_strain_data
    
    # Define execution sequence
    tasks = []
    
    # Add NULL injections
    n_null_injections = min(n_injections_per_type * 4, 1000) # scale NULLs based on run size
    if n_null_injections < 20: n_null_injections = 20
    for i in range(n_null_injections):
        tasks.append(("NULL", 0.0, i))
        
    # Add actual injections
    for gtype in glitch_types:
        for amp in amplitude_grid:
            for i in range(n_injections_per_type):
                tasks.append((gtype, amp, i))
                
    # Shuffle to distribute types/amplitudes over time
    np.random.shuffle(tasks)
    
    # Keep track of saved spectrograms per type
    saved_specs = {gt: 0 for gt in glitch_types + ["NULL"]}
    
    # Accumulate null similarities for baseline estimation
    null_similarities: list[float] = []
    baseline_stats: dict | None = None
    min_null = int(dyn_cfg.get("min_null_samples", 20))
    
    # Process tasks
    pbar = tqdm(tasks, desc="Running MDC Injections")
    
    for i, (gtype, amp, idx) in enumerate(pbar):
        # Choose a random segment
        seg_start = np.random.choice(available_starts)
        seg_end = seg_start + segment_length
        
        try:
            # Fetch strain
            ts_clean = fetch_strain_data(detector, seg_start, seg_end, cache_raw=True)
            
            # Injection point (center of the 32s segment)
            t_inject = seg_start + segment_length / 2.0
            
            if gtype == "NULL":
                ts_injected = ts_clean
                snr = 0.0
            else:
                glitch = glitch_gen.generate(gtype, amp, duration=1.0)
                ts_injected = injector.inject(ts_clean, glitch, t_inject)
                snr = injector.compute_snr(ts_clean, glitch)
                
            # Process segment
            ts_white = whiten(ts_injected)
            ts_bp = bandpass(ts_white)
            
            # Use the full 32s segment — this matches the operational pipeline
            # (batch_process in full_analysis.py generates Q-transforms on full 32s chunks).
            # A 4s crop was previously used here, but created an inconsistency: MDC
            # sensitivity measured at 4s ≠ sensitivity of the operational O4a analysis.
            ts_crop = ts_bp.crop(seg_start, seg_end)

            save_spec_path = None
            if saved_specs[gtype] < 5:
                # Save 5 spectrograms per type
                save_spec_path = spec_dir / f"{gtype}_amp{amp:.1e}_{idx}.png"
                saved_specs[gtype] += 1
                
            spec = generate_qtransform(ts_crop, save_path=save_spec_path)
            
            # If we didn't save it, we still need to process it through DINOv2
            # DINOv2Encoder expects a file path, or we can adapt to use array
            # We must save a temp file if save_spec_path is None
            temp_path = None
            if save_spec_path is None:
                temp_path = spec_dir / "temp.png"
                generate_qtransform(ts_crop, save_path=temp_path)
                target_path = temp_path
            else:
                target_path = save_spec_path
                
            # Embed
            emb = encoder.extract(target_path)
            
            # Cleanup temp
            if temp_path and temp_path.exists():
                temp_path.unlink()
                
            # Morphological check
            emb_batch = np.array([emb])
            knn_res = cosine_knn_search(emb_batch, ref_emb, ref_labels, k=5)[0]
            
            # Collect null similarities to build session-local baseline
            if gtype == "NULL":
                null_similarities.append(knn_res["top_similarity"])
                # Recompute baseline stats as nulls accumulate
                if len(null_similarities) >= min_null:
                    baseline_stats = compute_baseline_stats(null_similarities)
                    logger.debug(
                        "Baseline updated: mean=%.4f std=%.4f (n=%d)",
                        baseline_stats["mean"], baseline_stats["std"], baseline_stats["n_samples"],
                    )
            
            # Enrich with novelty — dynamic if baseline is ready, else static fallback
            if use_dynamic and gtype != "NULL":
                active_baseline = baseline_stats if baseline_stats is not None else fallback_baseline
                if baseline_stats is None:
                    logger.warning(
                        "Dynamic baseline not yet established (only %d NULL segments so far, "
                        "need %d). Using empirical fallback baseline for %s.",
                        len(null_similarities), min_null, gtype,
                    )
                enriched = assess_novelty_dynamic(
                    [knn_res],
                    baseline_stats=active_baseline,
                    k_sigma=k_sigma,
                    consensus_threshold=cons_thresh,
                )[0]
            else:
                enriched = assess_novelty([knn_res], novelty_threshold=nov_thresh, consensus_threshold=cons_thresh)[0]
            
            status = enriched["novelty_status"]
            top_sim = enriched["top_similarity"]
            top_label = enriched["top_label"]
            
            results.append({
                "glitch_type": gtype,
                "amplitude": amp,
                "snr": snr,
                "novelty_status": status,
                "top_label": top_label,
                "top_similarity": top_sim,
                "gps_time": t_inject
            })
            
            pbar.set_postfix({"gtype": gtype, "snr": f"{snr:.1f}", "status": status})
            
        except Exception as e:
            logger.warning(f"Failed injection {gtype} at {seg_start}: {e}")
            continue
            
    # Finalise baseline stats — use live if enough nulls, else empirical fallback
    import json as _json
    if baseline_stats is None:
        baseline_stats = fallback_baseline
        logger.warning("Not enough NULL segments (%d) to establish live baseline. Used empirical fallback.", len(null_similarities))
    else:
        # Update with full null set
        baseline_stats = compute_baseline_stats(null_similarities)
    
    logger.info(
        "Session baseline: mean=%.4f std=%.4f n=%d  →  dynamic threshold (k=%.1f): %.4f",
        baseline_stats["mean"], baseline_stats["std"], baseline_stats["n_samples"],
        k_sigma, baseline_stats["mean"] - k_sigma * baseline_stats["std"],
    )
    baseline_stats["detector"] = detector
    baseline_stats["k_sigma"] = k_sigma
    baseline_stats["dynamic_threshold"] = baseline_stats["mean"] - k_sigma * baseline_stats["std"]
    baseline_path = output_dir / "mdc_baseline_stats.json"
    with open(baseline_path, "w", encoding="utf-8") as _f:
        _json.dump(baseline_stats, _f, indent=2)
    logger.info("Saved session baseline → %s", baseline_path)
    
    # Aggregate results
    df = pd.DataFrame(results)
    df.to_csv(output_dir / "mdc_raw_results.csv", index=False)
    
    # Calculate summary metrics
    summary = []
    
    for gtype in df["glitch_type"].unique():
        if gtype == "NULL":
            subset = df[df["glitch_type"] == "NULL"]
            n_tot = len(subset)
            n_nov = sum(subset["novelty_status"] == "NOVEL")
            n_kno = sum(subset["novelty_status"] == "KNOWN")
            n_amb = sum(subset["novelty_status"] == "AMBIGUOUS")
            recall = n_nov / n_tot if n_tot > 0 else 0
            
            summary.append({
                "glitch_type": "NULL",
                "amplitude": 0.0,
                "snr_mean": 0.0,
                "snr_std": 0.0,
                "recall": recall,
                "n_novel": n_nov,
                "n_known": n_kno,
                "n_ambiguous": n_amb,
                "n_total": n_tot
            })
            continue
            
        for amp in amplitude_grid:
            subset = df[(df["glitch_type"] == gtype) & (np.isclose(df["amplitude"], amp, atol=1e-30, rtol=1e-5))]
            if len(subset) == 0:
                continue
                
            snr_mean = subset["snr"].mean()
            snr_std = subset["snr"].std()
            n_tot = len(subset)
            n_nov = sum(subset["novelty_status"] == "NOVEL")
            n_kno = sum(subset["novelty_status"] == "KNOWN")
            n_amb = sum(subset["novelty_status"] == "AMBIGUOUS")
            recall = n_nov / n_tot if n_tot > 0 else 0
            
            summary.append({
                "glitch_type": gtype,
                "amplitude": amp,
                "snr_mean": snr_mean,
                "snr_std": snr_std,
                "recall": recall,
                "n_novel": n_nov,
                "n_known": n_kno,
                "n_ambiguous": n_amb,
                "n_total": n_tot
            })
            
    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(output_dir / "mdc_results.csv", index=False)
    
    return summary_df
