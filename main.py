#!/usr/bin/env python3
"""gravi-signal-ml — CLI entry point.

Provides subcommands for each pipeline stage.  Supports multiple
observing runs via ``--run`` (O2, O3a, O3b, O4a — default O4a).

    fetch                    — Download and process a known reference event (PoC)
    scan                     — Batch-scan segments for a detector
    scan-extended            — Extended scan of H1 + L1 detectors
    reprocess-spectrograms   — Re-render existing spectrograms with updated colormap
    encode                   — Extract DINOv2-Reg embeddings from spectrograms
    cluster                  — Cluster embeddings to discover novel glitch classes
    report                   — Regenerate UMAP and cluster gallery from existing outputs
    crosscheck               — Cross-check anomalous clusters against Gravity Spy
    build-indomain-reference — Build in-domain reference from labeled GPS timestamps
    validate-reference       — Validate reference index with a known event
    benchmark-clustering     — Validate unsupervised clustering using ground truth labels
    benchmark-methods        — Benchmark comparative analysis of clustering methods
    full-analysis            — Automated end-to-end analysis (Cluster, Morph, Ablation, Stability, Timeslide)
    calibrate-threshold      — Calibrate per-class cosine similarity thresholds (Autopilot)
    calibrate-loglikelihood  — Calibrate DPMM log-likelihood anomaly threshold
    scan-live                — Autopilot live scanner: classify spectrograms as KNOWN/NOVEL
    download-all-references  — Download and build in-domain references for multiple runs/detectors
    aggregate-report         — Cross-session aggregation, deduplication, and Spearman stability
    poisson-upper-limit      — Calculate the Poisson Upper Limit on a null-result detector
    pem-coherence-analysis   — Run PEM offline coherence analysis

Usage:
    python main.py fetch                    --event GW150914
    python main.py scan                     --detector H1 --hours 2
    python main.py scan                     --detector H1 --run O3a
    python main.py scan-extended            --workers 6 --hours 72
    python main.py encode                   --session-id 20260510_143022 --detector H1
    python main.py cluster                  --session-id 20260510_143022 --detector H1
    python main.py report                   --session-id 20260510_143022 --detector H1
    python main.py crosscheck               --report data/clusters/cluster_report.json --metadata data/embeddings/o4a_h1_6h.json
    python main.py build-indomain-reference --output data/reference/indomain_index.npz
    python main.py validate-reference       --reference data/reference/indomain_index.npz
    python main.py poisson-upper-limit      # (Defaults to all configured detectors)
    python main.py aggregate-report         # (Aggregates reports and injects offline validation)
    python main.py pem-coherence-analysis   --nds-host nds.gwosc.org

    # Backward-compatible explicit paths (override session-id):
    python main.py encode  --input-dir data/spectrograms/o4a/H1/ --output data/embeddings/o4a_h1_48h.npy
    python main.py cluster --input data/embeddings/o4a_h1_6h.npy --output data/clusters/
"""

from __future__ import annotations
from pathlib import Path

import argparse
import sys
from datetime import datetime


import numpy as np
import astropy.utils.data
from astropy.time import Time

from src.core.data_loader import fetch_o4a_segments, fetch_strain_data
from src.core.encoder import DINOv2Encoder
from src.core.preprocessor import bandpass, batch_process, generate_qtransform, whiten_context, extract_clean_subwindow
from src.core.utils import enable_ansi_colors, load_config, setup_logger, session_path

# Enable ANSI escape sequences for Windows terminal
enable_ansi_colors()

logger = setup_logger("main", log_file=Path("logs/gravi-signal-ml.log"))


# ---------------------------------------------------------------------------
# Multi-run support
# ---------------------------------------------------------------------------

VALID_RUNS: list[str] = ["O2", "O3a", "O3b", "O4a"]


def _resolve_session_id(args: argparse.Namespace) -> str:
    """Return the session ID from args or generate one from current timestamp."""
    if hasattr(args, "session_id") and args.session_id:
        return args.session_id
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _resolve_run(args: argparse.Namespace) -> str:
    """Return the observing run from args (default: O4a)."""
    return getattr(args, "run", "O4a") or "O4a"


def _run_start_gps(run: str, cfg: dict | None = None) -> int:
    """Compute the GPS start time for a given observing run.

    Uses ``run_config[run].start_date`` from config.yaml.
    """
    if cfg is None:
        cfg = load_config()
    run_cfg = cfg.get("run_config", {})
    if run not in run_cfg:
        raise ValueError(f"Unknown run '{run}'. Valid runs: {VALID_RUNS}")
    start_date = run_cfg[run]["start_date"]
    gps = int(Time(start_date, format="iso", scale="utc").gps)
    return gps


def _log_run_header(run: str, detector: str | None, session_id: str) -> None:
    """Log the standard run header at command start."""
    det_str = detector or "ALL"
    logger.info("Run: %s | Detector: %s | Session: %s", run, det_str, session_id)


def str2bool(v: str | bool) -> bool:
    """Parse common boolean strings into actual bools."""
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")
def _find_first_gps(session_id: str, detector: str, run: str = "O4a") -> int | None:
    """Scan existing PNGs and return the lowest GPS start-time, or None."""
    import re
    spec_dir = session_path(run, session_id) / "spectrograms" / detector
    if not spec_dir.exists():
        return None
    pattern = re.compile(r"^[A-Z]\d_(\d+)_(\d+)\.png$")
    min_gps = float('inf')
    for png_file in spec_dir.glob("*.png"):
        m = pattern.match(png_file.name)
        if m:
            start_gps = int(m.group(1))
            if start_gps < min_gps:
                min_gps = start_gps
    return int(min_gps) if min_gps < float('inf') else None


def _find_last_gps(session_id: str, detector: str, run: str = "O4a") -> int | None:
    """Scan existing PNGs and return the highest GPS end-time, or None.

    Filename convention: ``<detector>_<gps_start>_<gps_end>.png``.
    """
    import re

    spec_dir = session_path(run, session_id) / "spectrograms" / detector
    if not spec_dir.exists():
        return None

    pattern = re.compile(r"^[A-Z]\d_(\d+)_(\d+)\.png$")
    max_gps = 0
    count = 0
    for png_file in spec_dir.glob("*.png"):
        m = pattern.match(png_file.name)
        if m:
            end_gps = int(m.group(2))
            if end_gps > max_gps:
                max_gps = end_gps
            count += 1

    return max_gps if count > 0 else None


def parse_stop_date_to_gps(stop_date_str: str) -> int:
    """Parse a stop date (ISO string or GPS time) to GPS integer."""
    try:
        return int(stop_date_str)
    except ValueError:
        pass

    for fmt in ["iso", "isot", "fits", "yday"]:
        try:
            return int(Time(stop_date_str, format=fmt, scale="utc").gps)
        except Exception:
            continue
    try:
        return int(Time(stop_date_str, scale="utc").gps)
    except Exception as e:
        raise ValueError(f"Could not parse stop date '{stop_date_str}': {e}")


def _run_continue_loop(
    initial_session_id: str,
    run: str,
    max_iterations: int,
    stop_date_str: str | None,
    args: argparse.Namespace,
) -> None:
    """Run the continuous scan-extended + full-analysis loop."""
    import time
    logger.info("=== Starting Continuous Run Loop ===")
    logger.info("Initial Session: %s", initial_session_id)
    logger.info("Max Iterations: %d", max_iterations)
    
    stop_gps = None
    if stop_date_str:
        logger.info("Stop Date: %s", stop_date_str)
        try:
            stop_gps = parse_stop_date_to_gps(stop_date_str)
            logger.info("Stop GPS: %d", stop_gps)
        except Exception as e:
            logger.error("Invalid stop-date: %s", e)
            sys.exit(1)

    current_session_id = initial_session_id
    cfg = load_config()
    
    run_cfg = cfg.get("run_config", {})
    if run not in run_cfg:
        logger.error("Unknown run '%s'. Valid runs: %s", run, VALID_RUNS)
        sys.exit(1)
    hours = run_cfg[run]["hours_per_detector"]
    logger.info("Iteration scan duration: %d hours per detector", hours)

    # Determina il GPS sincronizzato iniziale
    ultimo_H1 = _find_last_gps(current_session_id, "H1", run=run)
    ultimo_L1 = _find_last_gps(current_session_id, "L1", run=run)
    
    if ultimo_H1 is None or ultimo_L1 is None:
        gps_sincronizzato = getattr(args, "start_gps", None)
        if gps_sincronizzato is None:
            gps_sincronizzato = _run_start_gps(run, cfg)
        logger.info("Initial session %s empty. Synchronized GPS = %d", current_session_id, gps_sincronizzato)
    else:
        gps_sincronizzato = min(ultimo_H1, ultimo_L1)
        logger.info(
            "Initial session %s ends: H1=%s, L1=%s. Synchronized GPS = %d",
            current_session_id, ultimo_H1, ultimo_L1, gps_sincronizzato
        )

    for iteration in range(1, max_iterations + 1):
        logger.info("--- Continuous Run Loop: Iteration %d / %d ---", iteration, max_iterations)
        
        next_start_gps = gps_sincronizzato + 1
        logger.info("Next iteration start GPS: %d", next_start_gps)
        
        # Check stop date limit
        if stop_gps is not None and next_start_gps >= stop_gps:
            logger.info("Reached or exceeded stop date (GPS %d >= %d). Stopping loop.", next_start_gps, stop_gps)
            break
            
        # 3. Genera un nuovo session-id
        time.sleep(1.0)  # avoid collision
        new_session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        logger.info("Generated new session ID: %s", new_session_id)
        
        # Update the active session log file to target the new session directory
        from src.core.utils import set_session_log_file
        new_log_dir = session_path(run, new_session_id) / "logs"
        new_log_file = new_log_dir / "session.log"
        set_session_log_file(new_log_file)
        
        logger.info(
            "=== CONTINUOUS RUN LOOP: NEW ITERATION SESSION STARTED: %s ===", 
            new_session_id, 
            extra={"session_key": True}
        )
        
        # 4. Lancia automaticamente scan-extended sulla nuova sessione
        logger.info("Launching scan-extended on session %s starting from GPS %d...", new_session_id, next_start_gps)
        
        scan_args = argparse.Namespace(
            run=run,
            session_id=new_session_id,
            hours=hours,
            workers=args.workers if hasattr(args, "workers") else 2,
            no_cache_raw=args.no_cache_raw if hasattr(args, "no_cache_raw") else True,
            full_analysis=False,  # We handle full-analysis manually in the loop
            skip_timeslide=args.skip_timeslide if hasattr(args, "skip_timeslide") else False,
            n_runs=args.n_runs if hasattr(args, "n_runs") else 20,
            sequential=args.sequential if hasattr(args, "sequential") else False,
            start_gps=next_start_gps,
        )
        
        try:
            cmd_scan_extended(scan_args)
        except Exception as e:
            logger.error("scan-extended failed in iteration %d: %s", iteration, e, exc_info=True)
            break
            
        if getattr(args, "full_analysis", False):
            # 5. Al termine dello scan, rilancia automaticamente full-analysis sulla nuova sessione
            logger.info("Launching full-analysis on session %s...", new_session_id)
            from src.pipeline_v1_legacy.full_analysis import run_full_analysis
            
            try:
                result = run_full_analysis(
                    session_id=new_session_id,
                    detectors=["H1", "L1"],
                    run=run,
                    skip_timeslide=scan_args.skip_timeslide,
                    n_runs=scan_args.n_runs,
                    sequential=scan_args.sequential,
                )
                
                status_val = result.get("status")
                is_failed = False
                if status_val == "FAILED":
                    is_failed = True
                elif isinstance(status_val, dict) and any(v == "FAILED" for v in status_val.values()):
                    is_failed = True
    
                if is_failed:
                    logger.error("full-analysis failed in iteration %d: %s", iteration, result.get("error"))
                    # Non interrompere il ciclo, prosegui alla prossima iterazione
            except Exception as e:
                logger.error("full-analysis failed in iteration %d: %s", iteration, e, exc_info=True)
                # Non interrompere il ciclo, prosegui alla prossima iterazione
            
        # Update gps_sincronizzato per la prossima iterazione
        u_H1 = _find_last_gps(new_session_id, "H1", run=run)
        u_L1 = _find_last_gps(new_session_id, "L1", run=run)
        if u_H1 is None or u_L1 is None:
            gps_sincronizzato = next_start_gps + int(hours * 3600)
        else:
            gps_sincronizzato = min(u_H1, u_L1)
            
        # Advance to the new session
        current_session_id = new_session_id

    logger.info("=== Continuous Run Loop Completed ===")


def cmd_fetch(args: argparse.Namespace) -> None:
    """Fetch a known reference event, preprocess it, and save a spectrogram."""
    cfg = load_config()
    event_name: str = args.event

    if event_name not in cfg["reference_events"]:
        available = ", ".join(cfg["reference_events"].keys())
        logger.error("Unknown event '%s'. Available: %s", event_name, available)
        sys.exit(1)

    event = cfg["reference_events"][event_name]
    detector = event["detector"]
    gps_start = event["start"]
    gps_end = event["end"]

    logger.info("=== FETCH: %s (%s) ===", event_name, detector)

    # 1. Fetch strain data
    ts_super = fetch_strain_data(detector, gps_start - 4.0, gps_end + 4.0, edge_tolerance=4.0)

    # 2. Whiten
    ts_w_padded, _ = whiten_context(ts_super, gps_start, gps_end, pad=4.0)
    ts_bp = extract_clean_subwindow(ts_w_padded, gps_start, gps_end)  # already whitened+bandpassed

    # 4. Generate Q-transform spectrogram
    output_dir = Path("data/spectrograms")
    output_dir.mkdir(parents=True, exist_ok=True)
    save_path = output_dir / f"{event_name}_{detector}.png"

    spectrogram = generate_qtransform(ts_bp, save_path=save_path)

    logger.info(
        "Phase 1 complete. Chirp visible at %s (shape: %s)",
        save_path,
        spectrogram.shape,
    )


def cmd_scan(args: argparse.Namespace) -> None:
    """Batch-scan segments for a given detector and observing run.

    Incremental mode (automatic):
        When ``--session-id`` is provided and the session directory already
        contains spectrograms, the scan resumes from the highest GPS
        end-time found in the existing filenames.  The resume window is
        ``last_gps … last_gps + run_config[run].hours_per_detector * 3600``
        (read from config.yaml, **not** from ``--hours``).

        If ``--session-id`` is provided but the directory is empty, the
        scan starts from ``run_config[run].start_date + 6h``.
    """
    if getattr(args, "reprocess", False):
        _reprocess_spectrograms(args)
        return

    from src.core.data_loader import generate_segments_from_gps_range

    detector: str = args.detector
    run = _resolve_run(args)
    run_lower = run.lower()
    session_id = _resolve_session_id(args)
    cfg = load_config()

    hours = getattr(args, "hours", None)
    if hours is None:
        run_cfg = cfg.get("run_config", {}).get(run, {})
        hours = float(run_cfg.get("hours_per_detector", 72.0))

    from src.core.logging_utils import PhaseTracker
    from src.core.utils import setup_logger
    cmd_logger = setup_logger("main.scan", log_file=Path("logs/gravi-signal-ml.log"), session_id=session_id, run=run, detector=detector)
    tracker = PhaseTracker(cmd_logger, "scan", session_id, run, detector)

    _log_run_header(run, detector, session_id)

    # --- Incremental logic ---------------------------------------------------
    explicit_session = hasattr(args, "session_id") and args.session_id
    last_gps: int | None = None

    if explicit_session:
        last_gps = _find_last_gps(session_id, detector, run=run)

    # --- Raw Path Logic ---
    raw_path = getattr(args, "raw_path", None)
    if not raw_path:
        from src.core.data_loader import _find_latest_raw_session, _find_raw_session_by_id
        raw_path = _find_raw_session_by_id(session_id)
        if not raw_path:
            raw_path = _find_latest_raw_session()
        
    if raw_path:
        import re
        
        raw_path = Path(raw_path)
        logger.info("Using raw session: %s", raw_path)
        segment_length = 4096
        
        min_start = float('inf')
        max_end = 0
        pattern = re.compile(rf"^{detector}_(\d+)_(\d+)\.hdf5$")
        for f in raw_path.glob("*.hdf5"):
            m = pattern.match(f.name)
            if m:
                min_start = min(min_start, int(m.group(1)))
                max_end = max(max_end, int(m.group(2)))
                
        if min_start < float('inf') and max_end > 0:
            if last_gps is not None:
                start_gps = last_gps
                logger.info("Resuming session %s from GPS %d", session_id, last_gps)
                if start_gps >= max_end:
                    logger.info("I dati in raw_path terminano al GPS %d, ma la sessione è già al GPS %d. Scan completato.", max_end, start_gps)
                    sys.exit(0)
            else:
                start_gps = min_start
                logger.info("=== SCAN: %s [%s] ===", detector, run)
                logger.info("Auto-detected start GPS da raw_path: %d", start_gps)
            end_gps = max_end
            logger.info("Auto-detected end GPS da raw_path: %d", end_gps)
        else:
            logger.warning("Nessun file HDF5 valido per %s in %s. Fallback a config standard.", detector, raw_path)
            if last_gps is not None:
                resume_hours = cfg["run_config"][run]["hours_per_detector"]
                start_gps = last_gps
                end_gps = last_gps + int(resume_hours * 3600)
                logger.info("Resuming session %s from GPS %d (+%.1fh)", session_id, last_gps, resume_hours)
            else:
                start_gps = _run_start_gps(run, cfg)
                end_gps = start_gps + int(hours * 3600)
                logger.info("=== SCAN: %s [%s], %.1f hours ===", detector, run, hours)
    else:
        segment_length = 4096
        if last_gps is not None:
            resume_hours = cfg["run_config"][run]["hours_per_detector"]
            start_gps = last_gps
            end_gps = last_gps + int(resume_hours * 3600)
            logger.info("Resuming session %s from GPS %d (+%.1fh)", session_id, last_gps, resume_hours)
        else:
            start_gps = _run_start_gps(run, cfg)
            end_gps = start_gps + int(hours * 3600)
            logger.info("=== SCAN: %s [%s], %.1f hours ===", detector, run, hours)

    tracker.start(gps_start=start_gps)

    segments = generate_segments_from_gps_range(start_gps, end_gps, segment_length=segment_length)

    if not segments:
        logger.warning("No segments found for %s in the requested window.", detector)
        sys.exit(0)

    # Output directory — isolated by run and session_id
    output_dir = session_path(run, session_id) / "spectrograms" / detector
    logger.info("Output dir: %s", output_dir)

    workers: int = args.workers

    # Run batch processing
    if workers == 1:
        saved_paths = batch_process(segments, detector, output_dir)
        processed_count = len(saved_paths)
    else:
        from src.core.parallel_processor import batch_process_parallel
        cfg = load_config()  # noqa: F841 — needed by batch_process_parallel
        fetch_workers = cfg.get("performance", {}).get("gwosc_fetch_threads", 4)
        processed_count, _ = batch_process_parallel(
            segments, detector, output_dir, cfg, workers=workers, fetch_workers=fetch_workers, cache_raw=not args.no_cache_raw
        )

    total_duration = sum(end - start for start, end in segments)

    try:
        astropy.utils.data.clear_download_cache()
        logger.info("Cleaned astropy download cache.")
    except Exception:
        pass

    logger.info(
        "Scan complete: %d processed, %d skipped, %.1f h scanned",
        processed_count,
        len(segments) - processed_count,
        total_duration / 3600,
    )
    
    tracker.end(gps_end=end_gps, n_processed=processed_count, n_total=len(segments))


def _gwosc_download_worker(detector: str, start: int, end: int, filepath: Path, cache_raw: bool):
    """Standalone worker to fetch GWOSC data in a separate process to enforce hard timeouts."""
    import os
    import tempfile
    import warnings
    warnings.filterwarnings("ignore")
    
    # Isola completamente la cache di astropy per evitare OSError: file exist in multiprocessing
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["ASTROPY_CACHE_DIR"] = tmpdir
        from gwpy.timeseries import TimeSeries
        ts = TimeSeries.fetch_open_data(
            detector,
            start,
            end,
            verbose=False,
            cache=False,
        )
        if cache_raw:
            ts.write(filepath, format="hdf5", overwrite=True)


def _fetch_single_block(detector: str, start: int, end: int, output_dir: Path, retry_delays: list[int], base_delay: float, cache_raw: bool) -> tuple[bool, str]:
    import time
    from gwpy.timeseries import TimeSeries

    filename = f"{detector}_{start}_{end}.hdf5"
    filepath = output_dir / filename

    if cache_raw and filepath.exists():
        return True, f"File {filename} already exists. Skipping."

    success = False
    for attempt, backoff in enumerate(retry_delays):
        try:
            while True:
                time.sleep(base_delay)
                import multiprocessing
                p = multiprocessing.Process(
                    target=_gwosc_download_worker,
                    args=(detector, start, end, filepath, cache_raw)
                )
                p.start()
                # GWOSC 4096s block usually downloads in 20-40 seconds. 
                # If the server is broken, it hangs forever. So timeout at 180s.
                p.join(180)
                if p.is_alive():
                    p.terminate()
                    p.join()
                    # Aggiungiamo un ritardo in caso di timeout per non floodare
                    base_delay += 0.3
                    time.sleep(2.0)
                    raise TimeoutError(f"GWOSC server hanging/timeout after 180s")
                
                if p.exitcode != 0:
                    raise RuntimeError(f"Download worker failed with exit code {p.exitcode}")
                
                break # success

            success = True
            return True, f"Saved {filename}" if cache_raw else f"Fetched {filename} (cache disabled)"
        except Exception as e:
            if attempt < len(retry_delays) - 1:
                time.sleep(backoff)
            else:
                return False, f"Failed {filename}: {e}"
    return False, f"Failed {filename}"


