"""Autopilot live scanner — classify spectrograms as KNOWN/AMBIGUOUS/NOVEL.

Implements a producer-consumer architecture using :class:`queue.Queue`:

* **Producer** (``ThreadPoolExecutor``, up to ``--workers`` threads):
  Fetches strain data from GWOSC, preprocesses it (whiten → bandpass →
  Q-transform), saves a temporary PNG, and enqueues it for classification.

* **Consumer** (single thread): Encodes each PNG with DINOv2, runs KNN
  cosine search against the in-domain reference index, and classifies
  the spectrogram using per-class thresholds from
  ``data/autopilot/reference/thresholds.json``.

This module is **completely separate** from the existing pipeline
(``data/runs/``).  All output is written to ``data/autopilot/<session_id>/``.

Usage::

    python main.py scan-live --detector H1 --run O4a --workers 4
    python main.py scan-live --detector H1 --run O4a \\
        --session-id autopilot_20260516_120000 --workers 4 --min-novel 10
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.utils import setup_logger

logger: logging.Logger = setup_logger(__name__)

# Sentinel value to signal the consumer that production is done
_SENTINEL = None

# GWOSC rate-limit delay (same as data_loader._GWOSC_BASE_DELAY)
_GWOSC_BASE_DELAY = 0.3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_processed_gps(metadata_path: Path) -> set[int]:
    """Read already-processed GPS start times from metadata.jsonl.

    Used for incremental resume: segments whose ``gps_start`` appears
    in this set are skipped by the producer.
    """
    processed: set[int] = set()
    if not metadata_path.exists():
        return processed
    with open(metadata_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                processed.add(int(record["gps_start"]))
            except (json.JSONDecodeError, KeyError):
                continue
    return processed


def _append_metadata(metadata_path: Path, record: dict) -> None:
    """Append a single JSON record to metadata.jsonl (thread-safe via GIL)."""
    with open(metadata_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _classify_status(
    top_similarity: float,
    top_label: str,
    label_distribution: dict[str, int],
    thresholds: dict[str, float],
    consensus_threshold: float = 0.6,
) -> tuple[str, float]:
    """Classify a spectrogram as KNOWN, AMBIGUOUS, or NOVEL.

    Uses the per-class threshold from ``thresholds.json``.  Falls back
    to a global default of 0.85 if the class is not in the thresholds
    dict.

    Returns:
        ``(status, threshold_used)``
    """
    threshold = thresholds.get(top_label, 0.85)

    if top_similarity < threshold:
        return "NOVEL", threshold

    # Check consensus among K neighbors
    total_k = sum(label_distribution.values())
    agreement = label_distribution.get(top_label, 0) / total_k if total_k > 0 else 0.0

    if agreement >= consensus_threshold:
        return "KNOWN", threshold
    else:
        return "AMBIGUOUS", threshold


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------


def _produce_spectrogram_chunk(
    gps_start: int,
    gps_end: int,
    detector: str,
    tmp_dir: Path,
    semaphore: threading.Semaphore,
) -> tuple[list[tuple[Path, int, int]], Path, int, int, str] | None:
    """Fetch 4096s chunk, preprocess 128 32s segments, and save PNGs.

    Returns ``(pngs, hdf5_path, gps_start, gps_end, detector)`` on success, or ``None``
    on failure.
    """
    from src.data_loader import download_gwosc_4096s
    from gwpy.timeseries import TimeSeries
    from src.preprocessor import bandpass, generate_qtransform, whiten
    import numpy as np

    with semaphore:
        try:
            hdf5_path = download_gwosc_4096s(detector, gps_start, gps_end, tmp_dir)
            ts = TimeSeries.read(hdf5_path)
            
            chunk_size = 32
            pngs = []
            
            for c_start in range(gps_start, gps_end, chunk_size):
                c_end = c_start + chunk_size
                save_path = tmp_dir / f"{detector}_{c_start}_{c_end}.png"
                
                try:
                    ts_chunk = ts.crop(c_start, c_end)
                    ts_white = whiten(ts_chunk)
                    ts_bp = bandpass(ts_white)
                    if np.isfinite(ts_bp.value).all():
                        generate_qtransform(ts_bp, save_path=save_path)
                        pngs.append((save_path, c_start, c_end))
                except Exception as exc:
                    logger.warning("Producer failed on chunk [%d, %d]: %s", c_start, c_end, exc)
                    
            return (pngs, hdf5_path, gps_start, gps_end, detector)

        except Exception as exc:
            logger.warning(
                "Producer failed for [%d, %d]: %s",
                gps_start,
                gps_end,
                exc,
            )
            return None


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


def _consumer_loop(
    q: queue.Queue,
    encoder,
    ref_embeddings: np.ndarray,
    ref_labels: np.ndarray,
    thresholds: dict[str, float],
    session_dir: Path,
    metadata_path: Path,
    k: int = 5,
) -> dict:
    """Consumer thread: encode, search, classify, and record results.

    Returns:
        Summary counters dict.
    """
    novel_dir = session_dir / "novel"
    novel_dir.mkdir(parents=True, exist_ok=True)

    counts: Counter = Counter()
    novel_gps_list: list[int] = []
    sim_by_class: defaultdict[str, list[float]] = defaultdict(list)

    while True:
        item = q.get()
        if item is _SENTINEL:
            q.task_done()
            break

        pngs, hdf5_path, chunk_gps_start, chunk_gps_end, detector = item

        novel_count = 0

        for png_path, gps_start, gps_end in pngs:
            try:
                # Encode
                embedding = encoder.extract(png_path)  # (384,) L2-normalised

                # KNN cosine search (dot product of L2-normed vectors)
                similarities = embedding @ ref_embeddings.T  # (N_ref,)
                top_k_indices = np.argsort(similarities)[-k:][::-1]

                neighbors_labels = [str(ref_labels[idx]) for idx in top_k_indices]
                label_dist = dict(Counter(neighbors_labels))
                top_label = max(label_dist.items(), key=lambda x: x[1])[0]
                top_similarity = float(similarities[top_k_indices[0]])

                # Classify
                status, threshold_used = _classify_status(
                    top_similarity, top_label, label_dist, thresholds
                )

                # Record
                record = {
                    "gps_start": gps_start,
                    "gps_end": gps_end,
                    "status": status,
                    "top_label": top_label,
                    "top_similarity": round(top_similarity, 4),
                    "threshold_used": round(threshold_used, 4),
                }
                _append_metadata(metadata_path, record)

                # Track statistics
                counts[status] += 1
                sim_by_class[top_label].append(top_similarity)

                if status == "NOVEL":
                    novel_gps_list.append(gps_start)
                    novel_count += 1

                    # Move PNG to novel/
                    novel_png = novel_dir / png_path.name
                    shutil.move(str(png_path), str(novel_png))

                    # Save embedding
                    emb_path = novel_dir / f"{gps_start}.npy"
                    np.save(emb_path, embedding)

                    logger.info(
                        "[NOVEL] GPS %d | nearest=%s | sim=%.4f",
                        gps_start,
                        top_label,
                        top_similarity,
                    )
                else:
                    # KNOWN or AMBIGUOUS — delete temp PNG
                    try:
                        png_path.unlink()
                    except OSError:
                        pass

            except Exception as exc:
                logger.warning(
                    "Consumer failed for GPS %d: %s",
                    gps_start,
                    exc,
                )
                counts["ERROR"] += 1
                
        logger.info("[%s] Chunk %d-%d | %d NOVEL / %d segments", detector, chunk_gps_start, chunk_gps_end, novel_count, len(pngs))
        
        # Cleanup HDF5 after processing chunk
        try:
            hdf5_path.unlink()
        except OSError:
            pass

        q.task_done()

    return {
        "counts": dict(counts),
        "novel_gps": novel_gps_list,
        "sim_by_class": dict(sim_by_class),
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _generate_report(
    consumer_result: dict,
    session_dir: Path,
    run: str,
    detector: str,
    session_id: str,
    segments_total: int,
    time_span_seconds: int,
) -> dict:
    """Generate and save the final report.json."""
    counts = consumer_result["counts"]
    novel_gps = consumer_result["novel_gps"]
    sim_by_class = consumer_result["sim_by_class"]

    # Similarity distribution per class
    sim_distribution: dict[str, dict] = {}
    for cls, sims in sim_by_class.items():
        arr = np.array(sims)
        sim_distribution[cls] = {
            "count": len(sims),
            "mean": round(float(arr.mean()), 4),
            "std": round(float(arr.std()), 4),
            "min": round(float(arr.min()), 4),
            "max": round(float(arr.max()), 4),
        }

    processed = sum(counts.values())
    duty_cycle = (processed * 32) / time_span_seconds if time_span_seconds > 0 else 0.0

    report = {
        "session_id": session_id,
        "run": run,
        "detector": detector,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "segments_total": segments_total,
        "segments_processed": processed,
        "counts": {
            "KNOWN": counts.get("KNOWN", 0),
            "AMBIGUOUS": counts.get("AMBIGUOUS", 0),
            "NOVEL": counts.get("NOVEL", 0),
            "ERROR": counts.get("ERROR", 0),
        },
        "novel_gps": sorted(novel_gps),
        "similarity_distribution": sim_distribution,
        "duty_cycle": round(duty_cycle, 4),
    }

    report_path = session_dir / "report.json"
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    logger.info("Report saved → %s", report_path)
    return report


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_scan_live(
    detector: str,
    run: str,
    workers: int = 4,
    session_id: str | None = None,
    min_novel: int = 10,
    reference_path: str | Path = "data/reference/indomain_index.npz",
    hours: float | None = None,
) -> dict:
    """Run the autopilot live scan pipeline.

    Args:
        detector: Detector identifier (``"H1"``, ``"L1"``, ``"V1"``).
        run: Observing run (``"O2"``, ``"O3a"``, ``"O3b"``, ``"O4a"``).
        workers: Number of producer threads for GWOSC fetch.
        session_id: Optional session ID.  Defaults to
            ``autopilot_{timestamp}``.
        min_novel: Minimum NOVEL count to suggest clustering.
        reference_path: Path to the in-domain reference ``.npz``.
        hours: Override scan duration (hours).  Defaults to
            ``run_config[run].hours_per_detector``.

    Returns:
        The report dict.
    """
    from src.data_loader import generate_segments_from_gps_range
    from src.encoder import DINOv2Encoder
    from src.reference_builder import load_reference_index
    from src.threshold_calibrator import calibrate_thresholds
    from src.utils import load_config

    reference_path = Path(reference_path)
    cfg = load_config()

    # ---- 1. Thresholds ------------------------------------------------
    thresholds_path = Path("data/autopilot/reference/thresholds.json")
    if not thresholds_path.exists():
        logger.info("Thresholds not found — running calibration...")
        calibrate_thresholds(
            reference_path=reference_path,
            percentile=5,
            output_path=thresholds_path,
        )

    with open(thresholds_path, "r", encoding="utf-8") as fh:
        thresholds_doc = json.load(fh)
    thresholds: dict[str, float] = thresholds_doc["thresholds"]
    logger.info("Loaded %d class thresholds from %s", len(thresholds), thresholds_path)

    # ---- 2. Load DINOv2 + reference once -----------------------------
    encoder = DINOv2Encoder()
    ref_embeddings, ref_labels = load_reference_index(reference_path)
    logger.info(
        "Reference loaded: %d embeddings, %d classes",
        len(ref_embeddings),
        len(set(ref_labels)),
    )

    # ---- 3. Session setup --------------------------------------------
    if session_id is None:
        session_id = f"autopilot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    session_dir = Path("data/autopilot") / session_id
    tmp_dir = session_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "novel").mkdir(parents=True, exist_ok=True)

    metadata_path = session_dir / "metadata.jsonl"

    logger.info("Run: %s | Detector: %s | Session: %s", run, detector, session_id)

    # ---- 4. Generate segments ----------------------------------------
    from astropy.time import Time

    run_cfg = cfg.get("run_config", {})
    if run not in run_cfg:
        raise ValueError(f"Unknown run '{run}'. Valid: {list(run_cfg.keys())}")

    start_date = run_cfg[run]["start_date"]
    gps_start = int(Time(start_date, format="iso", scale="utc").gps) + 6 * 3600

    if hours is None:
        hours = run_cfg[run]["hours_per_detector"]

    gps_end = gps_start + int(hours * 3600)
    segments = generate_segments_from_gps_range(gps_start, gps_end, segment_length=4096)

    if not segments:
        logger.warning("No segments generated for the requested window.")
        return {"status": "NO_SEGMENTS"}

    # Resume: skip already-processed GPS
    processed_gps = _load_processed_gps(metadata_path)
    if processed_gps:
        before = len(segments)
        segments = [(s, e) for s, e in segments if s not in processed_gps]
        logger.info(
            "Resume: skipping %d already-processed segments (%d remaining)",
            before - len(segments),
            len(segments),
        )

    if not segments:
        logger.info("All segments already processed. Nothing to do.")
        return {"status": "ALL_DONE"}

    time_span = gps_end - gps_start
    total_segments = len(segments)

    logger.info(
        "Scanning %d segments (%.1f hours, GPS %d–%d)",
        total_segments,
        hours,
        gps_start,
        gps_end,
    )

    # ---- 5. Producer-consumer pipeline -------------------------------
    q: queue.Queue = queue.Queue(maxsize=workers * 2)
    semaphore = threading.Semaphore(workers)

    # Start consumer thread
    consumer_result_holder: list[dict] = [{}]

    def _consumer_wrapper():
        consumer_result_holder[0] = _consumer_loop(
            q=q,
            encoder=encoder,
            ref_embeddings=ref_embeddings,
            ref_labels=ref_labels,
            thresholds=thresholds,
            session_dir=session_dir,
            metadata_path=metadata_path,
        )

    consumer_thread = threading.Thread(target=_consumer_wrapper, daemon=True)
    consumer_thread.start()

    # Producer pool
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for seg_start, seg_end in segments:
            future = executor.submit(
                _produce_spectrogram_chunk,
                seg_start,
                seg_end,
                detector,
                tmp_dir,
                semaphore,
            )
            futures.append(future)

        # Collect results and enqueue for consumer
        for future in futures:
            result = future.result()
            if result is not None:
                q.put(result)

    # Signal consumer to stop
    q.put(_SENTINEL)
    consumer_thread.join()

    consumer_result = consumer_result_holder[0]

    # ---- 6. Clean up tmp/ (should be mostly empty) -------------------
    try:
        # Remove any remaining temp files
        for f in tmp_dir.iterdir():
            f.unlink()
        tmp_dir.rmdir()
    except OSError:
        pass

    # ---- 7. Generate report ------------------------------------------
    report = _generate_report(
        consumer_result=consumer_result,
        session_dir=session_dir,
        run=run,
        detector=detector,
        session_id=session_id,
        segments_total=total_segments,
        time_span_seconds=time_span,
    )

    # Summary log
    counts = report["counts"]
    logger.info(
        "Scan complete: KNOWN=%d  AMBIGUOUS=%d  NOVEL=%d  ERROR=%d  (duty=%.1f%%)",
        counts["KNOWN"],
        counts["AMBIGUOUS"],
        counts["NOVEL"],
        counts["ERROR"],
        report["duty_cycle"] * 100,
    )

    if counts["NOVEL"] >= min_novel:
        logger.info(
            "Ready for clustering — use standard pipeline:\n"
            "  python main.py full-analysis --session-id %s --run %s",
            session_id,
            run,
        )

    return report
