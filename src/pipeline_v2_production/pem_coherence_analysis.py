"""
PEM Offline Coherence Analysis

This standalone script analyzes the spectral coherence between gravitational-wave strain
and the available public (safe) O4a auxiliary channels for structurally anomalous candidates
(e.g., Family_01 and Singletons).

Data fetching uses NDS2 to nds.gwosc.org, with a local cache in data/raw/auxiliary/
to prevent repeated slow network requests.
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from gwpy.timeseries import TimeSeries
import h5py

from src.core.utils import setup_logger
from src.core.data_loader import fetch_strain_data

logger = setup_logger(__name__)

# O4a Public Safe Auxiliary Channels
AUX_CHANNELS = {
    "H1": [
        "H1:CAL-PCALX_RX_PD_OUT_DQ",
        "H1:CAL-PCALY_RX_PD_OUT_DQ",
        "H1:IMC-WFS_A_DC_PIT_OUT_DQ",
        "H1:IMC-WFS_A_DC_YAW_OUT_DQ",
        "H1:LSC-POP_A_LF_OUT_DQ",
        "H1:LSC-REFL_A_RIN_OUT_DQ",
        "H1:OAF-IMC_WFS_A_DC_PIT_PREFILT_OUT_DQ",
        "H1:OAF-IMC_WFS_A_DC_YAW_PREFILT_OUT_DQ",
        "H1:OAF-REFL_A_RIN_PREFILT_OUT_DQ",
        "H1:PEM-EY_MAINSMON_EBAY_1_DQ",
        "H1:SUS-ETMX_L1_CAL_LINE_OUT_DQ",
        "H1:SUS-ETMX_L2_CAL_LINE_OUT_DQ",
        "H1:SUS-ETMX_L3_CAL_LINE_OUT_DQ",
        "H1:SUS-PI_PROC_COMPUTE_MODE29_RMSMON",
    ],
    "L1": [
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
}


def fetch_auxiliary_data(channel: str, gps_start: int, gps_end: int, cache_dir: Path) -> Optional[TimeSeries]:
    """Fetch auxiliary channel data with local caching as HDF5."""
    safe_channel = channel.replace(":", "_")
    cache_file = cache_dir / f"{safe_channel}_{gps_start}_{gps_end}.hdf5"

    if cache_file.exists():
        logger.debug(f"Loading cached aux data for {channel}: {cache_file}")
        try:
            return TimeSeries.read(cache_file, format='hdf5', name=channel)
        except Exception as e:
            logger.warning(f"Failed to read cache {cache_file}: {e}. Will re-fetch.")

    logger.info(f"Fetching {channel} from NDS2 ({gps_start} - {gps_end})...")
    try:
        ts = TimeSeries.fetch(channel, start=gps_start, end=gps_end, host='nds.gwosc.org')
        cache_dir.mkdir(parents=True, exist_ok=True)
        ts.write(cache_file, format='hdf5', overwrite=True, name=channel)
        return ts
    except Exception as e:
        logger.error(f"Failed to fetch {channel}: {e}")
        return None


def calculate_coherence_and_plot(
        strain: TimeSeries,
        aux: TimeSeries,
        channel_name: str,
        detector: str,
        gps_start: int,
        output_dir: Path,
        fftlength: float = 2.0,
        freq_bounds: tuple = (20, 500),
        threshold: float = 0.6
) -> dict:
    """Calculate coherence, extract max peak, and generate plot if significant."""
    try:
        # Match sample rates. Resample the higher rate one to the lower rate one.
        if strain.sample_rate != aux.sample_rate:
            target_sr = min(strain.sample_rate.value, aux.sample_rate.value)
            if strain.sample_rate.value > target_sr:
                strain = strain.resample(target_sr)
            if aux.sample_rate.value > target_sr:
                aux = aux.resample(target_sr)

        # Calculate coherence
        coh = strain.coherence(aux, fftlength=fftlength, overlap=fftlength/2)
        
        # Limit to frequency bounds
        freqs = coh.frequencies.value
        mask = (freqs >= freq_bounds[0]) & (freqs <= freq_bounds[1])
        coh_band = coh.value[mask]
        freq_band = freqs[mask]
        
        if len(coh_band) == 0:
            return {"max_coherence": 0.0, "peak_freq": 0.0, "significant": False}

        max_coh = float(np.max(coh_band))
        peak_freq = float(freq_band[np.argmax(coh_band)])
        significant = max_coh >= threshold

        if significant:
            logger.info(f"*** SIGNIFICANT COHERENCE DETECTED *** {channel_name} (GPS {gps_start}): C={max_coh:.2f} at {peak_freq:.1f}Hz")
            
            # Plot
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(coh.frequencies, coh.value, color='purple')
            ax.set_xlim(*freq_bounds)
            ax.set_ylim(0, 1)
            ax.set_xlabel('Frequency [Hz]')
            ax.set_ylabel('Coherence')
            ax.set_title(f'Coherence: {detector} Strain vs {channel_name}\nGPS: {gps_start} | Max C={max_coh:.2f} @ {peak_freq:.1f}Hz')
            ax.grid(True, alpha=0.5)
            
            plot_dir = output_dir / "pem" / "coherence_plots"
            plot_dir.mkdir(parents=True, exist_ok=True)
            safe_chan = channel_name.replace(":", "_")
            plot_path = plot_dir / f"coh_{detector}_{safe_chan}_{gps_start}.png"
            fig.savefig(plot_path, dpi=150, bbox_inches='tight')
            plt.close(fig)

        return {
            "max_coherence": max_coh,
            "peak_freq": peak_freq,
            "significant": significant
        }

    except Exception as e:
        logger.error(f"Error calculating coherence for {channel_name}: {e}")
        return {"max_coherence": np.nan, "peak_freq": np.nan, "significant": False}


def run_pem_coherence_analysis(
        taxonomy_csv: Path,
        cache_dir: Path,
        output_dir: Path,
        target_families: list = ["Family_01"],
        include_singletons: bool = True,
        max_events_per_family: int = 5
):
    """Orchestrate the PEM coherence analysis."""
    if not taxonomy_csv.exists():
        logger.error(f"Taxonomy CSV not found: {taxonomy_csv}")
        return

    df = pd.read_csv(taxonomy_csv)
    
    # Select targets
    targets = []
    
    for fam in target_families:
        fam_df = df[df['global_family_id'] == fam]
        # if 'snr' in columns, sort by it, otherwise just take head
        if not fam_df.empty:
            fam_df = fam_df.head(max_events_per_family)
            for _, row in fam_df.iterrows():
                targets.append({
                    "detector": row['detector'],
                    "gps_start": int(row['gps_start']),
                    "family": row['global_family_id'],
                    "source": "family"
                })
                
    if include_singletons:
        sing_df = df[df['global_family_id'] == 'Singleton']
        for _, row in sing_df.iterrows():
            targets.append({
                "detector": row['detector'],
                "gps_start": int(row['gps_start']),
                "family": 'Singleton',
                "source": "singleton"
            })
            
    logger.info(f"Selected {len(targets)} candidate events for coherence analysis.")
    
    results = []
    
    for i, target in enumerate(targets):
        det = target["detector"]
        gps_start = target["gps_start"]
        gps_end = gps_start + 32
        fam = target["family"]
        
        logger.info(f"[{i+1}/{len(targets)}] Analyzing {det} event at GPS {gps_start} ({fam})")
        
        # 1. Fetch Strain
        try:
            strain_ts = fetch_strain_data(det, gps_start, gps_end)
            # DANTE pipeline applies whitening and bandpass before feature extraction.
            # We'll just apply a 20Hz highpass to remove seismic rumble.
            strain_ts = strain_ts.highpass(20)
        except Exception as e:
            logger.error(f"Failed to fetch strain for GPS {gps_start}: {e}")
            continue
            
        # 2. Iterate Aux Channels
        channels = AUX_CHANNELS.get(det, [])
        for ch in channels:
            aux_ts = fetch_auxiliary_data(ch, gps_start, gps_end, cache_dir)
            if aux_ts is None:
                continue
            
            # Apply highpass to aux as well if it's high sample rate
            if aux_ts.sample_rate.value >= 40:
                 try:
                     aux_ts = aux_ts.highpass(20)
                 except:
                     pass
                     
            coh_metrics = calculate_coherence_and_plot(
                strain=strain_ts,
                aux=aux_ts,
                channel_name=ch,
                detector=det,
                gps_start=gps_start,
                output_dir=output_dir
            )
            
            results.append({
                "detector": det,
                "gps_start": gps_start,
                "family": fam,
                "aux_channel": ch,
                "max_coherence": coh_metrics["max_coherence"],
                "peak_freq": coh_metrics["peak_freq"],
                "significant": coh_metrics["significant"]
            })
            
    # Save Report
    if results:
        res_df = pd.DataFrame(results)
        pem_out_dir = output_dir / "pem"
        pem_out_dir.mkdir(parents=True, exist_ok=True)
        report_path = pem_out_dir / "coherence_report.csv"
        res_df.to_csv(report_path, index=False)
        logger.info(f"Saved coherence report to {report_path}")
        
        # Inject into Final Discovery Report if it exists
        _inject_into_final_report(output_dir, res_df, pem_out_dir / "coherence_plots")

def _inject_into_final_report(output_dir: Path, res_df: pd.DataFrame, plots_dir: Path):
    report_path = output_dir / "Final_Discovery_Report.md"
    if not report_path.exists():
        return
        
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        if "## 16. PEM Offline Coherence Defense" in content:
            logger.info("PEM section already exists in Final_Discovery_Report.md. Skipping injection to avoid duplicates.")
            return
            
        md_lines = []
        md_lines.append("## 16. PEM Offline Coherence Defense")
        md_lines.append("> Instrumental validation against GWOSC safe auxiliary channels.")
        md_lines.append("")
        md_lines.append("| Detector | GPS Start | Family | Aux Channel | Max Coherence | Peak Freq (Hz) | Significant |")
        md_lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for _, row in res_df.iterrows():
            sig_icon = "🔴 YES" if row.get("significant", False) else "🟢 NO"
            md_lines.append(f"| {row['detector']} | {row['gps_start']} | {row['family']} | {row['aux_channel']} | {row['max_coherence']:.3f} | {row['peak_freq_hz']:.1f} | {sig_icon} |")
        md_lines.append("")
        
        if plots_dir.exists():
            plots = list(plots_dir.glob("*.png"))
            if plots:
                md_lines.append("````carousel")
                for i, p in enumerate(plots):
                    if i > 0:
                        md_lines.append("<!-- slide -->")
                    rel_p = "file:///" + str(p.resolve()).replace("\\", "/")
                    md_lines.append(f"![PEM Coherence {p.name}]({rel_p})")
                md_lines.append("````")
                md_lines.append("")
                
        new_section = "\n".join(md_lines)
        
        # Try to insert before Limitations
        if "## 17. Limitations and Caveats" in content:
            content = content.replace("## 17. Limitations and Caveats", new_section + "\n## 17. Limitations and Caveats")
        elif "## 14. Limitations and Caveats" in content:
            content = content.replace("## 14. Limitations and Caveats", new_section + "\n## 17. Limitations and Caveats")
        else:
            content += "\n" + new_section
            
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Successfully injected PEM results into Final_Discovery_Report.md")
    except Exception as e:
        logger.error(f"Failed to inject PEM results into Final_Discovery_Report.md: {e}")
        
        # Log summary
        sig_df = res_df[res_df['significant'] == True]
        if not sig_df.empty:
            logger.warning(f"Found {len(sig_df)} significant coherence couplings!")
            for _, row in sig_df.iterrows():
                logger.warning(f"  - {row['detector']} {row['family']} at {row['gps_start']} coupled with {row['aux_channel']} (C={row['max_coherence']:.2f})")
        else:
            logger.info("No significant instrumental coherence found for the selected events.")
    else:
        logger.warning("No results to save.")


if __name__ == "__main__":
    # Test script execution
    project_root = Path(__file__).resolve().parent.parent.parent
    tax_csv = project_root / "data" / "production" / "aggregated" / "Master_Taxonomy_O4a.csv"
    cache_d = project_root / "data" / "raw" / "auxiliary"
    out_d = project_root / "data" / "production" / "aggregated"
    
    run_pem_coherence_analysis(
        taxonomy_csv=tax_csv,
        cache_dir=cache_d,
        output_dir=out_d,
        target_families=["Family_01"],
        include_singletons=True,
        max_events_per_family=3
    )
