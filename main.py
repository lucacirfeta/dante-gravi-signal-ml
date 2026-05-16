#!/usr/bin/env python3
"""gravi-signal-ml — CLI entry point.

Provides subcommands for each pipeline stage.  Supports multiple
observing runs via ``--run`` (O2, O3a, O3b, O4a — default O4a).

    fetch                    — Download and process a known reference event (PoC)
    scan                     — Batch-scan segments for a detector
    scan-extended            — Extended scan of H1 + L1 (Phase 3.1)
    reprocess-spectrograms   — Re-render existing spectrograms with updated colormap
    encode                   — Extract embeddings from spectrograms (Phase 2)
    cluster                  — Cluster embeddings to discover novel classes (Phase 3)
    report                   — Regenerate UMAP and cluster gallery from existing outputs
    crosscheck               — Gravity Spy cross-check of anomalous clusters (Phase 3.1)
    build-indomain-reference — Build in-domain reference from labeled GPS (Phase 3.4)
    validate-reference       — Validate reference with GW150914 sanity check (Phase 3.4)

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

    # Backward-compatible explicit paths (override session-id):
    python main.py encode  --input-dir data/spectrograms/o4a/H1/ --output data/embeddings/o4a_h1_48h.npy
    python main.py cluster --input data/embeddings/o4a_h1_6h.npy --output data/clusters/
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from astropy.time import Time

from src.data_loader import fetch_o4a_segments, fetch_strain_data
from src.encoder import DINOv2Encoder
from src.preprocessor import bandpass, batch_process, generate_qtransform, whiten
from src.utils import load_config, setup_logger

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

    Uses ``run_config[run].start_date`` from config.yaml and adds a
    6-hour offset to avoid the exact beginning of the run.
    """
    if cfg is None:
        cfg = load_config()
    run_cfg = cfg.get("run_config", {})
    if run not in run_cfg:
        raise ValueError(f"Unknown run '{run}'. Valid runs: {VALID_RUNS}")
    start_date = run_cfg[run]["start_date"]
    gps = int(Time(start_date, format="iso", scale="utc").gps)
    return gps + 6 * 3600  # +6h offset


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


