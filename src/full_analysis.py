"""Orchestration logic for the full analysis pipeline.

Automates the sequential execution of:
1. Encode (if missing)
2. Cluster
3. Morphcheck
4. Ablation
5. Stability
6. Timeslide (if applicable)

Produces a unified report for each detector.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.clustering import run_full_pipeline
from src.reporter import save_cluster_report, print_summary
from src.similarity_checker import run_morphological_crosscheck, print_morphological_summary
from src.ablation import run_ablation_study
from src.stability import run_stability_analysis
from src.timeslide import run_timeslide
from src.encoder import DINOv2Encoder
from src.utils import load_config, setup_logger

from concurrent.futures import ThreadPoolExecutor, as_completed

logger: logging.Logger = setup_logger(__name__)

def _get_det_color(det: str) -> str:
    """Return ANSI color code for a detector."""
    colors = {
        "H1": "\033[96m",  # Cyan
        "L1": "\033[92m",  # Green
        "V1": "\033[95m",  # Magenta
        "TIMESLIDE": "\033[93m",  # Yellow
    }
    return colors.get(det.upper(), "\033[0m")

def _reset_color() -> str:
    """Return ANSI reset code."""
    return "\033[0m"

def _analyze_detector(
    det: str,
    session_id: str,
    run: str,
    run_lower: str,
    cfg: dict,
    n_runs: int,
    reference_path: str,
    batch_size: int,
) -> tuple[str, dict, Path]:
    """Internal helper to run analysis for a single detector."""
    det = det.upper()
    color = _get_det_color(det)
    reset = _reset_color()
    
    logger.info("%s=== Starting Full Analysis for %s ===%s", color, det, reset)
    
    det_report = {
        "session_id": session_id,
        "detector": det,
        "run": run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": {}
    }
    
    # Descriptive Statistics
    input_dir = Path(f"data/spectrograms/{run_lower}/{session_id}/{det}")
    png_files = list(input_dir.glob(f"{det}_*.png"))
    gps_starts = []
    gps_ends = []
    for f in png_files:
        parts = f.stem.split("_")
        if len(parts) >= 3:
            try:
                gps_starts.append(int(parts[1]))
                gps_ends.append(int(parts[2]))
            except ValueError:
                continue
    
    if gps_starts:
        g_start = min(gps_starts)
        g_end = max(gps_ends)
        n_specs = len(png_files)
        duration_hours = round((g_end - g_start) / 3600, 1)
        
        # Formula: (n_spectrograms * 32) / (duration_hours * 3600) * 100
        if duration_hours > 0:
            duty_cycle = round((n_specs * 32) / (duration_hours * 3600) * 100, 1)
        else:
            duty_cycle = 0.0
            
        det_report["session_summary"] = {
            "n_spectrograms": n_specs,
            "gps_start": g_start,
            "gps_end": g_end,
            "duration_hours": duration_hours,
            "duty_cycle_percent": duty_cycle
        }
    else:
        det_report["session_summary"] = {
            "n_spectrograms": 0,
            "gps_start": 0,
            "gps_end": 0,
            "duration_hours": 0.0,
            "duty_cycle_percent": 0.0
        }

    try:
        # Step 0: Encode
        output_path = Path(f"data/embeddings/{run_lower}/{session_id}/{run_lower}_{det.lower()}.npy")
        
        step_start = datetime.now(timezone.utc).isoformat()
        if not output_path.exists():
            logger.info("%s[%s]%s Step 0: Encoding spectrograms...", color, det, reset)
            encoder = DINOv2Encoder(batch_size=batch_size)
            encoder.extract_dataset(input_dir, output_path, batch_size)
            det_report["steps"]["encode"] = {"status": "OK", "timestamp": step_start}
        else:
            logger.info("%s[%s]%s Step 0: Embeddings already exist. Skipping encode.", color, det, reset)
            det_report["steps"]["encode"] = {"status": "SKIPPED", "timestamp": step_start}

        # Load embeddings and metadata
        embeddings = np.load(output_path)
        json_path = output_path.with_suffix(".json")
        with open(json_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # Step 1: Cluster
        logger.info("%s[%s]%s Step 1: Clustering...", color, det, reset)
        step_start = datetime.now(timezone.utc).isoformat()
        cluster_cfg = cfg["clustering"]
        cluster_dir = Path(f"data/clusters/{run_lower}/{session_id}/{det.lower()}")
        
        result = run_full_pipeline(embeddings, cluster_cfg)
        save_cluster_report(result, metadata, cluster_dir, detector=det)
        print_summary(result, detector=det)
        
        det_report["steps"]["cluster"] = {
            "status": "OK",
            "timestamp": step_start,
            "n_clusters": result["hdbscan_stats"]["n_clusters"],
            "n_noise": result["hdbscan_stats"]["n_noise"],
            "pca_variance": result["pca_variance"],
            "anomalous_clusters": result["anomalous_clusters"]
        }

        # Step 2: Morphcheck
        logger.info("%s[%s]%s Step 2: Morphological cross-check...", color, det, reset)
        step_start = datetime.now(timezone.utc).isoformat()
        morph_report_path = cluster_dir / "morphcheck_report.json"
        
        # Prepare anomalous data for morphcheck
        all_files = metadata["files"]
        anomalous_indices = []
        anomalous_files = []
        anomalous_cluster_ids = []
        
        for cid_str, cluster in result["hdbscan_stats"]["cluster_sizes"].items():
            cid = int(cid_str)
            if cid in result["anomalous_clusters"]:
                mask = result["labels"] == cid
                indices = np.where(mask)[0]
                for idx in indices:
                    anomalous_indices.append(idx)
                    anomalous_files.append(all_files[idx])
                    anomalous_cluster_ids.append(cid)
        
        if anomalous_indices:
            anomalous_embeddings = embeddings[anomalous_indices]
            sim_cfg = cfg.get("similarity", {})
            morph_summary = run_morphological_crosscheck(
                anomalous_embeddings,
                anomalous_files,
                anomalous_cluster_ids,
                Path(reference_path),
                morph_report_path,
                k=sim_cfg.get("k_neighbors", 5),
                novelty_threshold=sim_cfg.get("novelty_threshold", 0.85),
                consensus_threshold=sim_cfg.get("consensus_threshold", 0.60)
            )
            print_morphological_summary(morph_summary, detector=det)
            det_report["steps"]["morphcheck"] = {
                "status": "OK",
                "timestamp": step_start,
                "novel": morph_summary["novel"],
                "known": morph_summary["known"],
                "ambiguous": morph_summary["ambiguous"]
            }
        else:
            logger.info("%s[%s]%s No anomalous clusters found. Skipping morphcheck.", color, det, reset)
            det_report["steps"]["morphcheck"] = {"status": "SKIPPED", "timestamp": step_start}

        # Step 3: Ablation
        logger.info("%s[%s]%s Step 3: Ablation study...", color, det, reset)
        step_start = datetime.now(timezone.utc).isoformat()
        ablation_dir = Path(f"data/ablation/{run_lower}/{session_id}")
        
        image_paths = [input_dir / Path(f).name for f in all_files]
        encoder = DINOv2Encoder(batch_size=batch_size)
        
        run_ablation_study(
            original_labels=result["labels"],
            image_paths=image_paths,
            encoder=encoder,
            cluster_cfg=cluster_cfg,
            output_dir=ablation_dir,
            session_id=session_id,
            detector=det
        )
        
        # Read back ablation report
        ablation_report_file = ablation_dir / f"ablation_report_{det}.json"
        if ablation_report_file.exists():
            with open(ablation_report_file, "r") as f:
                ablation_data = json.load(f)
            det_report["steps"]["ablation"] = {
                "status": "OK",
                "timestamp": step_start,
                "results": {k: v["ari"] for k, v in ablation_data["results"].items()}
            }
        else:
            det_report["steps"]["ablation"] = {"status": "FAILED", "timestamp": step_start, "error": "Report not found"}

        # Step 4: Stability
        logger.info("%s[%s]%s Step 4: Stability analysis...", color, det, reset)
        step_start = datetime.now(timezone.utc).isoformat()
        
        run_stability_analysis(
            embeddings=embeddings,
            cluster_cfg=cluster_cfg,
            n_runs=n_runs,
            session_id=session_id,
            detector=det
        )
        
        # Read back stability report
        stability_report_file = Path(f"data/stability/{session_id}/stability_report_{det}.json")
        if stability_report_file.exists():
            with open(stability_report_file, "r") as f:
                stability_data = json.load(f)
            det_report["steps"]["stability"] = {
                "status": "OK",
                "timestamp": step_start,
                "mean_ari": stability_data["ari_stats"]["mean"],
                "stable_anomalous_clusters": stability_data["stable_anomalous_clusters_baseline_ids"]
            }
        else:
            det_report["steps"]["stability"] = {"status": "FAILED", "timestamp": step_start, "error": "Report not found"}

    except Exception as e:
        logger.error("Error during full analysis for %s: %s", det, str(e), exc_info=True)
        det_report["status"] = "FAILED"
        det_report["error"] = str(e)
    else:
        det_report["status"] = "OK"

    # Save unified report for this detector
    report_dir = Path(f"data/reports/{run_lower}/{session_id}")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{det}_full_report.json"
    with open(report_path, "w") as f:
        json.dump(det_report, f, indent=2)
    
    return det, det_report, report_path

def run_full_analysis(
    session_id: str,
    detectors: list[str] | None = None,
    run: str = "O4a",
    skip_timeslide: bool = False,
    n_runs: int = 20,
    reference_path: str = "data/reference/indomain_index.npz",
    batch_size: int = 32,
    sequential: bool = False,
) -> dict:
    """Run the full analysis pipeline for one or more detectors.
    
    Args:
        session_id: The session ID to analyze.
        detectors: List of detectors (e.g. ['H1', 'L1']). If None, auto-discovers from directories.
        run: Observing run (O2, O3a, O3b, O4a).
        skip_timeslide: If True, skips the timeslide analysis.
        n_runs: Number of runs for stability analysis.
        reference_path: Path to the morphological reference index.
        batch_size: Batch size for encoding and ablation.
        sequential: If True, executes detectors in sequence. Default: False (parallel).
        
    Returns:
        A dictionary containing the status and report paths for each detector and timeslide.
    """
    run_lower = run.lower()
    cfg = load_config()
    
    # 1. Discovery
    if not detectors:
        spec_dir = Path(f"data/spectrograms/{run_lower}/{session_id}")
        if not spec_dir.exists():
            logger.error("Session directory not found: %s", spec_dir)
            return {"status": "FAILED", "error": "Session directory not found"}
        
        detectors = [d.name for d in spec_dir.iterdir() if d.is_dir() and d.name.upper() in ["H1", "L1", "V1"]]
        logger.info("Auto-discovered detectors: %s", detectors)
        
    if not detectors:
        logger.error("No detectors found for session %s", session_id)
        return {"status": "FAILED", "error": "No detectors found"}

    overall_status = {}
    reports = {}
    
    # 2. Per-detector analysis
    if sequential or len(detectors) == 1:
        # Sequential execution
        for det in detectors:
            det_name, det_report, report_path = _analyze_detector(
                det, session_id, run, run_lower, cfg, n_runs, reference_path, batch_size
            )
            reports[det_name] = report_path
            overall_status[det_name] = det_report["status"]
    else:
        # Parallel execution
        logger.info("Starting parallel analysis for detectors: %s", detectors)
        with ThreadPoolExecutor(max_workers=len(detectors)) as executor:
            futures = {
                executor.submit(
                    _analyze_detector, 
                    det, session_id, run, run_lower, cfg, n_runs, reference_path, batch_size
                ): det for det in detectors
            }
            for future in as_completed(futures):
                try:
                    det_name, det_report, report_path = future.result()
                    reports[det_name] = report_path
                    overall_status[det_name] = det_report["status"]
                except Exception as e:
                    det = futures[future]
                    logger.error("Parallel analysis failed for %s: %s", det, str(e))
                    overall_status[det.upper()] = "FAILED"

    # 3. Timeslide (if H1 and L1 are both OK)
    if not skip_timeslide and "H1" in overall_status and "L1" in overall_status:
        if overall_status["H1"] == "OK" and overall_status["L1"] == "OK":
            ts_color = _get_det_color("TIMESLIDE")
            reset = _reset_color()
            logger.info("%s=== Starting Timeslide Analysis (H1 + L1) ===%s", ts_color, reset)
            step_start = datetime.now(timezone.utc).isoformat()
            
            try:
                meta_h1 = Path(f"data/embeddings/{run_lower}/{session_id}/{run_lower}_h1.json")
                rep_h1 = Path(f"data/clusters/{run_lower}/{session_id}/h1/cluster_report.json")
                meta_l1 = Path(f"data/embeddings/{run_lower}/{session_id}/{run_lower}_l1.json")
                rep_l1 = Path(f"data/clusters/{run_lower}/{session_id}/l1/cluster_report.json")
                output_dir = Path(f"data/timeslide/{run_lower}/{session_id}")
                
                ts_report = run_timeslide(
                    meta_h1=meta_h1,
                    rep_h1=rep_h1,
                    meta_l1=meta_l1,
                    rep_l1=rep_l1,
                    output_dir=output_dir,
                    iterations=50,
                    window=32
                )
                
                reports["timeslide"] = output_dir / "timeslide_report_H1_L1.json"
                overall_status["timeslide"] = "OK"
                
                # Update unified reports with timeslide info
                for det in ["H1", "L1"]:
                    r_path = reports.get(det)
                    if r_path and r_path.exists():
                        with open(r_path, "r") as f:
                            r_data = json.load(f)
                        r_data["steps"]["timeslide"] = {
                            "status": "OK",
                            "timestamp": step_start,
                            "p_value": ts_report["p_value"],
                            "z_score": ts_report["z_score"]
                        }
                        with open(r_path, "w") as f:
                            json.dump(r_data, f, indent=2)
                        
            except Exception as e:
                logger.error("Error during timeslide analysis: %s", str(e))
                overall_status["timeslide"] = "FAILED"
        else:
            logger.info("Skipping timeslide: H1 or L1 analysis failed.")
            overall_status["timeslide"] = "SKIPPED (dependencies failed)"
    else:
        overall_status["timeslide"] = "SKIPPED"

    return {
        "session_id": session_id,
        "run": run,
        "detectors": detectors,
        "status": overall_status,
        "reports": {k: str(v) for k, v in reports.items()}
    }
