"""Orchestration logic for the full analysis pipeline.

Automates the sequential execution of:
1. Encode (if missing)
2. Cluster
3. Morphcheck
4. Ablation
5. Stability
6. Timeslide (if applicable)

Produces a unified report for each detector.

Parallel safety notes
---------------------
Cluster, morphcheck and stability are CPU-bound and can run fully in parallel.
Encode and ablation both instantiate DINOv2Encoder and use the GPU.  A single
module-level ``_gpu_lock`` (threading.Lock) serialises those sections so that
only one detector thread accesses the GPU at a time, preventing CUDA OOM
errors.  Each pipeline step has its own try/except so that a failure in
ablation does **not** prevent stability from running.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import torch
from src.clustering import run_full_pipeline
from src.reporter import save_cluster_report, print_summary
from src.similarity_checker import run_morphological_crosscheck, print_morphological_summary
from src.ablation import run_ablation_study
from src.stability import run_stability_analysis
from src.timeslide import run_timeslide
from src.encoder import DINOv2Encoder
from src.utils import load_config, setup_logger, session_path

from concurrent.futures import ThreadPoolExecutor, as_completed

logger: logging.Logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level GPU lock — ensures only one thread uses the GPU at a time.
# Both the encode step and the ablation step (which re-runs DINOv2 inference)
# acquire this lock so they never race on CUDA memory.
# ---------------------------------------------------------------------------
_gpu_lock: threading.Lock = threading.Lock()


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


def _save_detector_report(det_report: dict, run: str, session_id: str, det: str) -> Path:
    """Persist the per-detector unified report and return its path."""
    report_dir = session_path(run, session_id) / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{det}_full_report.json"
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(det_report, fh, indent=2)
    return report_path


def _analyze_detector(
        det: str,
        session_id: str,
        run: str,
        run_lower: str,
        n_runs: int,
        reference_path: str | None,
        batch_size: int,
        gpu_lock: threading.Lock | None = None,
) -> tuple[str, dict, Path]:
    """Internal helper to run analysis for a single detector.

    Each pipeline step is wrapped in its own try/except so that a failure in
    one optional step (e.g. ablation) does not prevent subsequent steps (e.g.
    stability) from running.

    Steps 0–2 (encode → cluster → morphcheck) share a common dependency chain:
    if encode or cluster fails we cannot continue and return early.  Morphcheck
    failure is logged but does not abort ablation/stability.

    Steps 3 (ablation) and 4 (stability) are independent of each other and are
    each individually guarded.
    """
    det = det.upper()
    color = _get_det_color(det)
    reset = _reset_color()

    logger.info("%s=== Starting Full Analysis for %s ===%s", color, det, reset)

    det_report: dict = {
        "session_id": session_id,
        "detector": det,
        "run": run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": {},
    }

    # ------------------------------------------------------------------ #
    # Fail-fast check for references (BUG 2 FIX)                          #
    # ------------------------------------------------------------------ #
    from src.utils import discover_references
    if reference_path is not None:
        references = [Path(reference_path)]
        auto_discovery = False
    else:
        references = discover_references()
        auto_discovery = True
        
    if not references:
        error_msg = "Nessun file indomain_*.npz trovato in data/reference/. Eseguire download-all-references prima di morphcheck."
        logger.error("%s[%s]%s %s", color, det, reset, error_msg)
        det_report["status"] = "FAILED"
        det_report["error"] = error_msg
        return det, det_report, _save_detector_report(det_report, run, session_id, det)

    # ------------------------------------------------------------------ #
    # Descriptive statistics from spectrogram filenames                   #
    # ------------------------------------------------------------------ #
    input_dir = session_path(run, session_id) / "spectrograms" / det
    png_files = list(input_dir.glob(f"{det}_*.png"))
    gps_starts, gps_ends = [], []
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
        duty_cycle = (
            round((n_specs * 32) / (duration_hours * 3600) * 100, 1)
            if duration_hours > 0
            else 0.0
        )
        det_report["session_summary"] = {
            "n_spectrograms": n_specs,
            "gps_start": g_start,
            "gps_end": g_end,
            "duration_hours": duration_hours,
            "duty_cycle_percent": duty_cycle,
        }
    else:
        det_report["session_summary"] = {
            "n_spectrograms": 0,
            "gps_start": 0,
            "gps_end": 0,
            "duration_hours": 0.0,
            "duty_cycle_percent": 0.0,
        }

    # ------------------------------------------------------------------ #
    # Step 0: Encode  (GPU — serialised via gpu_lock)                     #
    # ------------------------------------------------------------------ #
    output_path = session_path(run, session_id) / "embeddings" / f"{run_lower}_{det.lower()}.npy"
    step_start = datetime.now(timezone.utc).isoformat()
    embeddings: np.ndarray | None = None
    metadata: dict | None = None

    try:
        if not output_path.exists():
            logger.info("%s[%s]%s Step 0: Encoding spectrograms...", color, det, reset)
            _lock = gpu_lock if gpu_lock is not None else _gpu_lock
            encoder_enc = DINOv2Encoder(batch_size=batch_size)
            encoder_enc.extract_dataset(input_dir, output_path, batch_size, gpu_lock=_lock)
            del encoder_enc
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            det_report["steps"]["encode"] = {"status": "OK", "timestamp": step_start}
        else:
            logger.info("%s[%s]%s Step 0: Embeddings already exist. Skipping encode.", color, det, reset)
            det_report["steps"]["encode"] = {"status": "SKIPPED", "timestamp": step_start}

        # Load embeddings + metadata (required by all downstream steps)
        embeddings = np.load(output_path)
        json_path = output_path.with_suffix(".json")
        with open(json_path, "r", encoding="utf-8") as fh:
            metadata = json.load(fh)

    except Exception as exc:
        logger.error(
            "%s[%s]%s Step 0 FAILED: %s", color, det, reset, exc, exc_info=True
        )
        det_report["steps"]["encode"] = {
            "status": "FAILED",
            "timestamp": step_start,
            "error": str(exc),
        }
        det_report["status"] = "FAILED"
        det_report["error"] = f"Encode failed: {exc}"
        return det, det_report, _save_detector_report(det_report, run, session_id, det)

    # ------------------------------------------------------------------ #
    # Step 1: Cluster  (CPU)                                              #
    # ------------------------------------------------------------------ #
    step_start = datetime.now(timezone.utc).isoformat()
    result: dict | None = None

    try:
        cluster_cfg = cfg["clustering"]
        cluster_dir = session_path(run, session_id) / "clusters" / det.lower()
        cluster_report_file = cluster_dir / "cluster_report.json"

        if cluster_report_file.exists():
            logger.info("%s[%s]%s Step 1: Cluster report already exists. Skipping clustering.", color, det, reset)
            with open(cluster_report_file, "r", encoding="utf-8") as f:
                rep = json.load(f)

            # Reconstruct result dict for downstream steps
            labels = np.full(len(metadata["files"]), -1)
            file_to_idx = {f: i for i, f in enumerate(metadata["files"])}
            for cid_str, details in rep.get("results", {}).get("clusters", {}).items():
                cid = int(cid_str)
                for sf in details.get("sample_files", []):
                    if sf in file_to_idx:
                        labels[file_to_idx[sf]] = cid

            result = {
                "labels": labels,
                "hdbscan_stats": {
                    "cluster_sizes": {int(k): v for k, v in rep.get("results", {}).get("cluster_sizes", {}).items()},
                    "n_clusters": rep.get("results", {}).get("n_clusters", 0),
                    "n_noise": rep.get("results", {}).get("n_noise", 0),
                },
                "anomalous_clusters": rep.get("results", {}).get("anomalous_clusters", []),
                "anomalous_samples": rep.get("results", {}).get("anomalous_samples", []),
                "pca_variance": rep.get("pipeline", {}).get("pca_variance_explained", 0.0)
            }
            det_report["steps"]["cluster"] = {"status": "SKIPPED", "timestamp": step_start}
        else:
            logger.info("%s[%s]%s Step 1: Clustering...", color, det, reset)
            result = run_full_pipeline(embeddings, cluster_cfg)
            save_cluster_report(result, metadata, cluster_dir, detector=det)
            print_summary(result, detector=det)

            det_report["steps"]["cluster"] = {
                "status": "OK",
                "timestamp": step_start,
                "n_clusters": result["hdbscan_stats"]["n_clusters"],
                "n_noise": result["hdbscan_stats"]["n_noise"],
                "pca_variance": result["pca_variance"],
                "anomalous_clusters": result["anomalous_clusters"],
            }

    except Exception as exc:
        logger.error(
            "%s[%s]%s Step 1 FAILED: %s", color, det, reset, exc, exc_info=True
        )
        det_report["steps"]["cluster"] = {
            "status": "FAILED",
            "timestamp": step_start,
            "error": str(exc),
        }
        det_report["status"] = "FAILED"
        det_report["error"] = f"Cluster failed: {exc}"
        return det, det_report, _save_detector_report(det_report, run, session_id, det)

    # ------------------------------------------------------------------ #
    # Step 2: Morphcheck  (CPU)                                           #
    # Failure is non-fatal: we log and continue to ablation/stability.   #
    # ------------------------------------------------------------------ #
    step_start = datetime.now(timezone.utc).isoformat()
    cluster_dir = session_path(run, session_id) / "clusters" / det.lower()
    all_files: list = metadata["files"]
    cluster_cfg = cfg["clustering"]

    try:
        if auto_discovery:
            morph_report_path = cluster_dir / "morphcheck_summary.json"
        else:
            morph_report_path = cluster_dir / "morphcheck_report.json"

        if morph_report_path.exists():
            logger.info("%s[%s]%s Step 2: Morphcheck report already exists. Skipping.", color, det, reset)
            with open(morph_report_path, "r", encoding="utf-8") as f:
                morph_summary = json.load(f)
                
            if auto_discovery:
                # Get stats from the last reference in the summary_results
                res = morph_summary.get("results", {})
                if res:
                    last_ref = list(res.values())[-1]
                    det_report["steps"]["morphcheck"] = {
                        "status": "SKIPPED",
                        "timestamp": step_start,
                        "novel": last_ref.get("novel", 0),
                        "known": last_ref.get("known", 0),
                        "ambiguous": last_ref.get("ambiguous", 0),
                    }
                else:
                    det_report["steps"]["morphcheck"] = {
                        "status": "SKIPPED",
                        "timestamp": step_start,
                        "novel": 0, "known": 0, "ambiguous": 0
                    }
            else:
                det_report["steps"]["morphcheck"] = {
                    "status": "SKIPPED",
                    "timestamp": step_start,
                    "novel": morph_summary.get("novel", 0),
                    "known": morph_summary.get("known", 0),
                    "ambiguous": morph_summary.get("ambiguous", 0),
                }
        else:
            logger.info("%s[%s]%s Step 2: Morphological cross-check...", color, det, reset)
            anomalous_indices: list[int] = []
            anomalous_files: list = []
            anomalous_cluster_ids: list[int] = []

            for cid_str in result["hdbscan_stats"]["cluster_sizes"]:
                cid = int(cid_str)
                if cid >= 0:
                    mask = result["labels"] == cid
                    for idx in np.where(mask)[0]:
                        anomalous_indices.append(idx)
                        anomalous_files.append(all_files[idx])
                        anomalous_cluster_ids.append(cid)

            # if not anomalous_indices:
            #     logger.info(
            #         "%s[%s]%s No anomalous clusters found. Generating empty morphcheck report.",
            #         color, det, reset,
            #     )
            #     morph_summary = {
            #         "total_checked": 0,
            #         "novel": 0,
            #         "known": 0,
            #         "ambiguous": 0,
            #         "novel_files": [],
            #         "details": [],
            #     }
            #     morph_report_path.parent.mkdir(parents=True, exist_ok=True)
            #     with open(morph_report_path, "w", encoding="utf-8") as f:
            #         json.dump(morph_summary, f, indent=2)
            #
            #     det_report["steps"]["morphcheck"] = {
            #         "status": "OK",
            #         "timestamp": step_start,
            #         "novel": 0,
            #         "known": 0,
            #         "ambiguous": 0,
            #     }
            # else:
            anomalous_embeddings = embeddings[anomalous_indices]
            sim_cfg = cfg.get("similarity", {})
            
            summary_results = {}
            all_details = {}

            for ref_path in references:
                ref_name = ref_path.name
                
                if auto_discovery:
                    current_morph_path = morph_report_path.parent / "morphcheck" / f"{ref_path.stem}.json"
                else:
                    current_morph_path = morph_report_path

                try:
                    morph_summary = run_morphological_crosscheck(
                        anomalous_embeddings,
                        anomalous_files,
                        anomalous_cluster_ids,
                        ref_path,
                        current_morph_path,
                        k=sim_cfg.get("k_neighbors", 5),
                        novelty_threshold=sim_cfg.get("novelty_threshold", 0.85),
                        consensus_threshold=sim_cfg.get("consensus_threshold", 0.60),
                    )
                    print_morphological_summary(morph_summary, detector=det)
                    
                    summary_results[ref_name] = {
                        "novel": morph_summary["novel"],
                        "known": morph_summary["known"],
                        "ambiguous": morph_summary["ambiguous"]
                    }
                    all_details[ref_name] = {d["file"]: d["novelty_status"] for d in morph_summary["details"]}
                except Exception as e:
                    logger.error("%s[%s]%s Morphcheck failed for reference %s: %s", color, det, reset, ref_name, e, exc_info=True)
                    continue
            
            if auto_discovery:
                newly_resolved = 0
                still_ambiguous = 0
                still_novel = 0

                if len(references) == 2:
                    ref1 = references[0].name
                    ref2 = references[1].name
                    
                    for file_name, status1 in all_details[ref1].items():
                        status2 = all_details[ref2].get(file_name)
                        if status1 in ["NOVEL", "AMBIGUOUS"] and status2 == "KNOWN":
                            newly_resolved += 1
                        elif status2 == "AMBIGUOUS":
                            still_ambiguous += 1
                        elif status2 == "NOVEL":
                            still_novel += 1
                elif len(references) > 0:
                    last_ref = references[-1].name
                    for file_name, status in all_details[last_ref].items():
                        if status == "AMBIGUOUS":
                            still_ambiguous += 1
                        elif status == "NOVEL":
                            still_novel += 1

                summary_report = {
                    "session_id": session_id,
                    "detector": det,
                    "references_used": [r.name for r in references],
                    "results": summary_results,
                    "comparison": {
                        "newly_resolved": newly_resolved,
                        "still_ambiguous": still_ambiguous,
                        "still_novel": still_novel
                    }
                }
                with open(morph_report_path, "w", encoding="utf-8") as f:
                    json.dump(summary_report, f, indent=2)
                
                if len(references) > 0 and len(summary_results) > 0:
                    det_report["steps"]["morphcheck"] = {
                        "status": "OK",
                        "timestamp": step_start,
                        "references_used": summary_report["references_used"],
                        "results": summary_report["results"],
                        "comparison": summary_report["comparison"],
                    }
            else:
                det_report["steps"]["morphcheck"] = {
                    "status": "OK",
                    "timestamp": step_start,
                    "novel": morph_summary["novel"],
                    "known": morph_summary["known"],
                    "ambiguous": morph_summary["ambiguous"],
                }

    except Exception as exc:
        logger.error(
            "%s[%s]%s Step 2 (morphcheck) FAILED — continuing: %s",
            color, det, reset, exc, exc_info=True,
        )
        det_report["steps"]["morphcheck"] = {
            "status": "FAILED",
            "timestamp": step_start,
            "error": str(exc),
        }

    # ------------------------------------------------------------------ #
    # Step 2b: Similarity Analysis  (CPU)                                 #
    # ------------------------------------------------------------------ #
    step_start = datetime.now(timezone.utc).isoformat()
    try:
        analysis_dir = session_path(run, session_id) / "analysis"
        similarity_report_file = analysis_dir / f"{det}_similarity_analysis.json"

        if similarity_report_file.exists():
            logger.info("%s[%s]%s Step 2b: Similarity analysis report already exists. Skipping.", color, det, reset)
            with open(similarity_report_file, "r", encoding="utf-8") as fh:
                sim_data = json.load(fh)
            
            novel_count = sum(1 for c in sim_data if "NOVEL" in c.get("interpretation", ""))
            
            det_report["steps"]["similarity_analysis"] = {
                "status": "SKIPPED",
                "timestamp": step_start,
                "total_clusters_analyzed": len(sim_data),
                "potential_novel_clusters": novel_count,
                "results": sim_data,
            }
        else:
            if det_report["steps"].get("morphcheck", {}).get("status") in ("OK", "SKIPPED"):
                logger.info("%s[%s]%s Step 2b: Similarity analysis...", color, det, reset)
                from src.similarity_analysis import analyze_similarity
                
                analyze_similarity(
                    session_id=session_id,
                    detector=det,
                    run=run,
                    reference_path=reference_path
                )
                
                sim_data = []
                if similarity_report_file.exists():
                    with open(similarity_report_file, "r", encoding="utf-8") as fh:
                        sim_data = json.load(fh)
                        
                novel_count = sum(1 for c in sim_data if "NOVEL" in c.get("interpretation", ""))
                
                det_report["steps"]["similarity_analysis"] = {
                    "status": "OK",
                    "timestamp": step_start,
                    "total_clusters_analyzed": len(sim_data),
                    "potential_novel_clusters": novel_count,
                    "results": sim_data,
                }
            else:
                logger.info("%s[%s]%s Step 2b: Skipping similarity analysis because morphcheck failed.", color, det, reset)
                det_report["steps"]["similarity_analysis"] = {
                    "status": "SKIPPED",
                    "timestamp": step_start,
                    "reason": "morphcheck failed"
                }

    except Exception as exc:
        logger.error(
            "%s[%s]%s Step 2b (similarity_analysis) FAILED — continuing: %s",
            color, det, reset, exc, exc_info=True,
        )
        det_report["steps"]["similarity_analysis"] = {
            "status": "FAILED",
            "timestamp": step_start,
            "error": str(exc),
        }

    # ------------------------------------------------------------------ #
    # Step 3: Ablation  (GPU — serialised via gpu_lock)                  #
    # Independent of morphcheck; failure does NOT abort stability.        #
    # ------------------------------------------------------------------ #
    step_start = datetime.now(timezone.utc).isoformat()
    ablation_dir = session_path(run, session_id) / "ablation"
    image_paths = [input_dir / Path(f).name for f in all_files]

    try:
        ablation_report_file = ablation_dir / f"ablation_report_{det}.json"

        if ablation_report_file.exists():
            logger.info("%s[%s]%s Step 3: Ablation report already exists. Skipping.", color, det, reset)
            with open(ablation_report_file, "r", encoding="utf-8") as fh:
                ablation_data = json.load(fh)
            det_report["steps"]["ablation"] = {
                "status": "SKIPPED",
                "timestamp": step_start,
                "results": {k: v["ari"] for k, v in ablation_data.get("results", {}).items()},
            }
        else:
            logger.info("%s[%s]%s Step 3: Ablation study...", color, det, reset)
            run_ablation_study(
                original_labels=result["labels"],
                image_paths=image_paths,
                cluster_cfg=cluster_cfg,
                output_dir=ablation_dir,
                session_id=session_id,
                detector=det,
                gpu_lock=gpu_lock,
                batch_size=batch_size,
            )


            if ablation_report_file.exists():
                with open(ablation_report_file, "r", encoding="utf-8") as fh:
                    ablation_data = json.load(fh)
                det_report["steps"]["ablation"] = {
                    "status": "OK",
                    "timestamp": step_start,
                    "results": {k: v["ari"] for k, v in ablation_data["results"].items()},
                }
            else:
                det_report["steps"]["ablation"] = {
                    "status": "FAILED",
                    "timestamp": step_start,
                    "error": "Report file not found after run",
                }

    except Exception as exc:
        logger.error(
            "%s[%s]%s Step 3 (ablation) FAILED — continuing to stability: %s",
            color, det, reset, exc, exc_info=True,
        )
        det_report["steps"]["ablation"] = {
            "status": "FAILED",
            "timestamp": step_start,
            "error": str(exc),
        }

    # ------------------------------------------------------------------ #
    # Step 4: Stability  (CPU — fully parallel-safe)                     #
    # Independent of ablation; always attempted if embeddings are valid. #
    # ------------------------------------------------------------------ #
    step_start = datetime.now(timezone.utc).isoformat()

    try:
        stability_report_file = (
                session_path(run, session_id) / "stability" / f"stability_report_{det}.json"
        )
        if stability_report_file.exists():
            logger.info("%s[%s]%s Step 4: Stability report already exists. Skipping.", color, det, reset)
            with open(stability_report_file, "r", encoding="utf-8") as fh:
                stability_data = json.load(fh)
            det_report["steps"]["stability"] = {
                "status": "SKIPPED",
                "timestamp": step_start,
                "mean_ari": stability_data.get("ari_stats", {}).get("mean", 0.0),
                "stable_anomalous_clusters": stability_data.get("stable_anomalous_clusters_baseline_ids", []),
            }
        else:
            logger.info("%s[%s]%s Step 4: Stability analysis...", color, det, reset)
            run_stability_analysis(
                embeddings=embeddings,
                cluster_cfg=cluster_cfg,
                n_runs=n_runs,
                session_id=session_id,
                detector=det,
                run=run,
            )

            if stability_report_file.exists():
                with open(stability_report_file, "r", encoding="utf-8") as fh:
                    stability_data = json.load(fh)
                det_report["steps"]["stability"] = {
                    "status": "OK",
                    "timestamp": step_start,
                    "mean_ari": stability_data["ari_stats"]["mean"],
                    "stable_anomalous_clusters": stability_data[
                        "stable_anomalous_clusters_baseline_ids"
                    ],
                }
            else:
                det_report["steps"]["stability"] = {
                    "status": "FAILED",
                    "timestamp": step_start,
                    "error": "Report file not found after run",
                }

    except Exception as exc:
        logger.error(
            "%s[%s]%s Step 4 (stability) FAILED: %s",
            color, det, reset, exc, exc_info=True,
        )
        det_report["steps"]["stability"] = {
            "status": "FAILED",
            "timestamp": step_start,
            "error": str(exc),
        }

    # ------------------------------------------------------------------ #
    # Aggregate overall status                                            #
    # ------------------------------------------------------------------ #
    failed_steps = [s for s, v in det_report["steps"].items() if v.get("status") == "FAILED"]
    if failed_steps:
        det_report["status"] = "PARTIAL"
        det_report["failed_steps"] = failed_steps
        logger.warning(
            "%s[%s]%s Completed with failures in: %s",
            color, det, reset, failed_steps,
        )
    else:
        det_report["status"] = "OK"
        logger.info("%s[%s]%s All steps completed successfully.%s", color, det, reset, reset)

    return det, det_report, _save_detector_report(det_report, run, session_id, det)


def run_full_analysis(
        session_id: str,
        detectors: list[str] | None = None,
        run: str = "O4a",
        skip_timeslide: bool = False,
        n_runs: int = 20,
        reference_path: str | None = None,
        batch_size: int = 32,
        sequential: bool = False,
) -> dict:
    """Run the full analysis pipeline for one or more detectors.

    Args:
        session_id: The session ID to analyze.
        detectors: List of detectors (e.g. ['H1', 'L1']). If None, auto-discovers.
        run: Observing run (O2, O3a, O3b, O4a).
        skip_timeslide: If True, skips the timeslide analysis.
        n_runs: Number of runs for stability analysis.
        reference_path: Path to the morphological reference index.
        batch_size: Batch size for encoding and ablation.
        sequential: If True, executes detectors in sequence. Default: False (parallel).

    Returns:
        A dictionary containing the status and report paths for each detector
        and timeslide.

    Notes on parallelism
    --------------------
    When ``sequential=False`` each detector runs in its own thread.
    GPU-heavy steps (encode, ablation) share a single ``threading.Lock``
    (``_gpu_lock``) so they never execute concurrently even across threads.
    CPU-only steps (cluster, morphcheck, stability) run fully in parallel.
    """
    run_lower = run.lower()
    cfg = load_config()

    # 1. Discovery
    if not detectors:
        spec_dir = session_path(run, session_id) / "spectrograms"
        if not spec_dir.exists():
            logger.error("Session directory not found: %s", spec_dir)
            return {"status": "FAILED", "error": "Session directory not found"}

        detectors = [
            d.name
            for d in spec_dir.iterdir()
            if d.is_dir() and d.name.upper() in ("H1", "L1", "V1")
        ]
        logger.info("Auto-discovered detectors: %s", detectors)

    if not detectors:
        logger.error("No detectors found for session %s", session_id)
        return {"status": "FAILED", "error": "No detectors found"}

    overall_status: dict[str, str] = {}
    reports: dict[str, Path] = {}

    # 2. Per-detector analysis
    if sequential or len(detectors) == 1:
        # Sequential execution — no parallelism, gpu_lock still passed for consistency
        for det in detectors:
            det_name, det_report, report_path = _analyze_detector(
                det, session_id, run, run_lower, cfg, n_runs, reference_path, batch_size,
                gpu_lock=_gpu_lock,
            )
            reports[det_name] = report_path
            overall_status[det_name] = det_report["status"]
    else:
        # Parallel execution.
        # All threads share the same _gpu_lock so GPU-heavy operations
        # (encode, ablation) are serialised while CPU steps run in parallel.
        logger.info(
            "Starting parallel analysis for detectors: %s "
            "(GPU steps serialised via _gpu_lock)",
            detectors,
        )
        with ThreadPoolExecutor(max_workers=len(detectors)) as executor:
            futures = {
                executor.submit(
                    _analyze_detector,
                    det, session_id, run, run_lower, cfg, n_runs, reference_path, batch_size,
                    _gpu_lock,  # shared lock — passed explicitly
                ): det
                for det in detectors
            }
            for future in as_completed(futures):
                det = futures[future]
                try:
                    det_name, det_report, report_path = future.result()
                    reports[det_name] = report_path
                    overall_status[det_name] = det_report["status"]
                    logger.info(
                        "Detector %s finished with status: %s",
                        det_name, det_report["status"],
                    )
                except Exception as exc:
                    logger.error(
                        "Parallel analysis raised an unhandled exception for %s: %s",
                        det, exc, exc_info=True,
                    )
                    overall_status[det.upper()] = "FAILED"

    # 3. Timeslide (if H1 and L1 are both OK or PARTIAL)
    h1_ok = overall_status.get("H1") in ("OK", "PARTIAL")
    l1_ok = overall_status.get("L1") in ("OK", "PARTIAL")

    if not skip_timeslide and "H1" in overall_status and "L1" in overall_status:
        if h1_ok and l1_ok:
            ts_color = _get_det_color("TIMESLIDE")
            reset = _reset_color()
            logger.info("%s=== Starting Timeslide Analysis (H1 + L1) ===%s", ts_color, reset)
            step_start = datetime.now(timezone.utc).isoformat()

            try:
                meta_h1 = session_path(run, session_id) / "embeddings" / f"{run_lower}_h1.json"
                rep_h1 = session_path(run, session_id) / "clusters" / "h1" / "cluster_report.json"
                meta_l1 = session_path(run, session_id) / "embeddings" / f"{run_lower}_l1.json"
                rep_l1 = session_path(run, session_id) / "clusters" / "l1" / "cluster_report.json"
                output_dir = session_path(run, session_id) / "timeslide"
                timeslide_report_path = output_dir / "timeslide_report_H1_L1.json"

                if timeslide_report_path.exists():
                    logger.info("%s=== Timeslide report already exists. Skipping. ===%s", ts_color, reset)
                    with open(timeslide_report_path, "r", encoding="utf-8") as fh:
                        ts_report = json.load(fh)
                else:
                    ts_cfg = cfg.get("timeslide", {})
                    ts_iterations: int = ts_cfg.get("iterations", 100)
                    ts_window: int = ts_cfg.get("window", 32)

                    ts_report = run_timeslide(
                        meta_h1=meta_h1,
                        rep_h1=rep_h1,
                        meta_l1=meta_l1,
                        rep_l1=rep_l1,
                        output_dir=output_dir,
                        iterations=ts_iterations,
                        window=ts_window,
                    )

                reports["timeslide"] = timeslide_report_path
                overall_status["timeslide"] = "OK"

                # Annotate each detector's report with timeslide results
                for det in ("H1", "L1"):
                    r_path = reports.get(det)
                    if r_path and r_path.exists():
                        with open(r_path, "r", encoding="utf-8") as fh:
                            r_data = json.load(fh)
                        r_data["steps"]["timeslide"] = {
                            "status": "OK",
                            "timestamp": step_start,
                            "p_value": ts_report["p_value"],
                            "z_score": ts_report["z_score"],
                        }
                        with open(r_path, "w", encoding="utf-8") as fh:
                            json.dump(r_data, fh, indent=2)

            except Exception as exc:
                logger.error("Error during timeslide analysis: %s", exc, exc_info=True)
                overall_status["timeslide"] = "FAILED"
        else:
            logger.info("Skipping timeslide: H1 or L1 analysis did not complete.")
            overall_status["timeslide"] = "SKIPPED (dependencies failed)"
    else:
        overall_status["timeslide"] = "SKIPPED"

    return {
        "session_id": session_id,
        "run": run,
        "detectors": detectors,
        "status": overall_status,
        "reports": {k: str(v) for k, v in reports.items()},
    }


def generate_reports_only(session_id: str, run: str = "O4a") -> dict:
    """Re-generate the final summary reports by parsing individual step reports.

    This function does not execute any computational steps (e.g. clustering or
    ablation). It only aggregates existing reports.
    """
    run_lower = run.lower()
    session_dir = session_path(run, session_id)
    
    if not session_dir.exists():
        logger.error("Session directory not found: %s", session_dir)
        return {"status": "FAILED", "error": "Session directory not found"}

    # Discover detectors
    detectors = []
    clusters_dir = session_dir / "clusters"
    if clusters_dir.exists():
        detectors = [d.name.upper() for d in clusters_dir.iterdir() if d.is_dir() and d.name.upper() in ("H1", "L1", "V1")]
    if not detectors:
        spec_dir = session_dir / "spectrograms"
        if spec_dir.exists():
            detectors = [d.name.upper() for d in spec_dir.iterdir() if d.is_dir() and d.name.upper() in ("H1", "L1", "V1")]
            
    if not detectors:
        logger.error("No detectors found for session %s", session_id)
        return {"status": "FAILED", "error": "No detectors found"}

    overall_status = {}
    reports = {}
    ts_report_data = None
    
    # Read timeslide if available
    timeslide_path = session_dir / "timeslide" / "timeslide_report_H1_L1.json"
    if timeslide_path.exists():
        try:
            with open(timeslide_path, "r", encoding="utf-8") as fh:
                ts_report_data = json.load(fh)
            overall_status["timeslide"] = "OK"
            reports["timeslide"] = timeslide_path
        except Exception as exc:
            logger.warning("Could not read timeslide report: %s", exc)
            overall_status["timeslide"] = "FAILED"
    else:
        overall_status["timeslide"] = "SKIPPED"

    for det in detectors:
        det_lower = det.lower()
        color = _get_det_color(det)
        reset = _reset_color()
        logger.info("%s=== Generating Full Report for %s ===%s", color, det, reset)
        
        det_report: dict = {
            "session_id": session_id,
            "detector": det,
            "run": run,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "steps": {},
        }
        
        # Spectrogram statistics
        input_dir = session_dir / "spectrograms" / det
        if input_dir.exists():
            png_files = list(input_dir.glob(f"{det}_*.png"))
            gps_starts, gps_ends = [], []
            for f in png_files:
                parts = f.stem.split("_")
                if len(parts) >= 3:
                    try:
                        gps_starts.append(int(parts[1]))
                        gps_ends.append(int(parts[2]))
                    except ValueError:
                        continue
            if gps_starts:
                g_start, g_end = min(gps_starts), max(gps_ends)
                n_specs = len(png_files)
                duration_hours = round((g_end - g_start) / 3600, 1)
                duty_cycle = round((n_specs * 32) / (duration_hours * 3600) * 100, 1) if duration_hours > 0 else 0.0
                det_report["session_summary"] = {
                    "n_spectrograms": n_specs, "gps_start": g_start, "gps_end": g_end,
                    "duration_hours": duration_hours, "duty_cycle_percent": duty_cycle,
                }
            else:
                det_report["session_summary"] = {"n_spectrograms": 0, "gps_start": 0, "gps_end": 0, "duration_hours": 0.0, "duty_cycle_percent": 0.0}
        else:
            det_report["session_summary"] = {"n_spectrograms": 0, "gps_start": 0, "gps_end": 0, "duration_hours": 0.0, "duty_cycle_percent": 0.0}

        # Embeddings
        embed_json = session_dir / "embeddings" / f"{run_lower}_{det_lower}.json"
        if embed_json.exists():
            det_report["steps"]["encode"] = {"status": "OK", "timestamp": datetime.fromtimestamp(embed_json.stat().st_mtime, timezone.utc).isoformat()}
        else:
            det_report["steps"]["encode"] = {"status": "SKIPPED", "timestamp": det_report["timestamp"]}

        # Cluster
        cluster_rep_path = session_dir / "clusters" / det_lower / "cluster_report.json"
        if cluster_rep_path.exists():
            try:
                with open(cluster_rep_path, "r", encoding="utf-8") as fh:
                    cl_data = json.load(fh)
                det_report["steps"]["cluster"] = {
                    "status": "OK",
                    "timestamp": cl_data.get("timestamp", datetime.fromtimestamp(cluster_rep_path.stat().st_mtime, timezone.utc).isoformat()),
                    "n_clusters": cl_data.get("results", {}).get("n_clusters", 0),
                    "n_noise": cl_data.get("results", {}).get("n_noise", 0),
                    "pca_variance": cl_data.get("pipeline", {}).get("pca_variance_explained", 0.0),
                    "anomalous_clusters": cl_data.get("results", {}).get("anomalous_clusters", []),
                }
            except Exception as e:
                det_report["steps"]["cluster"] = {"status": "FAILED", "error": str(e), "timestamp": det_report["timestamp"]}
        else:
            det_report["steps"]["cluster"] = {"status": "SKIPPED", "timestamp": det_report["timestamp"]}

        # Morphcheck
        morph_rep_path = session_dir / "clusters" / det_lower / "morphcheck_report.json"
        if morph_rep_path.exists():
            try:
                with open(morph_rep_path, "r", encoding="utf-8") as fh:
                    m_data = json.load(fh)
                det_report["steps"]["morphcheck"] = {
                    "status": "OK",
                    "timestamp": m_data.get("timestamp", datetime.fromtimestamp(morph_rep_path.stat().st_mtime, timezone.utc).isoformat()),
                    "novel": m_data.get("novel", 0),
                    "known": m_data.get("known", 0),
                    "ambiguous": m_data.get("ambiguous", 0),
                }
            except Exception as e:
                det_report["steps"]["morphcheck"] = {"status": "FAILED", "error": str(e), "timestamp": det_report["timestamp"]}
        else:
            det_report["steps"]["morphcheck"] = {"status": "SKIPPED", "timestamp": det_report["timestamp"]}

        # Similarity Analysis
        sim_rep_path = session_dir / "analysis" / f"{det}_similarity_analysis.json"
        if sim_rep_path.exists():
            try:
                with open(sim_rep_path, "r", encoding="utf-8") as fh:
                    sim_data = json.load(fh)
                    
                novel_count = sum(1 for c in sim_data if "NOVEL" in c.get("interpretation", ""))
                
                det_report["steps"]["similarity_analysis"] = {
                    "status": "OK",
                    "timestamp": datetime.fromtimestamp(sim_rep_path.stat().st_mtime, timezone.utc).isoformat(),
                    "total_clusters_analyzed": len(sim_data),
                    "potential_novel_clusters": novel_count,
                    "results": sim_data,
                }
            except Exception as e:
                det_report["steps"]["similarity_analysis"] = {"status": "FAILED", "error": str(e), "timestamp": det_report["timestamp"]}
        else:
            det_report["steps"]["similarity_analysis"] = {"status": "SKIPPED", "timestamp": det_report["timestamp"]}

        # Ablation
        ablation_rep_path = session_dir / "ablation" / f"ablation_report_{det}.json"
        if ablation_rep_path.exists():
            try:
                with open(ablation_rep_path, "r", encoding="utf-8") as fh:
                    a_data = json.load(fh)
                det_report["steps"]["ablation"] = {
                    "status": "OK",
                    "timestamp": a_data.get("timestamp", datetime.fromtimestamp(ablation_rep_path.stat().st_mtime, timezone.utc).isoformat()),
                    "results": {k: v.get("ari", 0.0) for k, v in a_data.get("results", {}).items()},
                }
            except Exception as e:
                det_report["steps"]["ablation"] = {"status": "FAILED", "error": str(e), "timestamp": det_report["timestamp"]}
        else:
            det_report["steps"]["ablation"] = {"status": "SKIPPED", "timestamp": det_report["timestamp"]}

        # Stability
        stability_rep_path = session_dir / "stability" / f"stability_report_{det}.json"
        if stability_rep_path.exists():
            try:
                with open(stability_rep_path, "r", encoding="utf-8") as fh:
                    s_data = json.load(fh)
                det_report["steps"]["stability"] = {
                    "status": "OK",
                    "timestamp": s_data.get("timestamp", datetime.fromtimestamp(stability_rep_path.stat().st_mtime, timezone.utc).isoformat()),
                    "mean_ari": s_data.get("ari_stats", {}).get("mean", 0.0),
                    "stable_anomalous_clusters": s_data.get("stable_anomalous_clusters_baseline_ids", []),
                }
            except Exception as e:
                det_report["steps"]["stability"] = {"status": "FAILED", "error": str(e), "timestamp": det_report["timestamp"]}
        else:
            det_report["steps"]["stability"] = {"status": "SKIPPED", "timestamp": det_report["timestamp"]}

        # Timeslide mapping
        if ts_report_data:
            det_report["steps"]["timeslide"] = {
                "status": "OK",
                "timestamp": ts_report_data.get("timestamp", det_report["timestamp"]),
                "p_value": ts_report_data.get("p_value", 1.0),
                "z_score": ts_report_data.get("z_score", 0.0),
            }
        else:
            det_report["steps"]["timeslide"] = {"status": "SKIPPED", "timestamp": det_report["timestamp"]}

        # Finalize Status
        failed_steps = [s for s, v in det_report["steps"].items() if v.get("status") == "FAILED"]
        skipped_steps = [s for s, v in det_report["steps"].items() if v.get("status") == "SKIPPED"]
        if failed_steps:
            det_report["status"] = "FAILED"
            det_report["failed_steps"] = failed_steps
        elif skipped_steps:
            det_report["status"] = "PARTIAL"
            det_report["skipped_steps"] = skipped_steps
        else:
            det_report["status"] = "OK"

        report_path = _save_detector_report(det_report, run, session_id, det)
        overall_status[det] = det_report["status"]
        reports[det] = report_path

    return {
        "session_id": session_id,
        "run": run,
        "detectors": detectors,
        "status": overall_status,
        "reports": {k: str(v) for k, v in reports.items()},
    }