def _find_last_gps(session_id: str, detector: str, run: str = "O4a") -> int | None:
    """Scan existing PNGs and return the highest GPS end-time, or None.

    Filename convention: ``<detector>_<gps_start>_<gps_end>.png``.
    """
    import re

    run_lower = run.lower()
    spec_dir = Path(f"data/spectrograms/{run_lower}/{session_id}/{detector}")
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
    ts = fetch_strain_data(detector, gps_start, gps_end)

    # 2. Whiten
    ts_white = whiten(ts)

    # 3. Bandpass
    ts_bp = bandpass(ts_white)

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
    from src.data_loader import generate_segments_from_gps_range

    detector: str = args.detector
    hours: float = args.hours
    run = _resolve_run(args)
    run_lower = run.lower()
    session_id = _resolve_session_id(args)
    cfg = load_config()

    _log_run_header(run, detector, session_id)

    # --- Incremental logic ---------------------------------------------------
    explicit_session = hasattr(args, "session_id") and args.session_id
    last_gps: int | None = None

    if explicit_session:
        last_gps = _find_last_gps(session_id, detector, run=run)

    if last_gps is not None:
        # Resume from last GPS end-time.
        # Duration comes from config, not from the CLI --hours flag.
        resume_hours: float = cfg["run_config"][run]["hours_per_detector"]
        start_gps = last_gps
        end_gps = last_gps + int(resume_hours * 3600)
        logger.info(
            "Resuming session %s from GPS %d (+%.1fh)",
            session_id, last_gps, resume_hours,
        )
        segments = generate_segments_from_gps_range(start_gps, end_gps)
    else:
        # Fresh scan — use start_date from run_config
        start_gps = _run_start_gps(run, cfg)
        end_gps = start_gps + int(hours * 3600)
        logger.info("=== SCAN: %s [%s], %.1f hours ===", detector, run, hours)
        segments = generate_segments_from_gps_range(start_gps, end_gps)

    if not segments:
        logger.warning("No segments found for %s in the requested window.", detector)
        sys.exit(0)

    # Output directory — isolated by run and session_id
    output_dir = Path(f"data/spectrograms/{run_lower}/{session_id}/{detector}")
    logger.info("Output dir: %s", output_dir)

    workers: int = args.workers

    # Run batch processing
    if workers == 1:
        saved_paths = batch_process(segments, detector, output_dir)
        processed_count = len(saved_paths)
    else:
        from src.parallel_processor import batch_process_parallel
        cfg = load_config()  # noqa: F841 — needed by batch_process_parallel
        fetch_workers = cfg.get("performance", {}).get("gwosc_fetch_threads", 4)
        processed_count, _ = batch_process_parallel(
            segments, detector, output_dir, cfg, workers=workers, fetch_workers=fetch_workers, cache_raw=not args.no_cache_raw
        )

    total_duration = sum(end - start for start, end in segments)
    logger.info(
        "Scan complete: %d processed, %d skipped, %.1f h scanned",
        processed_count,
        len(segments) - processed_count,
        total_duration / 3600,
    )


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
                try:
                    ts = TimeSeries.fetch_open_data(
                        detector,
                        start,
                        end,
                        verbose=False,
                        cache=True,
                    )
                    break
                except Exception as inner_e:
                    err_str = str(inner_e)
                    if "429" in err_str or "Too Many Requests" in err_str:
                        base_delay += 0.3
                        time.sleep(1.0)
                    else:
                        raise inner_e

            if cache_raw:
                ts.write(filepath, format="hdf5")
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

    hours: float = args.hours
    output_dir_str: str = args.output_dir
    segment_duration: int = args.segment_duration
    run = _resolve_run(args)
    cfg = load_config()

    output_dir = Path(output_dir_str)
    output_dir.mkdir(parents=True, exist_ok=True)

    resume = getattr(args, "resume", True)
    workers = getattr(args, "workers", None)
    cache_raw = not getattr(args, "no_cache_raw", True)

    if workers is not None:
        if workers == 1 or workers % 2 != 0:
            logger.error("Errore: --workers deve essere un numero pari maggiore di 1 (es. 2, 4, 6, 8).")
            sys.exit(1)
        if workers > 8:
            logger.error("Errore: il limite massimo è di 4 thread per detector (--workers 8).")
            sys.exit(1)
        detectors = ["H1", "L1"]
        W = workers // 2
    else:
        if not args.detector:
            logger.error("Errore: specificare --detector oppure usare --workers.")
            sys.exit(1)
        detectors = [args.detector]
        W = 1

    current_start = None

    if resume and cache_raw:
        # Trova max GPS per ciascun detector
        max_ends = []
        for det in detectors:
            pattern = re.compile(rf"^{det}_(\d+)_(\d+)\.hdf5$")
            max_end_gps = 0
            for f in output_dir.glob("*.hdf5"):
                m = pattern.match(f.name)
                if m:
                    file_end = int(m.group(2))
                    if file_end > max_end_gps:
                        max_end_gps = file_end
            max_ends.append(max_end_gps)

        # Se tutti i detector hanno almeno un file, prendiamo il minimo dei max GPS
        if all(m > 0 for m in max_ends) and len(max_ends) > 0:
            current_start = min(max_ends)
            logger.info("Ripresa contemporanea dal GPS %d (minimo tra i detector)", current_start)
        elif len(max_ends) == 1 and max_ends[0] > 0:
            current_start = max_ends[0]
            logger.info("Ripresa dal GPS %d (ultimo file trovato)", current_start)

    if current_start is None:
        # Fresh scan
        current_start = _run_start_gps(run, cfg)
        logger.info("Nuovo download dall'inizio della run: GPS %d", current_start)

    aligned_start = (current_start // 4096) * 4096
    if aligned_start != current_start:
        logger.warning("GPS di partenza allineato da %d a %d per evitare boundary bug", current_start, aligned_start)
        current_start = aligned_start

    end_gps = current_start + int(hours * 3600)

    logger.info("=== FETCH-RAW: %s [%s] ===", detectors, run)
    logger.info("Interval: %d to %d (%.1f hours)", current_start, end_gps, hours)
    if not cache_raw:
        logger.info("Cache raw disabled: data will be fetched but not saved.")

    total_blocks = (end_gps - current_start + segment_duration - 1) // segment_duration
    if total_blocks <= 0:
        logger.info("No data to download for the requested interval.")
        return

    retry_delays = [5, 10, 20] if getattr(args, "retry", False) else [0]
    base_delay = 0.3

    if workers is not None:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            block_num = 1
            while current_start < end_gps:
                futures = []
                # Prepare batch of size W for each detector
                for det in detectors:
                    for i in range(W):
                        s = current_start + i * segment_duration
                        e = min(s + segment_duration, end_gps)
                        if s >= end_gps:
                            break
                        futures.append(executor.submit(_fetch_single_block, det, s, e, output_dir, retry_delays, base_delay, cache_raw))
                
                # Wait for all to finish
                wait(futures)
                
                # Log results
                for f in futures:
                    ok, msg = f.result()
                    if ok:
                        logger.info(msg)
                    else:
                        logger.error(msg)
                
                current_start += W * segment_duration
                block_num += W
    else:
        # Sequential logic
        block_num = 1
        while current_start < end_gps:
            current_end = min(current_start + segment_duration, end_gps)
            print(f"Blocco {block_num}/{total_blocks}: {detectors[0]} da {current_start} a {current_end}...", end=" ", flush=True)
            ok, msg = _fetch_single_block(detectors[0], current_start, current_end, output_dir, retry_delays, base_delay, cache_raw)
            if ok:
                print("OK")
                logger.info(msg)
            else:
                print("ERRORE")
                logger.error(msg)
            
            current_start = current_end
            block_num += 1

    print("Download completato.")


def cmd_scan_extended(args: argparse.Namespace) -> None:
    """Run an extended scan of H1 + L1 contemporaneously.

    Incremental mode (automatic):
        When ``--session-id`` is provided and detector directories already
        contain spectrograms, the scan resumes from the minimum highest GPS
        end-time found across the detectors to ensure strict alignment.
    """
    from src.data_loader import generate_segments_from_gps_range

    cfg = load_config()
    scan_cfg = cfg["scan_extended"]
    run = _resolve_run(args)
    run_lower = run.lower()
    session_id = _resolve_session_id(args)

    hours = getattr(args, "hours", None) or scan_cfg["hours_per_detector"]
    detectors = scan_cfg["detectors"]
    workers: int = args.workers
    fetch_workers = cfg.get("performance", {}).get("gwosc_fetch_threads", 4)
    explicit_session = hasattr(args, "session_id") and args.session_id

    _log_run_header(run, None, session_id)
    logger.info("=== SCAN-EXTENDED: %s [%s], %d h per detector ===", detectors, run, hours)

    if workers == 1 or workers % 2 != 0:
        logger.error("Errore: per scan-extended parallelo --workers deve essere un numero pari maggiore di 1 (es. 2, 4, 6, 8).")
        sys.exit(1)

    # Trova il min max_gps tra i detector per un resume condiviso
    last_gps_list = []
    if explicit_session:
        for det in detectors:
            lgps = _find_last_gps(session_id, det, run=run)
            last_gps_list.append(lgps if lgps is not None else 0)

    start_gps = _run_start_gps(run, cfg)

    if explicit_session and any(g > 0 for g in last_gps_list):
        start_gps = min(g for g in last_gps_list if g > 0)
        logger.info("Ripresa contemporanea session %s da GPS %d (minimo tra i detector attivi)", session_id, start_gps)

    end_gps = start_gps + int(hours * 3600)
    segments = generate_segments_from_gps_range(start_gps, end_gps)

    if not segments:
        logger.warning("Nessun segmento trovato per la finestra temporale richiesta.")
        sys.exit(0)

    output_dir_base = Path(f"data/spectrograms/{run_lower}/{session_id}")
    logger.info("Output dir base: %s", output_dir_base)

    from src.parallel_processor import batch_process_parallel
    processed_count, skipped = batch_process_parallel(
        segments, detectors, output_dir_base, cfg, workers=workers, fetch_workers=fetch_workers, cache_raw=not args.no_cache_raw
    )

    total_duration = sum(end - start for start, end in segments)
    logger.info(
        "Extended scan complete: %d saved, %d skipped, %.1f h scanned per detector",
        processed_count,
        skipped,
        total_duration / 3600,
    )
    print(f"Extended scan complete: {processed_count} saved, {skipped} skipped.")


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

    spec_dir = Path(f"data/spectrograms/{run_lower}/{session_id}/{detector}")

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

        # Try local cache first if requested
        ts = None
        if use_cache:
            cache_dir = _Path("data/raw")
            cache_file = cache_dir / f"{detector}_{gps_start}_{gps_end}.hdf5"
            if cache_file.exists():
                from gwpy.timeseries import TimeSeries
                ts = TimeSeries.read(cache_file)
                print(f"  Cache hit: {cache_file.name}")

        if ts is None:
            from src.data_loader import fetch_strain_data
            ts = fetch_strain_data(detector, gps_start, gps_end)

        from src.preprocessor import whiten, bandpass, generate_qtransform
        ts_w = whiten(ts)
        ts_bp = bandpass(ts_w)
        generate_qtransform(ts_bp, save_path=save_path, cmap=cmap)

        return (filename, True, "OK")

    except Exception as exc:
        return (filename, False, str(exc))


def cmd_reprocess_spectrograms(args: argparse.Namespace) -> None:
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
        input_dir = Path(f"data/spectrograms/{run_lower}/{session_id}/{detector}")
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
        input_dir = Path(f"data/spectrograms/{run_lower}/{session_id}/{detector}")
    else:
        logger.error(
            "Either --input-dir or both --session-id and --detector are required."
        )
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    elif session_id and detector:
        output_path = Path(
            f"data/embeddings/{run_lower}/{session_id}/{run_lower}_{detector.lower()}.npy"
        )
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
        input_path = Path(
            f"data/embeddings/{run_lower}/{session_id}/{run_lower}_{detector.lower()}.npy"
        )
    else:
        logger.error(
            "Either --input or both --session-id and --detector are required."
        )
        sys.exit(1)

    if args.output is not None:
        # Explicit --output was given — take priority
        output_dir = Path(args.output)
    elif session_id and detector:
        output_dir = Path(f"data/clusters/{run_lower}/{session_id}/{detector.lower()}")
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

    # 4. Run full clustering pipeline
    from src.clustering import run_full_pipeline

    result = run_full_pipeline(embeddings, cluster_cfg)

    # 5. Save cluster report (JSON + UMAP plot + gallery)
    from src.reporter import print_summary, save_cluster_report

    save_cluster_report(result, metadata, output_dir, detector=detector or "H1")

    # 6. Print human-readable summary
    print_summary(result)

    print(f"Phase 3 complete. Results in {output_dir}")


def cmd_report(args: argparse.Namespace) -> None:
    """Regenerate UMAP and cluster gallery from existing embeddings and cluster_report.json."""
    import json
    from src.clustering import run_pca, run_umap
    from src.reporter import _save_umap_plot, _save_cluster_gallery

    session_id = getattr(args, "session_id", None) or None
    detector = getattr(args, "detector", None)
    run = _resolve_run(args)
    run_lower = run.lower()

    # Resolve paths
    if args.embeddings:
        embeddings_path = Path(args.embeddings)
    elif session_id and detector:
        embeddings_path = Path(f"data/embeddings/{run_lower}/{session_id}/{run_lower}_{detector.lower()}.npy")
    else:
        logger.error("Either --embeddings or both --session-id and --detector are required.")
        sys.exit(1)

    if args.report:
        report_path = Path(args.report)
    elif session_id and detector:
        report_path = Path(f"data/clusters/{run_lower}/{session_id}/{detector.lower()}/cluster_report.json")
    else:
        logger.error("Either --report or both --session-id and --detector are required.")
        sys.exit(1)

    if args.output_dir:
        output_dir = Path(args.output_dir)
    elif session_id and detector:
        output_dir = Path(f"data/clusters/{run_lower}/{session_id}/{detector.lower()}")
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
        min_dist=umap_clust_cfg.get("min_dist", 0.0),
        metric=umap_clust_cfg.get("metric", "cosine"),
    )

    umap_viz_cfg = cluster_cfg.get("umap_viz", {})
    umap_2d = run_umap(
        pca_reduced,
        n_components=umap_viz_cfg.get("n_components", 2),
        n_neighbors=umap_viz_cfg.get("n_neighbors", 20),
        min_dist=umap_viz_cfg.get("min_dist", 0.1),
        metric=umap_viz_cfg.get("metric", "cosine"),
    )

    # 3. Regenerate plots
    _save_umap_plot(umap_2d, labels, stats, anomalous, output_dir, detector=detector_val)
    _save_cluster_gallery(labels, umap_10d, stats, anomalous, metadata, output_dir)

    print(f"Report generation complete. Outputs updated in {output_dir}")