def cmd_fetch_raw(args: argparse.Namespace) -> None:
    """Standalone downloader for raw GWOSC strain data."""
    import re
    from concurrent.futures import ThreadPoolExecutor, wait

    run = _resolve_run(args)
    cfg = load_config()

    hours: float = args.hours if args.hours is not None else float(cfg.get("run_config", {}).get(run, {}).get("hours_per_detector", 72.0))
    base_dir_str: str = args.output_dir
    segment_duration: int = args.segment_duration

    base_dir = Path(base_dir_str)
    base_dir.mkdir(parents=True, exist_ok=True)

    continue_download = getattr(args, "continue_download", False)
    loop_download = getattr(args, "loop", False)
    max_iterations = getattr(args, "max_iterations", 100)
    workers = args.workers
    cache_raw = True
    resume = getattr(args, "resume", True)

    detectors = args.detector if args.detector else ["H1", "L1"]

    if workers == 1 or workers % 2 != 0:
        logger.error("Errore: --workers deve essere un numero pari maggiore di 1 (es. 2, 4, 6, 8).")
        sys.exit(1)
    if workers > 8:
        logger.error("Errore: il limite massimo è di 4 thread per detector (--workers 8).")
        sys.exit(1)

    session_id = getattr(args, "session_id", None)
    run_start = getattr(args, "start_gps", None)
    
    if session_id is not None:
        run_start = session_id

    if run_start is None:
        run_start = _run_start_gps(run, cfg)

    if session_id is None and getattr(args, "start_gps", None) is None:
        aligned_start = (run_start // 4096) * 4096
        if aligned_start != run_start:
            logger.warning("GPS di partenza allineato da %d a %d per evitare boundary bug", run_start, aligned_start)
            run_start = aligned_start

    run_end = cfg.get(f"{run.lower()}_window", {}).get("gps_end", 9999999999)
    folder_size = int(hours * 3600)
    current_folder_start = run_start

    if continue_download:
        if session_id is not None:
            # Se è specificato il session_id e --continue, partiamo esattamente dal session_id 
            # colmando i buchi e impostiamo il loop per continuare con i successivi.
            loop_download = True
            logger.info("Session ID %d specificato con --continue. Il download riprenderà da questa cartella e continuerà in loop.", current_folder_start)
        else:
            logger.info("Ricerca prima cartella incompleta a partire da %d...", current_folder_start)
            while current_folder_start < run_end:
                folder_path = base_dir / str(current_folder_start)
                expected_end = current_folder_start + folder_size
                if expected_end > run_end:
                    expected_end = run_end
                    
                missing_files = False
                if not folder_path.exists():
                    missing_files = True
                else:
                    for det in detectors:
                        s = current_folder_start
                        while s < expected_end:
                            e = min(s + segment_duration, expected_end)
                            if not (folder_path / f"{det}_{s}_{e}.hdf5").exists():
                                missing_files = True
                                break
                            s += segment_duration
                        if missing_files:
                            break
                
                if missing_files:
                    logger.info("Trovata cartella da completare: %d", current_folder_start)
                    break
                
                current_folder_start += folder_size

    if current_folder_start >= run_end:
        logger.info("Tutti i dati fino a %d sono già stati scaricati o non ci sono più dati da scaricare.", run_end)
        print("Download completato.")
        return

    iteration = 0
    while current_folder_start < run_end:
        if iteration >= max_iterations:
            logger.info("Raggiunto il limite massimo di iterazioni (%d). Termino il loop.", max_iterations)
            break
            
        expected_end_gps = current_folder_start + folder_size
        if expected_end_gps > run_end:
            expected_end_gps = run_end

        output_dir = base_dir / str(current_folder_start)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=== FETCH-RAW: %s [%s] (Loop %d) ===", detectors, run, iteration + 1)
        logger.info("Interval: %d to %d", current_folder_start, expected_end_gps)
        logger.info("Output dir: %s", output_dir)
        if not cache_raw:
            logger.info("Cache raw disabled: data will be fetched but not saved.")

        # Generiamo i task controllando l'esistenza dei file prima di sottomettere al worker.
        tasks = []
        for det in detectors:
            s = current_folder_start
            while s < expected_end_gps:
                e = min(s + segment_duration, expected_end_gps)
                filepath = output_dir / f"{det}_{s}_{e}.hdf5"
                if resume and cache_raw and filepath.exists():
                    pass
                else:
                    tasks.append((det, s, e, filepath))
                s += segment_duration

        if not tasks:
            logger.info("Nessun blocco mancante in questa cartella. (Già completata)")
        else:
            logger.info("Trovati %d blocchi mancanti da scaricare per la cartella %d", len(tasks), current_folder_start)
            
            retry_delays = [5, 10, 20] if getattr(args, "retry", False) else [0]
            base_delay = 0.3

            # Usiamo ThreadPoolExecutor
            # Sottomettiamo tutti i task all'executor, lui eseguirà 'workers' thread in parallelo.
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = []
                for det, s, e, filepath in tasks:
                    futures.append(executor.submit(_fetch_single_block, det, s, e, output_dir, retry_delays, base_delay, cache_raw))
                
                # Attendiamo la fine di tutti i task della cartella
                wait(futures)
                
                # Log results
                for f in futures:
                    ok, msg = f.result()
                    if ok:
                        logger.info(msg)
                    else:
                        logger.error(msg)
                
                # Pulizia cache per prevenire errori
                try:
                    import astropy
                    astropy.utils.data.clear_download_cache()
                except Exception:
                    pass

        if not loop_download:
            break
            
        current_folder_start += folder_size
        iteration += 1

    print("Download completato.")


def cmd_scan_extended(args: argparse.Namespace) -> None:
    """Orchestrate automatic scan on H1 and L1 in parallel."""
    if getattr(args, "reprocess", False):
        _reprocess_spectrograms(args)
        return
    """Run an extended scan of H1 + L1 contemporaneously.

    Incremental mode (automatic):
        When ``--session-id`` is provided and detector directories already
        contain spectrograms, the scan resumes from the minimum highest GPS
        end-time found across the detectors to ensure strict alignment.
    """
    from src.core.data_loader import generate_segments_from_gps_range

    cfg = load_config()
    scan_cfg = cfg["scan_extended"]
    run = _resolve_run(args)
    run_lower = run.lower()
    session_id = _resolve_session_id(args)

    run_cfg = cfg.get("run_config", {}).get(run, {})
    hours = getattr(args, "hours", None) or run_cfg.get("hours_per_detector", scan_cfg.get("hours_per_detector", 72))
    detectors = scan_cfg["detectors"]
    workers: int = args.workers
    fetch_workers = cfg.get("performance", {}).get("gwosc_fetch_threads", 4)
    explicit_session = hasattr(args, "session_id") and args.session_id

    from src.core.logging_utils import PhaseTracker
    from src.core.utils import setup_logger
    det_str = ",".join(detectors)
    cmd_logger = setup_logger("main.scan_extended", log_file=Path("logs/gravi-signal-ml.log"), session_id=session_id, run=run, detector=det_str)
    tracker = PhaseTracker(cmd_logger, "scan_extended", session_id, run, det_str)

    _log_run_header(run, None, session_id)
    logger.info("=== SCAN-EXTENDED: %s [%s], %d h per detector ===", detectors, run, hours)

    if workers == 1 or workers % 2 != 0:
        logger.error("Errore: per scan-extended parallelo --workers deve essere un numero pari maggiore di 1 (es. 2, 4, 6, 8).")
        sys.exit(1)

    # Trova il min start_gps e max_gps tra i detector per un resume condiviso
    last_gps_list = []
    first_gps_list = []
    if explicit_session:
        for det in detectors:
            lgps = _find_last_gps(session_id, det, run=run)
            last_gps_list.append(lgps if lgps is not None else 0)
            fgps = _find_first_gps(session_id, det, run=run)
            first_gps_list.append(fgps if fgps is not None else float('inf'))

    start_gps_arg = getattr(args, "start_gps", None)
    
    last_gps = None
    if explicit_session and any(g > 0 for g in last_gps_list):
        last_gps = min(g for g in last_gps_list if g > 0)

    first_gps = None
    if explicit_session and any(g < float('inf') for g in first_gps_list):
        first_gps = min(g for g in first_gps_list if g < float('inf'))

    # 1. Determine the Intended Original Start GPS
    if start_gps_arg is not None:
        intended_start_gps = start_gps_arg
    elif first_gps is not None:
        intended_start_gps = first_gps
    else:
        intended_start_gps = _run_start_gps(run, cfg)

    # 2. Determine the Target End GPS
    target_end_gps = intended_start_gps + int(hours * 3600)
    
    from src.core.utils import gps_to_utc
    logger.info("Target session window: %s to %s (GPS %d - %d)", gps_to_utc(intended_start_gps), gps_to_utc(target_end_gps), intended_start_gps, target_end_gps)

    if explicit_session and last_gps is not None:
        raw_path = getattr(args, "raw_path", None)
        segment_duration = 4096 if raw_path else 32
        
        if last_gps >= target_end_gps - (segment_duration * 2):
            logger.info("Scan already complete for session %s. Skipping to full-analysis.", session_id)
            is_failed = False
            if getattr(args, "full_analysis", False):
                from src.pipeline_v1_legacy.full_analysis import run_full_analysis
                logger.info("Triggering automatic full analysis...")
                result = run_full_analysis(
                    session_id=session_id,
                    detectors=detectors,
                    run=run,
                    skip_timeslide=getattr(args, "skip_timeslide", False),
                    n_runs=getattr(args, "n_runs", 20),
                    sequential=getattr(args, "sequential", False)
                )
                
                status_val = result.get("status")
                if status_val == "FAILED":
                    is_failed = True
                elif isinstance(status_val, dict) and any(v == "FAILED" for v in status_val.values()):
                    is_failed = True

            if not is_failed and getattr(args, "continue_run", False):
                max_iterations = getattr(args, "max_iterations", 10)
                stop_date = getattr(args, "stop_date", None)
                _run_continue_loop(
                    initial_session_id=session_id,
                    run=run,
                    max_iterations=max_iterations,
                    stop_date_str=stop_date,
                    args=args,
                )
            return

        from src.core.utils import gps_to_utc
        logger.info(
            "Ripresa sessione %s dal GPS %d fino a %d (%d ore rimanenti su %d totali previste)",
            session_id, last_gps, target_end_gps,
            (target_end_gps - last_gps) // 3600,
            hours
        )
        start_gps = last_gps
    else:
        start_gps = intended_start_gps

    # --- Raw Path Logic ---
    raw_path = getattr(args, "raw_path", None)
    explicit_raw_path = raw_path is not None
    if not raw_path:
        from src.core.data_loader import _find_latest_raw_session, _find_raw_session_by_id
        raw_path = _find_raw_session_by_id(session_id)
        if not raw_path:
            raw_path = _find_latest_raw_session()
        
    end_gps = target_end_gps
    segment_length = 4096

    if raw_path:
        import re
        
        raw_path = Path(raw_path)
        logger.info("Using raw session: %s", raw_path)
        
        # Auto-detect boundaries from raw HDF5 files for all requested detectors
        min_start = float('inf')
        max_end = 0
        pattern = re.compile(r"^[A-Z]\d_(\d+)_(\d+)\.hdf5$")
        for f in raw_path.glob("*.hdf5"):
            m = pattern.match(f.name)
            if m:
                det = f.name.split('_')[0]
                if det in detectors:
                    min_start = min(min_start, int(m.group(1)))
                    max_end = max(max_end, int(m.group(2)))
                    
        if min_start < float('inf') and max_end > 0:
            if explicit_raw_path:
                if start_gps_arg is None and last_gps is None:
                    start_gps = min_start
                    logger.info("Auto-detected start GPS da raw_path: %d", start_gps)
                if start_gps >= max_end:
                    logger.info("I dati in raw_path terminano al GPS %d, ma la sessione è già al GPS %d. Scan completato.", max_end, start_gps)
                    sys.exit(0)
                end_gps = max_end
                logger.info("Auto-detected end GPS da raw_path: %d", end_gps)
        else:
            logger.warning("Nessun file HDF5 valido in %s. Fallback a config standard.", raw_path)
        
    tracker.start(gps_start=start_gps)

    segments = generate_segments_from_gps_range(start_gps, end_gps, segment_length=segment_length)

    if not segments:
        logger.warning("Nessun segmento trovato per la finestra temporale richiesta.")
        sys.exit(0)

    output_dir_base = session_path(run, session_id) / "spectrograms"
    logger.info("Output dir base: %s", output_dir_base)

    expected_segments_per_det = max(0, (target_end_gps - intended_start_gps)) // segment_length
    completed_segments_per_det = max(0, (start_gps - intended_start_gps)) // segment_length
    total_expected = expected_segments_per_det * len(detectors)
    initial_completed = completed_segments_per_det * len(detectors)

    from src.core.parallel_processor import batch_process_parallel
    processed_count, skipped = batch_process_parallel(
        segments, detectors, output_dir_base, cfg, 
        workers=workers, fetch_workers=fetch_workers, cache_raw=not args.no_cache_raw,
        initial_completed=initial_completed, total_expected=total_expected
    )

    total_duration = sum(end - start for start, end in segments)

    try:
        astropy.utils.data.clear_download_cache()
        logger.info("Cleaned astropy download cache.")
    except Exception as e:
        logger.warning("Failed to clean astropy download cache: %s", e)

    logger.info(
        "Extended scan complete: %d saved, %d skipped, %.1f h scanned per detector",
        processed_count,
        skipped,
        total_duration / 3600,
    )
    print(f"Extended scan complete: {processed_count} saved, {skipped} skipped.")
    
    tracker.end(gps_end=end_gps, n_processed=processed_count, n_total=len(segments))

    # --- Automatic full analysis trigger ---
    is_failed = False
    if getattr(args, "full_analysis", False):
        from src.pipeline_v1_legacy.full_analysis import run_full_analysis
        logger.info("Triggering automatic full analysis...")
        result = run_full_analysis(
            session_id=session_id,
            detectors=detectors,
            run=run,
            skip_timeslide=getattr(args, "skip_timeslide", False),
            n_runs=getattr(args, "n_runs", 20),
            sequential=getattr(args, "sequential", False)
        )
        
        status_val = result.get("status")
        if status_val == "FAILED":
            is_failed = True
        elif isinstance(status_val, dict) and any(v == "FAILED" for v in status_val.values()):
            is_failed = True

    if not is_failed and getattr(args, "continue_run", False):
        max_iterations = getattr(args, "max_iterations", 10)
        stop_date = getattr(args, "stop_date", None)
        _run_continue_loop(
            initial_session_id=session_id,
            run=run,
            max_iterations=max_iterations,
            stop_date_str=stop_date,
            args=args,
        )


def cmd_last_gps(args: argparse.Namespace) -> None:
    """Print the highest GPS end-time found in spectrogram filenames of a session.

    Filename convention: ``<detector>_<gps_start>_<gps_end>.png``.
    Scans the directory without touching GWOSC.
    """
    import re

    session_id = args.session_id
    if not session_id:
        logger.error("--session-id is required for last-gps.")
        sys.exit(1)

    detector: str = args.detector
    run = _resolve_run(args)
    run_lower = run.lower()

    _log_run_header(run, detector, session_id)

    spec_dir = session_path(run, session_id) / "spectrograms" / detector

    if not spec_dir.exists():
        logger.error("Spectrogram directory not found: %s", spec_dir)
        sys.exit(1)

    # Filename pattern: H1_<start>_<end>.png  (or L1_, V1_)
    pattern = re.compile(r"^[A-Z]\d_(\d+)_(\d+)\.png$")

    max_gps = 0
    count = 0
    for png_file in spec_dir.glob("*.png"):
        m = pattern.match(png_file.name)
        if m:
            end_gps = int(m.group(2))
            if end_gps > max_gps:
                max_gps = end_gps
            count += 1

    if count == 0:
        logger.warning("No matching spectrogram PNGs found in %s", spec_dir)
        sys.exit(1)

    logger.info(
        "Scanned %d PNGs in %s — max GPS end-time: %d", count, spec_dir, max_gps
    )
    print(max_gps)


def _reprocess_single_png(
    args: tuple,
) -> tuple[str, bool, str]:
    """Autonomous worker for reprocessing a single spectrogram PNG.

    Receives only picklable primitives — safe for Windows ``spawn``.

    Returns:
        ``(filename, success, message)``
    """
    filename, detector, gps_start, gps_end, output_dir_str, cmap, backup, use_cache = args
    from pathlib import Path as _Path

    save_path = _Path(output_dir_str) / filename

    try:
        # Optional backup
        if backup and save_path.exists():
            bak_name = save_path.stem + ".viridis.bak" + save_path.suffix
            bak_path = save_path.parent / bak_name
            if not bak_path.exists():
                import shutil
                shutil.copy2(save_path, bak_path)

        # fetch_strain_data automatically searches _DATA_DIRECTORIES before downloading
        from src.core.data_loader import fetch_strain_data
        ts_super = fetch_strain_data(detector, gps_start - 4.0, gps_end + 4.0, edge_tolerance=4.0)

        from src.core.preprocessor import whiten_context, extract_clean_subwindow, bandpass, generate_qtransform
        ts_w_padded, _ = whiten_context(ts_super, gps_start, gps_end, pad=4.0)
        ts_bp = extract_clean_subwindow(ts_w_padded, gps_start, gps_end)  # already whitened+bandpassed
        generate_qtransform(ts_bp, save_path=save_path, cmap=cmap)

        return (filename, True, "OK")

    except Exception as exc:
        return (filename, False, str(exc))


def _reprocess_spectrograms(args: argparse.Namespace) -> None:
    """Re-render existing spectrograms with the current colormap from config.

    For each PNG in the target directory, parse the GPS range from the
    filename (``<detector>_<gps_start>_<gps_end>.png``), re-fetch the raw
    strain data, and re-run the full preprocessing pipeline with the
    colormap specified in ``config.yaml → preprocessing.colormap``.
    """
    import re
    from concurrent.futures import ProcessPoolExecutor, as_completed

    cfg = load_config()
    cmap = cfg["preprocessing"].get("colormap", "cividis")
    session_id = getattr(args, "session_id", None)
    detector = getattr(args, "detector", None)
    run = _resolve_run(args)
    run_lower = run.lower()
    workers: int = args.workers
    backup: bool = args.backup
    dry_run: bool = args.dry_run
    use_cache: bool = args.use_cache

    if session_id:
        _log_run_header(run, detector, session_id)

    # Resolve input directory
    if args.input_dir:
        input_dir = Path(args.input_dir)
    elif session_id and detector:
        input_dir = session_path(run, session_id) / "spectrograms" / detector
    else:
        logger.error(
            "Either --input-dir or both --session-id and --detector are required."
        )
        sys.exit(1)

    if not input_dir.exists():
        logger.error("Directory not found: %s", input_dir)
        sys.exit(1)

    # Discover PNGs and parse GPS ranges
    pattern = re.compile(r"^([A-Z]\d)_(\d+)_(\d+)\.png$")
    tasks: list[tuple[str, str, int, int]] = []  # (filename, det, start, end)

    for png_file in sorted(input_dir.glob("*.png")):
        m = pattern.match(png_file.name)
        if m:
            det = m.group(1)
            gps_start = int(m.group(2))
            gps_end = int(m.group(3))
            # If --detector is given, only reprocess matching files
            if detector and det != detector:
                continue
            tasks.append((png_file.name, det, gps_start, gps_end))

    if not tasks:
        logger.warning("No matching spectrogram PNGs found in %s", input_dir)
        sys.exit(0)

    logger.info(
        "=== REPROCESS-SPECTROGRAMS: %d PNGs, cmap=%s ===",
        len(tasks), cmap,
    )

    if dry_run:
        total_seconds = sum(end - start for _, _, start, end in tasks)
        print(f"\n[DRY RUN] Would reprocess {len(tasks)} spectrograms")
        print(f"  Directory : {input_dir}")
        print(f"  Colormap  : {cmap}")
        print(f"  Backup    : {'yes' if backup else 'no'}")
        print(f"  Use cache : {'yes' if use_cache else 'no'}")
        print(f"  Workers   : {workers}")
        print(f"  Total GPS : {total_seconds:,} s ({total_seconds/3600:.1f} h)")
        # Estimate time: ~5s per segment for GWOSC fetch + preprocessing
        eff_workers = max(1, workers - 2) if workers > 1 else 1
        est_seconds = (len(tasks) * 5) / eff_workers
        print(f"  Est. time : ~{est_seconds/60:.0f} min (assuming ~5s/segment, {eff_workers} workers)")
        return

    # Build picklable args for workers
    worker_args = [
        (fname, det, gps_s, gps_e, str(input_dir), cmap, backup, use_cache)
        for fname, det, gps_s, gps_e in tasks
    ]

    succeeded = 0
    failed = 0

    if workers <= 1:
        # Sequential mode
        from tqdm import tqdm as _tqdm
        for wa in _tqdm(worker_args, desc="Reprocessing", unit="png"):
            fname, ok, msg = _reprocess_single_png(wa)
            if ok:
                succeeded += 1
            else:
                logger.warning("Failed %s: %s", fname, msg)
                failed += 1
    else:
        # Parallel mode
        cpu_workers = max(1, workers - 2)
        from tqdm import tqdm as _tqdm
        with ProcessPoolExecutor(max_workers=cpu_workers) as executor:
            futures = {
                executor.submit(_reprocess_single_png, wa): wa[0]
                for wa in worker_args
            }
            for future in _tqdm(
                as_completed(futures),
                total=len(futures),
                desc="Reprocessing",
                unit="png",
            ):
                try:
                    fname, ok, msg = future.result(timeout=120)
                    if ok:
                        succeeded += 1
                    else:
                        logger.warning("Failed %s: %s", fname, msg)
                        failed += 1
                except Exception:
                    failed += 1

    print(
        f"\nReprocessing complete: {succeeded} succeeded, {failed} failed "
        f"(colormap: {cmap})"
    )


def cmd_encode(args: argparse.Namespace) -> None:
    """Extract embeddings from spectrograms using the DINOv2-Reg encoder."""
    session_id = getattr(args, "session_id", None) or None
    detector = getattr(args, "detector", None)
    run = _resolve_run(args)
    run_lower = run.lower()
    batch_size: int = args.batch_size

    # Resolve paths: explicit flags take priority over session-id
    if args.input_dir:
        input_dir = Path(args.input_dir)
    elif session_id and detector:
        input_dir = session_path(run, session_id) / "spectrograms" / detector
    else:
        logger.error(
            "Either --input-dir or both --session-id and --detector are required."
        )
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    elif session_id and detector:
        output_path = session_path(run, session_id) / "embeddings" / f"{run_lower}_{detector.lower()}.npy"
    else:
        logger.error(
            "Either --output or both --session-id and --detector are required."
        )
        sys.exit(1)

    if session_id:
        _log_run_header(run, detector, session_id)
    logger.info("=== ENCODE: %s ===", input_dir)
    logger.info("Output: %s", output_path)

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    encoder = DINOv2Encoder()

    try:
        encoder.extract_dataset(input_dir, output_path, batch_size)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        print(f"Error: {exc}")
        sys.exit(1)

    print("Phase 2 complete. Embeddings ready for Phase 3 clustering.")


def cmd_cluster_similarity(args: argparse.Namespace) -> None:
    """Analyze the distribution of cosine similarities for each cluster."""
    from src.pipeline_v1_legacy.similarity_analysis import cluster_similarity
    
    run = _resolve_run(args)
    session_id = _resolve_session_id(args)
    
    logger.info("=== ANALYZE-SIMILARITY: %s [%s] ===", args.detector, run)
    cluster_similarity(
        session_id=session_id,
        detector=args.detector,
        run=run,
        reference_path=args.reference
    )


def cmd_explain(args: argparse.Namespace) -> None:
    """[STUB] Generate attention maps for anomaly explainability."""
    logger.info("=== EXPLAIN (Attention Maps) ===")
    logger.warning("Feature not yet implemented. Stub for Phase 2: DINOv2 Explainability.")


def cmd_cluster(args: argparse.Namespace) -> None:
    """Cluster embeddings to discover novel glitch classes."""
    session_id = getattr(args, "session_id", None) or None
    detector = getattr(args, "detector", None)
    run = _resolve_run(args)
    run_lower = run.lower()

    # Resolve paths: explicit flags take priority over session-id
    if args.input:
        input_path = Path(args.input)
    elif session_id and detector:
        input_path = session_path(run, session_id) / "embeddings" / f"{run_lower}_{detector.lower()}.npy"
    else:
        logger.error(
            "Either --input or both --session-id and --detector are required."
        )
        sys.exit(1)

    if args.output is not None:
        # Explicit --output was given — take priority
        output_dir = Path(args.output)
    elif session_id and detector:
        output_dir = session_path(run, session_id) / "clusters" / detector.lower()
    else:
        output_dir = Path("data/clusters/")

    if session_id:
        _log_run_header(run, detector, session_id)
    logger.info("=== CLUSTER: %s ===", input_path)
    logger.info("Output dir: %s", output_dir)

    # 1. Load embeddings (.npy)
    if not input_path.exists():
        logger.error("Embeddings file not found: %s", input_path)
        sys.exit(1)

    embeddings = np.load(input_path)
    logger.info("Loaded embeddings: shape %s, dtype %s", embeddings.shape, embeddings.dtype)

    # 2. Load companion metadata JSON (same path, .json suffix)
    json_path = input_path.with_suffix(".json")
    metadata = {}
    if json_path.exists():
        import json

        with open(json_path, "r", encoding="utf-8") as fh:
            metadata = json.load(fh)
        logger.info("Loaded metadata: %d files", len(metadata.get("files", [])))
    else:
        logger.warning("No companion metadata JSON found at %s", json_path)

    # 3. Load clustering config
    cfg = load_config()
    cluster_cfg = cfg["clustering"]
    if hasattr(args, "algorithm"):
        cluster_cfg["algorithm"] = args.algorithm

    # 4. Run full clustering pipeline
    from src.pipeline_v1_legacy.clustering import run_full_pipeline

    result = run_full_pipeline(embeddings, cluster_cfg)

    # 5. Save cluster report (JSON + UMAP plot + gallery)
    from src.pipeline_v1_legacy.reporter import print_summary, save_cluster_report

    save_cluster_report(result, metadata, output_dir, detector=detector or "H1")

    # 6. Print human-readable summary
    print_summary(result)

    print(f"Phase 3 complete. Results in {output_dir}")


def cmd_report(args: argparse.Namespace) -> None:
    """Regenerate UMAP and cluster gallery from existing embeddings and cluster_report.json."""
    import json
    from src.pipeline_v1_legacy.clustering import run_pca, run_umap
    from src.pipeline_v1_legacy.reporter import _save_umap_plot, _save_cluster_gallery

    session_id = getattr(args, "session_id", None) or None
    detector = getattr(args, "detector", None)
    run = _resolve_run(args)
    run_lower = run.lower()

    # Resolve paths
    if args.embeddings:
        embeddings_path = Path(args.embeddings)
    elif session_id and detector:
        embeddings_path = session_path(run, session_id) / "embeddings" / f"{run_lower}_{detector.lower()}.npy"
    else:
        logger.error("Either --embeddings or both --session-id and --detector are required.")
        sys.exit(1)

    if args.report:
        report_path = Path(args.report)
    elif session_id and detector:
        report_path = session_path(run, session_id) / "clusters" / detector.lower() / "cluster_report.json"
    else:
        logger.error("Either --report or both --session-id and --detector are required.")
        sys.exit(1)

    if args.output_dir:
        output_dir = Path(args.output_dir)
    elif session_id and detector:
        output_dir = session_path(run, session_id) / "clusters" / detector.lower()
    else:
        output_dir = Path("data/clusters/")

    if session_id:
        _log_run_header(run, detector, session_id)
    logger.info("=== REPORT ===")
    logger.info("Embeddings: %s", embeddings_path)
    logger.info("Report: %s", report_path)
    logger.info("Output dir: %s", output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    if not embeddings_path.exists():
        logger.error("Embeddings file not found: %s", embeddings_path)
        sys.exit(1)
    if not report_path.exists():
        logger.error("Report file not found: %s", report_path)
        sys.exit(1)

    # 1. Load data
    embeddings = np.load(embeddings_path)
    with open(report_path, "r", encoding="utf-8") as f:
        cluster_report = json.load(f)

    json_path = embeddings_path.with_suffix(".json")
    metadata = {}
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as fh:
            metadata = json.load(fh)

    files = metadata.get("files", [])
    if not files:
        logger.warning("No file list in metadata. Gallery generation might fail or be incomplete.")

    # Reconstruct labels from cluster_report
    labels = np.full(len(embeddings), -1, dtype=int)
    file_to_idx = {str(Path(f).name): i for i, f in enumerate(files)}
    for cid_str, cdata in cluster_report.get("results", {}).get("clusters", {}).items():
        cid = int(cid_str)
        if cid < 0:
            continue
        for f_path in cdata.get("sample_files", []):
            name = str(Path(f_path).name)
            if name in file_to_idx:
                labels[file_to_idx[name]] = cid

    results = cluster_report.get("results", {})
    stats = {
        "n_clusters": results.get("n_clusters", 0),
        "n_noise": results.get("n_noise", 0),
        "noise_ratio": results.get("noise_ratio", 0.0),
        "cluster_sizes": {int(k): v for k, v in results.get("cluster_sizes", {}).items()},
    }
    anomalous = results.get("anomalous_clusters", [])
    anomalous_samples = results.get("anomalous_samples", [])
    
    detector_val = detector or cluster_report.get("detector", "H1")

    # 2. Recalculate PCA and UMAP
    cfg = load_config()
    cluster_cfg = cfg["clustering"]

    pca_reduced, _ = run_pca(embeddings, n_components=cluster_cfg.get("pca_components", 50))

    umap_clust_cfg = cluster_cfg.get("umap_clustering", {})
    umap_10d = run_umap(
        pca_reduced,
        n_components=umap_clust_cfg.get("n_components", 10),
        n_neighbors=umap_clust_cfg.get("n_neighbors", 20),
        min_dist=umap_clust_cfg.get("min_dist", 0.0)
    )

    umap_viz_cfg = cluster_cfg.get("umap_viz", {})
    umap_2d = run_umap(
        pca_reduced,
        n_components=umap_viz_cfg.get("n_components", 2),
        n_neighbors=umap_viz_cfg.get("n_neighbors", 20),
        min_dist=umap_viz_cfg.get("min_dist", 0.1)
    )

    # 3. Regenerate plots
    _save_umap_plot(umap_2d, labels, stats, anomalous, anomalous_samples, output_dir, detector=detector_val)
    _save_cluster_gallery(labels, umap_10d, stats, anomalous, anomalous_samples, metadata, output_dir)

    print(f"Report generation complete. Outputs updated in {output_dir}")


def cmd_stability(args: argparse.Namespace) -> None:
    """Measure clustering robustness with ARI on multiple perturbed runs."""
    from src.pipeline_v1_legacy.stability import run_stability_analysis

    session_id = getattr(args, "session_id", None) or "default"
    detector = getattr(args, "detector", None) or "H1"
    run = _resolve_run(args)
    run_lower = run.lower()
    n_runs = getattr(args, "n_runs", 20)

    if session_id != "default":
        _log_run_header(run, detector, session_id)

    # Resolve paths
    if args.embeddings:
        embeddings_path = Path(args.embeddings)
    elif session_id != "default" and detector:
        embeddings_path = session_path(run, session_id) / "embeddings" / f"{run_lower}_{detector.lower()}.npy"
    else:
        logger.error("Either --embeddings or both --session-id and --detector are required.")
        sys.exit(1)

    logger.info("=== STABILITY ===")
    logger.info("Embeddings: %s", embeddings_path)
    logger.info("Runs: %d", n_runs)

    if not embeddings_path.exists():
        logger.error("Embeddings file not found: %s", embeddings_path)
        sys.exit(1)

    # 1. Load embeddings
    embeddings = np.load(embeddings_path)

    # 2. Load config
    cfg = load_config()
    cluster_cfg = cfg.get("clustering", {})

    # 3. Run stability analysis
    run_stability_analysis(
        embeddings=embeddings,
        cluster_cfg=cluster_cfg,
        n_runs=n_runs,
        session_id=session_id,
        detector=detector,
        run=run,
        anomaly_criterion=getattr(args, "anomaly_criterion", "likelihood"),
    )


def cmd_ablation(args: argparse.Namespace) -> None:
    """Run ablation study to test clustering robustness against image perturbations."""
    import json
    from src.pipeline_v1_legacy.ablation import run_ablation_study
    from src.pipeline_v1_legacy.clustering import run_full_pipeline

    session_id = getattr(args, "session_id", None) or None
    detector = getattr(args, "detector", None)
    run = _resolve_run(args)
    run_lower = run.lower()

    if session_id:
        _log_run_header(run, detector, session_id)

    # Resolve paths
    if args.embeddings:
        embeddings_path = Path(args.embeddings)
    elif session_id and detector:
        embeddings_path = session_path(run, session_id) / "embeddings" / f"{run_lower}_{detector.lower()}.npy"
    else:
        logger.error("Either --embeddings or both --session-id and --detector are required.")
        sys.exit(1)

    if args.spectrogram_dir:
        spec_dir = Path(args.spectrogram_dir)
    elif session_id and detector:
        spec_dir = session_path(run, session_id) / "spectrograms" / detector
    else:
        logger.error("Either --spectrogram-dir or both --session-id and --detector are required.")
        sys.exit(1)

    if args.output_dir:
        output_dir = Path(args.output_dir)
    elif session_id and detector:
        output_dir = session_path(run, session_id) / "ablation"
    else:
        output_dir = Path("data/ablation/")

    logger.info("=== ABLATION ===")
    logger.info("Embeddings: %s", embeddings_path)
    logger.info("Spectrograms: %s", spec_dir)
    logger.info("Output dir: %s", output_dir)

    if not embeddings_path.exists():
        logger.error("Embeddings file not found: %s", embeddings_path)
        sys.exit(1)
    if not spec_dir.exists():
        logger.error("Spectrogram directory not found: %s", spec_dir)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load baseline embeddings and original file paths
    embeddings = np.load(embeddings_path)
    json_path = embeddings_path.with_suffix(".json")
    if not json_path.exists():
        logger.error("Metadata JSON not found for embeddings: %s", json_path)
        sys.exit(1)
    
    with open(json_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    
    files = metadata.get("files", [])
    if not files:
        logger.error("No file list found in metadata.")
        sys.exit(1)
        
    image_paths = [spec_dir / Path(f).name for f in files]
    
    # Verify a few exist
    for p in image_paths[:5]:
        if not p.exists():
            logger.error("Could not find expected spectrogram: %s", p)
            sys.exit(1)
            
    # 2. Run baseline clustering to get original labels
    logger.info("Running baseline clustering to establish original labels...")
    cfg = load_config()
    cluster_cfg = cfg["clustering"]
    baseline_result = run_full_pipeline(embeddings, cluster_cfg)
    original_labels = baseline_result["labels"]
    
    # 4. Run Ablation
    actual_session_id = session_id or "default_session"
    run_ablation_study(
        original_labels=original_labels,
        image_paths=image_paths,
        cluster_cfg=cluster_cfg,
        output_dir=output_dir,
        session_id=actual_session_id,
        detector=detector or "H1",
        batch_size=args.batch_size
    )


def cmd_crosscheck(args: argparse.Namespace) -> None:
    """Cross-check anomalous clusters against the Gravity Spy database."""
    from src.pipeline_v1_legacy.gravity_spy_checker import (
        cross_check_anomalous_clusters,
        print_crosscheck_summary,
    )

    report_path = Path(args.report)
    metadata_path = Path(args.metadata)
    detector: str = args.detector
    output_path = Path(args.output) if args.output else None

    logger.info("=== CROSSCHECK: %s, report=%s ===", detector, report_path)

    # 1. Run the full cross-check
    results = cross_check_anomalous_clusters(
        cluster_report_path=report_path,
        metadata_path=metadata_path,
        detector=detector,
        output_path=output_path,
    )

    # 2. Print human-readable summary
    print_crosscheck_summary(results)

    # 3. Final message
    n_unclassified = results["unclassified"]
    print(f"Cross-check complete. Results: {n_unclassified} unclassified candidates.")


def cmd_build_reference(args: argparse.Namespace) -> None:
    """Dispatch to the correct reference builder based on domain."""
    domain = getattr(args, "domain", "in-domain")
    if domain == "in-domain":
        _build_indomain_reference(args)
    else:
        _build_reference(args)


def _build_reference(args: argparse.Namespace) -> None:
    """Build a DINOv2 embedding reference index from the Gravity Spy training set."""
    from src.pipeline_v1_legacy.reference_builder import (
        download_training_set_metadata,
        extract_from_tar,
        build_reference_index_from_paths,
    )

    output_path = Path(args.output)
    tar_path = Path(args.tar_path)
    max_per_class: int = args.max_per_class
    cfg = load_config()
    sim_cfg = cfg.get("similarity", {})
    # Use exact zenodo url string matching the expected file
    zenodo_url = f"https://zenodo.org/records/{sim_cfg.get('training_set_zenodo', '10.5281/zenodo/1476551').split('/')[-1]}/files/trainingset_v1d1_metadata.csv"
    if '10.5281' in zenodo_url:
        zenodo_url = "https://zenodo.org/records/1476551/files/trainingset_v1d1_metadata.csv"
    duration = sim_cfg.get("duration", 1.0)

    logger.info("=== BUILD-REFERENCE ===")

    # Step 1: metadata
    metadata_df = download_training_set_metadata(output_path.parent, zenodo_url=zenodo_url)

    # Step 2: check tar exists
    if not tar_path.exists():
        logger.error(
            "tar.gz not found at %s. "
            "Download it manually from: "
            "https://zenodo.org/records/1476551/files/trainingsetv1d1.tar.gz",
            tar_path
        )
        raise FileNotFoundError(f"Training set tar.gz not found: {tar_path}")

    # Step 3: extract PNGs from tar
    image_paths, labels = extract_from_tar(
        tar_path=tar_path,
        output_dir=output_path.parent,
        metadata=metadata_df,
        max_per_class=max_per_class,
        sample_type="train",
        duration=str(duration),
    )

    if not image_paths:
        raise RuntimeError("No images extracted from tar.gz. Check file integrity.")

    # Step 4: build DINOv2 reference index
    meta = build_reference_index_from_paths(
        image_paths=image_paths,
        labels=labels,
        output_path=output_path,
        batch_size=32,
    )

    print(f"Reference index complete: {meta['n_samples']} samples, "
          f"{meta['n_classes']} classes → {output_path}")


def cmd_morphcheck(args: argparse.Namespace) -> None:
    """Run morphological similarity cross-check against reference index."""
    import json
    from src.pipeline_v1_legacy.similarity_checker import (
        run_morphological_crosscheck,
        print_morphological_summary,
    )
    from src.core.utils import discover_references

    session_id = getattr(args, "session_id", None) or None
    detector = getattr(args, "detector", None)
    run = _resolve_run(args)
    run_lower = run.lower()

    if getattr(args, "embeddings", None):
        embeddings_path = Path(args.embeddings)
    elif session_id and detector:
        embeddings_path = session_path(run, session_id) / "embeddings" / f"{run_lower}_{detector.lower()}.npy"
    else:
        logger.error("Either --embeddings or both --session-id and --detector are required.")
        sys.exit(1)

    if getattr(args, "report", None):
        report_path = Path(args.report)
    elif session_id and detector:
        report_path = session_path(run, session_id) / "clusters" / detector.lower() / "cluster_report.json"
    else:
        logger.error("Either --report or both --session-id and --detector are required.")
        sys.exit(1)

    reference_path_arg = getattr(args, "reference", None)

    if reference_path_arg:
        references = [Path(reference_path_arg)]
        auto_discovery = False
    else:
        references = discover_references()
        if not references:
            logger.error("No references found during auto-discovery in data/reference")
            return
        logger.info("Auto-discovered %d references: %s", len(references), [r.name for r in references])
        auto_discovery = True

    if getattr(args, "output", None):
        output_path = Path(args.output)
    elif session_id and detector:
        if auto_discovery:
            # output_path.parent will be session_path, so morphcheck/ goes inside session
            output_path = session_path(run, session_id) / f"morphcheck_summary_{detector}.json"
        else:
            output_path = session_path(run, session_id) / "morphcheck" / detector / f"{references[0].stem}.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        logger.error("Either --output or both --session-id and --detector are required.")
        sys.exit(1)

    if session_id:
        _log_run_header(run, detector, session_id)

    logger.info("=== MORPHCHECK ===")

    # 1. Load embeddings and cluster report
    embeddings = np.load(embeddings_path)
    with open(report_path, "r", encoding="utf-8") as f:
        cluster_report = json.load(f)

    # Extract anomalous embeddings based on cluster report
    anomalous_files = []
    anomalous_cluster_ids = []
    anomalous_indices = []

    # Map files to their indices in the embeddings array
    metadata_path = embeddings_path.with_suffix(".json")
    with open(metadata_path, "r", encoding="utf-8") as f:
        embedding_metadata = json.load(f)
        
    all_files = embedding_metadata["files"]
    file_to_idx = {str(Path(f).name): i for i, f in enumerate(all_files)}

    # Collect anomalous samples
    for cluster_id_str, cluster in cluster_report.get("results", {}).get("clusters", {}).items():
        cluster_id = int(cluster_id_str)
        if cluster_id >= 0:
            for sample_file in cluster.get("sample_files", []):
                file_name = Path(sample_file).name
                if file_name in file_to_idx:
                    anomalous_files.append(sample_file)
                    anomalous_cluster_ids.append(cluster_id)
                    anomalous_indices.append(file_to_idx[file_name])

    if not anomalous_indices:
        print("No cluster samples to check.")
        return

    anomalous_embeddings = embeddings[anomalous_indices]

    # Load config for thresholds
    cfg = load_config()
    sim_cfg = cfg.get("similarity", {})
    k = sim_cfg.get("k_neighbors", 5)
    novelty_threshold = sim_cfg.get("novelty_threshold", 0.85)
    consensus_threshold = sim_cfg.get("consensus_threshold", 0.60)

    summary_results = {}
    all_details = {}

    for ref_path in references:
        ref_name = ref_path.name
        logger.info("Running morphcheck against reference: %s", ref_name)
        
        if auto_discovery:
            det_val = detector
            if not det_val:
                det_val = "UNKNOWN"
                parts = report_path.parts
                if "clusters" in parts:
                    idx = parts.index("clusters")
                    if idx + 1 < len(parts):
                        det_val = parts[idx + 1].upper()
            current_output_path = output_path.parent / "morphcheck" / det_val / f"{ref_path.stem}.json"
        else:
            current_output_path = output_path

        try:
            summary = run_morphological_crosscheck(
                anomalous_embeddings,
                anomalous_files,
                anomalous_cluster_ids,
                ref_path,
                current_output_path,
                k=k,
                novelty_threshold=novelty_threshold,
                consensus_threshold=consensus_threshold,
            )

            print_morphological_summary(summary)
            print(f"Morphological check complete against {ref_name}. {summary['novel']} novel candidates.")
            
            summary_results[ref_name] = {
                "novel": summary["novel"],
                "known": summary["known"],
                "ambiguous": summary["ambiguous"]
            }
            all_details[ref_name] = {d["file"]: d["novelty_status"] for d in summary["details"]}
        except Exception as e:
            logger.error("Morphcheck failed for reference %s: %s", ref_name, e, exc_info=True)
            continue

    if auto_discovery:
        det_val = detector
        if not det_val:
            det_val = "Unknown"
            parts = report_path.parts
            if "clusters" in parts:
                idx = parts.index("clusters")
                if idx + 1 < len(parts):
                    det_val = parts[idx + 1].upper()
                
        session_val = session_id
        if not session_val:
            session_val = "Unknown"
            parts = output_path.parts
            if "runs" in parts:
                idx = parts.index("runs")
                if idx + 2 < len(parts):
                    session_val = parts[idx + 2]

        newly_resolved = 0
        still_ambiguous = 0
        still_novel = 0

        successful_refs = [r.name for r in references if r.name in all_details]
        if len(successful_refs) >= 2:
            ref1 = successful_refs[0]
            ref2 = successful_refs[1]
            
            for file_name, status1 in all_details[ref1].items():
                status2 = all_details[ref2].get(file_name)
                if status1 in ["NOVEL", "AMBIGUOUS"] and status2 == "KNOWN":
                    newly_resolved += 1
                elif status2 == "AMBIGUOUS":
                    still_ambiguous += 1
                elif status2 == "NOVEL":
                    still_novel += 1
        elif len(successful_refs) > 0:
            last_ref = successful_refs[-1]
            for file_name, status in all_details[last_ref].items():
                if status == "AMBIGUOUS":
                    still_ambiguous += 1
                elif status == "NOVEL":
                    still_novel += 1

        summary_report = {
            "session_id": session_val,
            "detector": det_val,
            "references_used": [r.name for r in references],
            "results": summary_results,
            "comparison": {
                "newly_resolved": newly_resolved,
                "still_ambiguous": still_ambiguous,
                "still_novel": still_novel
            }
        }
        
        if getattr(args, "output", None):
            summary_path = output_path.parent / f"morphcheck_summary_{det_val}.json"
        else:
            summary_path = output_path
            
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_report, f, indent=2)
        logger.info("Saved morphcheck summary to %s", summary_path)


def _build_indomain_reference(args: argparse.Namespace) -> None:
    """Build an in-domain DINOv2 reference index from labeled O3b spectrograms."""
    from src.core.reference_index_builder import (
        build_indomain_reference,
        download_gs_classifications_csv,
        select_reference_events,
    )

    from src.core.utils import generate_reference_filename

    detector: str = args.detector
    run: str = args.run

    if args.output:
        output_path = Path(args.output)
    else:
        ref_dir = Path("data/reference")
        ref_dir.mkdir(parents=True, exist_ok=True)
        output_path = ref_dir / generate_reference_filename(run, detector)
        logger.info("Auto-generated output path: %s", output_path)
    cfg = load_config()
    max_per_class: int = args.max_per_class if args.max_per_class is not None else cfg.get("indomain_reference", {}).get("max_per_class", 30)
    min_confidence: float = args.min_confidence if args.min_confidence is not None else cfg.get("indomain_reference", {}).get("min_confidence", 0.95)
    workers: int = args.workers
    local_csv: Path | None = Path(args.local_csv) if getattr(args, "local_csv", None) else None

    logger.info("=== BUILD-INDOMAIN-REFERENCE ===")

    # Step 1: Download GPS classifications CSV from Zenodo
    csv_path = download_gs_classifications_csv(
        output_path.parent, run=run, detector=detector, local_csv=local_csv
    )

    # Step 2: Select high-confidence events
    events_df = select_reference_events(
        csv_path,
        detector=detector,
        min_confidence=min_confidence,
        max_per_class=max_per_class,
    )

    if events_df.empty:
        print("No events passed filters. Check the CSV and filter criteria.")
        sys.exit(1)

    # Step 3: Build in-domain reference (fetch → preprocess → embed)
    meta = build_indomain_reference(
        events_df, output_path, workers=workers
    )

    print(
        f"In-domain reference ready: {meta['n_samples']} samples, "
        f"{meta['n_classes']} classes → {output_path}"
    )

def cmd_download_all_references(args: argparse.Namespace) -> None:
    """Download and build in-domain references for multiple run/detector combos.

    For each run/detector pair:
      1. Download the Gravity Spy classifications CSV from Zenodo
      2. Select high-confidence events
      3. Build the in-domain reference index with the naming convention

    Downloads are sequential to respect Zenodo rate limits.
    """
    from src.core.reference_index_builder import (
        build_indomain_reference,
        download_gs_classifications_csv,
        select_reference_events,
    )
    from src.core.utils import generate_reference_filename

    # Resolve which runs to process
    if args.all_runs:
        runs = list(VALID_RUNS)
    elif args.run:
        if args.run not in VALID_RUNS:
            logger.error("Unknown run '%s'. Valid runs: %s", args.run, VALID_RUNS)
            sys.exit(1)
        runs = [args.run]
    else:
        logger.error("Either --run or --all is required.")
        sys.exit(1)

    detectors: list[str] = args.detector
    cfg = load_config()
    min_confidence: float = args.min_confidence if args.min_confidence is not None else cfg.get("indomain_reference", {}).get("min_confidence", 0.95)
    max_per_class: int = args.max_per_class if args.max_per_class is not None else cfg.get("indomain_reference", {}).get("max_per_class", 30)
    workers: int = args.workers
    ref_dir = Path("data/reference")
    ref_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== DOWNLOAD-ALL-REFERENCES ===")
    logger.info("Runs: %s | Detectors: %s", runs, detectors)
    logger.info("min_confidence=%.2f, max_per_class=%d", min_confidence, max_per_class)

    built = 0
    skipped = 0
    failed = 0

    for run in runs:
        for det in detectors:
            ref_name = generate_reference_filename(run, det)
            output_path = ref_dir / ref_name

            # Skip if already exists (resume support)
            if output_path.exists():
                logger.info(
                    "[%s/%s] Reference already exists: %s — skipping.",
                    run, det, output_path,
                )
                skipped += 1
                continue

            logger.info("[%s/%s] Building reference: %s", run, det, ref_name)

            try:
                # Step 1: Download CSV
                csv_path = download_gs_classifications_csv(
                    ref_dir, run=run, detector=det,
                )

                # Step 2: Select events
                events_df = select_reference_events(
                    csv_path,
                    detector=det,
                    min_confidence=min_confidence,
                    max_per_class=max_per_class,
                )

                if events_df.empty:
                    logger.warning(
                        "[%s/%s] No events passed filters. "
                        "This detector may not have data for this run.",
                        run, det,
                    )
                    failed += 1
                    continue

                # Step 3: Build reference
                meta = build_indomain_reference(
                    events_df, output_path, workers=workers,
                )
                logger.info(
                    "[%s/%s] Reference built: %d samples, %d classes → %s",
                    run, det, meta["n_samples"], meta["n_classes"], output_path,
                )
                built += 1

            except Exception as exc:
                logger.warning(
                    "[%s/%s] Failed to build reference: %s — continuing.",
                    run, det, exc,
                )
                failed += 1

    print(
        f"\ndownload-all-references complete: "
        f"{built} built, {skipped} skipped, {failed} failed."
    )


def cmd_validate_reference(args: argparse.Namespace) -> None:
    """Validate reference index with a GW150914 sanity check."""
    from src.pipeline_v1_legacy.similarity_checker import cosine_knn_search
    from src.pipeline_v1_legacy.reference_builder import load_reference_index

    reference_path = Path(args.reference)
    cfg = load_config()
    test_event: str = args.test_event if args.test_event is not None else next(iter(cfg.get("reference_events", {"GW150914": {}})))

    logger.info("=== VALIDATE-REFERENCE: %s ===", test_event)

    if test_event not in cfg["reference_events"]:
        available = ", ".join(cfg["reference_events"].keys())
        logger.error("Unknown event '%s'. Available: %s", test_event, available)
        sys.exit(1)

    event = cfg["reference_events"][test_event]
    detector = event["detector"]
    gps_start = event["start"]
    gps_end = event["end"]

    # Step 1: Fetch and preprocess the test event with our pipeline
    from src.core.data_loader import fetch_strain_data as _fetch
    from src.core.preprocessor import bandpass as _bp, generate_qtransform as _qt, whiten_context as _wh_ctx, extract_clean_subwindow as _ecs

    logger.info("Fetching %s (%s) [%d, %d]", test_event, detector, gps_start, gps_end)
    ts_super = _fetch(detector, gps_start - 4.0, gps_end + 4.0, edge_tolerance=4.0)
    ts_w_padded, _ = _wh_ctx(ts_super, gps_start, gps_end, pad=4.0)
    ts_white = _ecs(ts_w_padded, gps_start, gps_end)
    ts_bp = _bp(ts_white)

    test_dir = reference_path.parent / "validation"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_png = test_dir / f"{test_event}_{detector}.png"
    _qt(ts_bp, save_path=test_png)

    # Step 2: Extract DINOv2 embedding
    encoder = DINOv2Encoder()
    query_embedding = encoder.extract(test_png)
    query_embedding = query_embedding.reshape(1, -1)

    # Step 3: Run cosine KNN search against reference
    ref_embeddings, ref_labels = load_reference_index(reference_path)

    results = cosine_knn_search(
        query_embedding, ref_embeddings, ref_labels, k=5
    )

    # Step 4: Print top-5 neighbors
    r = results[0]
    print(f"\n{'='*60}")
    print(f"  REFERENCE VALIDATION: {test_event}")
    print(f"{'='*60}")
    print(f"  Top-5 neighbors:")
    for n in r["neighbors"]:
        print(f"    #{n['rank']}: {n['label']:<25s} sim={n['similarity']:.3f}")

    # Step 5: Assess result
    nearest_label = r["top_label"]
    nearest_sim = r["top_similarity"]

    print(f"\n  Domain gap check: {test_event} → nearest={nearest_label} sim={nearest_sim:.3f}")

    # For GW150914 we expect Chirp (it's a real CBC merger)
    chirp_labels = {"Chirp", "chirp"}
    if nearest_label in chirp_labels:
        print(f"  ✅ PASS: in-domain reference is working correctly")
    else:
        # Check if Chirp is anywhere in top-5
        chirp_in_top5 = any(
            n["label"] in chirp_labels for n in r["neighbors"]
        )
        if chirp_in_top5:
            print(f"  ⚠️  WARN: Chirp in top-5 but not nearest — acceptable")
        else:
            print(
                f"  ⚠️  WARN: {test_event} not nearest to Chirp — "
                f"check preprocessing consistency"
            )
    print(f"{'='*60}\n")


def cmd_benchmark_clustering(args: argparse.Namespace) -> None:
    """Run benchmark of the clustering pipeline against a reference index."""
    from src.pipeline_v1_legacy.benchmark import run_benchmark
    
    logger.info("=== BENCHMARK CLUSTERING ===")
    
    try:
        run_benchmark(
            reference_path=args.reference,
            min_samples_per_class=args.min_samples_per_class,
            output_path=args.output,
            algorithm=args.algorithm,
        )
    except Exception as e:
        logger.error("Benchmark failed: %s", e)
        sys.exit(1)


def cmd_timeslide(args: argparse.Namespace) -> None:
    """Run time-slide analysis to estimate background coincidence significance."""
    from src.pipeline_v1_legacy.timeslide import run_timeslide

    run = _resolve_run(args)
    run_lower = run.lower()

    logger.info("=== TIMESLIDE ===")

    cfg = load_config()
    iterations: int = getattr(args, "iterations", None) or cfg.get("timeslide", {}).get("iterations", 100)
    window: int = getattr(args, "window", None) or cfg.get("timeslide", {}).get("window", 32)

    # Check if we have explicit inputs or session-id
    session_id = getattr(args, "session_id", None)

    if session_id:
        _log_run_header(run, None, session_id)
        # Auto-resolve paths; CLI overrides take precedence
        meta_h1 = (
            Path(args.metadata_h1)
            if getattr(args, "metadata_h1", None)
            else session_path(run, session_id) / "embeddings" / f"{run_lower}_h1.json"
        )
        meta_l1 = (
            Path(args.metadata_l1)
            if getattr(args, "metadata_l1", None)
            else session_path(run, session_id) / "embeddings" / f"{run_lower}_l1.json"
        )
        rep_h1 = (
            Path(args.report_h1)
            if getattr(args, "report_h1", None)
            else session_path(run, session_id) / "clusters" / "h1" / "cluster_report.json"
        )
        rep_l1 = (
            Path(args.report_l1)
            if getattr(args, "report_l1", None)
            else session_path(run, session_id) / "clusters" / "l1" / "cluster_report.json"
        )
        output_dir = session_path(run, session_id) / "timeslide"
    else:
        # Without session-id, metadata AND report paths are both required.
        # (embeddings are NOT needed by run_timeslide)
        missing = []
        if not getattr(args, "metadata_h1", None):
            missing.append("--metadata-h1")
        if not getattr(args, "metadata_l1", None):
            missing.append("--metadata-l1")
        if not getattr(args, "report_h1", None):
            missing.append("--report-h1")
        if not getattr(args, "report_l1", None):
            missing.append("--report-l1")
        if missing:
            logger.error(
                "Must provide --session-id OR all explicit paths. Missing: %s",
                ", ".join(missing),
            )
            sys.exit(1)

        meta_h1 = Path(args.metadata_h1)
        meta_l1 = Path(args.metadata_l1)
        rep_h1 = Path(args.report_h1)
        rep_l1 = Path(args.report_l1)
        output_dir = Path("data/timeslide/")

    logger.info("Metadata H1 : %s", meta_h1)
    logger.info("Metadata L1 : %s", meta_l1)
    logger.info("Report H1   : %s", rep_h1)
    logger.info("Report L1   : %s", rep_l1)
    logger.info("Output dir  : %s", output_dir)
    logger.info("Iterations  : %d | Window: %ds", iterations, window)

    run_timeslide(
        meta_h1=meta_h1,
        rep_h1=rep_h1,
        meta_l1=meta_l1,
        rep_l1=rep_l1,
        output_dir=output_dir,
        iterations=iterations,
        window=window,
    )


def cmd_full_analysis_report(args: argparse.Namespace) -> None:
    """Generate final summary reports from existing step reports without running analysis."""
    from src.pipeline_v1_legacy.full_analysis import generate_reports_only

    session_id = _resolve_session_id(args)
    if not session_id:
        logger.error("--session-id is required for full-analysis-report.")
        sys.exit(1)
        
    run = _resolve_run(args)
    _log_run_header(run, "AUTO", session_id)

    result = generate_reports_only(session_id=session_id, run=run)

    status_val = result.get("status")
    is_failed = False
    if status_val == "FAILED":
        is_failed = True
    elif isinstance(status_val, dict) and any(v == "FAILED" for v in status_val.values()):
        is_failed = True

    if is_failed:
        logger.error("Report generation failed.")
        sys.exit(1)

    print("\nReport Generation Complete.")
    if isinstance(status_val, dict):
        for det, status in status_val.items():
            if det in ["H1", "L1", "V1", "timeslide"]:
                print(f"  - {det}: {status}")


def cmd_full_analysis(args: argparse.Namespace) -> None:
    """Automate the full analysis pipeline for one or more detectors."""
    from src.pipeline_v1_legacy.full_analysis import run_full_analysis

    session_id = _resolve_session_id(args)
    run = _resolve_run(args)
    detectors = getattr(args, "detector", None)
    skip_timeslide = getattr(args, "skip_timeslide", False)
    n_runs = getattr(args, "n_runs", 20)

    _log_run_header(run, str(detectors) if detectors else "AUTO", session_id)

    # Hardware diagnostics — log active device at startup
    from src.core.utils import get_device
    active_device = get_device(verbose=True)

    result = run_full_analysis(
        session_id=session_id,
        detectors=detectors,
        run=run,
        skip_timeslide=skip_timeslide,
        n_runs=n_runs,
        sequential=getattr(args, "sequential", False)
    )

    status_val = result.get("status")
    is_failed = False
    if status_val == "FAILED":
        is_failed = True
    elif isinstance(status_val, dict) and any(v == "FAILED" for v in status_val.values()):
        is_failed = True

    if is_failed:
        logger.error("Full analysis failed.")
        sys.exit(1)

    print("\nFull Analysis Complete.")
    for det, status in result["status"].items():
        if det in ["H1", "L1", "V1", "timeslide"]:
            print(f"  {det:<10}: {status}")
            if det in result["reports"]:
                print(f"    Report: {result['reports'][det]}")


def cmd_calibrate(args: argparse.Namespace) -> None:
    """Dispatch to the correct calibration method."""
    method = getattr(args, "method", "cosine")
    if method == "cosine":
        _calibrate_threshold(args)
    elif method == "loglikelihood":
        _calibrate_loglikelihood(args)
    else:
        logger.error("Unknown calibration method: %s", method)


def _calibrate_loglikelihood(args: argparse.Namespace) -> None:
    """Calibrate the DPMM log-likelihood anomaly threshold from the reference."""
    from src.pipeline_v1_legacy.loglikelihood_calibrator import calibrate_loglikelihood_threshold

    result = calibrate_loglikelihood_threshold(
        reference_path=args.reference,
        percentile=args.percentile,
        output_path=args.output,
    )
    threshold = result["threshold"]
    print(
        f"\n[OK] Log-likelihood threshold calibrated: {result['threshold']} -> {args.output}\n"
        f"\nTo use this threshold, update config.yaml:\n"
        f"  clustering:\n"
        f"    dpmm:\n"
        f"      anomaly_threshold: {threshold}\n"
    )


def _calibrate_threshold(args: argparse.Namespace) -> None:
    """Calibrate per-class cosine similarity thresholds from the reference index."""
    from src.pipeline_v1_legacy.threshold_calibrator import calibrate_thresholds

    result = calibrate_thresholds(
        reference_path=args.reference,
        percentile=args.percentile,
        output_path=args.output,
    )
    n_classes = result["metadata"]["n_classes"]
    logger.info("Calibration complete: %d class thresholds saved.", n_classes)


def cmd_scan_live(args: argparse.Namespace) -> None:
    """Run the autopilot live scanner."""
    from src.pipeline_v1_legacy.scan_live import run_scan_live

    logger.warning(
        "scan-live is a frozen V1 exploratory command, not the validated V2 "
        "pipeline and not DANTE-Light"
    )

    run = _resolve_run(args)
    session_id = getattr(args, "session_id", None)
    hours = getattr(args, "hours", None)

    # Hardware diagnostics — log active device at startup
    from src.core.utils import get_device
    active_device = get_device(verbose=True)

    run_scan_live(
        detector=args.detector,
        run=run,
        workers=args.workers,
        session_id=session_id,
        min_novel=args.min_novel,
        reference_path=args.reference,
        hours=hours,
        percentile=args.percentile,
        thresholds_path=args.thresholds_path,
    )


def cmd_run_injection(args: argparse.Namespace) -> None:
    """Run Mock Data Challenge with synthetic glitch injection."""
    from src.core.injection import run_mdc
    from src.pipeline_v1_legacy.plot_mdc import plot_sensitivity_curve, plot_confusion_matrix, generate_mdc_report
    import yaml
    import pandas as pd
    
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Injection config not found: {config_path}")
        sys.exit(1)
        
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
        
    n_injections = cfg.get("n_injections_per_type", 50)
    grid_start = cfg.get("amplitude_grid_start", -22.0)
    grid_end = cfg.get("amplitude_grid_end", -20.7)
    grid_steps = cfg.get("amplitude_grid_steps", 10)
    
    amplitude_grid = np.logspace(grid_start, grid_end, grid_steps)
    
    glitch_types = cfg.get("glitch_types", ["ZSweep", "SpiralBurst", "StepLadder", "Butterfly", "NoiseBlob"])
    detector = cfg.get("detector", "L1")
    seed = cfg.get("seed", 42)
    
    run = _resolve_run(args)
    global_cfg = load_config()
    start_gps = _run_start_gps(run, global_cfg)
    
    # We'll run over 4 hours of data starting 1 week into the run
    session_gps_start = start_gps + 3600 * 24 * 7
    session_gps_end = session_gps_start + 3600 * 4
    
    output_dir = Path("results/mdc")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("=== MOCK DATA CHALLENGE ===")
    logger.info("Injecting into %s data from %d to %d", detector, session_gps_start, session_gps_end)
    
    summary_df = run_mdc(
        session_gps_start=session_gps_start,
        session_gps_end=session_gps_end,
        detector=detector,
        glitch_types=glitch_types,
        n_injections_per_type=n_injections,
        amplitude_grid=amplitude_grid,
        output_dir=output_dir,
        seed=seed
    )
    
    raw_df = pd.read_csv(output_dir / "mdc_raw_results.csv", keep_default_na=False)
    
    snr_50_dict = plot_sensitivity_curve(summary_df, output_dir)
    plot_confusion_matrix(raw_df, output_dir)
    generate_mdc_report(summary_df, raw_df, snr_50_dict, output_dir)
    
    logger.info("MDC complete. Results in %s", output_dir)


def _add_run_argument(parser: argparse.ArgumentParser) -> None:
    """Add the ``--run`` argument to a subparser."""
    parser.add_argument(
        "--run",
        type=str,
        default="O4a",
        choices=VALID_RUNS,
        help=(
            "Observing run: O2, O3a, O3b, O4a. "
            "Controls directory layout and scan start date. Default: O4a."
        ),
    )


def _add_mode_argument(parser: argparse.ArgumentParser) -> None:
    """Add the ``--mode`` argument to a subparser."""
    parser.add_argument(
        "--mode",
        choices=["global", "patch"],
        default="global",
        help="Specifica il paradigma architetturale: 'global' (pool [CLS] standard) o 'patch' (Multi-Instance Learning)"
    )


def cmd_build_patch_reference(args: argparse.Namespace) -> None:
    """Build a compressed patch-level reference index from an images directory."""
    from src.pipeline_v1_legacy.index_builder import PatchIndexBuilder
    
    images_dir = Path(args.images_dir)
    output_npz = Path(args.output)
    
    logger.info("=== BUILD PATCH REFERENCE ===")
    logger.info("Images Dir: %s", images_dir)
    logger.info("Output: %s", output_npz)
    
    builder = PatchIndexBuilder()
    builder.build_index(images_dir, output_npz)


def cmd_patch_production(args: argparse.Namespace) -> None:
    import time
    import random
    from datetime import datetime, timezone
    from src.core.patch_producer import PatchProducer
    from src.core.patch_scorer import PatchScorer
    from src.pipeline_v2_production.production_writer import ProductionWriter

    data_dir = Path(args.data_dir)
    detector = args.detector
    sessions = args.sessions
    output_dir = Path(args.output_dir)
    resume = args.resume
    k = args.k
    k_ablations = getattr(args, "k_ablations", [15, 37, 68, 100])
    fpr = args.fpr
    n_background = args.n_background
    seed = getattr(args, "seed", 42)
    workers = getattr(args, "workers", 8)
    batch_size = getattr(args, "batch_size", 32)
    engine = getattr(args, "engine", "canonical")

    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Inject data_dir into global directories to support --data-dir override globally
    from src.core.data_loader import _DATA_DIRECTORIES
    if data_dir not in _DATA_DIRECTORIES:
        _DATA_DIRECTORIES.insert(0, data_dir)
    
    seed = getattr(args, "seed", 42)
    reference_run = getattr(args, "reference_run", "O3b").lower()
    
    from src.core.utils import get_reference_dir
    _ref_dir = get_reference_dir()
    primary_index_path = str(_ref_dir / f"patch_compressed_index_{reference_run}.npz")
    if not Path(primary_index_path).exists():
        logger.warning(f"Primary reference index {primary_index_path} not found. Ensure it was built.")
        
    # 1. Initialize PatchScorer
    scorer = PatchScorer(
        reference_index_path=primary_index_path,
        k=k,
        k_ablations=k_ablations,
        fpr=fpr,
        n_background=n_background,
        seed=seed
    )
    
    native_scorer = None
    run_str = getattr(args, "run", "O4a").lower()
    
    # Native dual-scoring must use the same representation as PatchProducer.
    # Historical unversioned Q32 indices are not silently accepted.
    from src.core.index_contract import load_index_contract, qrange_tag
    from src.core.utils import load_config
    production_qrange = tuple(
        int(value) for value in load_config()["preprocessing"]["qrange"]
    )
    coherent_index = (
        _ref_dir
        / f"patch_compressed_index_{run_str}_"
          f"{qrange_tag(production_qrange)}_ex.npz"
    )
    index_ex = _ref_dir / f"patch_compressed_index_{run_str}_ex.npz"
    index_official = _ref_dir / f"patch_compressed_index_{run_str}.npz"

    auto_native_index = None
    for candidate_index in (coherent_index, index_ex, index_official):
        if not candidate_index.exists():
            continue
        try:
            contract = load_index_contract(candidate_index)
        except Exception as exc:
            logger.warning(
                "Skipping native dual-scoring index %s: %s",
                candidate_index,
                exc,
            )
            continue
        if tuple(contract.qrange) != production_qrange:
            logger.warning(
                "Skipping native dual-scoring index %s: qrange %s != %s",
                candidate_index,
                contract.qrange,
                production_qrange,
            )
            continue
        auto_native_index = candidate_index
        break
        
    if auto_native_index is not None:
        logger.info(
            "Loading representation-matched native index for dual-scoring: %s",
            auto_native_index,
        )
        native_scorer = PatchScorer(
            reference_index_path=str(auto_native_index),
            k=k,
            k_ablations=k_ablations,
            fpr=fpr,
            n_background=0,  # Optimization: skip empirical background modeling for the secondary scorer
            seed=seed,
            model=scorer.model if engine == "shared_encoder" else None,
        )
    else:
        logger.warning(
            "No declared native index matches PatchProducer qrange %s; "
            "secondary native dual-scoring is disabled.",
            production_qrange,
        )
    
    if not sessions:
        logger.info("Nessuna sessione fornita esplicitamente. Tento l'auto-discovery delle cartelle in data_dir...")
        
        from src.core.data_loader import _DATA_DIRECTORIES
        
        search_dirs = []
        if data_dir.exists():
            search_dirs.append(data_dir)
        for d in _DATA_DIRECTORIES:
            if d.exists() and d not in search_dirs:
                search_dirs.append(d)
                
        if not search_dirs:
            error_msg = f"Errore: Nessuna cartella dati disponibile (né {data_dir} né i fallback in config.yaml)."
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
            
        discovered_sessions = []
        for s_dir in search_dirs:
            for path in s_dir.iterdir():
                if path.is_dir() and path.name.isdigit() and list(path.rglob(f"*{detector}*.hdf5")):
                    discovered_sessions.append(path.name)
                    
        discovered_sessions = list(set(discovered_sessions))
                
        if discovered_sessions:
            args.sessions = sorted(discovered_sessions)
            sessions = args.sessions
            logger.info(f"Trovate {len(sessions)} sessioni. Ordine cronologico: {sessions}")
        else:
            logger.warning("Nessuna sottocartella valida trovata. Processo data_dir come sessione unica ('ALL').")
            args.sessions = ["ALL"]
            sessions = args.sessions
        
    for session in sessions:
        logger.info(f"=== Starting Patch-Level Production for Session {session} ===")
        writer = ProductionWriter(output_dir, session, detector)
        
        if resume and writer.is_completed():
            logger.info(f"[SKIP] Session {session} is already fully parsed (DONE in checkpoint). Skipping Patch Production.")
            continue
            
        # Setup session logging manually since root wrapper misses list args
        from src.core.utils import set_session_log_file, close_session_log
        log_file = writer.logs_dir / "session.log"
        set_session_log_file(log_file)
        
        import warnings
        warnings.filterwarnings("ignore", module="gwpy.signal.qtransform")
        
        session_data_dir = data_dir / session if session != "ALL" else data_dir
        producer = PatchProducer(session_data_dir, detector, workers=workers, batch_size=batch_size)
        
        # Calibrate Threshold
        logger.info("Calibrating threshold...")
        existing_threshold = writer.load_threshold() if resume else None
        
        if existing_threshold is not None:
            logger.info(f"Loaded existing calibrated threshold ({existing_threshold:.4f}) from HDF5.")
            threshold = existing_threshold
            
            # Verify MD5 without overwriting metadata
            metadata = {
                "reference_md5": scorer.reference_md5,
                "reference_sha256": scorer.reference_sha256,
                "index_integrity_verified": scorer.index_integrity_verified,
            }
            writer.verify_and_init(metadata, np.zeros(1), threshold)
            
        else:
            logger.info(f"Extracting {n_background} background samples for p99 calibration...")
            bg_samples = []
            bg_gps = []
            rng = random.Random(seed)
            shuffled_files = list(producer.hdf5_files)
            rng.shuffle(shuffled_files)
            
            calib_producer = PatchProducer(session_data_dir, detector, workers=workers, batch_size=batch_size)
            calib_producer.hdf5_files = shuffled_files
            
            from tqdm import tqdm
            with tqdm(total=n_background, desc="Calibrating p99") as pbar:
                for gps_batch, spec_batch in calib_producer:
                    bg_samples.extend(spec_batch)
                    bg_gps.extend(gps_batch)
                    pbar.update(len(spec_batch))
                    if len(bg_samples) >= n_background:
                        break
            
            # Trim excess background samples
            bg_samples = bg_samples[:n_background]
            bg_gps = bg_gps[:n_background]
                    
            if len(bg_samples) == 0:
                logger.warning(f"No valid segments found for session {session}. Skipping.")
                continue
                
            threshold, bg_scores, gev_params = scorer.calibrate_threshold(bg_samples)
            bg_gps_np = np.array(bg_gps, dtype=np.float64)
            
            metadata = {
                "session_id": session,
                "detector": detector,
                "threshold": float(threshold),
                "k": k,
                "reference_md5": scorer.reference_md5,
                "reference_sha256": scorer.reference_sha256,
                "index_integrity_verified": scorer.index_integrity_verified,
                "index_artifact_id": scorer.index_artifact_id,
                "n_background": len(bg_samples),
                "timestamp_created": datetime.now(timezone.utc).isoformat(),
                "gev_params": gev_params
            }
            
            writer.verify_and_init(metadata, bg_scores, threshold, bg_gps_np)
        
        last_gps = writer.load_checkpoint() if resume else None
        if last_gps:
            logger.info(f"[RESUME] Riprendendo da GPS: {last_gps}")
            producer.resume_gps = last_gps
            
        processed = 0
        novel_count = 0
        import torch
        
        native_scores_log = []
        
        for gps_batch, spec_batch in producer:
            # Filter batch items that are already processed
            valid_gps = []
            valid_spec = []
            for g, s in zip(gps_batch, spec_batch):
                if not (last_gps and g <= last_gps):
                    valid_gps.append(g)
                    valid_spec.append(s)
                    
            if not valid_gps:
                continue
                
            if native_scorer and engine == "shared_encoder":
                dual_results = scorer.score_multi_index(
                    valid_spec,
                    {
                        "primary": (scorer, threshold),
                        "native": (native_scorer, 1.0),
                    },
                    output_modes={"native": "score_only"},
                )
                results = dual_results["primary"]
                native_results = dual_results["native"]
            else:
                results = scorer.score_spectrogram(valid_spec, threshold)
                native_results = (
                    native_scorer.score_spectrogram(valid_spec, 1.0)
                    if native_scorer
                    else []
                )

            if native_results:
                for nr in native_results:
                    native_scores_log.append(nr["novelty_score"])

            processed += len(valid_gps)
            novel_records = [
                (gps_start, result_dict)
                for gps_start, result_dict in zip(valid_gps, results)
                if result_dict["is_novel"]
            ]
            writer.append_batch(valid_gps, novel_records)
            novel_count += len(novel_records)
            # Advance only after both coverage and novelty rows are committed.
            writer.save_checkpoint(valid_gps[-1])
            
            if processed % 500 < len(valid_gps): # Roughly every 500 items
                mem_mb = torch.cuda.memory_allocated() / (1024 * 1024)
                rate = (novel_count / processed) * 100
                estimated_total = len(list(producer.hdf5_files)) * int(4096 / producer.segment_duration)
                logger.info(
                    "[PROGRESS] Session: %s | Processati: %d / ~%d | Novel: %d (%.2f%%) | GPU Mem: %.1f MB",
                    session, processed, estimated_total, novel_count, rate, mem_mb
                )
            
            if processed % 1000 < len(valid_gps):
                torch.cuda.empty_cache()
                
        writer.mark_completed()
        logger.info(f"=== Session {session} Complete. Novel found: {novel_count} ===")
        
        if native_scorer and native_scores_log:
            run_str = getattr(args, "run", "O4a")
            native_arr = np.array(native_scores_log, dtype=np.float32)
            out_file = output_dir / session / f"{run_str}_{session}_{detector}_native_scores.npy"
            np.save(out_file, native_arr)
            logger.info(f"Saved {len(native_scores_log)} native background scores for Domain Shift Defense to {out_file}")
        
        from src.core.data_loader import clear_astropy_cache
        clear_astropy_cache()
        
        close_session_log()


def _cmd_dante_light(args: argparse.Namespace, *, prospective: bool) -> None:
    import json
    from src.dante_light.runner import run_replay

    args.prospective = prospective
    if not args.role:
        args.role = ["background_stratified"]
    result = run_replay(args)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


def cmd_dante_light_replay(args: argparse.Namespace) -> None:
    """Run exact finite replay without claiming prospective causality."""
    _cmd_dante_light(args, prospective=False)


def cmd_dante_light_shadow(args: argparse.Namespace) -> None:
    """Run prospective shadow mode; historical/non-causal epochs DEFER."""
    _cmd_dante_light(args, prospective=True)


def cmd_production_cluster(args):
    from src.pipeline_v2_production.production_cluster import H5Clusterer
    from pathlib import Path
    import sys
    
    input_file = Path(args.input)
    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        sys.exit(1)
        
    output_dir = Path(args.output_dir) if args.output_dir else input_file.parent
    
    clusterer = H5Clusterer(h5_path=input_file, output_dir=output_dir)
    clusterer.run_clustering()
def cmd_production_report(args):
    """Run the Phase 6 production report pipeline."""
    logger.info("=== Starting Production Report ===")
    from src.pipeline_v2_production.production_report import ValidationReporter
    output_dir = getattr(args, "output_dir", "data/production")
    reference_run = getattr(args, "reference_run", "O3b")
    nds_host_arg = getattr(args, "nds_host", None)
    if getattr(args, "skip_pem", False):
        nds_host_arg = None
        
    reporter = ValidationReporter(
        session_id=args.session_id, 
        detector=args.detector, 
        run_name=getattr(args, "run", "O4a"),
        reference_run=reference_run,
        output_dir=output_dir,
        nds_host=nds_host_arg
    )
    if getattr(args, "only_plots", False):
        reporter.run_only_plots()
    else:
        reporter.run()


def cmd_validate_reports(args):
    """Validate all required artifacts and metadata constraints."""
    import sys
    import json
    from pathlib import Path
    logger.info(f"=== Validating Reports for Session {args.session_id} ({args.detector}) ===")
    
    output_dir = getattr(args, "output_dir", "data/production")
    prod_dir = Path(output_dir) / str(args.session_id)
    report_dir = prod_dir / "report"
    
    # Required files map
    files_to_check = [
        prod_dir / f"cluster_report_novelties_{args.session_id}_{args.detector}.json",
        prod_dir / f"umap_novelties_{args.session_id}_{args.detector}.png",
        report_dir / f"full_discovery_report_{args.session_id}_{args.detector}.md",
        report_dir / f"morphcheck_novelties_{args.session_id}_{args.detector}.csv",
        report_dir / f"temporal_distribution_{args.session_id}_{args.detector}.png",
        report_dir / f"pooling_comparison_{args.session_id}_{args.detector}.png",
        report_dir / f"report_status_{args.session_id}_{args.detector}.json",
    ]
    
    failed = False
    
    for f in files_to_check:
        if not f.exists():
            logger.error(f"[VALIDATION FAILED] Missing required file: {f.name}")
            failed = True
            
    # Check JSON specifics
    json_path = prod_dir / f"cluster_report_novelties_{args.session_id}_{args.detector}.json"
    if json_path.exists():
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
                
            # Check GPS duplicates in each cluster
            total_unique = 0
            singletons = 0
            for cid, cdata in data.get("clusters", {}).items():
                gps_list = cdata.get("gps_times", [])
                if len(gps_list) != len(set(gps_list)):
                    logger.error(f"[VALIDATION FAILED] GPS duplicates found in cluster {cid}")
                    failed = True
                total_unique += len(set(gps_list))
                if len(set(gps_list)) == 1:
                    singletons += 1
                    
            if data.get("n_samples") != total_unique:
                logger.error(f"[VALIDATION FAILED] n_samples mismatch: {data.get('n_samples')} != {total_unique}")
                failed = True
                
            req_fields = [
                "session_start_gps", "session_end_gps", "detector", "dq_flag_used", 
                "threshold_p99", "background_n_samples", "background_gps_saved", 
                "vq_index_md5", "generation_timestamp", "gps_dedup_validated", 
                "distribution_separation_sigma", "n_singleton_clusters"
            ]
            for field in req_fields:
                if field not in data:
                    logger.error(f"[VALIDATION FAILED] Missing root metadata field in JSON: {field}")
                    failed = True
                    
        except Exception as e:
            logger.error(f"[VALIDATION FAILED] Could not parse JSON: {e}")
            failed = True
            
    if failed:
        logger.error(f"Validation FAILED for {args.session_id}_{args.detector}. Exiting with code 1.")
        sys.exit(1)
    else:
        logger.info(f"[VALIDATION PASSED] Session {args.session_id}_{args.detector} is fully valid.")
        sys.exit(0)


def cmd_aggregate_report(args):
    """Cross-session aggregation, deduplication, and Spearman stability defense."""
    logger.info("=== Starting Aggregate Report ===")
    run = _resolve_run(args)
    from src.pipeline_v2_production.aggregate_report import AggregateReporter
    reporter = AggregateReporter(
        production_dir=args.production_dir,
        run=run,
        native_index_path=getattr(args, "native_index", None),
        allow_legacy_cross_representation=getattr(
            args,
            "allow_legacy_cross_representation",
            False,
        ),
        candidate_window_offset=getattr(
            args,
            "candidate_window_offset",
            4.0,
        ),
        native_background_n=getattr(args, "dsd_background_n", 5000),
    )
    reporter.run()

    # Automatically run offline validation scripts
    logger.info("Starting automated offline validation...")
    import subprocess
    import sys
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.abspath(".")
    
    try:
        from src.core.utils import load_config
        detectors = load_config().get("detectors", ["H1", "L1"])
        
        for det in detectors:
            logger.info(f"-> Running Poisson Upper Limit ({det})...")
            subprocess.run([sys.executable, "src/pipeline_v2_production/poisson_upper_limit.py", "--detector", det], env=env, check=True)

        logger.info("-> Running PEM Coherence Analysis...")
        nds_host = getattr(args, "nds_host", None)
        pem_cmd = [sys.executable, "src/pipeline_v2_production/pem_coherence_analysis.py"]
        if nds_host:
            pem_cmd.extend(["--nds-host", nds_host])
            
        subprocess.run(pem_cmd, env=env, check=True)
        
        logger.info("All automated offline validation scripts completed and injected successfully.")
    except Exception as e:
        logger.error(f"Failed to execute automated offline validation scripts: {e}")


def cmd_patch_analysis(args):
    """Orchestrates the full Phase 4 & 5 pipeline."""
    logger.info("=== Starting Automated Patch-Analysis Pipeline ===")
    
    # Enable resume by default for automated full-pipeline runs
    args.resume = True
    
    logger.info("STEP 1: Patch Production")
    cmd_patch_production(args)
    
    from pathlib import Path
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    
    sessions_to_process = args.sessions
    if not sessions_to_process:
        logger.error("No sessions found to process for patch-analysis.")
        return
        
    detectors = [args.detector]
    
    for session in sessions_to_process:
        for det in detectors:
            # Check if session is already fully completed (report exists)
            report_file = output_dir / str(session) / "report" / f"full_discovery_report_{session}_{det}.md"
            if report_file.exists():
                logger.info(f"[SKIP] Session {session} ({det}) is already fully analyzed (report exists).")
                continue
                
            h5_path = output_dir / str(session) / f"novelties_{session}_{det}.h5"
            if h5_path.exists():
                logger.info(f"STEP 2: Clustering for session {session} ({det})")
                class ClusterArgs:
                    pass
                c_args = ClusterArgs()
                c_args.input = str(h5_path)
                c_args.output_dir = str(output_dir / str(session))
                cmd_production_cluster(c_args)
                
                logger.info(f"STEP 3: Production Report for session {session} ({det})")
                class ReportArgs:
                    pass
                r_args = ReportArgs()
                r_args.session_id = str(session)
                r_args.detector = det
                r_args.run = getattr(args, "run", "O4a")
                r_args.reference_run = getattr(args, "reference_run", "O3b")
                r_args.output_dir = str(output_dir)
                cmd_production_report(r_args)
                
                logger.info(f"STEP 4: Report Validation for session {session} ({det})")
                try:
                    # Run without exiting since we are in a loop
                    import sys
                    from unittest.mock import patch
                    with patch.object(sys, 'exit') as mock_exit:
                        cmd_validate_reports(r_args)
                        if mock_exit.call_args and mock_exit.call_args[0][0] == 1:
                            logger.error(f"Validation failed for {session}_{det}. Halting loop.")
                            sys.exit(1)
                except SystemExit as e:
                    if e.code != 0: raise
                    
                from src.core.data_loader import clear_astropy_cache
                clear_astropy_cache()
            else:
                logger.warning(f"No production output found at {h5_path}. Skipping clustering.")


def cmd_pem_coherence_analysis(args: argparse.Namespace) -> None:
    """Run PEM offline coherence analysis."""
    from src.pipeline_v2_production.pem_coherence_analysis import run_pem_coherence_analysis

    logger.info("=== PEM COHERENCE ANALYSIS ===")
    
    tax_csv = (
        Path(args.taxonomy_csv)
        if args.taxonomy_csv is not None
        else None
    )
    cache_d = Path(args.cache_dir)
    out_d = Path(args.output_dir)
    
    run_pem_coherence_analysis(
        taxonomy_csv=tax_csv,
        cache_dir=cache_d,
        output_dir=out_d,
        target_families=args.target_families,
        include_singletons=not args.no_singletons,
        max_events_per_family=args.max_events,
        nds_host=args.nds_host,
        robustness_class=args.robustness_class,
        run_name=args.run,
        inject_final_report=args.inject_final_report,
        events_per_class=(
            {
                "ROBUST": args.robust_events or 0,
                "AMBIGUOUS": args.ambiguous_events or 0,
                "BACKGROUND": args.background_events or 0,
            }
            if any(
                value is not None
                for value in (
                    args.robust_events,
                    args.ambiguous_events,
                    args.background_events,
                )
            )
            else None
        ),
        reuse_existing_dir=args.reuse_existing_dir,
        selection_only=args.selection_only,
    )


def cmd_coincidence_physical(args: argparse.Namespace) -> None:
    """Authoritative cross-detector coincidence test (audit COINC-3).

    Normally runs automatically as phase 3b of `aggregate-report`; exposed here
    so it can be re-run standalone without regenerating the whole report.
    """
    from src.pipeline_v2_production.coincidence_physical import run as run_coinc

    summary = run_coinc(
        args.run,
        n_candidates=args.n,
        aggregated_dir=Path(args.aggregated_dir),
        production_dir=Path(args.aggregated_dir).parent,
        with_iou=not args.no_iou,
    )
    logger.info(
        f"{summary.get('n_exceeding')} of {summary.get('n')} candidates exceed "
        f"the pooled null threshold {summary.get('cc_null_max_p99')}"
    )


def cmd_coincidence_efficiency(args: argparse.Namespace) -> None:
    """Measure epsilon_coh of the PHYSICAL coincidence statistic.

    Note: `coincidence_injection_test.py` measures the RETIRED embedding
    statistic and is not a substitute for this.
    """
    from src.pipeline_v2_production.coincidence_physical_efficiency import run as run_eps

    out = run_eps(
        args.run,
        n_trials=args.n_trials,
        n_null=args.n_null,
        seed=args.seed,
        aggregated_dir=Path(args.aggregated_dir),
    )
    rows = out.get("rows", [])
    n_sat = len({r["morphology"] for r in rows if r.get("epsilon_coh", 0) >= 1.0})
    n_morph = len({r["morphology"] for r in rows})
    logger.info(
        f"{n_sat}/{n_morph} morphologies reach epsilon_coh=100%; "
        f"null exceeding {out.get('null_exceeding_frac', float('nan')):.1%}"
    )


def cmd_background_cohesion(args: argparse.Namespace) -> None:
    """Falsification test: is the survivor macro-cluster specific to survivors?

    On O4a it is not -- unselected native background is the most monolithic
    population of all, so the topology carries no anomaly information.
    """
    from src.pipeline_v2_production.background_cohesion_test import run as run_cohesion

    out = run_cohesion(
        args.run,
        n_segments=args.n_segments,
        n_draws=args.n_draws,
        seed=args.seed,
        aggregated_dir=Path(args.aggregated_dir),
        production_dir=Path(args.aggregated_dir).parent,
    )
    sm = out.get("size_matched", {})
    bg = sm.get("NATIVE_BACKGROUND", {}).get("largest_frac_mean")
    ro = sm.get("ROBUST", {}).get("largest_frac_mean")
    if bg is not None and ro is not None:
        logger.info(f"native background {bg:.3%} vs ROBUST {ro:.3%} in largest cluster")


def cmd_dsd_absorption(args: argparse.Namespace) -> None:
    """At what prevalence does the DSD stop seeing a glitch morphology?

    The native index is built from the run's own background, so a morphology
    common enough there is learned by the dictionary and re-scored as background
    by construction. This measures where that happens, against a same-size
    all-background control.
    """
    from src.pipeline_v2_production.dsd_absorption_threshold import run as run_absorption

    out = run_absorption(
        morphology=args.morphology,
        amplitude=args.amplitude,
        duration=args.duration,
        n_background=args.n_background,
        run_name=args.run,
        seed=args.seed,
    )
    rows = out.get("rows", [])
    if rows:
        z0 = rows[0]["z_injected_vs_background"]
        zn = rows[-1]["z_injected_vs_background"]
        logger.info(
            f"{out['morphology']}: separation {z0:.2f} -> {zn:.2f} sigma "
            f"between {rows[0]['prevalence']:.0%} and {rows[-1]['prevalence']:.0%} prevalence"
        )


def cmd_dsd_index_stability(args: argparse.Namespace) -> None:
    """Are the DSD survivors an artifact of which background built the index?

    Rebuilds the native index from independent background draws and re-scores
    near-threshold candidates. Reports threshold-independent stability metrics.
    """
    from src.pipeline_v2_production.dsd_index_stability import run as run_stab

    out = run_stab(args.run, n_candidates=args.n_candidates,
                   n_draws=args.n_draws, seed=args.seed)
    logger.info(
        f"rank correlation {out['score_rank_correlation_mean']:.3f}, "
        f"per-candidate std {out['per_candidate_score_std_median']:.4f}, "
        f"ROBUST {out['robust_mean_score']:.3f} vs rejected "
        f"{out['rejected_mean_score']:.3f}"
    )


def cmd_pca_baseline(args: argparse.Namespace) -> None:
    """What does the frozen DINOv2 encoder buy over a classical baseline?

    Scores the same near-threshold candidate pool with a PCA subspace novelty
    detector and raw spectral energy, then measures how their ranking agrees
    with DANTE's. Bounds the value of the natural-image transfer (B2).
    """
    from src.pipeline_v2_production.pca_baseline import run as run_pca

    out = run_pca(args.run, n_candidates=args.n_candidates,
                  n_background=args.n_background, seed=args.seed)
    pr, se = out["pca_reconstruction_residual"], out["spectral_energy"]
    logger.info(
        f"PCA-residual rank-corr {pr['rank_correlation_with_dante']:.3f} "
        f"AUC {pr['auc_robust_vs_rejected']:.3f} | spectral-energy rank-corr "
        f"{se['rank_correlation_with_dante']:.3f} AUC "
        f"{se['auc_robust_vs_rejected']:.3f}"
    )


def cmd_whitening_context_sensitivity(args: argparse.Namespace) -> None:
    """How many DSD verdicts flip when the whitening context changes?

    Re-scores near-threshold candidates at several whitening pad lengths and
    counts verdict flips vs the production pad=4 context, quantifying the
    LAB_NOTEBOOK section 12 single-candidate swing at the population level.
    """
    from src.pipeline_v2_production.whitening_context_sensitivity import run as run_wc

    out = run_wc(
        args.run,
        n_candidates=args.n_candidates,
        pads=args.pads,
        seed=args.seed,
        native_index_path=args.native_index,
        n_background=args.n_background,
        anchor_tolerance=args.anchor_tolerance,
        window_offset=args.window_offset,
    )
    logger.info(
        f"context swing median {out['per_candidate_swing_median']:.4f}, "
        f"{out['n_large_swing']} large-swing candidates; recalibrated flip rates "
        f"{ {p: round(f['flip_rate'], 3) for p, f in out['pad_recalibrated_pipeline_flips'].items()} }"
    )


def cmd_blind_spot_map(args: argparse.Namespace) -> None:
    """Where in the time-frequency plane is DANTE blind? An empirical map.

    Injects sine-Gaussian bursts on a (f0, Q) grid at fixed SNR and maps the
    flag rate, validating the analytic T=Q_max/f blind-spot boundary against
    what actually happens near it.
    """
    from src.pipeline_v2_production.blind_spot_map import run as run_bs

    out = run_bs(args.run, n_realizations=args.n_realizations, seed=args.seed)
    logger.info(
        f"mean flag rate Q<=Qmax {out['mean_flag_rate_Q_le_Qmax']} vs "
        f"Q>Qmax {out['mean_flag_rate_Q_gt_Qmax']}, "
        f"{len(out['blind_cells'])} blind cells"
    )


def cmd_characterize_candidate(args: argparse.Namespace) -> None:
    """Generic independent descriptors plus a production-veto lookup."""
    from src.pipeline_v2_production.characterize_candidate import run as run_char

    out = run_char(
        args.detector,
        args.gps,
        args.feature_gps,
        band=args.band,
        partner=args.partner,
        n_background=args.n_background,
        bg_spacing=args.bg_spacing,
        catalog_gps=args.catalog_gps,
        coincidence_artifact=args.coincidence_artifact,
    )
    logger.info(
        f"peak {out['peak_frequency_hz']:.1f} Hz | loudness "
        f"{out['loudness_ratio_to_background_mean']:.0f}x | raw cross-corr "
        f"{out['raw_cross_detector_max_corr']:.3f}"
    )


def cmd_dsd_threshold_mc_error(args: argparse.Namespace) -> None:
    """Monte-Carlo error on the DSD thresholds (R3).

    Bootstraps the per-detector tau_hi/tau_lo from the stored native background
    scores. Produces a representation-versioned MC-error diagnostic. The
    robustness samplers read the authoritative coherent DSD threshold artifact,
    not this diagnostic.
    """
    from src.pipeline_v2_production.dsd_threshold_mc_error import run as run_mc

    out = run_mc(args.run, reps=args.reps, B=args.B)
    for det, r in out.get("detectors", {}).items():
        logger.info(
            f"{det}: tau_hi={r['tau_hi']['mean']:.5f}+/-{r['tau_hi']['mc_std']:.5f}"
        )


def cmd_dsd_k_sensitivity(args: argparse.Namespace) -> None:
    """Is the DSD survivor population an artifact of the dictionary size K? (P4)

    Rebuilds the native index at several K from P5's cached background tokens and
    re-scores the same candidates. Reports threshold-independent stability.
    """
    from src.pipeline_v2_production.dsd_k_sensitivity import run as run_k

    out = run_k(args.run, n_candidates=args.n_candidates,
                k_values=args.k_values, seed=args.seed)
    logger.info(
        f"rank-corr vs production K {out['rank_correlation_vs_production_k']}, "
        f"per-candidate std {out['per_candidate_score_std_median']:.4f}"
    )


def cmd_catalog_cross_match(args: argparse.Namespace) -> None:
    """Catalogue-window overlap control with a circular-shift null (P11)."""
    from src.pipeline_v2_production.catalog_cross_match import run as run_xm

    out = run_xm(
        args.run,
        refresh=args.refresh,
        coverage_source=args.coverage_source,
        n_shifts=args.n_shifts,
        seed=args.seed,
        minimum_shift_s=args.minimum_shift_s,
        production_dir=args.production_dir,
    )
    observed = out["observed"]
    null = out["circular_shift_null"]["overlap_any"]
    logger.info(
        f"observed overlap={observed['overlap_any']}, "
        f"null mean={null['null_mean']:.3f}, "
        f"empirical p={null['empirical_p_ge_observed']:.4g}"
    )


def cmd_inter_session_recurrence(args: argparse.Namespace) -> None:
    """Does any morphology recur across widely separated sessions?

    A glitch class recurs months apart; noise does not. Tested on the stored
    MIL vectors, against the baseline set by how candidates are distributed
    over sessions.
    """
    from src.pipeline_v2_production.inter_session_recurrence import run as run_isr

    out = run_isr(args.run, top_n=args.top_n, k_neighbours=args.k_neighbours,
                  seed=args.seed)
    for det, r in out.get("detectors", {}).items():
        logger.info(
            f"{det}: cross-session enrichment x{r['enrichment_top_vs_baseline']:.2f}, "
            f"neighbour-span z={r['neighbour_session_span_z']:+.1f}"
        )


def cmd_poisson_upper_limit(args: argparse.Namespace) -> None:
    from src.pipeline_v2_production.poisson_upper_limit import run_poisson_upper_limit
    from src.core.utils import load_config
    
    detectors = [args.detector] if args.detector else load_config().get("detectors", ["H1", "L1"])
    
    for det in detectors:
        logger.info(f"Running poisson upper limit for {det}")
        run_poisson_upper_limit(
            aggregated_dir=Path(args.production_dir) / "aggregated",
            target_detector=det,
            cl=0.90,
            run=getattr(args, "run", "O4a"),
        )


def cmd_multiscale_analysis(args: argparse.Namespace) -> None:
    """V3 multiscale characterization of V2 candidates (no discovery fusion)."""
    from src.pipeline_v3_multiscale.multiscale_candidates import profile_candidates
    profile_candidates(
        run=args.run,
        aggregated_dir=Path(args.production_dir) / "aggregated",
        detectors=tuple(args.detectors),
    )


def cmd_multiscale_report(args: argparse.Namespace) -> None:
    """One-shot V3 entrypoint (mirror of aggregate-report for the V3 layer).

    1. Preflight: per-detector patch dictionaries and block-bootstrap
       thresholds must exist and be tagged for the target run
       (assert_threshold_run). Missing artifacts abort with the exact
       command needed to build them — nothing is silently skipped.
    2. Profiles every V2 survivor at the {0.5,1,2,4}s scales
       (Multiscale_Profile_{run}.csv).
    3. Regenerates Final_Discovery_Report.md from aggregate_summary.json
       so the disposition ledger picks up the new dominant scales —
       the V3 layer therefore updates the final report dynamically.
    """
    import json as _json
    from src.pipeline_v3_multiscale.multiscale_candidates import profile_candidates
    from src.pipeline_v3_multiscale.sampling import assert_threshold_run

    v3_dir = Path("results/micro_mdc/multiscale")
    scales = ["0.5", "1", "2", "4"]
    problems: list[str] = []
    for det in args.detectors:
        for s in scales:
            dpath = v3_dir / f"{det}_patch_dict_{s}s.npz"
            if not dpath.exists():
                problems.append(
                    f"missing dictionary {dpath} — build with: python -m "
                    f"src.pipeline_v3_multiscale.build_multiscale_dictionaries "
                    f"--detector {det}")
                break
        tpath = v3_dir / f"{det}_thresholds.json"
        if not tpath.exists():
            problems.append(
                f"missing thresholds {tpath} — calibrate with: python -m "
                f"src.pipeline_v3_multiscale.micro_mdc_multiscale "
                f"--detector {det}")
        else:
            with open(tpath) as f:
                assert_threshold_run(_json.load(f), args.run)
    if problems:
        for p in problems:
            logger.error(f"[V3 PREFLIGHT] {p}")
        raise SystemExit(
            "multiscale-report aborted: V3 artifacts incomplete (see above).")

    aggregated_dir = Path(args.production_dir) / "aggregated"
    profile_candidates(
        run=args.run,
        aggregated_dir=aggregated_dir,
        detectors=tuple(args.detectors),
    )

    if args.skip_report:
        logger.info("Report regeneration skipped (--skip-report).")
        return
    from src.pipeline_v2_production.aggregate_report import AggregateReporter
    rep = AggregateReporter(production_dir=args.production_dir, run=args.run)
    summary_path = rep.output_dir / "aggregate_summary.json"
    if not summary_path.exists():
        raise SystemExit(
            f"{summary_path} not found: run aggregate-report first — the V3 "
            "layer characterizes V2 output, it cannot precede it.")
    with open(summary_path) as f:
        metrics = _json.load(f)
    rep._generate_markdown_report(metrics)
    logger.info("Final report regenerated with updated multiscale profiles.")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="gravi-signal-ml",
        description=(
            "Unsupervised anomaly detection pipeline for gravitational-wave "
            "data.  Discovers novel glitch classes in LIGO/Virgo data "
            "across observing runs O2–O4a."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--cudnn-autotune",
        action="store_true",
        help="Enable cuDNN auto-tuner for max convolution efficiency (may increase GPU memory usage).",
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- fetch ---
    p_fetch = subparsers.add_parser(
        "fetch",
        help="Fetch a known reference event and generate a spectrogram.",
    )
    p_fetch.add_argument(
        "--event",
        type=str,
        required=True,
        help="Event name (e.g., GW150914). Must be in config.yaml.",
    )
    p_fetch.set_defaults(func=cmd_fetch)

    # --- run-injection ---
    p_injection = subparsers.add_parser(
        "run-injection",
        help="Run Mock Data Challenge with synthetic glitch injection.",
    )
    p_injection.add_argument(
        "--config",
        type=str,
        default="injection_config.yaml",
        help="Path to injection config. Default: injection_config.yaml",
    )
    _add_run_argument(p_injection)
    _add_mode_argument(p_injection)
    p_injection.set_defaults(func=cmd_run_injection)


    # --- patch-production ---
    p_patch_production = subparsers.add_parser(
        "patch-production",
        help="Run the Phase 4 Patch-Level Production pipeline on raw O4a data.",
    )
    p_patch_production.add_argument("--data-dir", type=str, default="data/raw/o4a/", help="Directory with raw .hdf5 files")
    p_patch_production.add_argument("--detector", type=str, required=True, choices=["H1", "L1"])
    p_patch_production.add_argument("--sessions", type=str, nargs="+", default=[], help="List of sessions to process")
    p_patch_production.add_argument("--output-dir", type=str, default="data/production/")
    p_patch_production.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    p_patch_production.add_argument("--k", type=int, default=68)
    p_patch_production.add_argument("--fpr", type=float, default=0.01)
    p_patch_production.add_argument("--n-background", type=int, default=500)
    p_patch_production.add_argument("--seed", type=int, default=42)
    p_patch_production.add_argument("--workers", type=int, default=8, help="Number of CPU workers for Q-Transform")
    p_patch_production.add_argument("--batch-size", type=int, default=32, help="Batch size for DINOv2 GPU inference")
    p_patch_production.add_argument("--run", type=str, default="O4a", help="Observing run name (e.g., O4a, O4b, O5)")
    p_patch_production.add_argument("--reference-run", type=str, default="O3b", help="Observing run to use as the primary memory index")
    p_patch_production.add_argument(
        "--engine",
        choices=("canonical", "shared_encoder"),
        default="canonical",
        help="Exact scoring engine. canonical remains the default; shared_encoder is opt-in.",
    )
    p_patch_production.set_defaults(func=cmd_patch_production)

    def add_dante_light_arguments(command):
        command.add_argument(
            "--manifest",
            type=Path,
            default=Path("config/dante_light_replay_v1.json"),
        )
        command.add_argument(
            "--epochs",
            type=Path,
            default=Path("config/dante_light_epochs_v1.json"),
        )
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--role", action="append", default=None)
        command.add_argument("--limit", type=int, default=8)
        command.add_argument("--device", default=None)
        command.add_argument(
            "--engine",
            choices=("canonical", "shared_encoder_score_only"),
            default="canonical",
            help="canonical is the permanent reference; the exact optimized engine is opt-in.",
        )
        command.add_argument("--workers", type=int, default=2)
        command.add_argument("--batch-size", type=int, default=8)
        command.add_argument("--max-in-flight", type=int, default=16)
        command.add_argument("--max-pending-writes", type=int, default=2)
        command.add_argument(
            "--latency-objective-s",
            type=float,
            default=None,
            help=(
                "Pre-register the durable-write p99 objective for prospective "
                "shadow evidence; recorded immutably in the run manifest."
            ),
        )
        command.add_argument("--local-only", action="store_true")
        command.add_argument(
            "--strain-source",
            choices=("auto", "local-only", "gwosc-only"),
            default="auto",
            help=(
                "Strain source contract. gwosc-only bypasses every configured "
                "local mirror and is required for public clean-clone evidence."
            ),
        )
        command.add_argument(
            "--cat1-mode",
            choices=("gwosc", "frozen-replay-attestation"),
            default="gwosc",
            help=(
                "CAT1 evidence source. frozen-replay-attestation is historical "
                "only and is never a prospective DQ claim."
            ),
        )

    p_light_replay = subparsers.add_parser(
        "dante-light-replay",
        help="Opt-in exact DANTE-Light replay with append-only evidence records.",
    )
    add_dante_light_arguments(p_light_replay)
    p_light_replay.set_defaults(func=cmd_dante_light_replay)

    p_light_shadow = subparsers.add_parser(
        "dante-light-shadow",
        help="Prospective shadow runner; rejects historical non-causal epochs.",
    )
    add_dante_light_arguments(p_light_shadow)
    p_light_shadow.set_defaults(func=cmd_dante_light_shadow)

    # --- scan ---
    p_scan = subparsers.add_parser(
        "scan",
        help="Batch-scan segments for a detector (use --run to select observing run).",
    )
    p_scan.add_argument(
        "--detector",
        type=str,
        required=True,
        choices=["H1", "L1", "V1"],
        help="Detector identifier.",
    )
    p_scan.add_argument(
        "--hours",
        type=float,
        default=None,
        help="Duration to scan from run start (hours). Default: value from config.yaml.",
    )
    p_scan.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Number of parallel workers. Use 1 (default) for sequential mode "
            "(any hardware). Use cpu_count-2 for maximum speed on multi-core "
            "systems. Recommended: 6 for Ryzen 7 7800X3D."
        ),
    )
    p_scan.add_argument(
        "--session-id",
        type=str,
        default=None,
        help=(
            "Session identifier for output isolation (e.g. 20260510_143022). "
            "Auto-generated as YYYYMMDD_HHMMSS if omitted."
        ),
    )

    p_scan.add_argument(
        "--no-cache-raw",
        type=str2bool,
        default=True,
        help="If True (default), disables saving raw HDF5 files to data/raw during scan. Set to False to enable.",
    )
    p_scan.add_argument(
        "--raw-path",
        type=str,
        default=None,
        help="Manual path to a specific raw session (e.g., data/raw/1369211232). If omitted, the latest folder is used.",
    )
    p_scan.add_argument(
        "--reprocess",
        action="store_true",
        help="Re-render existing spectrograms with the current colormap.",
    )
    p_scan.set_defaults(func=cmd_scan)
    _add_run_argument(p_scan)

    # --- scan-extended ---
    p_scan_ext = subparsers.add_parser(
        "scan-extended",
        help="Extended scan of H1 + L1 detectors.",
    )
    p_scan_ext.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Number of parallel workers. Use 1 (default) for sequential mode "
            "(any hardware). Use cpu_count-2 for maximum speed on multi-core "
            "systems. Recommended: 6 for Ryzen 7 7800X3D."
        ),
    )
    p_scan_ext.add_argument(
        "--hours",
        type=int,
        default=None,
        help=(
            "Override hours_per_detector from config.yaml. "
            "If omitted, uses scan_extended.hours_per_detector."
        ),
    )
    p_scan_ext.add_argument(
        "--session-id",
        type=str,
        default=None,
        help=(
            "Session identifier for output isolation (e.g. 20260510_143022). "
            "Auto-generated as YYYYMMDD_HHMMSS if omitted."
        ),
    )

    p_scan_ext.add_argument(
        "--no-cache-raw",
        type=str2bool,
        default=True,
        help="If True (default), disables saving raw HDF5 files to data/raw during scan. Set to False to enable.",
    )
    p_scan_ext.add_argument(
        "--full-analysis",
        type=str2bool,
        default=False,
        help="If True, automatically runs the full analysis pipeline (clustering, morphcheck, ablation, stability, timeslide) after scanning.",
    )
    p_scan_ext.add_argument(
        "--skip-timeslide",
        action="store_true",
        help="Skip time-slide analysis during automatic full-analysis.",
    )
    p_scan_ext.add_argument(
        "--n-runs",
        type=int,
        default=20,
        help="Number of stability runs if full-analysis is enabled. Default: 20.",
    )
    p_scan_ext.add_argument(
        "--sequential",
        action="store_true",
        help="If full-analysis is enabled, execute detector analysis sequentially.",
    )
    p_scan_ext.add_argument(
        "--start-gps",
        type=int,
        default=None,
        help="Optional GPS start time to override the run start or resume logic.",
    )
    p_scan_ext.add_argument(
        "--continue-run",
        action="store_true",
        help="Enable continuous run loop after full-analysis.",
    )
    p_scan_ext.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum iterations for the continuous run loop. Default: 10.",
    )
    p_scan_ext.add_argument(
        "--stop-date",
        type=str,
        default=None,
        help="Stop date (ISO string or GPS time) for the continuous run loop.",
    )
    p_scan_ext.add_argument(
        "--raw-path",
        type=str,
        default=None,
        help="Manual path to a specific raw session (e.g., data/raw/1369211232). If omitted, the latest folder is used.",
    )
    p_scan_ext.add_argument(
        "--reprocess",
        action="store_true",
        help="Re-render existing spectrograms with the current colormap.",
    )
    p_scan_ext.set_defaults(func=cmd_scan_extended)
    _add_run_argument(p_scan_ext)

    # --- full-analysis ---
    p_full = subparsers.add_parser(
        "full-analysis",
        help="Automated end-to-end analysis (Cluster, Morph, Ablation, Stability, Timeslide).",
    )
    p_full.add_argument(
        "--session-id",
        type=str,
        required=True,
        help="Session identifier to analyze.",
    )
    p_full.add_argument(
        "--detector",
        type=str,
        nargs="+",
        choices=["H1", "L1", "V1"],
        help="One or more detectors to analyze. If omitted, auto-discovers from session data.",
    )
    p_full.add_argument(
        "--skip-timeslide",
        action="store_true",
        help="Skip time-slide analysis even if H1 and L1 are both analyzed.",
    )
    p_full.add_argument(
        "--n-runs",
        type=int,
        default=20,
        help="Number of runs for stability analysis. Default: 20.",
    )
    p_full.add_argument(
        "--sequential",
        action="store_true",
        help="Execute detector analysis sequentially instead of in parallel.",
    )

    p_full.add_argument(
        "--algorithm",
        type=str,
        choices=["dpmm", "hdbscan"],
        default="dpmm",
        help="Clustering algorithm to use. Default: dpmm.",
    )
    _add_run_argument(p_full)
    _add_mode_argument(p_full)
    p_full.set_defaults(func=cmd_full_analysis)

    # --- full-analysis-report ---
    p_full_report = subparsers.add_parser(
        "full-analysis-report",
        help="Generate final summary reports from existing step reports without running analysis.",
    )
    p_full_report.add_argument(
        "--session-id",
        type=str,
        required=True,
        help="Session identifier to analyze.",
    )
    _add_run_argument(p_full_report)
    _add_mode_argument(p_full_report)
    p_full_report.set_defaults(func=cmd_full_analysis_report)

    # --- last-gps ---
    p_last_gps = subparsers.add_parser(
        "last-gps",
        help="Print the highest GPS end-time from spectrogram filenames in a session.",
    )
    p_last_gps.add_argument(
        "--session-id",
        type=str,
        required=True,
        help="Session identifier to locate the spectrogram directory.",
    )
    p_last_gps.add_argument(
        "--detector",
        type=str,
        required=True,
        choices=["H1", "L1", "V1"],
        help="Detector identifier.",
    )
    p_last_gps.set_defaults(func=cmd_last_gps)
    _add_run_argument(p_last_gps)

    # --- fetch-raw ---
    p_fetch_raw = subparsers.add_parser(
        "fetch-raw",
        help="Download raw GWOSC strain data into local cache.",
    )
    p_fetch_raw.add_argument(
        "--detector",
        type=str,
        nargs="+",
        default=None,
        choices=["H1", "L1", "V1"],
        help="Detector identifier(s). Default: H1 L1.",
    )
    p_fetch_raw.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Numero di worker totali da suddividere tra H1 e L1. Default: 2.",
    )
    p_fetch_raw.add_argument(
        "--hours",
        type=float,
        default=None,
        help="Total hours to download. Default: value from config.yaml for the specific run.",
    )
    p_fetch_raw.add_argument(
        "--start-gps",
        type=int,
        default=None,
        help="Optional GPS start time to override the run start logic.",
    )
    p_fetch_raw.add_argument(
        "--session-id",
        type=int,
        default=None,
        help="Alias for --start-gps to resume or start from a specific folder. If --continue is also passed, it will loop forward from this session.",
    )
    p_fetch_raw.add_argument(
        "--output-dir",
        type=str,
        default="data/raw",
        help="Base directory for HDF5 files. Saves to {base}/{gps_start}/. Default: data/raw.",
    )
    p_fetch_raw.add_argument(
        "--segment-duration",
        type=int,
        default=4096,
        help="Duration of each download block in seconds. Default: 4096.",
    )
    p_fetch_raw.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Disable automatic resume from existing files.",
    )
    p_fetch_raw.add_argument(
        "--retry",
        action="store_true",
        default=False,
        help="Enable retry logic on download failure. Default: False.",
    )
    p_fetch_raw.add_argument(
        "--continue",
        action="store_true",
        default=False,
        dest="continue_download",
        help="Continue download from the last GPS folder in data/raw/. Default: False.",
    )
    p_fetch_raw.add_argument(
        "--loop",
        action="store_true",
        default=False,
        help="Loop continuously downloading new blocks until stopped.",
    )
    p_fetch_raw.add_argument(
        "--max-iterations",
        type=int,
        default=100,
        help="Max loop iterations. Default: 100.",
    )
    p_fetch_raw.set_defaults(func=cmd_fetch_raw)
    _add_run_argument(p_fetch_raw)

    # --- encode (Phase 2) ---
    p_encode = subparsers.add_parser(
        "encode",
        help="Extract DINOv2-Reg embeddings from spectrograms.",
    )
    p_encode.add_argument(
        "--input-dir",
        type=str,
        default=None,
        help=(
            "Directory containing spectrogram PNGs. "
            "Can be omitted if --session-id and --detector are provided."
        ),
    )
    p_encode.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Output .npy file path (e.g. data/embeddings/o4a_h1.npy). "
            "Can be omitted if --session-id and --detector are provided."
        ),
    )
    p_encode.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Batch size for inference. Default: auto-detect.",
    )
    p_encode.add_argument(
        "--session-id",
        type=str,
        default=None,
        help=(
            "Session identifier to resolve input/output paths automatically. "
            "Requires --detector. Explicit --input-dir/--output take priority."
        ),
    )
    p_encode.add_argument(
        "--detector",
        type=str,
        default=None,
        choices=["H1", "L1", "V1"],
        help="Detector identifier. Required when using --session-id.",
    )
    p_encode.set_defaults(func=cmd_encode)
    _add_run_argument(p_encode)

    # --- explain ---
    p_explain = subparsers.add_parser(
        "explain",
        help="[STUB] Generate attention maps for anomaly explainability.",
    )
    p_explain.set_defaults(func=cmd_explain)

    # --- cluster (Phase 3) ---
    p_cluster = subparsers.add_parser(
        "cluster",
        help="Cluster embeddings to discover novel glitch classes.",
    )
    p_cluster.add_argument(
        "--input",
        type=str,
        default=None,
        help=(
            "Path to embedding .npy file (e.g. data/embeddings/o4a_h1_6h.npy). "
            "Can be omitted if --session-id and --detector are provided."
        ),
    )
    p_cluster.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Output directory for cluster report. Default: data/clusters/. "
            "Can be omitted if --session-id and --detector are provided."
        ),
    )
    p_cluster.add_argument(
        "--session-id",
        type=str,
        default=None,
        help=(
            "Session identifier to resolve input/output paths automatically. "
            "Requires --detector. Explicit --input/--output take priority."
        ),
    )
    p_cluster.add_argument(
        "--detector",
        type=str,
        default=None,
        choices=["H1", "L1", "V1"],
        help="Detector identifier. Required when using --session-id.",
    )
    p_cluster.add_argument(
        "--algorithm",
        type=str,
        choices=["dpmm", "hdbscan"],
        default="dpmm",
        help="Clustering algorithm to use. Default: dpmm.",
    )
    _add_mode_argument(p_cluster)
    p_cluster.set_defaults(func=cmd_cluster)
    _add_run_argument(p_cluster)

    # --- report ---
    p_report = subparsers.add_parser(
        "report",
        help="Regenerate UMAP and gallery from existing embeddings and report.",
    )
    p_report.add_argument(
        "--embeddings",
        type=str,
        default=None,
        help="Path to embeddings .npy.",
    )
    p_report.add_argument(
        "--report",
        type=str,
        default=None,
        help="Path to cluster_report.json.",
    )
    p_report.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory to save generated plots and gallery.",
    )
    p_report.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Session identifier to resolve paths automatically. Requires --detector.",
    )
    p_report.add_argument(
        "--detector",
        type=str,
        default=None,
        choices=["H1", "L1", "V1"],
        help="Detector identifier. Required when using --session-id.",
    )
    p_report.add_argument(
        "--algorithm",
        type=str,
        choices=["dpmm", "hdbscan"],
        default="dpmm",
        help="Clustering algorithm to use. Default: dpmm.",
    )
    p_report.set_defaults(func=cmd_report)
    _add_run_argument(p_report)

    # --- stability ---
    p_stability = subparsers.add_parser(
        "stability",
        help="Measure clustering robustness with ARI on multiple runs.",
    )
    p_stability.add_argument(
        "--embeddings",
        type=str,
        default=None,
        help="Path to baseline embeddings .npy.",
    )
    p_stability.add_argument(
        "--n-runs",
        type=int,
        default=20,
        help="Number of perturbed runs to perform. Default: 20.",
    )
    p_stability.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Session identifier to resolve paths automatically.",
    )
    p_stability.add_argument(
        "--detector",
        type=str,
        default="H1",
        choices=["H1", "L1", "V1"],
        help="Detector identifier. Default: H1.",
    )
    p_stability.add_argument(
        "--anomaly-criterion",
        type=str,
        choices=["size", "likelihood"],
        default="likelihood",
        help="Criterion to use for anomaly detection. Default: likelihood.",
    )
    _add_mode_argument(p_stability)
    p_stability.set_defaults(func=cmd_stability)
    _add_run_argument(p_stability)

    # --- ablation ---
    p_ablation = subparsers.add_parser(
        "ablation",
        help="Run ablation study to test clustering robustness against perturbations.",
    )
    p_ablation.add_argument(
        "--embeddings",
        type=str,
        default=None,
        help="Path to baseline embeddings .npy.",
    )
    p_ablation.add_argument(
        "--spectrogram-dir",
        type=str,
        default=None,
        help="Path to original spectrograms directory.",
    )
    p_ablation.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for ablation report.",
    )
    p_ablation.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Session identifier to resolve paths automatically.",
    )
    p_ablation.add_argument(
        "--detector",
        type=str,
        default=None,
        choices=["H1", "L1", "V1"],
        help="Detector identifier. Required when using --session-id.",
    )
    p_ablation.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Batch size for DINOv2 inference. Default: auto-detect.",
    )
    _add_mode_argument(p_ablation)
    p_ablation.set_defaults(func=cmd_ablation)
    _add_run_argument(p_ablation)

    # --- build-reference (Phase 3.3) ---
    p_build = subparsers.add_parser(
        "build-reference",
        help="Build a reference index from Gravity Spy training set.",
    )
    p_build.add_argument(
        "--output",
        type=str,
        required=True,
        help="Path to save the .npz index.",
    )
    p_build.add_argument(
        "--max-per-class",
        type=int,
        default=50,
        help="Maximum samples per class to download.",
    )
    p_build.add_argument(
        "--tar-path",
        default="data/reference/trainingsetv1d1.tar.gz",
        help="Path to the Gravity Spy tar.gz training set "
             "(default: data/reference/trainingsetv1d1.tar.gz)"
    )
    p_build.set_defaults(func=cmd_build_reference)

    # --- build-patch-reference (Phase 2) ---
    p_patch_build = subparsers.add_parser(
        "build-patch-reference",
        help="Build a compressed reference index at patch-level.",
    )
    p_patch_build.add_argument(
        "--images-dir",
        type=str,
        required=True,
        help="Path to the directory containing reference images organized by class (e.g. data/reference/build/o3b_h1/).",
    )
    p_patch_build.add_argument(
        "--output",
        type=str,
        default="data/reference/patch_compressed_index.npz",
        help="Path to save the compressed .npz index.",
    )
    p_patch_build.set_defaults(func=cmd_build_patch_reference)

    # --- morphcheck (Phase 3.3 / 3.4) ---
    p_morph = subparsers.add_parser(
        "morphcheck",
        help="Run morphological similarity cross-check.",
    )
    p_morph.add_argument(
        "--embeddings",
        type=str,
        default=None,
        help="Path to embeddings .npy. Required if not using --session-id.",
    )
    p_morph.add_argument(
        "--report",
        type=str,
        default=None,
        help="Path to cluster_report.json. Required if not using --session-id.",
    )
    p_morph.add_argument(
        "--reference",
        type=str,
        default=None,
        help=(
            "Path to reference index .npz. Accepts either: "
            "(1) Gravity Spy training set index (build-reference), or "
            "(2) In-domain reference index (build-indomain-reference, recommended). "
            "If omitted, runs auto-discovery across all references in data/reference."
        ),
    )
    p_morph.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON path for morphcheck results. Required if not using --session-id.",
    )
    p_morph.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Session identifier to resolve paths automatically. Requires --detector.",
    )
    p_morph.add_argument(
        "--detector",
        type=str,
        default=None,
        choices=["H1", "L1", "V1"],
        help="Detector identifier. Required when using --session-id.",
    )
    p_morph.set_defaults(func=cmd_morphcheck)
    _add_run_argument(p_morph)

    # --- timeslide ---
    p_ts = subparsers.add_parser(
        "timeslide",
        help="Estimate background coincidence significance between H1 and L1.",
    )
    p_ts.add_argument(
        "--session-id",
        type=str,
        default=None,
        help=(
            "Session identifier to auto-resolve metadata and report paths. "
            "If provided, individual --metadata-* and --report-* are optional overrides."
        ),
    )
    p_ts.add_argument(
        "--metadata-h1",
        type=str,
        default=None,
        help="Path to H1 embeddings metadata JSON (overrides session-id auto-resolution).",
    )
    p_ts.add_argument(
        "--metadata-l1",
        type=str,
        default=None,
        help="Path to L1 embeddings metadata JSON (overrides session-id auto-resolution).",
    )
    p_ts.add_argument(
        "--report-h1",
        type=str,
        default=None,
        help="Path to H1 cluster report JSON (overrides session-id auto-resolution).",
    )
    p_ts.add_argument(
        "--report-l1",
        type=str,
        default=None,
        help="Path to L1 cluster report JSON (overrides session-id auto-resolution).",
    )
    p_ts.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Number of time-slide iterations for background estimation. Default: from config.yaml.",
    )
    p_ts.add_argument(
        "--window",
        type=int,
        default=None,
        help="Coincidence window in seconds. Default: from config.yaml.",
    )
    _add_mode_argument(p_ts)
    p_ts.set_defaults(func=cmd_timeslide)
    _add_run_argument(p_ts)

    # --- download-all-references ---
    p_dl = subparsers.add_parser(
        "download-all-references",
        help="Download and build in-domain references for one or more run/detector combos.",
    )
    p_dl.add_argument(
        "--run",
        type=str,
        default=None,
        help="Observing run (e.g. O4a). Use --all for all runs.",
    )
    p_dl.add_argument(
        "--all",
        action="store_true",
        dest="all_runs",
        help="Download all available runs (%s)." % ", ".join(VALID_RUNS),
    )
    p_dl.add_argument(
        "--detector",
        nargs="+",
        default=["H1", "L1", "V1"],
        choices=["H1", "L1", "V1"],
        help="Detectors to build references for. Default: H1 L1 V1.",
    )
    p_dl.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Minimum ml_confidence threshold. Default: from config.yaml.",
    )
    p_dl.add_argument(
        "--max-per-class",
        type=int,
        default=None,
        help="Maximum samples per class. Default: from config.yaml.",
    )
    p_dl.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers for GWOSC fetch. Default: 1.",
    )
    p_dl.set_defaults(func=cmd_download_all_references)

    # --- validate-reference (Phase 3.4) ---
    p_validate = subparsers.add_parser(
        "validate-reference",
        help="Validate reference index with a known event.",
    )
    p_validate.add_argument(
        "--reference",
        type=str,
        required=True,
        help="Path to reference index .npz.",
    )
    p_validate.add_argument(
        "--test-event",
        type=str,
        default=None,
        help="Known event to test against (default: first from config.yaml).",
    )
    p_validate.set_defaults(func=cmd_validate_reference)

    # --- benchmark-clustering ---
    p_benchmark = subparsers.add_parser(
        "benchmark-clustering",
        help="Validate unsupervised clustering pipeline using ground truth labels.",
    )
    p_benchmark.add_argument(
        "--reference",
        type=str,
        default=None,
        help="Path to reference index .npz. Default: dynamically resolved.",
    )
    p_benchmark.add_argument(
        "--min-samples-per-class",
        type=int,
        default=10,
        help="Exclude classes with fewer samples. Default: 10.",
    )
    p_benchmark.add_argument(
        "--output",
        type=str,
        default="data/reference/benchmark_report.json",
        help="Output JSON path for benchmark report.",
    )
    p_benchmark.add_argument(
        "--algorithm",
        type=str,
        choices=["hdbscan", "dpmm"],
        default="dpmm",
        help="Clustering algorithm to use. Default: dpmm.",
    )
    _add_mode_argument(p_benchmark)
    p_benchmark.set_defaults(func=cmd_benchmark_clustering)
    # --- calibrate (Autopilot) ---
    p_cal = subparsers.add_parser(
        "calibrate",
        help="[Autopilot] Calibrate thresholds (cosine or loglikelihood).",
    )
    p_cal.add_argument(
        "--method",
        choices=["cosine", "loglikelihood"],
        required=True,
        help="Method to calibrate.",
    )
    p_cal.add_argument(
        "--reference",
        type=str,
        default=None,
        help="Path to reference index .npz. Default: dynamically resolved.",
    )
    p_cal.add_argument(
        "--percentile",
        type=float,
        default=5,
        help="Percentile threshold. Default: 5.",
    )
    p_cal.add_argument(
        "--output",
        type=str,
        default="data/autopilot/reference/thresholds.json",
        help="Output JSON path. Default: data/autopilot/reference/thresholds.json.",
    )
    p_cal.set_defaults(func=cmd_calibrate)

    # --- scan-live (Autopilot) ---
    p_live = subparsers.add_parser(
        "scan-live",
        help="[Autopilot] Live scanner: classify spectrograms as KNOWN/AMBIGUOUS/NOVEL.",
    )
    p_live.add_argument(
        "--detector",
        type=str,
        required=True,
        choices=["H1", "L1", "V1"],
        help="Detector identifier.",
    )
    p_live.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel producer threads for GWOSC fetch. Default: 4.",
    )
    p_live.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Session identifier. Default: autopilot_{timestamp}.",
    )
    p_live.add_argument(
        "--min-novel",
        type=int,
        default=10,
        help="Minimum NOVEL count to suggest clustering. Default: 10.",
    )
    p_live.add_argument(
        "--reference",
        type=str,
        default=None,
        help="Path to reference index .npz. Default: dynamically resolved.",
    )
    p_live.add_argument(
        "--hours",
        type=float,
        default=None,
        help="Override scan duration in hours. Default: from run_config.",
    )
    p_live.add_argument(
        "--percentile",
        type=int,
        default=None,
        help="Percentile for threshold calibration if not found. Default: from config.",
    )
    p_live.add_argument(
        "--thresholds-path",
        type=str,
        default="data/autopilot/reference/thresholds.json",
        help="Path to thresholds.json. Default: data/autopilot/reference/thresholds.json.",
    )
    _add_run_argument(p_live)
    _add_mode_argument(p_live)
    p_live.set_defaults(func=cmd_scan_live)

    # --- analyze-similarity ---
    p_sim = subparsers.add_parser(
        "cluster-similarity",
        help="Analyze the distribution of cosine similarities for each cluster.",
    )
    p_sim.add_argument(
        "--session-id",
        type=str,
        required=True,
        help="Session identifier.",
    )
    p_sim.add_argument(
        "--detector",
        type=str,
        required=True,
        choices=["H1", "L1", "V1"],
        help="Detector identifier.",
    )
    _add_run_argument(p_sim)
    p_sim.add_argument(
        "--reference",
        type=str,
        default=None,
        help="Path to reference index .npz. Default: dynamically resolved.",
    )
    p_sim.set_defaults(func=cmd_cluster_similarity)

    # --- production-cluster ---
    p_prod_cluster = subparsers.add_parser(
        "production-cluster",
        help="Clusters the 384D novel anomalies extracted during patch-production.",
    )
    p_prod_cluster.add_argument(
        "--input",
        type=str,
        required=True,
        help="Path to the novelties.h5 file generated by patch-production.",
    )
    p_prod_cluster.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for the cluster report and UMAP plots.",
    )
    p_prod_cluster.set_defaults(func=cmd_production_cluster)

    # --- patch-analysis ---
    p_patch_analysis = subparsers.add_parser(
        "patch-analysis",
        help="Automated continuous workflow: patch-production -> production-cluster.",
    )
    p_patch_analysis.add_argument(
        "--detector",
        type=str,
        required=True,
        choices=["H1", "L1"],
        help="Detector to use.",
    )
    p_patch_analysis.add_argument(
        "--data-dir",
        type=str,
        default="data/raw/o4a/",
        help="Directory containing raw HDF5 files.",
    )
    p_patch_analysis.add_argument(
        "--sessions",
        nargs="*",
        default=[],
        help="List of sessions to process. If empty, processes all folders in data-dir.",
    )
    p_patch_analysis.add_argument(
        "--output-dir",
        type=str,
        default="data/production/",
        help="Output directory for HDF5 archives and clusters.",
    )
    p_patch_analysis.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint.",
    )
    p_patch_analysis.add_argument(
        "--k",
        type=int,
        default=68,
        help="Number of top-k patches for MIL vector. Default: 68.",
    )
    p_patch_analysis.add_argument(
        "--k-ablations",
        nargs="*",
        type=int,
        default=[15, 37, 68, 100],
        help="List of k values for spatial pooling ablation. Default: 15 37 68 100",
    )
    p_patch_analysis.add_argument(
        "--fpr",
        type=float,
        default=0.01,
        help="False Positive Rate for thresholding. Default: 0.01.",
    )
    p_patch_analysis.add_argument(
        "--n-background",
        type=int,
        default=500,
        help="Number of background samples for threshold calibration. Default: 500.",
    )
    p_patch_analysis.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed. Default: 42.",
    )
    p_patch_analysis.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of CPU workers for dataset reading. Default: 8.",
    )
    p_patch_analysis.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="PyTorch batch size for DINOv2 extraction. Default: 32.",
    )
    p_patch_analysis.add_argument(
        "--nds-host", type=str, default=None, help="NDS2 server hostname for PEM analysis (e.g. nds.gwosc.org). If omitted, uses standard logic."
    )
    p_patch_analysis.set_defaults(func=cmd_patch_analysis)

    # --- production-report ---
    p_production_report = subparsers.add_parser(
        "production-report",
        help="Automated Scientific Validation and Reporting (Phase 6).",
    )
    p_production_report.add_argument(
        "--session-id", type=str, required=True, help="Session ID to report."
    )
    p_production_report.add_argument(
        "--detector", type=str, default="H1", choices=["H1", "L1"]
    )
    p_production_report.add_argument(
        "--output-dir", type=str, default="data/production/", help="Output directory."
    )
    p_production_report.add_argument(
        "--nds-host", type=str, default=None, help="NDS2 server hostname for PEM analysis (e.g. nds.gwosc.org). If omitted, uses standard logic."
    )
    p_production_report.add_argument(
        "--skip-pem", action="store_true", help="Explicitly skip PEM analysis by forcing nds_host to None."
    )
    p_production_report.add_argument(
        "--only-plots", action="store_true", help="Only regenerate saliency plots without running clustering or checks."
    )
    p_production_report.set_defaults(func=cmd_production_report)

    # --- validate-reports ---
    p_validate_reports = subparsers.add_parser(
        "validate-reports",
        help="Validate all required artifacts and metadata constraints.",
    )
    p_validate_reports.add_argument(
        "--session-id", type=str, required=True, help="Session ID to validate."
    )
    p_validate_reports.add_argument(
        "--detector", type=str, default="H1", choices=["H1", "L1"]
    )
    p_validate_reports.add_argument(
        "--output-dir", type=str, default="data/production/", help="Output directory."
    )
    p_validate_reports.set_defaults(func=cmd_validate_reports)

    # --- aggregate-report ---
    p_aggregate = subparsers.add_parser(
        "aggregate-report",
        help="Cross-session aggregation, deduplication, and Spearman stability defense.",
    )
    p_aggregate.add_argument(
        "--production-dir",
        type=str,
        default="data/production/",
        help="Root production directory containing all session subdirectories.",
    )
    p_aggregate.add_argument(
        "--run",
        type=str,
        default="O4a",
        help="Observing run context for EVT thresholds (e.g. O4a, O3b).",
    )
    p_aggregate.add_argument(
        "--nds-host", 
        type=str, 
        default="nds.gwosc.org", 
        help="NDS2 server hostname for PEM analysis (e.g. nds.gwosc.org). If omitted, runs in public NULL-RESULT mode."
    )
    p_aggregate.add_argument(
        "--native-index",
        type=str,
        default=None,
        help="Explicit versioned native DSD index. By default the coherent "
             "qrange-tagged index for the production representation is preferred.",
    )
    p_aggregate.add_argument(
        "--allow-legacy-cross-representation",
        action="store_true",
        help="Audit-only opt-in for the historical Q32-index/Q64-query path. "
             "Never enabled silently.",
    )
    p_aggregate.add_argument(
        "--candidate-window-offset",
        type=float,
        default=4.0,
        help="Seconds to add to catalogue GPS before candidate rescoring. "
             "Use 4 for the historical pre-2026-07-24 O4a catalogue and 0 "
             "for catalogues produced after the PatchProducer label fix.",
    )
    p_aggregate.add_argument(
        "--dsd-background-n",
        type=int,
        default=5000,
        help="Representation-matched background scores per detector for DSD "
             "calibration. The paper protocol uses 5000; smaller values are "
             "for hermetic integration tests only.",
    )
    p_aggregate.set_defaults(func=cmd_aggregate_report)

    # --- multiscale-analysis (V3 characterization) ---
    p_ms = subparsers.add_parser(
        "multiscale-analysis",
        help="V3: re-score V2 candidates at {0.5,1,2,4}s scales (duration profiling, no OR-fusion).",
    )
    p_ms.add_argument("--run", type=str, default="O4a")
    p_ms.add_argument("--production-dir", type=str, default="data/production/")
    p_ms.add_argument("--detectors", nargs="*", default=["L1", "H1"])
    p_ms.set_defaults(func=cmd_multiscale_analysis)

    # --- multiscale-report (one-shot V3: preflight + profiling + report) ---
    p_msr = subparsers.add_parser(
        "multiscale-report",
        help="V3 one-shot: preflight dictionaries/thresholds, profile V2 "
             "survivors at all scales, regenerate the Final Discovery Report.",
    )
    p_msr.add_argument("--run", type=str, default="O4a")
    p_msr.add_argument("--production-dir", type=str, default="data/production/")
    p_msr.add_argument("--detectors", nargs="*", default=["L1", "H1"])
    p_msr.add_argument(
        "--skip-report", action="store_true",
        help="Only profile; do not regenerate Final_Discovery_Report.md.")
    p_msr.set_defaults(func=cmd_multiscale_report)

    # --- coincidence-physical ---
    p_cph = subparsers.add_parser(
        "coincidence-physical",
        help="Authoritative cross-detector coincidence test (physical "
             "cross-correlation over the light-travel lag window).",
    )
    p_cph.add_argument("--run", type=str, default="O4a")
    p_cph.add_argument(
        "--n", type=int, default=0,
        help="Number of candidates to test; 0 = the full pool (default).")
    p_cph.add_argument(
        "--aggregated-dir", type=str, default="data/production/aggregated")
    p_cph.add_argument(
        "--no-iou", action="store_true",
        help="Skip the complementary patch-overlap check (faster).")
    p_cph.set_defaults(func=cmd_coincidence_physical)

    # --- coincidence-efficiency ---
    p_ceff = subparsers.add_parser(
        "coincidence-efficiency",
        help="Measure coherent recovery efficiency (epsilon_coh) of the "
             "physical coincidence statistic across morphologies.",
    )
    p_ceff.add_argument("--run", type=str, default="O4a")
    p_ceff.add_argument("--n-trials", type=int, default=60,
                        help="Injections per morphology and amplitude.")
    p_ceff.add_argument("--n-null", type=int, default=200)
    p_ceff.add_argument("--seed", type=int, default=42)
    p_ceff.add_argument(
        "--aggregated-dir", type=str, default="data/production/aggregated")
    p_ceff.set_defaults(func=cmd_coincidence_efficiency)

    # --- background-cohesion ---
    p_bch = subparsers.add_parser(
        "background-cohesion",
        help="Falsification test: cluster each DSD outcome class AND "
             "unselected native background with the identical procedure.",
    )
    p_bch.add_argument("--run", type=str, default="O4a")
    p_bch.add_argument("--n-segments", type=int, default=3000,
                       help="Native background segments to encode.")
    p_bch.add_argument("--n-draws", type=int, default=5,
                       help="Random subsamples for the size-matched comparison.")
    p_bch.add_argument("--seed", type=int, default=42)
    p_bch.add_argument(
        "--aggregated-dir", type=str, default="data/production/aggregated")
    p_bch.set_defaults(func=cmd_background_cohesion)

    # --- dsd-absorption ---
    p_abs = subparsers.add_parser(
        "dsd-absorption",
        help="Measure the prevalence at which the DSD absorbs a glitch "
             "morphology into its own background dictionary.",
    )
    p_abs.add_argument("--run", type=str, default="O4a")
    p_abs.add_argument("--morphology", type=str, default="Blip",
                       help="Synthetic morphology to inject (default: Blip).")
    p_abs.add_argument("--amplitude", type=float, default=12.0,
                       help="Peak amplitude on whitened (~unit-variance) noise.")
    p_abs.add_argument("--duration", type=float, default=1.0)
    p_abs.add_argument("--n-background", type=int, default=300,
                       help="Background segments forming the index (default 300).")
    p_abs.add_argument("--seed", type=int, default=42)
    p_abs.set_defaults(func=cmd_dsd_absorption)

    # --- inter-session-recurrence ---
    p_isr = subparsers.add_parser(
        "inter-session-recurrence",
        help="Test whether any morphology recurs across widely separated "
             "observing sessions, as a glitch class would and noise would not.",
    )
    p_isr.add_argument("--run", type=str, default="O4a")
    p_isr.add_argument("--top-n", type=int, default=2000,
                       help="Most-similar pairs examined (default 2000).")
    p_isr.add_argument("--k-neighbours", type=int, default=10)
    p_isr.add_argument("--seed", type=int, default=42)
    p_isr.set_defaults(func=cmd_inter_session_recurrence)

    # --- dsd-index-stability ---
    p_stab = subparsers.add_parser(
        "dsd-index-stability",
        help="Test whether the DSD survivors are an artifact of which "
             "background sample built the native index.",
    )
    p_stab.add_argument("--run", type=str, default="O4a")
    p_stab.add_argument("--n-candidates", type=int, default=40,
                        help="Near-threshold candidates per (class, detector).")
    p_stab.add_argument("--n-draws", type=int, default=4)
    p_stab.add_argument("--seed", type=int, default=42)
    p_stab.set_defaults(func=cmd_dsd_index_stability)

    # --- pca-baseline ---
    p_pca = subparsers.add_parser(
        "pca-baseline",
        help="Measure what the frozen DINOv2 encoder buys over a classical "
             "PCA + spectral-energy baseline on the same candidate pool.",
    )
    p_pca.add_argument("--run", type=str, default="O4a")
    p_pca.add_argument("--n-candidates", type=int, default=40,
                       help="Near-threshold candidates per (class, detector).")
    p_pca.add_argument("--n-background", type=int, default=1300,
                       help="Vetoed background segments the PCA subspace is fit on.")
    p_pca.add_argument("--seed", type=int, default=42)
    p_pca.set_defaults(func=cmd_pca_baseline)

    # --- characterize-candidate ---
    p_char = subparsers.add_parser(
        "characterize-candidate",
        help="Generic independent Kretski-style descriptors, with optional "
             "lookup of the separate production coincidence-veto result.",
    )
    p_char.add_argument("--detector", required=True, choices=("H1", "L1"))
    p_char.add_argument("--gps", type=float, required=True,
                        help="Start of the 32 s descriptor window.")
    p_char.add_argument("--feature-gps", type=float, required=True,
                        help="Feature time centring the 4 s peak/correlation windows.")
    p_char.add_argument("--band", type=float, nargs=2, default=[26.0, 42.0],
                        metavar=("F_LO", "F_HI"), help="In-band range (Hz), "
                        "default = forum cross-check band.")
    p_char.add_argument("--partner", choices=("H1", "L1"), default=None)
    p_char.add_argument("--n-background", type=int, default=16)
    p_char.add_argument("--bg-spacing", type=float, default=40.0)
    p_char.add_argument("--catalog-gps", type=float,
                        help="GPS key in the stored production coincidence artifact.")
    p_char.add_argument(
        "--coincidence-artifact", type=Path,
        default=Path("data/production/aggregated/coincidence_physical_o4a.json"),
    )
    p_char.set_defaults(func=cmd_characterize_candidate)

    # --- dsd-threshold-mc-error ---
    p_mc = subparsers.add_parser(
        "dsd-threshold-mc-error",
        help="Bootstrap the Monte-Carlo error on the per-detector DSD thresholds "
             "(R3). Reads the coherent threshold artifact and its exact stored "
             "native score arrays.",
    )
    p_mc.add_argument("--run", type=str, default="O4a")
    p_mc.add_argument("--reps", type=int, default=200,
                      help="Independent bootstrap runs used to estimate the spread.")
    p_mc.add_argument("--B", type=int, default=1000,
                      help="Replicas per bootstrap run (production value: 1000).")
    p_mc.set_defaults(func=cmd_dsd_threshold_mc_error)

    # --- dsd-k-sensitivity ---
    p_ksen = subparsers.add_parser(
        "dsd-k-sensitivity",
        help="Sweep the native-index dictionary size K and test whether the DSD "
             "survivor population is an artifact of the K=1216 choice.",
    )
    p_ksen.add_argument("--run", type=str, default="O4a")
    p_ksen.add_argument("--n-candidates", type=int, default=40,
                        help="Must match the P5 token cache this test reuses.")
    p_ksen.add_argument("--k-values", type=int, nargs="+",
                        default=[512, 1024, 1216, 2048])
    p_ksen.add_argument("--seed", type=int, default=42)
    p_ksen.set_defaults(func=cmd_dsd_k_sensitivity)

    # --- blind-spot-map ---
    p_bs = subparsers.add_parser(
        "blind-spot-map",
        help="Map DANTE's flag rate over a sine-Gaussian (f0, Q) grid at fixed "
             "SNR to validate the analytic T=Q_max/f blind-spot boundary.",
    )
    p_bs.add_argument("--run", type=str, default="O4a")
    p_bs.add_argument("--n-realizations", type=int, default=6,
                      help="Background segments injected per grid cell.")
    p_bs.add_argument("--seed", type=int, default=42)
    p_bs.set_defaults(func=cmd_blind_spot_map)

    # --- whitening-context-sensitivity ---
    p_wc = subparsers.add_parser(
        "whitening-context-sensitivity",
        help="Re-score near-threshold candidates at several whitening context "
             "lengths and count DSD verdict flips vs the production pad=4.",
    )
    p_wc.add_argument("--run", type=str, default="O4a")
    p_wc.add_argument("--n-candidates", type=int, default=15,
                      help="Near-threshold candidates per (class, detector).")
    p_wc.add_argument("--pads", type=float, nargs="+",
                      default=[4.0, 16.0, 64.0, 128.0])
    p_wc.add_argument("--native-index", type=str, default=None)
    p_wc.add_argument("--n-background", type=int, default=5000)
    p_wc.add_argument("--anchor-tolerance", type=float, default=1e-3)
    p_wc.add_argument(
        "--window-offset",
        type=float,
        default=4.0,
        help="Historical O4a catalogue offset; use 0 for post-label-fix data.",
    )
    p_wc.add_argument("--seed", type=int, default=42)
    p_wc.set_defaults(func=cmd_whitening_context_sensitivity)

    # --- catalog-cross-match ---
    p_xm = subparsers.add_parser(
        "catalog-cross-match",
        help="Test GWTC/DANTE candidate-window overlap against a common-offset "
             "circular-shift null; this is not a recall estimate.",
    )
    p_xm.add_argument("--run", type=str, default="O4a")
    p_xm.add_argument("--refresh", action="store_true",
                      help="Re-fetch the GWTC event list from GWOSC (else cached).")
    p_xm.add_argument(
        "--coverage-source",
        choices=("auto", "exact", "raw-blocks", "legacy-spans"),
        default="auto",
        help="Coverage hierarchy. auto prefers exact processed-window ledgers "
             "and labels historical proxies explicitly.",
    )
    p_xm.add_argument("--n-shifts", type=int, default=10000)
    p_xm.add_argument("--seed", type=int, default=42)
    p_xm.add_argument("--minimum-shift-s", type=float, default=86400.0)
    p_xm.add_argument("--production-dir", type=Path, default=Path("data/production"))
    p_xm.set_defaults(func=cmd_catalog_cross_match)

    # --- poisson-upper-limit ---
    p_poisson = subparsers.add_parser(
        "poisson-upper-limit",
        help="Calculate the Poisson Upper Limit on a null-result detector.",
    )
    p_poisson.add_argument(
        "--detector", type=str, default=None, help="Target detector (e.g. H1, L1). If omitted, runs for all detectors in config."
    )
    p_poisson.add_argument(
        "--production-dir", type=str, default="data/production/", help="Production directory"
    )
    p_poisson.set_defaults(func=cmd_poisson_upper_limit)

    # --- pem-coherence-analysis ---
    p_pem = subparsers.add_parser(
        "pem-coherence-analysis",
        help="Run PEM offline coherence analysis.",
    )
    p_pem.add_argument(
        "--taxonomy-csv",
        type=Path,
        default=None,
        help=(
            "Explicit coherent Master Taxonomy CSV. By default the Q-range "
            "contract resolves the representation-versioned artifact."
        ),
    )
    p_pem.add_argument("--run", type=str, default="O4a")
    p_pem.add_argument(
        "--cache-dir",
        type=str,
        default="data/raw/auxiliary",
        help="Cache directory for auxiliary channels.",
    )
    p_pem.add_argument(
        "--output-dir",
        type=str,
        default="data/production/aggregated",
        help="Output directory for reports and plots.",
    )
    p_pem.add_argument(
        "--target-families",
        nargs="*",
        default=[],
        help="List of family IDs to analyze. If empty, analyzes all families.",
    )
    p_pem.add_argument(
        "--no-singletons",
        action="store_true",
        help="Exclude Singleton anomalies from analysis.",
    )
    p_pem.add_argument(
        "--max-events",
        type=int,
        default=5,
        help="Max events to process per family.",
    )
    p_pem.add_argument(
        "--robustness-class",
        type=str,
        default=None,
        choices=["ROBUST", "AMBIGUOUS", "BACKGROUND"],
        help=(
            "Restrict selection to one robustness class. Use to interrogate a "
            "single population: the DSD-rejected (BACKGROUND) pool is either "
            "drift or pervasive glitches absorbed by the native dictionary, and "
            "auxiliary coupling discriminates between the two."
        ),
    )
    p_pem.add_argument(
        "--nds-host",
        type=str,
        default="nds.gwosc.org",
        help=(
            "NDS2 server hostname for auxiliary channels "
            "(e.g. nds.gwosc.org). "
            "Requires LVC credentials. If omitted, runs in null-result mode."
        ),
    )
    p_pem.add_argument("--robust-events", type=int, default=None)
    p_pem.add_argument("--ambiguous-events", type=int, default=None)
    p_pem.add_argument("--background-events", type=int, default=None)
    p_pem.add_argument(
        "--reuse-existing-dir",
        type=Path,
        default=None,
        help=(
            "Explicit PEM directory from which matching detector/GPS "
            "measurements and null calibrations may be reused."
        ),
    )
    p_pem.add_argument(
        "--selection-only",
        action="store_true",
        help="Write the coherent target/reuse ledger without fetching data.",
    )
    p_pem.add_argument(
        "--inject-final-report",
        action="store_true",
        help=(
            "Explicitly update Final_Discovery_Report.md. Disabled by "
            "default so a characterization rerun cannot silently mutate "
            "the legacy report."
        ),
    )
    p_pem.set_defaults(func=cmd_pem_coherence_analysis)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = build_parser()
    
    if len(sys.argv) == 1:
        from src.core.wizard import run_wizard
        run_wizard(parser)
        sys.exit(0)
        
    args = parser.parse_args()

    if hasattr(args, "func"):
        cmd_name = sys.argv[1] if len(sys.argv) > 1 else "unknown"
        cmd_args = {k: v for k, v in vars(args).items() if k != "func"}
        
        def print_config(extra_kwargs=None):
            kwargs = extra_kwargs or {}
            logger.info(f"=== STARTING COMMAND: {cmd_name.upper()} ===", **kwargs)
            logger.info("Configuration Parameters:", **kwargs)
            for key, value in cmd_args.items():
                logger.info(f"  --{key.replace('_', '-')}: {value}", **kwargs)
            logger.info("=" * 45, **kwargs)

        if hasattr(args, "session_id"):
            session_id = _resolve_session_id(args)
            args.session_id = session_id
            run = _resolve_run(args)
            
            from src.core.utils import set_session_log_file, close_session_log
            log_dir = session_path(run, session_id) / "logs"
            log_file = log_dir / "session.log"
            set_session_log_file(log_file)
            
            extra = {"extra": {"session_key": True}}
            print_config(extra)
            
            start_time = datetime.now()
            try:
                args.func(args)
                duration = (datetime.now() - start_time).total_seconds()
                logger.info("=== COMMAND END: %s (SUCCESS) === (Duration: %.2fs)", cmd_name, duration, **extra)
            except SystemExit as se:
                duration = (datetime.now() - start_time).total_seconds()
                status = "SUCCESS" if se.code in (0, None) else f"FAILED (Exit Code: {se.code})"
                if se.code in (0, None):
                    logger.info("=== COMMAND END: %s (%s) === (Duration: %.2fs)", cmd_name, status, duration, **extra)
                else:
                    logger.error("=== COMMAND END: %s (%s) === (Duration: %.2fs)", cmd_name, status, duration, **extra)
                raise se
            except KeyboardInterrupt as ki:
                duration = (datetime.now() - start_time).total_seconds()
                logger.warning("=== COMMAND END: %s (INTERRUPTED) === (Duration: %.2fs)", cmd_name, duration, **extra)
                raise ki
            except BaseException as e:
                duration = (datetime.now() - start_time).total_seconds()
                logger.error("=== COMMAND END: %s (FAILED) === (Duration: %.2fs, Error: %s)", cmd_name, duration, str(e), exc_info=True, **extra)
                raise e
            finally:
                close_session_log()
        else:
            # For global commands without a session
            print_config()
            args.func(args)


if __name__ == "__main__":
    main()
