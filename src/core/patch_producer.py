from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
from gwpy.timeseries import TimeSeries
from tqdm import tqdm

from src.core.preprocessor import whiten, bandpass, generate_qtransform
from src.core.utils import setup_logger

logger = setup_logger(__name__)


class IncompleteContextError(RuntimeError):
    """Raised when a requested whitening span is not fully available."""


class RawBlockConflictError(RuntimeError):
    """Raised when duplicate raw spans do not have identical content."""


@dataclass(frozen=True, slots=True)
class ContextSource:
    path: Path
    block_start: float
    block_end: float
    used_start: float
    used_end: float
    sha256: str


@dataclass(frozen=True, slots=True)
class CompleteContext:
    series: TimeSeries
    sources: tuple[ContextSource, ...]


@dataclass(frozen=True, slots=True)
class FrozenRawManifest:
    manifest_path: Path
    manifest_sha256: str
    entries: tuple[tuple[float, float, Path], ...]
    target_files: tuple[Path, ...]
    expected_sha256: Mapping[Path, str]


@lru_cache(maxsize=8192)
def _sha256_path_cached(path_text: str, size: int, mtime_ns: int) -> str:
    del size, mtime_ns
    digest = hashlib.sha256()
    with Path(path_text).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_sha256(path: Path, expected: str | None = None) -> str:
    stat = path.stat()
    actual = _sha256_path_cached(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    if expected is not None and actual != expected:
        raise RawBlockConflictError(f"raw source SHA-256 mismatch: {path}")
    return actual


def load_frozen_raw_manifest(
    manifest_path: Path,
    *,
    raw_root: Path,
    detector: str,
) -> FrozenRawManifest:
    """Resolve one versioned detector manifest without reading strain values."""

    manifest_path = Path(manifest_path).resolve()
    raw_root = Path(raw_root).resolve()
    if detector not in {"H1", "L1"}:
        raise ValueError(f"unsupported detector: {detector}")
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    entries: list[tuple[float, float, Path]] = []
    targets: list[Path] = []
    expected: dict[Path, str] = {}
    seen_spans: set[tuple[float, float]] = set()
    for line_number, line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("detector") != detector:
            continue
        start = float(row["gps_start"])
        end = float(row["gps_end"])
        span = (start, end)
        if span in seen_spans:
            raise RawBlockConflictError(
                f"duplicate logical span in raw manifest at line {line_number}: {span}"
            )
        seen_spans.add(span)
        logical_hash = str(row["sha256"])
        copies = row.get("physical_copies")
        if not isinstance(copies, list) or not copies:
            raise RawBlockConflictError(
                f"raw manifest span has no physical copies at line {line_number}"
            )
        available: list[Path] = []
        for copy in copies:
            relative = Path(str(copy["relative_path"]))
            copy_hash = str(copy["sha256"])
            if relative.is_absolute() or ".." in relative.parts or copy_hash != logical_hash:
                raise RawBlockConflictError(
                    f"invalid raw manifest copy at line {line_number}"
                )
            path = (raw_root / relative).resolve()
            if raw_root != path and raw_root not in path.parents:
                raise RawBlockConflictError(
                    f"raw manifest path escapes root at line {line_number}"
                )
            if path.is_file():
                available.append(path)
                entries.append((start, end, path))
                expected[path] = logical_hash
        if not available:
            raise IncompleteContextError(
                f"no physical copy available for {detector} span [{start}, {end}]"
            )
        targets.append(sorted(available, key=str)[0])
    if not targets:
        raise IncompleteContextError(f"raw manifest contains no {detector} spans")
    return FrozenRawManifest(
        manifest_path=manifest_path,
        manifest_sha256=_verified_sha256(manifest_path),
        entries=tuple(
            sorted(entries, key=lambda item: (item[0], item[1], str(item[2])))
        ),
        target_files=tuple(targets),
        expected_sha256=expected,
    )


def read_complete_context(
    entries: Sequence[tuple[float, float, Path]],
    *,
    gps_start: float,
    gps_end: float,
    sample_rate_hz: int,
    expected_sha256: Mapping[Path, str] | None = None,
) -> CompleteContext:
    """Read one exact span across immutable, contiguous local raw blocks.

    Duplicate physical copies are accepted only when their complete-file
    SHA-256 digests agree. Gaps, manifest mismatches and short crops fail
    closed; callers never receive a partially padded context.
    """

    from gwpy.timeseries import TimeSeriesList

    if gps_end <= gps_start:
        raise ValueError("context end must be greater than context start")
    expected = {
        Path(path).resolve(): value
        for path, value in (expected_sha256 or {}).items()
    }
    grouped: dict[tuple[float, float], list[Path]] = {}
    for raw_start, raw_end, raw_path in entries:
        start = float(raw_start)
        end = float(raw_end)
        path = Path(raw_path).resolve()
        if end <= gps_start or start >= gps_end:
            continue
        grouped.setdefault((start, end), []).append(path)
    if not grouped:
        raise IncompleteContextError(
            f"no local raw block overlaps [{gps_start}, {gps_end}]"
        )

    blocks: list[tuple[float, float, Path, str]] = []
    for (start, end), paths in grouped.items():
        path_hashes = []
        for path in sorted(set(paths), key=str):
            if not path.is_file():
                raise IncompleteContextError(f"raw source is missing: {path}")
            if expected_sha256 is not None and path not in expected:
                raise RawBlockConflictError(
                    f"raw source is absent from manifest: {path}"
                )
            path_hashes.append((path, _verified_sha256(path, expected.get(path))))
        digests = {digest for _, digest in path_hashes}
        if len(digests) != 1:
            raise RawBlockConflictError(
                f"conflicting copies for raw span [{start}, {end}]"
            )
        path, digest = path_hashes[0]
        blocks.append((start, end, path, digest))
    blocks.sort(key=lambda item: (item[0], item[1], str(item[2])))

    tolerance = 1.0 / float(sample_rate_hz)
    cursor = float(gps_start)
    selected: list[tuple[float, float, Path, str]] = []
    while cursor < gps_end - tolerance:
        candidates = [
            item
            for item in blocks
            if item[0] <= cursor + tolerance and item[1] > cursor + tolerance
        ]
        if not candidates:
            raise IncompleteContextError(
                f"gap in local raw coverage at GPS {cursor} for [{gps_start}, {gps_end}]"
            )
        chosen = sorted(
            candidates, key=lambda item: (-item[1], item[0], str(item[2]))
        )[0]
        selected.append(chosen)
        cursor = min(float(gps_end), chosen[1])

    pieces = TimeSeriesList()
    sources: list[ContextSource] = []
    cursor = float(gps_start)
    for block_start, block_end, path, digest in selected:
        used_start = cursor
        used_end = min(float(gps_end), block_end)
        series = TimeSeries.read(path)
        if int(round(float(series.sample_rate.value))) != int(sample_rate_hz):
            series = series.resample(sample_rate_hz)
        actual_start = float(series.t0.value)
        actual_end = actual_start + float(series.duration.value)
        if actual_start > used_start + tolerance or actual_end < used_end - tolerance:
            raise IncompleteContextError(
                f"raw metadata does not cover declared span for {path}"
            )
        pieces.append(series.crop(used_start, used_end))
        sources.append(
            ContextSource(
                path=path,
                block_start=block_start,
                block_end=block_end,
                used_start=used_start,
                used_end=used_end,
                sha256=digest,
            )
        )
        cursor = used_end
    try:
        joined = pieces[0] if len(pieces) == 1 else pieces.join(gap="raise")
        joined = joined.crop(gps_start, gps_end)
    except (ValueError, RuntimeError) as exc:
        raise IncompleteContextError("local raw blocks do not join exactly") from exc
    expected_samples = int(round((gps_end - gps_start) * sample_rate_hz))
    if len(joined) != expected_samples:
        raise IncompleteContextError(
            f"complete context has {len(joined)} samples, expected {expected_samples}"
        )
    actual_start = float(joined.t0.value)
    actual_end = actual_start + float(joined.duration.value)
    if abs(actual_start - gps_start) > tolerance or abs(actual_end - gps_end) > tolerance:
        raise IncompleteContextError("complete context interval is not exact")
    return CompleteContext(series=joined, sources=tuple(sources))


def _worker_preprocess(
    ts_value: np.ndarray,
    t0: float,
    dt: float,
    name: str,
    seg_start: float,
    seg_end: float,
    require_complete_padding: bool = True,
) -> tuple[int, np.ndarray | None]:
    """Module-level function for multiprocessing. 
    Applies Whiten Context -> Q-Transform -> Image conversion.
    """
    try:
        from gwpy.timeseries import TimeSeries
        import matplotlib.pyplot as plt
        import warnings
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ts_context = TimeSeries(ts_value, t0=t0, dt=dt, name=name)
            
            from src.core.preprocessor import whiten_context, extract_clean_subwindow
            # 1. Whitening & Bandpass with context
            pad = 4.0
            ts_w_context, pad_info = whiten_context(
                ts_context, seg_start, seg_end, pad=pad
            )
            tolerance = max(float(dt), np.finfo(np.float64).eps)
            if require_complete_padding and (
                float(pad_info["effective_left"]) < pad - tolerance
                or float(pad_info["effective_right"]) < pad - tolerance
            ):
                raise IncompleteContextError(
                    "whitening context is incomplete: "
                    f"left={pad_info['effective_left']}, "
                    f"right={pad_info['effective_right']}, required={pad}"
                )
            
            # 2. Extract strictly the target segment
            ts_clean = extract_clean_subwindow(ts_w_context, seg_start, seg_end)
            
            # 3. Q-Transform + Cividis normalize
            spectrogram = generate_qtransform(ts_clean, save_path=None, cmap="cividis")
            
            cmap = plt.get_cmap("cividis")
            rgb_spectrogram = cmap(spectrogram)[:, :, :3]
            rgb_spectrogram_uint8 = (rgb_spectrogram * 255).astype(np.uint8)
            
            # Label the ANALYSIS WINDOW, not the padded crop. This returned
            # `t0` (= seg_start - 4, the crop start) until 2026-07-24, so every
            # catalogued GPS in runs before that date is 4 s earlier than the
            # window actually scored. That offset is why those runs appeared
            # irreproducible: re-scoring [gps, gps+32] analyses a window shifted
            # by 4 s. Scored with [gps+4, gps+36] the stored values reproduce
            # exactly (verified to four decimals across 10 candidates).
            return int(seg_start), rgb_spectrogram_uint8
    except IncompleteContextError:
        logger.error(
            "Patch preprocessing refused incomplete context for [%s, %s]",
            seg_start,
            seg_end,
            exc_info=True,
        )
        raise
    except Exception as e:
        logger.error(
            "Patch preprocessing failed for analysis window [%s, %s]: %s",
            seg_start,
            seg_end,
            e,
            exc_info=True,
        )
        return int(seg_start), None

class PatchProducer:
    """CPU-bound Data Producer for Patch-Level production pipeline.
    
    Reads raw HDF5 files directly from disk, chunks them into 32-second segments,
    and applies the exact preprocessing pipeline: 
    Whitening -> Bandpass -> Q-Transform -> Cividis colormap -> (256, 256, 3) Numpy array.
    """
    def __init__(
        self, 
        data_dir: str | Path, 
        detector: str, 
        segment_duration: float = 32.0,
        sample_rate: int = 4096,
        workers: int = 8,
        batch_size: int = 32,
        raw_manifest: str | Path | None = None,
        raw_root: str | Path | None = None,
        manifest_targets: bool = False,
        incomplete_context_policy: str = "raise",
        excluded_gps_starts: Sequence[float] | None = None,
        worker_failure_policy: str = "record_and_skip",
        executor_backend: str = "process",
    ):
        self.data_dir = Path(data_dir)
        self.detector = detector
        self.segment_duration = segment_duration
        self.sample_rate = sample_rate
        self.workers = workers
        self.batch_size = batch_size
        self.resume_gps = None
        self.raw_manifest = None
        if incomplete_context_policy not in {"raise", "record_and_skip"}:
            raise ValueError(
                "incomplete_context_policy must be 'raise' or 'record_and_skip'"
            )
        self.incomplete_context_policy = incomplete_context_policy
        if worker_failure_policy not in {"raise", "record_and_skip"}:
            raise ValueError(
                "worker_failure_policy must be 'raise' or 'record_and_skip'"
            )
        self.worker_failure_policy = worker_failure_policy
        if executor_backend not in {"process", "thread"}:
            raise ValueError("executor_backend must be 'process' or 'thread'")
        self.executor_backend = executor_backend
        self.excluded_incomplete_context: list[dict[str, object]] = []
        self.excluded_gps_starts = frozenset(
            float(value) for value in (excluded_gps_starts or ())
        )
        self.excluded_explicit: list[dict[str, object]] = []
        
        from src.core.data_loader import _DATA_DIRECTORIES
        
        self.hdf5_files = []
        if self.data_dir.exists():
            self.hdf5_files.extend(list(self.data_dir.rglob(f"*{self.detector}*.hdf5")))
            
        if not self.hdf5_files:
            for d in _DATA_DIRECTORIES:
                if d.exists() and d != self.data_dir:
                    # Look for the specific session folder inside the global directory
                    if self.data_dir.name.isdigit():
                        session_aligned = str((int(self.data_dir.name) // 4096) * 4096)
                        fallback_dir = d / session_aligned
                    else:
                        fallback_dir = d / self.data_dir.name
                        
                    if fallback_dir.exists() and fallback_dir.is_dir():
                        self.hdf5_files.extend(list(fallback_dir.rglob(f"*{self.detector}*.hdf5")))
                    elif not self.data_dir.name.isdigit():
                        # If the data_dir is not a session folder (e.g. processing 'ALL' sessions), fallback to the whole global directory
                        self.hdf5_files.extend(list(d.rglob(f"*{self.detector}*.hdf5")))
                
        # Fallback finale: fetch_strain_data/fetch_local_or_remote_strain scrivono
        # sempre nella cache piatta (data/raw/o4a_cache/{det}_{start}_{end}.hdf5),
        # mai in una sottocartella di sessione. Se data_dir e' un ID di sessione
        # numerico e non abbiamo trovato nulla nelle sottocartelle attese, cerchiamo
        # nella cache piatta i blocchi 4096s-allineati il cui intervallo GPS
        # si sovrappone alla sessione, invece di richiedere uno spostamento manuale.
        if not self.hdf5_files and self.data_dir.name.isdigit():
            session_start = int(self.data_dir.name)
            session_end = session_start + 4096 # session duration is fixed to 4096
            for d in _DATA_DIRECTORIES:
                if not d.exists():
                    continue
                for f in d.glob(f"*{self.detector}*.hdf5"):
                    parts = f.stem.replace(f"{self.detector}_", "").split("_")
                    if len(parts) >= 2:
                        try:
                            f_start, f_end = int(float(parts[0])), int(float(parts[1]))
                            if f_start < session_end and f_end > session_start:
                                self.hdf5_files.append(f)
                        except ValueError:
                            continue
            if self.hdf5_files:
                logger.warning(
                    f"HDF5 per sessione {self.data_dir.name} trovati nella cache piatta "
                    f"({len(self.hdf5_files)} file), non nella sottocartella attesa. "
                    f"Verificare fetch_strain_data se questo accade sistematicamente."
                )

        self.hdf5_files = sorted(list(set(self.hdf5_files)))
        
        if not self.hdf5_files:
            if self.data_dir.name.isdigit():
                session_start = int(self.data_dir.name)
                session_end = session_start + 4096
                logger.info(f"HDF5 files for {self.detector} not found. Attempting auto-download of 4096s block...")
                
                try:
                    from src.core.data_loader import fetch_strain_data
                    # Download the whole 4096s block (will cache to data/raw/o4a_cache)
                    _ = fetch_strain_data(
                        self.detector, 
                        session_start, 
                        session_end, 
                        edge_tolerance=0.0, 
                        cache_raw=True
                    )
                    
                    cache_dir = Path("data/raw/o4a_cache")
                    # Move to the raw-data drive ONLY if its mount point already
                    # exists (WSL /mnt/e). The previous unconditional mkdir
                    # created a spurious C:\mnt\e\o4a on plain Windows.
                    raw_mount = Path("/mnt/e/o4a")
                    flat_cache_dir = raw_mount / str(session_start)
                    if raw_mount.exists():
                        flat_cache_dir.mkdir(parents=True, exist_ok=True)

                    expected_filename = f"{self.detector}_{session_start}_{session_end}.hdf5"
                    src_file = cache_dir / expected_filename
                    dst_file = flat_cache_dir / expected_filename

                    if src_file.exists() and raw_mount.exists() and flat_cache_dir.exists():
                        import shutil
                        shutil.move(str(src_file), str(dst_file))
                        logger.info(f"Moved downloaded block to {dst_file}")
                        self.hdf5_files.append(dst_file)
                    elif src_file.exists():
                        self.hdf5_files.append(src_file)
                    elif dst_file.exists():
                        self.hdf5_files.append(dst_file)
                    else:
                        error_msg = f"Auto-download failed to produce the expected file {expected_filename}"
                        logger.warning(error_msg)
                        raise FileNotFoundError(error_msg)
                        
                except Exception as e:
                    logger.error(f"Auto-download failed: {e}")
                    raise FileNotFoundError(f"Failed to auto-download missing HDF5 for {self.detector}: {e}")
            else:
                error_msg = f"No HDF5 files found for detector {self.detector} in {self.data_dir} or configured external drives."
                logger.warning(error_msg)
                raise FileNotFoundError(error_msg)

        # The target files may live in one session directory, but whitening
        # context is allowed to cross only into verified contiguous local
        # blocks from the surrounding immutable raw mirror. The per-process
        # data-loader index avoids an rglob for every 32-second window.
        self.expected_context_sha256: Mapping[Path, str] | None = None
        if raw_manifest is not None:
            manifest_root = Path(raw_root) if raw_root is not None else self.data_dir
            self.raw_manifest = load_frozen_raw_manifest(
                Path(raw_manifest), raw_root=manifest_root, detector=self.detector
            )
            self.context_entries = list(self.raw_manifest.entries)
            self.expected_context_sha256 = self.raw_manifest.expected_sha256
            if manifest_targets:
                self.hdf5_files = list(self.raw_manifest.target_files)
        else:
            context_roots: list[Path] = []
            if self.data_dir.exists():
                context_roots.append(
                    self.data_dir.parent
                    if self.data_dir.name.isdigit()
                    else self.data_dir
                )
            for directory in _DATA_DIRECTORIES:
                if directory.exists() and directory not in context_roots:
                    context_roots.append(directory)
            from src.core.data_loader import _local_block_index

            context_entries: dict[
                tuple[float, float, str], tuple[float, float, Path]
            ] = {}
            for root in context_roots:
                for start, end, path in _local_block_index(root, self.detector):
                    resolved = Path(path).resolve()
                    context_entries[(float(start), float(end), str(resolved))] = (
                        float(start),
                        float(end),
                        resolved,
                    )
            self.context_entries = sorted(
                context_entries.values(),
                key=lambda item: (item[0], item[1], str(item[2])),
            )
            
    def _read_channel_name(self, ts_dict) -> str:
        """Finds the correct strain channel name dynamically."""
        for key in ts_dict.keys():
            if "STRAIN" in key.upper():
                return key
        # Fallback to the known naming scheme if no dict key was easily extractable
        return f"{self.detector}:GWOSC-16KHZ_R1_STRAIN"
            
    def __iter__(self):
        """Generates (gps_starts, spectrogram_arrays) batched tuples."""
        skipped_nan = 0
        skipped_short = 0
        
        import concurrent.futures
        import multiprocessing as mp
        
        if self.executor_backend == "process":
            ctx = mp.get_context('spawn')
            executor_context = concurrent.futures.ProcessPoolExecutor(
                max_workers=self.workers, mp_context=ctx
            )
        else:
            executor_context = concurrent.futures.ThreadPoolExecutor(
                max_workers=self.workers
            )
        with executor_context as executor:
            futures = []
            
            gps_batch = []
            img_batch = []
            
            for file_path in self.hdf5_files:
                if self.resume_gps is not None:
                    # Skip entire file if it ends before or exactly at resume_gps
                    import os
                    basename = os.path.basename(file_path).replace(".hdf5", "")
                    parts = basename.split('_')
                    if len(parts) >= 3:
                        try:
                            file_end = float(parts[-1])
                            if file_end <= self.resume_gps:
                                logger.debug(f"Skipping already processed file: {file_path}")
                                continue
                        except ValueError:
                            pass
                
                logger.debug(f"Reading file: {file_path}")
                try:
                    resolved_file = Path(file_path).resolve()
                    if self.expected_context_sha256 is not None:
                        if resolved_file not in self.expected_context_sha256:
                            raise RawBlockConflictError(
                                f"target raw source is absent from manifest: {resolved_file}"
                            )
                        _verified_sha256(
                            resolved_file,
                            self.expected_context_sha256[resolved_file],
                        )
                    channel_name = f"{self.detector}:GWOSC-16KHZ_R1_STRAIN"
                    try:
                        ts_full = TimeSeries.read(file_path, name=channel_name)
                    except Exception:
                        from gwpy.timeseries import TimeSeriesDict
                        ts_dict = TimeSeriesDict.read(file_path)
                        ch = self._read_channel_name(ts_dict)
                        ts_full = ts_dict[ch]
                    
                    if ts_full.sample_rate.value != self.sample_rate:
                        ts_full = ts_full.resample(self.sample_rate)
                        
                    start_time = ts_full.t0.value
                    end_time = ts_full.t0.value + ts_full.duration.value
                    
                    current_start = start_time
                    while current_start + self.segment_duration <= end_time:
                        if self.resume_gps is not None and current_start <= self.resume_gps:
                            current_start += self.segment_duration
                            continue
                            
                        current_end = current_start + self.segment_duration

                        if float(current_start) in self.excluded_gps_starts:
                            self.excluded_explicit.append(
                                {
                                    "detector": self.detector,
                                    "gps_start": float(current_start),
                                    "duration_s": float(self.segment_duration),
                                    "target_source": str(resolved_file),
                                    "reason": "frozen_explicit_exclusion",
                                }
                            )
                            current_start += self.segment_duration
                            continue
                        
                        pad = 4.0
                        requested_start = current_start - pad
                        requested_end = current_end + pad
                        if (
                            start_time <= requested_start
                            and end_time >= requested_end
                        ):
                            ts_context = ts_full.crop(requested_start, requested_end)
                        else:
                            try:
                                ts_context = read_complete_context(
                                    self.context_entries,
                                    gps_start=requested_start,
                                    gps_end=requested_end,
                                    sample_rate_hz=self.sample_rate,
                                    expected_sha256=self.expected_context_sha256,
                                ).series
                            except IncompleteContextError as exc:
                                if self.incomplete_context_policy == "raise":
                                    raise
                                self.excluded_incomplete_context.append(
                                    {
                                        "detector": self.detector,
                                        "gps_start": float(current_start),
                                        "duration_s": float(self.segment_duration),
                                        "target_source": str(resolved_file),
                                        "reason": str(exc),
                                    }
                                )
                                current_start += self.segment_duration
                                continue
                        
                        ts_target = ts_full.crop(current_start, current_end)
                        if not np.isfinite(ts_target.value).all() or np.all(ts_target.value == 0):
                            skipped_nan += 1
                            current_start += self.segment_duration
                            continue
                            
                        # Inietta nel pool di processi
                        future = executor.submit(
                            _worker_preprocess,
                            ts_context.value,
                            ts_context.t0.value,
                            ts_context.dt.value,
                            ts_context.name,
                            current_start,
                            current_end
                        )
                        futures.append(future)
                        
                        # Yield if buffer is full enough to maintain a batch
                        while len(futures) >= self.workers * 2 and len(futures) >= self.batch_size:
                            completed_future = futures.pop(0)
                            gps, spec = completed_future.result()
                            if spec is not None:
                                gps_batch.append(gps)
                                img_batch.append(spec)
                                
                                if len(gps_batch) == self.batch_size:
                                    yield gps_batch, img_batch
                                    gps_batch = []
                                    img_batch = []
                            else:
                                if self.worker_failure_policy == "raise":
                                    raise RuntimeError(
                                        f"preprocessing failed for {self.detector} GPS {gps}"
                                    )
                                skipped_short += 1
                                
                        current_start += self.segment_duration
                        
                except (IncompleteContextError, RawBlockConflictError):
                    raise
                except Exception as e:
                    if self.raw_manifest is not None:
                        raise RuntimeError(
                            f"manifest-bound preprocessing failed for {file_path}"
                        ) from e
                    logger.error(f"Failed to read or process file {file_path}: {e}")
                    
                    # Auto-heal: sposta il file corrotto per escluderlo dai futuri run
                    err_str = str(e).lower()
                    if "synchronously read data" in err_str or "filter returned failure" in err_str or "unable to open file" in err_str:
                        try:
                            import shutil
                            # Riconoscimento dinamico del mount point (WSL "/mnt/e/" o Windows "E:/")
                            if len(file_path.parts) >= 4:
                                base_mount = file_path.parents[2] # Es. /mnt/e/ oppure E:/
                                run_name = file_path.parent.parent.name # Es. o4a
                                session_name = file_path.parent.name    # Es. 1386598912
                                corrupt_dir = base_mount / "corrupt" / run_name / session_name
                            else:
                                # Fallback sicuro per path corti (es. data/raw/file.hdf5)
                                corrupt_dir = file_path.parent / ".corrupt"
                                
                            corrupt_dir.mkdir(parents=True, exist_ok=True)
                            
                            corrupt_path = corrupt_dir / file_path.name
                            shutil.move(str(file_path), str(corrupt_path))
                            logger.warning(f"[AUTO-HEAL] File corrotto spostato in {corrupt_path}")
                        except Exception as ren_e:
                            logger.error(f"Impossibile spostare il file corrotto: {ren_e}")
                    
            # Svuota i rimanenti futures (Garantendo sempre l'ordine FIFO)
            for future in futures:
                gps, spec = future.result()
                if spec is not None:
                    gps_batch.append(gps)
                    img_batch.append(spec)
                    
                    if len(gps_batch) == self.batch_size:
                        yield gps_batch, img_batch
                        gps_batch = []
                        img_batch = []
                else:
                    if self.worker_failure_policy == "raise":
                        raise RuntimeError(
                            f"preprocessing failed for {self.detector} GPS {gps}"
                        )
                    skipped_short += 1
                    
            # Resa della batch finale incompleta (se presente)
            if len(gps_batch) > 0:
                yield gps_batch, img_batch

        logger.info(f"Iteration complete. Skipped {skipped_nan} NaN/Zero segments, {skipped_short} due to errors.")