def cmd_stability(args: argparse.Namespace) -> None:
    """Measure clustering robustness with ARI on multiple perturbed runs."""
    from src.stability import run_stability_analysis

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
        embeddings_path = Path(f"data/embeddings/{run_lower}/{session_id}/{run_lower}_{detector.lower()}.npy")
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
    )


def cmd_ablation(args: argparse.Namespace) -> None:
    """Run ablation study to test clustering robustness against image perturbations."""
    import json
    from src.ablation import run_ablation_study
    from src.clustering import run_full_pipeline

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
        embeddings_path = Path(f"data/embeddings/{run_lower}/{session_id}/{run_lower}_{detector.lower()}.npy")
    else:
        logger.error("Either --embeddings or both --session-id and --detector are required.")
        sys.exit(1)

    if args.spectrogram_dir:
        spec_dir = Path(args.spectrogram_dir)
    elif session_id and detector:
        spec_dir = Path(f"data/spectrograms/{run_lower}/{session_id}/{detector}")
    else:
        logger.error("Either --spectrogram-dir or both --session-id and --detector are required.")
        sys.exit(1)

    if args.output_dir:
        output_dir = Path(args.output_dir)
    elif session_id and detector:
        output_dir = Path(f"data/ablation/{run_lower}/{session_id}")
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
    
    # 3. Initialize Encoder once
    encoder = DINOv2Encoder(batch_size=args.batch_size)
    
    # 4. Run Ablation
    actual_session_id = session_id or "default_session"
    run_ablation_study(
        original_labels=original_labels,
        image_paths=image_paths,
        encoder=encoder,
        cluster_cfg=cluster_cfg,
        output_dir=output_dir,
        session_id=actual_session_id,
        detector=detector or "H1"
    )


