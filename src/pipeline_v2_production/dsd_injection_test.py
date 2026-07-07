"""Controlled Recovery Test for Domain Shift Defense Falsifiability.

This module implements the empirical experiment requested by peer reviewers
to demonstrate that the Domain Shift Defense (DSD) is SELECTIVE — it absorbs
only pervasive stationary features (like Family_01's 'wall of lines') but
does NOT absorb sparse, discrete transient signals.

The experiment injects known synthetic morphologies into real O4a strain
data at controlled SNR, scores them against the NATIVE O4a background index,
and measures the Recovery Rate (fraction surviving tau_op).

Expected outcome:
  - HarmonicComb (sparse, n=100):   Recovery Rate >> 0%  (positive control)
  - WallOfLines  (sparse, n=100):   Recovery Rate >> 0%  (key test)
  - ScatteredLight (sparse, n=100): Recovery Rate > 0%   (intermediate)

If all Recovery Rates >> 0%, the DSD is proven selective.
If any known signal is absorbed, the DSD exhibits circularity.

Author: Luca Cirfeta
Date: 2026-06-20
"""

from __future__ import annotations

import gc
import hashlib
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import torch
from tqdm import tqdm

from src.core.data_loader import fetch_local_or_remote_strain, _DATA_DIRECTORIES
from src.core.patch_scorer import PatchScorer
from src.core.preprocessor import generate_qtransform, whiten_context, extract_clean_subwindow
from src.core.injection import InjectionEngine, SyntheticGlitchGenerator

logger = setup_logger(__name__)

# =====================================================================
# Constants
# =====================================================================
NATIVE_INDEX_PATH = Path("data/reference/patch_compressed_index_o4a_ex.npz")
O3B_INDEX_PATH = Path("data/reference/patch_compressed_index.npz")
OUTPUT_DIR = Path("results/dsd_controlled_recovery_test")
SEGMENT_LENGTH = 32
SAMPLE_RATE = 4096
K_PRODUCTION = 68  # Production top-k value
SEED = 42


