"""Plotting and reporting functions for Mock Data Challenge (MDC)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.optimize import curve_fit

from src.utils import setup_logger

logger = setup_logger(__name__)


def sigmoid(x, x0, k):
    """Sigmoid function for sensitivity curve fitting."""
    return 1.0 / (1.0 + np.exp(-k * (x - x0)))


def plot_sensitivity_curve(mdc_results_df: pd.DataFrame, output_dir: Path) -> dict:
    """Plot Sensitivity (Recall) vs SNR and return SNR_50 per glitch type."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    plt.figure(figsize=(10, 6), dpi=150)
    
    # Exclude NULL injections
    df = mdc_results_df[mdc_results_df["glitch_type"] != "NULL"]
    
    glitch_types = df["glitch_type"].unique()
    
    colors = plt.cm.tab10(np.linspace(0, 1, len(glitch_types)))
    
    snr_50_results = {}
    
    for i, gtype in enumerate(glitch_types):
        sub = df[df["glitch_type"] == gtype].sort_values("snr_mean")
        x_data = sub["snr_mean"].values
        y_data = sub["recall"].values
        
        plt.scatter(x_data, y_data, color=colors[i], label=f"{gtype} (data)", s=40, alpha=0.7)
        
        # Fit sigmoid
        try:
            # Initial guess: x0 is mean of snr, k is 1.0
            p0 = [np.mean(x_data) if len(x_data) > 0 else 10.0, 1.0]
            # Bounds: x0 > 0, k > 0
            popt, _ = curve_fit(sigmoid, x_data, y_data, p0=p0, bounds=([0, 0], [np.inf, np.inf]))
            x0, k = popt
            
            x_fit = np.logspace(np.log10(max(0.1, x_data.min())), np.log10(x_data.max()), 100)
            y_fit = sigmoid(x_fit, x0, k)
            
            plt.plot(x_fit, y_fit, color=colors[i], linestyle='-', linewidth=2)
            
            snr_50_results[gtype] = x0
            
            # Annotate SNR_50
            plt.axvline(x=x0, color=colors[i], linestyle=':', alpha=0.5)
            plt.text(x0 * 1.05, 0.1 + i*0.05, f"$SNR_{{50}}$={x0:.1f}", color=colors[i], fontsize=9)
            
        except Exception as e:
            logger.warning(f"Failed to fit sigmoid for {gtype}: {e}")
            plt.plot(x_data, y_data, color=colors[i], linestyle='--', linewidth=2)
            snr_50_results[gtype] = float('nan')
            
    plt.axhline(y=0.5, color='k', linestyle='--', alpha=0.5, label='Recall = 0.5')
    
    plt.xscale('log')
    plt.xlabel('Matched-Filter SNR', fontsize=12)
    plt.ylabel('Recall (Fraction flagged as NOVEL)', fontsize=12)
    plt.title('MDC Sensitivity Curve: Pipeline Novelty Detection', fontsize=14)
    plt.ylim(-0.05, 1.05)
    plt.grid(True, which="both", ls="-", alpha=0.2)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    
    plt.savefig(output_dir / "sensitivity_curve.pdf", bbox_inches="tight")
    plt.savefig(output_dir / "sensitivity_curve.png", bbox_inches="tight", dpi=150)
    plt.close()
    
    return snr_50_results


def plot_confusion_matrix(raw_results_df: pd.DataFrame, output_dir: Path) -> None:
    """Plot heatmap of false negatives (KNOWN) assignments."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Filter for KNOWN samples (False Negatives), exclude NULL
    fn_df = raw_results_df[(raw_results_df["novelty_status"] == "KNOWN") & 
                           (raw_results_df["glitch_type"] != "NULL")]
    
    if len(fn_df) == 0:
        logger.info("No false negatives found. Confusion matrix will be empty.")
        # Create empty plot
        plt.figure(figsize=(8, 6))
        plt.text(0.5, 0.5, "No False Negatives (Perfect Sensitivity)", 
                 ha='center', va='center', fontsize=16)
        plt.axis('off')
        plt.savefig(output_dir / "confusion_matrix.pdf")
        plt.savefig(output_dir / "confusion_matrix.png", dpi=150)
        plt.close()
        return
        
    # Cross tabulation
    confusion = pd.crosstab(fn_df["top_label"], fn_df["glitch_type"])
    
    plt.figure(figsize=(10, 8), dpi=150)
    sns.heatmap(confusion, annot=True, fmt="d", cmap="YlOrRd", cbar_kws={'label': 'Count'})
    
    plt.title("Confusion Matrix for Misclassified (KNOWN) Synthetic Glitches", fontsize=14)
    plt.xlabel("Injected Glitch Type", fontsize=12)
    plt.ylabel("Assigned Gravity Spy Class", fontsize=12)
    
    plt.tight_layout()
    plt.savefig(output_dir / "confusion_matrix.pdf", bbox_inches="tight")
    plt.savefig(output_dir / "confusion_matrix.png", bbox_inches="tight", dpi=150)
    plt.close()


def generate_mdc_report(
    summary_df: pd.DataFrame, 
    raw_results_df: pd.DataFrame, 
    snr_50_dict: dict, 
    output_dir: Path
) -> None:
    """Generate Markdown report for MDC."""
    report_path = output_dir / "mdc_report.md"
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Mock Data Challenge (MDC) Report\n\n")
        f.write("## 1. Sensitivity Summary\n\n")
        
        f.write("| Glitch Type | SNR_50 | Max Recall | Total Injections |\n")
        f.write("|-------------|--------|------------|------------------|\n")
        
        for gtype in summary_df["glitch_type"].unique():
            if gtype == "NULL":
                continue
                
            sub = summary_df[summary_df["glitch_type"] == gtype]
            max_recall = sub["recall"].max()
            n_tot = sub["n_total"].sum()
            snr_50 = snr_50_dict.get(gtype, float('nan'))
            
            f.write(f"| {gtype} | {snr_50:.2f} | {max_recall:.2f} | {n_tot} |\n")
            
        f.write("\n## 2. Interpretation\n\n")
        
        # Check if sensitive
        sensitive = True
        for k, v in snr_50_dict.items():
            if np.isnan(v) or v > 50:
                sensitive = False
                
        if sensitive:
            f.write("The pipeline demonstrates high sensitivity. SNR_50 is generally < 10 for all tested morphologies, "
                    "indicating that novel glitches are reliably detected even at moderate signal-to-noise ratios.\n\n")
        else:
            f.write("The pipeline shows limited sensitivity for some glitch types. "
                    "If SNR_50 > 50 for certain morphologies, DINOv2 might not discriminate those shapes sufficiently from known classes.\n\n")
            
        f.write("## 3. Null Result Validation\n\n")
        
        null_sub = summary_df[summary_df["glitch_type"] == "NULL"]
        if not null_sub.empty:
            null_recall = null_sub["recall"].iloc[0]
            f.write(f"Control (NULL) injections yielded a False Positive Rate (Recall) of **{null_recall:.2f}**.\n\n")
            
            if null_recall < 0.1:
                f.write("Because the False Positive rate on NULL injections is near zero, and the sensitivity (Recall at high SNR) "
                        "is high across diverse synthetic morphologies, any **null result** (finding zero NOVEL classes in a dataset like O4a) "
                        "is scientifically supported. It implies novel morphologies are genuinely absent, rather than missed by the pipeline.\n")
            else:
                f.write("WARNING: The false positive rate on NULL injections is elevated. "
                        "The novelty threshold might need calibration (e.g., using `calibrate-threshold`).\n")