def cmd_crosscheck(args: argparse.Namespace) -> None:
    """Cross-check anomalous clusters against the Gravity Spy database."""
    from src.gravity_spy_checker import (
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
    """Build a DINOv2 embedding reference index from the Gravity Spy training set."""
    from src.reference_builder import (
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
    from src.similarity_checker import (
        run_morphological_crosscheck,
        print_morphological_summary,
    )

    embeddings_path = Path(args.embeddings)
    report_path = Path(args.report)
    reference_path = Path(args.reference)
    output_path = Path(args.output)

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
    # We need the companion metadata for the embeddings to know which row corresponds to which file
    metadata_path = embeddings_path.with_suffix(".json")
    with open(metadata_path, "r", encoding="utf-8") as f:
        embedding_metadata = json.load(f)
        
    all_files = embedding_metadata["files"]
    # Be robust against path string representations
    file_to_idx = {str(Path(f).name): i for i, f in enumerate(all_files)}

    # Collect anomalous samples
    # The user request mentioned checking all 42 anomalous H1 spectrograms.
    # We check clusters > 0, which are typically valid. If noise (-1) is not considered, we skip it.
    for cluster_id_str, cluster in cluster_report["results"]["clusters"].items():
        cluster_id = int(cluster_id_str)
        # If it's a valid cluster, we check it
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

    # Run check
    summary = run_morphological_crosscheck(
        anomalous_embeddings,
        anomalous_files,
        anomalous_cluster_ids,
        reference_path,
        output_path,
        k=k,
        novelty_threshold=novelty_threshold,
        consensus_threshold=consensus_threshold,
    )

    print_morphological_summary(summary)
    print(f"Morphological check complete. {summary['novel']} novel candidates.")


def cmd_build_indomain_reference(args: argparse.Namespace) -> None:
    """Build an in-domain DINOv2 reference index from Gravity Spy labeled GPS times."""
    from src.indomain_reference_builder import (
        build_indomain_reference,
        download_gs_classifications_csv,
        select_reference_events,
    )

    output_path = Path(args.output)
    detector: str = args.detector
    run: str = args.run
    max_per_class: int = args.max_per_class
    min_confidence: float = args.min_confidence
    workers: int = args.workers

    logger.info("=== BUILD-INDOMAIN-REFERENCE ===")

    # Step 1: Download GPS classifications CSV from Zenodo
    csv_path = download_gs_classifications_csv(
        output_path.parent, run=run, detector=detector
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


def cmd_validate_reference(args: argparse.Namespace) -> None:
    """Validate reference index with a GW150914 sanity check."""
    from src.similarity_checker import cosine_knn_search
    from src.reference_builder import load_reference_index

    reference_path = Path(args.reference)
    test_event: str = args.test_event

    logger.info("=== VALIDATE-REFERENCE: %s ===", test_event)

    cfg = load_config()

    if test_event not in cfg["reference_events"]:
        available = ", ".join(cfg["reference_events"].keys())
        logger.error("Unknown event '%s'. Available: %s", test_event, available)
        sys.exit(1)

    event = cfg["reference_events"][test_event]
    detector = event["detector"]
    gps_start = event["start"]
    gps_end = event["end"]

    # Step 1: Fetch and preprocess the test event with our pipeline
    from src.data_loader import fetch_strain_data as _fetch
    from src.preprocessor import bandpass as _bp, generate_qtransform as _qt, whiten as _wh

    logger.info("Fetching %s (%s) [%d, %d]", test_event, detector, gps_start, gps_end)
    ts = _fetch(detector, gps_start, gps_end)
    ts_white = _wh(ts)
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


def cmd_timeslide(args: argparse.Namespace) -> None:
    """Run time-slide analysis to estimate background coincidence significance."""
    from src.timeslide import run_timeslide

    run = _resolve_run(args)
    run_lower = run.lower()

    logger.info("=== TIMESLIDE ===")
    
    # Check if we have explicit inputs or session-id
    session_id = getattr(args, "session_id", None)
    
    if session_id:
        _log_run_header(run, None, session_id)
        # Auto-resolve paths if not provided
        meta_h1 = Path(args.metadata_h1) if getattr(args, "metadata_h1", None) else Path(f"data/embeddings/{run_lower}/{session_id}/{run_lower}_h1.json")
        meta_l1 = Path(args.metadata_l1) if getattr(args, "metadata_l1", None) else Path(f"data/embeddings/{run_lower}/{session_id}/{run_lower}_l1.json")
        rep_h1 = Path(args.report_h1) if getattr(args, "report_h1", None) else Path(f"data/clusters/{run_lower}/{session_id}/h1/cluster_report.json")
        rep_l1 = Path(args.report_l1) if getattr(args, "report_l1", None) else Path(f"data/clusters/{run_lower}/{session_id}/l1/cluster_report.json")
        output_dir = Path(f"data/timeslide/{run_lower}/{session_id}")
    else:
        # Require explicit inputs
        if not (args.embeddings_h1 and args.embeddings_l1 and args.metadata_h1 and args.metadata_l1):
            logger.error("Must provide --session-id OR all explicit --embeddings and --metadata paths.")
            sys.exit(1)
            
        # The prompt only specified --embeddings-* and --metadata-*.
        # We need report files to know which clusters are anomalous.
        # Try to infer them or expect them.
        meta_h1 = Path(args.metadata_h1)
        meta_l1 = Path(args.metadata_l1)
        
        # We assume reports are next to embeddings but in the clusters directory. 
        # But if the user didn't specify --report-*, we can try to guess or use the CLI args.
        rep_h1 = Path(args.report_h1) if getattr(args, "report_h1", None) else Path("data/clusters/h1/cluster_report.json")
        rep_l1 = Path(args.report_l1) if getattr(args, "report_l1", None) else Path("data/clusters/l1/cluster_report.json")
        output_dir = Path("data/timeslide/")

    logger.info("Metadata H1: %s", meta_h1)
    logger.info("Metadata L1: %s", meta_l1)
    logger.info("Report H1: %s", rep_h1)
    logger.info("Report L1: %s", rep_l1)
    logger.info("Output dir: %s", output_dir)
    
    run_timeslide(
        meta_h1=meta_h1,
        rep_h1=rep_h1,
        meta_l1=meta_l1,
        rep_l1=rep_l1,
        output_dir=output_dir,
        iterations=50,
        window=32
    )


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
        help="Reference event name (e.g. GW150914, GW170817, GW231123).",
    )
    p_fetch.set_defaults(func=cmd_fetch)

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
        default=1.0,
        help="Duration to scan from run start (hours). Default: 1.0",
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
    p_scan.set_defaults(func=cmd_scan)
    _add_run_argument(p_scan)

    # --- scan-extended (Phase 3.1) ---
    p_scan_ext = subparsers.add_parser(
        "scan-extended",
        help="[Phase 3.1] Extended 48h scan of H1 + L1 detectors.",
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
    p_scan_ext.set_defaults(func=cmd_scan_extended)
    _add_run_argument(p_scan_ext)

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
        default=None,
        choices=["H1", "L1", "V1"],
        help="Detector identifier. Opzionale se si usa --workers.",
    )
    p_fetch_raw.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Numero di worker totali da suddividere tra H1 e L1. Deve essere pari (es. 2, 4, 6, 8).",
    )
    p_fetch_raw.add_argument(
        "--hours",
        type=float,
        default=1.0,
        help="Total hours to download from the origin or from the resume point. Default: 1.0.",
    )
    p_fetch_raw.add_argument(
        "--output-dir",
        type=str,
        default="data/raw",
        help="Output directory for HDF5 files. Default: data/raw.",
    )
    p_fetch_raw.add_argument(
        "--segment-duration",
        type=int,
        default=3600,
        help="Duration of each download block in seconds. Default: 3600.",
    )
    p_fetch_raw.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Disable automatic resume from existing files.",
    )
    p_fetch_raw.add_argument(
        "--no-cache-raw",
        type=str2bool,
        default=True,
        help="If True (default), disables saving raw HDF5 files to data/raw. Set to False to enable.",
    )
    p_fetch_raw.add_argument(
        "--retry",
        action="store_true",
        default=False,
        help="Enable retry logic on download failure. Default: False.",
    )
    p_fetch_raw.set_defaults(func=cmd_fetch_raw)
    _add_run_argument(p_fetch_raw)

    # --- reprocess-spectrograms ---
    p_reprocess = subparsers.add_parser(
        "reprocess-spectrograms",
        help="Re-render existing spectrograms with the current colormap from config.",
    )
    p_reprocess.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Session identifier to locate the spectrogram directory.",
    )
    p_reprocess.add_argument(
        "--detector",
        type=str,
        default=None,
        choices=["H1", "L1", "V1"],
        help="Detector identifier. Required when using --session-id.",
    )
    p_reprocess.add_argument(
        "--input-dir",
        type=str,
        default=None,
        help=(
            "Explicit path to the spectrogram directory. "
            "Overrides --session-id + --detector."
        ),
    )
    p_reprocess.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Number of parallel workers. Use 1 (default) for sequential. "
            "Use cpu_count-2 for max speed on multi-core systems."
        ),
    )
    p_reprocess.add_argument(
        "--backup",
        action="store_true",
        default=False,
        help=(
            "Create a .viridis.bak.png backup of each PNG before overwriting. "
            "Off by default."
        ),
    )
    p_reprocess.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report how many PNGs would be reprocessed, without doing it.",
    )
    p_reprocess.add_argument(
        "--use-cache",
        action="store_true",
        default=False,
        help=(
            "Check data/raw/ for local HDF5 strain files before fetching "
            "from GWOSC. File pattern: <detector>_<start>_<end>.hdf5."
        ),
    )
    p_reprocess.set_defaults(func=cmd_reprocess_spectrograms)
    _add_run_argument(p_reprocess)

    # --- encode (Phase 2) ---
    p_encode = subparsers.add_parser(
        "encode",
        help="[Phase 2] Extract DINOv2-Reg embeddings from spectrograms.",
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
        default=32,
        help="Batch size for inference. Default: 32.",
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

    # --- cluster (Phase 3) ---
    p_cluster = subparsers.add_parser(
        "cluster",
        help="[Phase 3] Cluster embeddings to discover novel glitch classes.",
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
        default=32,
        help="Batch size for DINOv2 inference.",
    )
    p_ablation.set_defaults(func=cmd_ablation)
    _add_run_argument(p_ablation)

    # --- crosscheck (Phase 3.1) ---
    p_cross = subparsers.add_parser(
        "crosscheck",
        help="[Phase 3.1] Cross-check anomalous clusters against Gravity Spy.",
    )
    p_cross.add_argument(
        "--report",
        type=str,
        required=True,
        help="Path to cluster_report.json.",
    )
    p_cross.add_argument(
        "--metadata",
        type=str,
        required=True,
        help="Path to encoder metadata JSON (e.g. data/embeddings/o4a_h1_6h.json).",
    )
    p_cross.add_argument(
        "--detector",
        type=str,
        default="H1",
        choices=["H1", "L1", "V1"],
        help="Detector for Gravity Spy queries. Default: H1.",
    )
    p_cross.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON path for cross-check results.",
    )
    p_cross.set_defaults(func=cmd_crosscheck)

    # --- build-reference (Phase 3.3) ---
    p_build = subparsers.add_parser(
        "build-reference",
        help="[Phase 3.3] Build a reference index from Gravity Spy training set.",
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

    # --- morphcheck (Phase 3.3 / 3.4) ---
    p_morph = subparsers.add_parser(
        "morphcheck",
        help="[Phase 3.3/3.4] Run morphological similarity cross-check.",
    )
    p_morph.add_argument(
        "--embeddings",
        type=str,
        required=True,
        help="Path to embeddings .npy.",
    )
    p_morph.add_argument(
        "--report",
        type=str,
        required=True,
        help="Path to cluster_report.json.",
    )
    p_morph.add_argument(
        "--reference",
        type=str,
        required=True,
        help=(
            "Path to reference index .npz. Accepts either: "
            "(1) Gravity Spy training set index (Phase 3.3, build-reference), or "
            "(2) In-domain reference index (Phase 3.4, build-indomain-reference, recommended)."
        ),
    )
    p_morph.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output JSON path for morphcheck results.",
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
        help="Session identifier to resolve paths automatically.",
    )
    p_ts.add_argument("--embeddings-h1", type=str, help="Path to H1 embeddings")
    p_ts.add_argument("--embeddings-l1", type=str, help="Path to L1 embeddings")
    p_ts.add_argument("--metadata-h1", type=str, help="Path to H1 metadata JSON")
    p_ts.add_argument("--metadata-l1", type=str, help="Path to L1 metadata JSON")
    p_ts.add_argument("--report-h1", type=str, help="Path to H1 cluster report")
    p_ts.add_argument("--report-l1", type=str, help="Path to L1 cluster report")
    p_ts.set_defaults(func=cmd_timeslide)
    _add_run_argument(p_ts)

    # --- build-indomain-reference (Phase 3.4) ---
    p_indomain = subparsers.add_parser(
        "build-indomain-reference",
        help="[Phase 3.4] Build in-domain reference from labeled GPS timestamps.",
    )
    p_indomain.add_argument(
        "--output",
        type=str,
        required=True,
        help="Path to save the .npz index (e.g. data/reference/indomain_index.npz).",
    )
    p_indomain.add_argument(
        "--detector",
        type=str,
        default="H1",
        choices=["H1", "L1", "V1"],
        help="Detector to filter on. Default: H1.",
    )
    p_indomain.add_argument(
        "--run",
        type=str,
        default="O3b",
        help="Observing run (e.g. O3b). Default: O3b.",
    )
    p_indomain.add_argument(
        "--max-per-class",
        type=int,
        default=30,
        help="Maximum samples per class. Default: 30.",
    )
    p_indomain.add_argument(
        "--min-confidence",
        type=float,
        default=0.95,
        help="Minimum ml_confidence threshold. Default: 0.95.",
    )
    p_indomain.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers for GWOSC fetch. Default: 1.",
    )
    p_indomain.set_defaults(func=cmd_build_indomain_reference)

    # --- validate-reference (Phase 3.4) ---
    p_validate = subparsers.add_parser(
        "validate-reference",
        help="[Phase 3.4] Validate reference index with a known event.",
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
        default="GW150914",
        help="Known event to test against (default: GW150914).",
    )
    p_validate.set_defaults(func=cmd_validate_reference)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