class DSDControlledRecoveryTest:
    """Controlled Recovery Test for Domain Shift Defense falsifiability.

    Tests whether the native O4a index absorbs discrete synthetic signals
    (it should NOT) or only pervasive stationary noise (it SHOULD).
    """

    def __init__(
        self,
        native_index_path: Path = NATIVE_INDEX_PATH,
        o3b_index_path: Path = O3B_INDEX_PATH,
        detector: str = "L1",
        n_injections: int = 100,
        n_background: int = 200,
        seed: int = SEED,
    ):
        self.detector = detector
        self.n_injections = n_injections
        self.n_background = n_background
        self.seed = seed

        # Fix all seeds for reproducibility
        np.random.seed(seed)
        random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

        # Output directory
        self.output_dir = OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize synthetic generation
        self.glitch_gen = SyntheticGlitchGenerator(sample_rate=SAMPLE_RATE)
        self.injector = InjectionEngine(sample_rate=SAMPLE_RATE)

        # Load NATIVE O4a scorer (the one under test)
        if not native_index_path.exists():
            raise FileNotFoundError(
                f"Native O4a index not found at {native_index_path}. "
                "Run the index builder first."
            )

        logger.info("Loading native O4a PatchScorer...")
        self.native_scorer = PatchScorer(
            reference_index_path=str(native_index_path),
            verify_md5=False,
            k=K_PRODUCTION,
        )

        # Log index MD5
        with open(native_index_path, "rb") as f:
            self.native_index_md5 = hashlib.md5(f.read()).hexdigest()
        logger.info(f"Native O4a index MD5: {self.native_index_md5}")

        # Optionally load O3b scorer for comparison
        self.o3b_scorer = None
        if o3b_index_path.exists():
            logger.info("Loading O3b PatchScorer for comparative scoring...")
            self.o3b_scorer = PatchScorer(
                reference_index_path=str(o3b_index_path),
                verify_md5=False,
                k=K_PRODUCTION,
            )

    def _discover_available_segments(self) -> list[tuple[int, int]]:
        """Discover all available 32s O4a segments from E:\\o4a local cache."""
        directories = _DATA_DIRECTORIES

        all_segments = []
        for dir_path in directories:
            if not dir_path.exists():
                continue
            for file in dir_path.rglob(f"{self.detector}_*.hdf5"):
                parts = file.stem.split("_")
                if len(parts) >= 3:
                    try:
                        f_start = int(parts[1])
                        f_end = int(parts[2])
                        # Generate 32s segments from this block
                        for seg_start in range(f_start, f_end - SEGMENT_LENGTH, SEGMENT_LENGTH):
                            all_segments.append((seg_start, seg_start + SEGMENT_LENGTH))
                    except ValueError:
                        continue

        logger.info(f"Discovered {len(all_segments)} available {SEGMENT_LENGTH}s segments for {self.detector}")
        return all_segments

    def _calibrate_native_threshold(self, available_segments: list[tuple[int, int]]) -> float:
        """Calibrate native O4a threshold from background segments.

        Uses the identical procedure as production: P99 on null segments.
        """
        logger.info(f"Calibrating native threshold on {self.n_background} background segments...")

        # Sample random background segments
        bg_indices = np.random.choice(len(available_segments), size=min(self.n_background, len(available_segments)), replace=False)
        bg_segments = [available_segments[i] for i in bg_indices]

        background_spectrograms = []
        for seg_start, seg_end in tqdm(bg_segments, desc="Background calibration"):
            try:
                ts_super = fetch_local_or_remote_strain(self.detector, seg_start - 4.0, seg_end + 4.0, edge_tolerance=4.0)
                ts_w, pad_info = whiten_context(ts_super, seg_start, seg_end, pad=4.0)
                ts_bp = extract_clean_subwindow(ts_w, seg_start, seg_end)
                q_gram = generate_qtransform(ts_bp, output_size=(256, 256))
                q_gram_uint8 = (q_gram * 255).astype(np.uint8)
                if q_gram_uint8.ndim == 2:
                    q_gram_rgb = np.stack([q_gram_uint8] * 3, axis=-1)
                else:
                    q_gram_rgb = q_gram_uint8
                background_spectrograms.append(q_gram_rgb)
            except Exception as e:
                logger.debug(f"Failed background segment [{seg_start}, {seg_end}]: {e}")

            # Memory management
            if len(background_spectrograms) % 50 == 0:
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

        min_required = max(20, int(self.n_background * 0.8))
        if len(background_spectrograms) < min_required:
            raise RuntimeError(
                f"Only {len(background_spectrograms)} background spectrograms extracted "
                f"(need at least {min_required} = 80% of {self.n_background}). "
                "Check local data availability."
            )

        threshold, scores_np, gev_params = self.native_scorer.calibrate_threshold(
            background_spectrograms, batch_size=16
        )

        logger.info(
            f"[CALIBRATION] Threshold (P99): {threshold:.6f} | "
            f"Mean: {scores_np.mean():.6f} | Std: {scores_np.std():.6f} | "
            f"N: {len(scores_np)}"
        )

        # Cleanup
        del background_spectrograms
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return threshold

    def run_injection_test(
        self,
        morphologies: list[str] = None,
        amplitudes: np.ndarray = None,
    ) -> pd.DataFrame:
        """Execute the Controlled Recovery Test.

        For each morphology:
        1. Inject synthetic signal into real O4a noise
        2. Generate Q-transform
        3. Score against native O4a index
        4. Measure Recovery Rate (fraction > tau_op)

        Returns:
            DataFrame with per-injection results
        """
        if morphologies is None:
            morphologies = ["HarmonicComb", "WallOfLines", "ScatteredLight", "KoiFish", "Whistle"]

        if amplitudes is None:
            # Calibrated amplitude range: from barely visible to clearly dominant
            # For strain-domain injection, these are peak h(t) values
            amplitudes = np.logspace(-22, -20.5, 6)

        logger.info("=" * 70)
        logger.info("=== CONTROLLED RECOVERY TEST: Domain Shift Defense Falsification ===")
        logger.info("=" * 70)
        logger.info(f"Morphologies: {morphologies}")
        logger.info(f"Amplitudes: {amplitudes}")
        logger.info(f"N injections per bin: {self.n_injections}")
        logger.info(f"Detector: {self.detector}")

        # 1. Discover segments
        available_segments = self._discover_available_segments()
        if len(available_segments) < self.n_background + self.n_injections * len(amplitudes):
            logger.warning(
                f"Available segments ({len(available_segments)}) may be insufficient. "
                "Segments will be reused."
            )

        # 2. Calibrate native threshold
        native_threshold = self._calibrate_native_threshold(available_segments)

        # Also calibrate O3b threshold for comparison
        o3b_threshold = None
        if self.o3b_scorer is not None:
            logger.info("Calibrating O3b threshold for comparative scoring...")
            # We use a separate random subsample
            bg_indices = np.random.choice(
                len(available_segments),
                size=min(self.n_background, len(available_segments)),
                replace=False,
            )
            bg_spectrograms = []
            for i in bg_indices[:100]:  # Smaller sample for O3b
                seg_start, seg_end = available_segments[i]
                try:
                    ts_super = fetch_local_or_remote_strain(self.detector, seg_start - 4.0, seg_end + 4.0, edge_tolerance=4.0)
                    ts_w, pad_info = whiten_context(ts_super, seg_start, seg_end, pad=4.0)
                    ts_bp = extract_clean_subwindow(ts_w, seg_start, seg_end)
                    q_gram = generate_qtransform(ts_bp, output_size=(256, 256))
                    q_gram_uint8 = (q_gram * 255).astype(np.uint8)
                    if q_gram_uint8.ndim == 2:
                        q_gram_rgb = np.stack([q_gram_uint8] * 3, axis=-1)
                    else:
                        q_gram_rgb = q_gram_uint8
                    bg_spectrograms.append(q_gram_rgb)
                except Exception:
                    pass

            if bg_spectrograms:
                o3b_threshold, _, _ = self.o3b_scorer.calibrate_threshold(bg_spectrograms, batch_size=16)
                logger.info(f"O3b threshold: {o3b_threshold:.6f}")
                del bg_spectrograms
                gc.collect()

        # 3. Injection loop
        # Exclude background segments from injection pool
        injection_pool = available_segments[self.n_background:]
        if len(injection_pool) < 100:
            injection_pool = available_segments  # Fallback: reuse

        results = []

        for morph in morphologies:
            logger.info(f"\n--- Morphology: {morph} ---")

            for amp_idx, amp in enumerate(amplitudes):
                logger.info(f"  Amplitude: {amp:.2e}")

                # Select random segments for this bin
                seg_indices = np.random.choice(
                    len(injection_pool),
                    size=self.n_injections,
                    replace=(self.n_injections > len(injection_pool)),
                )

                for inj_idx, seg_idx in enumerate(
                    tqdm(seg_indices, desc=f"{morph} amp={amp:.1e}", leave=False)
                ):
                    seg_start, seg_end = injection_pool[seg_idx]
                    t_inject = seg_start + SEGMENT_LENGTH / 2.0

                    try:
                        # Fetch padded clean strain
                        ts_super = fetch_local_or_remote_strain(
                            self.detector, seg_start - 4.0, seg_end + 4.0, edge_tolerance=4.0
                        )

                        # Generate and inject synthetic signal into padded strain
                        glitch = self.glitch_gen.generate(morph, amp, duration=1.0)
                        ts_injected = self.injector.inject(ts_super, glitch, t_inject)
                        
                        # We compute SNR on the cropped center part for consistency
                        ts_clean_center = ts_super.crop(seg_start, seg_end)
                        snr = self.injector.compute_snr(ts_clean_center, glitch)

                        # Preprocess
                        ts_w, pad_info = whiten_context(ts_injected, seg_start, seg_end, pad=4.0)
                        ts_bp = extract_clean_subwindow(ts_w, seg_start, seg_end)

                        # Generate Q-transform
                        q_gram = generate_qtransform(ts_bp, output_size=(256, 256))
                        q_gram_uint8 = (q_gram * 255).astype(np.uint8)
                        if q_gram_uint8.ndim == 2:
                            q_gram_rgb = np.stack([q_gram_uint8] * 3, axis=-1)
                        else:
                            q_gram_rgb = q_gram_uint8

                        # Score against NATIVE O4a index
                        res_native = self.native_scorer.score_spectrogram(
                            [q_gram_rgb], threshold=native_threshold
                        )[0]

                        # Score against O3b index for comparison
                        score_o3b = None
                        survived_o3b = None
                        if self.o3b_scorer is not None and o3b_threshold is not None:
                            res_o3b = self.o3b_scorer.score_spectrogram(
                                [q_gram_rgb], threshold=o3b_threshold
                            )[0]
                            score_o3b = res_o3b["novelty_score"]
                            survived_o3b = res_o3b["is_novel"]

                        results.append({
                            "morphology": morph,
                            "amplitude": amp,
                            "snr": snr,
                            "gps_start": seg_start,
                            "mil_score_native": res_native["novelty_score"],
                            "survived_native": res_native["is_novel"],
                            "native_threshold": native_threshold,
                            "mil_score_o3b": score_o3b,
                            "survived_o3b": survived_o3b,
                            "o3b_threshold": o3b_threshold,
                            "injection_idx": inj_idx,
                        })

                    except Exception as e:
                        logger.warning(f"Failed injection {morph} at [{seg_start}]: {e}")
                        continue

                # Memory management after each amplitude bin
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

        # 4. Compile results
        df = pd.DataFrame(results)
        df.to_csv(self.output_dir / "dsd_recovery_raw_results.csv", index=False)

        # 5. Compute summary
        summary = self._compute_summary(df)

        # 6. Generate report
        self._generate_report(df, summary, native_threshold, o3b_threshold)

        logger.info("=" * 70)
        logger.info("=== CONTROLLED RECOVERY TEST COMPLETE ===")
        logger.info(f"Output: {self.output_dir}")
        logger.info("=" * 70)

        return df

    def _compute_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute Recovery Rate per morphology and amplitude."""
        summary_rows = []

        for (morph, amp), group in df.groupby(["morphology", "amplitude"]):
            n_total = len(group)
            n_survived_native = int(group["survived_native"].sum())
            recovery_rate = n_survived_native / n_total if n_total > 0 else 0.0

            # Wilson score 95% CI for binomial proportion
            from scipy.stats import norm
            z = norm.ppf(0.975)
            p_hat = recovery_rate
            denom = 1 + z**2 / n_total
            center = (p_hat + z**2 / (2 * n_total)) / denom
            margin = z * np.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n_total)) / n_total) / denom
            ci_low = max(0, center - margin)
            ci_high = min(1, center + margin)

            # O3b comparison
            n_survived_o3b = None
            recovery_o3b = None
            if "survived_o3b" in df.columns and group["survived_o3b"].notna().any():
                n_survived_o3b = int(group["survived_o3b"].sum())
                recovery_o3b = n_survived_o3b / n_total if n_total > 0 else 0.0

            summary_rows.append({
                "morphology": morph,
                "amplitude": amp,
                "snr_mean": group["snr"].mean(),
                "snr_std": group["snr"].std(),
                "n_total": n_total,
                "n_survived_native": n_survived_native,
                "recovery_rate_native": recovery_rate,
                "ci_95_low": ci_low,
                "ci_95_high": ci_high,
                "n_survived_o3b": n_survived_o3b,
                "recovery_rate_o3b": recovery_o3b,
            })

        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_csv(self.output_dir / "dsd_recovery_summary.csv", index=False)

        # Print summary table
        logger.info("\n=== RECOVERY RATE SUMMARY ===")
        for _, row in summary_df.iterrows():
            logger.info(
                f"  {row['morphology']:20s} | amp={row['amplitude']:.1e} | "
                f"SNR={row['snr_mean']:.1f}±{row['snr_std']:.1f} | "
                f"Recovery={row['recovery_rate_native']:.1%} "
                f"[{row['ci_95_low']:.1%}, {row['ci_95_high']:.1%}] "
                f"({row['n_survived_native']}/{row['n_total']})"
            )

        return summary_df

    def _generate_report(
        self,
        df: pd.DataFrame,
        summary: pd.DataFrame,
        native_threshold: float,
        o3b_threshold: Optional[float],
    ):
        """Generate publication-quality report JSON and figure."""

        # 1. JSON report
        report = {
            "experiment": "Controlled Recovery Test for DSD Falsifiability",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "seed": self.seed,
            "detector": self.detector,
            "native_index_md5": self.native_index_md5,
            "native_threshold_p99": native_threshold,
            "o3b_threshold_p99": o3b_threshold,
            "k_production": K_PRODUCTION,
            "n_injections_per_bin": self.n_injections,
            "n_background_calibration": self.n_background,
            "morphologies_tested": summary["morphology"].unique().tolist(),
            "results_by_morphology": {},
        }

        for morph in summary["morphology"].unique():
            morph_df = summary[summary["morphology"] == morph]
            # Peak recovery (at highest SNR)
            peak_row = morph_df.loc[morph_df["snr_mean"].idxmax()]
            report["results_by_morphology"][morph] = {
                "peak_recovery_rate": float(peak_row["recovery_rate_native"]),
                "peak_snr": float(peak_row["snr_mean"]),
                "peak_amplitude": float(peak_row["amplitude"]),
                "ci_95": [float(peak_row["ci_95_low"]), float(peak_row["ci_95_high"])],
                "n_amplitude_bins": len(morph_df),
                "all_bins": morph_df.to_dict(orient="records"),
            }

        # Verdict
        peak_rates = {
            morph: data["peak_recovery_rate"]
            for morph, data in report["results_by_morphology"].items()
        }
        all_recovered = all(r > 0.5 for r in peak_rates.values())
        report["verdict"] = {
            "dsd_is_selective": all_recovered,
            "conclusion": (
                "The Domain Shift Defense is SELECTIVE: all known synthetic "
                "transients survive the native O4a scoring with Recovery Rate > 50%. "
                "The DSD absorbs only pervasive stationary features, not discrete signals."
                if all_recovered
                else "WARNING: One or more synthetic morphologies were absorbed by the "
                "native O4a index. Further investigation required."
            ),
            "peak_recovery_rates": peak_rates,
        }

        with open(self.output_dir / "dsd_recovery_report.json", "w") as f:
            json.dump(report, f, indent=4, default=str)
        logger.info("Saved dsd_recovery_report.json")

        # 2. Generate figure
        self._plot_recovery_curves(summary)

    def _plot_recovery_curves(self, summary: pd.DataFrame):
        """Generate publication-quality Recovery Rate vs SNR figure."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 6))

        colors = {
            "HarmonicComb": "#2ecc71",
            "WallOfLines": "#e74c3c",
            "ScatteredLight": "#3498db",
            "KoiFish": "#9b59b6",
            "Whistle": "#f1c40f",
        }
        markers = {
            "HarmonicComb": "o",
            "WallOfLines": "s",
            "ScatteredLight": "^",
            "KoiFish": "v",
            "Whistle": "*",
        }

        for morph in summary["morphology"].unique():
            morph_df = summary[summary["morphology"] == morph].sort_values("snr_mean")
            color = colors.get(morph, "#95a5a6")
            marker = markers.get(morph, "D")

            yerr_low = np.clip(
                (morph_df["recovery_rate_native"] - morph_df["ci_95_low"]).values * 100,
                0, None,
            )
            yerr_high = np.clip(
                (morph_df["ci_95_high"] - morph_df["recovery_rate_native"]).values * 100,
                0, None,
            )

            ax.errorbar(
                morph_df["snr_mean"],
                morph_df["recovery_rate_native"] * 100,
                yerr=[yerr_low, yerr_high],
                label=morph,
                color=color,
                marker=marker,
                markersize=8,
                linewidth=2,
                capsize=4,
            )

        # Family_01 reference line
        ax.axhline(
            y=0,
            color="#e74c3c",
            linestyle="--",
            alpha=0.5,
            label="Family_01 Recovery (0%)",
        )

        ax.set_xlabel("Matched-Filter SNR ($\\rho$)", fontsize=13)
        ax.set_ylabel("Recovery Rate (%)", fontsize=13)
        ax.set_title(
            "Controlled Recovery Test: Domain Shift Defense Selectivity",
            fontsize=14,
            fontweight="bold",
        )
        ax.legend(fontsize=11, loc="lower right")
        ax.set_ylim(-5, 105)
        ax.set_xscale("log")
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=11)

        fig.tight_layout()
        fig.savefig(
            self.output_dir / "fig_dsd_recovery_curves.png",
            dpi=300,
            bbox_inches="tight",
        )
        plt.close(fig)
        logger.info("Saved fig_dsd_recovery_curves.png")


# =====================================================================
# CLI Entry Point
# =====================================================================

def main():
    """Run the Controlled Recovery Test from command line."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Controlled Recovery Test for DSD Falsifiability"
    )
    parser.add_argument(
        "--detector", type=str, default="L1",
        help="Detector to test (default: L1)"
    )
    parser.add_argument(
        "--n-injections", type=int, default=100,
        help="Number of injections per amplitude bin (default: 100)"
    )
    parser.add_argument(
        "--n-background", type=int, default=200,
        help="Number of background segments for threshold calibration (default: 200)"
    )
    parser.add_argument(
        "--morphologies", nargs="+",
        default=["HarmonicComb", "WallOfLines", "ScatteredLight", "KoiFish", "Whistle"],
        help="Morphologies to test"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (default: 42)"
    )
    args = parser.parse_args()

    test = DSDControlledRecoveryTest(
        detector=args.detector,
        n_injections=args.n_injections,
        n_background=args.n_background,
        seed=args.seed,
    )

    amplitudes = np.logspace(-22, -20.5, 6)
    test.run_injection_test(
        morphologies=args.morphologies,
        amplitudes=amplitudes,
    )


if __name__ == "__main__":
    main()
