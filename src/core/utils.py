"""Utility functions for gravi-signal-ml.

Provides GPS time conversion, spectrogram normalization, configuration
loading, and structured logging setup for batch processing jobs.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml
from astropy.time import Time


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------


def get_device(verbose: bool = True) -> torch.device:
    """Detect the optimal compute device available.

    Priority: CUDA (with compute validation) → MPS → CPU.
    Gracefully handles PyTorch stable limitations for Blackwell
    (sm_120) GPUs by catching missing-kernel errors at runtime.

    Args:
        verbose: If ``True``, log the selected device at INFO level.

    Returns:
        A :class:`torch.device` pointing to the best usable accelerator.
    """
    _logger = logging.getLogger("antigravity")

    # 1. Test CUDA — run a real compute op to catch missing sm_120 kernels
    if torch.cuda.is_available():
        try:
            test_tensor = torch.tensor([1.0, 2.0, 3.0]).cuda()
            _ = test_tensor * 2.0

            device_name = torch.cuda.get_device_name(0)
            capability = torch.cuda.get_device_capability(0)
            if verbose:
                _logger.info(
                    "GPU Acceleration Active: %s (sm_%d%d)",
                    device_name,
                    capability[0],
                    capability[1],
                )

            # L'auto-tuner cuDNN esaurisce la memoria durante l'ablation se i tensori cambiano.
            # Lo abilitiamo solo se l'utente lo richiede esplicitamente.
            if "--cudnn-autotune" in sys.argv:
                torch.backends.cudnn.benchmark = True
            else:
                torch.backends.cudnn.benchmark = False

            return torch.device("cuda:0")

        except RuntimeError as e:
            err_msg = str(e)
            if "no kernel image" in err_msg or "sm_120" in err_msg:
                device_name = torch.cuda.get_device_name(0)
                capability = torch.cuda.get_device_capability(0)
                _logger.warning(
                    "\u26a0\ufe0f GPU %s (sm_%d%d) detected but NOT supported "
                    "by current PyTorch Stable.\n"
                    "Falling back smoothly to CPU to prevent crash.\n"
                    "To enable full GPU acceleration on Blackwell, run:\n"
                    "  pip install --pre torch torchvision "
                    "--index-url https://download.pytorch.org/whl/nightly/cu128",
                    device_name,
                    capability[0],
                    capability[1],
                )
            else:
                _logger.warning(
                    "CUDA initialization failed (%s). Falling back to CPU.", e
                )

    # 2. Test Apple Silicon MPS
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        if verbose:
            _logger.info("Apple MPS Acceleration Active (Metal Framework)")
        return torch.device("mps")

    # 3. Fallback
    if verbose:
        _logger.info(
            "No hardware accelerator usable. Running on native CPU execution."
        )
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.yaml"


def get_reference_dir() -> Path:
    """Directory holding the VQ reference indices (patch_compressed_index_*).

    Defaults to the repo-relative data/reference; tests and alternate
    checkouts override it with the DANTE_REFERENCE_DIR environment
    variable so the production code never hardwires a shared path.
    """
    import os
    return Path(os.environ.get("DANTE_REFERENCE_DIR", "data/reference"))


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load the YAML configuration file.

    Args:
        path: Optional override path. Defaults to the project-root
            ``config.yaml``.

    Returns:
        Parsed configuration dictionary.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
    """
    config_path = path or _CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------


def gps_to_utc(gps_time: int | float) -> str:
    """Convert a GPS timestamp to a human-readable UTC string.

    Args:
        gps_time: GPS time (seconds since Jan 6 1980 00:00:00 UTC).

    Returns:
        ISO-8601 formatted UTC datetime string.

    Example:
        >>> gps_to_utc(1126259462)
        '2015-09-14T09:50:45.000'
    """
    t = Time(gps_time, format="gps", scale="utc")
    return t.iso


def get_observing_run(gps_start: int | float) -> str:
    """Deduce the observing run from the GPS start time.
    
    Args:
        gps_start: GPS start time of the segment/candidate.
        
    Returns:
        The observing run identifier (e.g. "O4a", "O3b").
        
    Raises:
        ValueError: If the GPS time falls outside known run epochs.
    """
    gps = float(gps_start)

    # Config-first: any run declared in config.yaml run_config with explicit
    # gps_start/gps_end bounds wins over the builtin table. This is how FUTURE
    # runs (O5, ...) are supported without code changes — without an entry,
    # post-O4a GPS times would silently inherit the open-ended "O4b" label.
    try:
        run_cfg = load_config().get("run_config", {})
        for run_name, entry in run_cfg.items():
            if isinstance(entry, dict) and "gps_start" in entry and "gps_end" in entry:
                if float(entry["gps_start"]) <= gps <= float(entry["gps_end"]):
                    return run_name
    except Exception:
        pass  # config unavailable: builtin table below still applies

    if 1126051217 <= gps <= 1137254417:
        return "O1"
    elif 1164556817 <= gps <= 1187733618:
        return "O2"
    elif 1238166018 <= gps <= 1253977218:
        return "O3a"
    elif 1256655618 <= gps <= 1269363618:
        return "O3b"
    elif 1368975618 <= gps <= 1389456018:
        # Official GWOSC O4a bounds: 2023-05-24 15:00 UTC to
        # 2024-01-16 16:00 UTC.
        return "O4a"
    elif gps > 1397062818:
        return "O4b"
    else:
        raise ValueError(f"GPS time {gps} does not fall into any known LIGO/Virgo observing run epoch.")


# ---------------------------------------------------------------------------
# Spectrogram normalization
# ---------------------------------------------------------------------------


def normalize_spectrogram(arr: np.ndarray) -> np.ndarray:
    """Min-max normalize a 2-D spectrogram array to [0, 1].

    Args:
        arr: Input 2-D array (e.g. Q-transform output).

    Returns:
        Normalized array with values in [0, 1].  If the array is
        constant (max == min), returns an array of zeros.
    """
    arr_min = arr.min()
    arr_max = arr.max()
    if arr_max == arr_min:
        return np.zeros_like(arr, dtype=np.float32)
    return ((arr - arr_min) / (arr_max - arr_min)).astype(np.float32)


def normalize_spectrogram_fixed(arr: np.ndarray, e_max: float) -> np.ndarray:
    """Run-independent normalization: clip to [0, e_max], scale to [0, 1].

    Unlike per-image min-max, the pixel<->energy mapping does not depend on
    the order statistics (max) of the individual image, so residual spectral
    lines of a given observing run cannot compress the contrast of the rest
    of the image (norm-leakage experiment, scheme B2). Legal on whitened
    data only, where Q-transform energy is in run-independent units.

    e_max must be FROZEN once (from pooled calibration data) and never
    re-derived per run, or the run signature re-enters through the back door.
    """
    if e_max <= 0:
        raise ValueError(f"e_max must be positive, got {e_max}")
    return (np.clip(arr, 0.0, e_max) / e_max).astype(np.float32)


def enable_ansi_colors() -> None:
    """Enable VT100 terminal support for Windows PowerShell/CMD.
    
    Ensures ANSI escape sequences (colors) work correctly on Windows.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # STD_OUTPUT_HANDLE = -11
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            # ENABLE_PROCESSED_OUTPUT = 0x0001
            # ENABLE_WRAP_AT_EOL_OUTPUT = 0x0002
            handle = kernel32.GetStdHandle(-11)
            mode = 0x0004 | 0x0001 | 0x0002
            kernel32.SetConsoleMode(handle, mode)
        except Exception:
            # Fallback: if it fails, colors might just not show up
            pass


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------


def setup_logger(
        name: str,
        log_file: Path | None = None,
        level: int = logging.INFO,
        session_id: str | None = None,
        run: str | None = None,
        detector: str | None = None,
) -> logging.Logger:
    """Create a structured logger with file and console handlers.

    The logger uses a uniform format that includes timestamps, severity,
    and the calling module — essential for reviewing long-running O4a
    batch scans.

    Args:
        name: Logger name (typically ``__name__`` of the calling module).
        log_file: Optional path to a log file.  Parent directories are
            created automatically.
        level: Logging level (default: ``logging.INFO``).
        session_id: Optional session identifier for structured logging.
        run: Optional observing run identifier.
        detector: Optional detector identifier.

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = True

    # Prevent duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler — always present
    # Force UTF-8 on Windows where the default cp1252 chokes on Unicode
    stream = open(sys.stdout.fileno(), "w", encoding="utf-8", closefd=False)  # noqa: SIM115
    console_handler = logging.StreamHandler(stream)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Legacy File handler — only when a path is provided
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Structured JSON Lines File Handler
    if session_id and run:
        from src.core.logging_utils import StructuredFormatter
        # The prompt requires: data/runs/<run>/<session_id>/logs/pipeline.log
        pipeline_log_path = Path(f"data/runs/{run.lower()}/{session_id}/logs/pipeline.log")
        pipeline_log_path.parent.mkdir(parents=True, exist_ok=True)

        json_handler = logging.FileHandler(pipeline_log_path, encoding="utf-8")
        json_handler.setLevel(level)
        json_handler.setFormatter(StructuredFormatter())

        # Add metadata filter to ensure structured data gets logged with this context
        class ContextFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                if not hasattr(record, "session_id"):
                    record.session_id = session_id
                if not hasattr(record, "run"):
                    record.run = run
                if detector and not hasattr(record, "detector"):
                    record.detector = detector
                return True

        json_handler.addFilter(ContextFilter())
        logger.addHandler(json_handler)

    return logger


def session_path(run: str, session_id: str) -> Path:
    """Return the base path for a run session.

    Args:
        run: Observing run (e.g. O4a).
        session_id: Session identifier.

    Returns:
        Path object pointing to the unified session directory.
    """
    return Path(f"data/runs/{run.lower()}/{session_id}")


# ---------------------------------------------------------------------------
# Session-specific essential logging
# ---------------------------------------------------------------------------

_SESSION_LOG_FILE: Path | None = None
_SESSION_LOG_HANDLER: logging.FileHandler | None = None


class SessionLogFilter(logging.Filter):
    """Filter that permits logs with level >= INFO or having session_key = True."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.INFO:
            return True
        return getattr(record, "session_key", False)


def set_session_log_file(log_file: Path) -> None:
    """Set the session-specific log file and add its handler to the root logger."""
    global _SESSION_LOG_FILE, _SESSION_LOG_HANDLER

    # Clean up any existing handler first
    close_session_log()

    _SESSION_LOG_FILE = log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(logging.INFO)  # Capture both INFO boundaries and WARNING/ERROR
    handler.setFormatter(formatter)
    handler.addFilter(SessionLogFilter())

    _SESSION_LOG_HANDLER = handler

    # Add to root logger only to prevent duplication through propagation
    root_logger = logging.getLogger()
    if handler not in root_logger.handlers:
        root_logger.addHandler(handler)


def close_session_log() -> None:
    """Safely detach and close the session log handler."""
    global _SESSION_LOG_FILE, _SESSION_LOG_HANDLER
    if _SESSION_LOG_HANDLER is not None:
        handler = _SESSION_LOG_HANDLER

        # Remove from root logger only
        root_logger = logging.getLogger()
        if handler in root_logger.handlers:
            root_logger.removeHandler(handler)

        handler.close()
        _SESSION_LOG_HANDLER = None
    _SESSION_LOG_FILE = None


def generate_reference_filename(run: str, detector: str) -> str:
    """Generate a standardized reference index filename.

    Format: ``indomain_{run_lower}_{detector_lower}.npz``

    Examples::

        >>> generate_reference_filename("O4a", "H1")
        'indomain_o4a_h1.npz'
        >>> generate_reference_filename("O3b", "L1")
        'indomain_o3b_l1.npz'

    Args:
        run: Observing run identifier (e.g. ``"O4a"``).
        detector: Detector identifier (e.g. ``"H1"``).

    Returns:
        Filename string in the canonical format.
    """
    return f"indomain_{run.lower()}_{detector.lower()}.npz"


def discover_references(reference_dir: Path = Path("data/reference")) -> list[Path]:
    """Find all indomain*.npz reference files in reference_dir."""
    if not reference_dir.exists():
        return []
    return sorted(reference_dir.glob("indomain*.npz"))


def compute_pca_ratio(top_k_indices: np.ndarray, grid_size: int = 37) -> float:
    """Computes the PCA eigenvalue ratio (Continuity) of the Top-K spatial coordinates.
    
    Args:
        top_k_indices: Array or list of 1D patch indices.
        grid_size: The grid size (e.g. 37 for DINOv2 518/14).

    Returns:
        The ratio of the principal eigenvalue to the trace (eigen1 / (eigen1 + eigen2)).
    """
    import torch
    if not isinstance(top_k_indices, torch.Tensor):
        top_k_indices = torch.tensor(top_k_indices)
        
    if len(top_k_indices) < 2:
        return 1.0
        
    i_coords = (top_k_indices // grid_size).float()
    j_coords = (top_k_indices % grid_size).float()
    
    i_c = i_coords - i_coords.mean()
    j_c = j_coords - j_coords.mean()
    X = torch.stack((i_c, j_c), dim=1)
    
    cov = (X.T @ X) / (X.size(0) - 1)
    try:
        L, _ = torch.linalg.eigh(cov)
        eigen1 = L[1].item()
        eigen2 = L[0].item()
        return eigen1 / (eigen1 + eigen2 + 1e-9)
    except:
        return 0.5


def compute_bbox(top_k_indices: np.ndarray, grid_size: int = 37) -> float:
    """Computes the normalized Bounding Box area of the Top-K patches.
    
    Args:
        top_k_indices: Array or list of 1D patch indices.
        grid_size: The grid size (e.g. 37 for DINOv2 518/14).

    Returns:
        The bounding box area normalized by the full grid area.
    """
    import torch
    if not isinstance(top_k_indices, torch.Tensor):
        top_k_indices = torch.tensor(top_k_indices)
        
    if not len(top_k_indices):
        return 0.0
        
    i_coords = top_k_indices // grid_size
    j_coords = top_k_indices % grid_size
    bbox_area = (torch.max(i_coords) - torch.min(i_coords) + 1) * (torch.max(j_coords) - torch.min(j_coords) + 1)
    
    return (bbox_area.float() / (grid_size * grid_size)).item()



# ---------------------------------------------------------------------------
# Environment provenance
# ---------------------------------------------------------------------------

def record_environment(
    out_dir: Path | str, context: str = "run", note: str | None = None
) -> Path | None:
    """Write the exact software environment of this run next to its artifacts.

    Every score in this pipeline passes through ``gwpy``'s ``whiten`` and
    ``q_transform``, so the encoder's input -- and therefore every downstream
    number -- depends on the installed version of that library. Because
    ``requirements.txt`` bounded versions from below rather than pinning them,
    a later ``gwpy`` major release reproduces the analysis qualitatively but
    not numerically, and the artifacts published in 2026 cannot be regenerated
    from the repository alone. See paper_draft/CORRECTIONS_2026-07-21.md (C4).

    This function exists so that never happens again: a run that writes results
    also writes the version set that produced them. Recording is best-effort
    and never interrupts an analysis -- a missing provenance file is bad, a
    crashed 12-hour run is worse.

    Returns the path written, or None if recording failed.
    """
    import hashlib
    import json
    import platform
    import subprocess
    import zipfile
    from datetime import datetime, timezone
    from importlib.metadata import distributions

    logger = logging.getLogger(__name__)
    try:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"environment_{context}.json"

        packages = {}
        for dist in distributions():
            name = dist.metadata["Name"]
            if name:
                packages[name.lower()] = dist.version
        packages = dict(sorted(packages.items()))

        repo_root = Path(__file__).resolve().parents[2]
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                timeout=10, cwd=repo_root,
            ).stdout.strip() or None
            dirty = bool(subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True,
                timeout=10, cwd=repo_root,
            ).stdout.strip())
        except Exception:
            commit, dirty = None, None

        # A dirty commit hash is not a reproducible source identifier. Capture
        # the complete scientific-code delta and relevant untracked source files
        # so a no-commit audit run can still be reconstructed exactly.
        source_snapshot = None
        source_snapshot_sha256 = None
        if dirty:
            try:
                source_roots = (
                    "main.py",
                    "config.yaml",
                    "pyproject.toml",
                    "requirements.txt",
                    "src",
                    "tests",
                    "scripts",
                )
                diff_proc = subprocess.run(
                    ["git", "diff", "--binary", "HEAD", "--", *source_roots],
                    capture_output=True,
                    timeout=30,
                    cwd=repo_root,
                )
                untracked_proc = subprocess.run(
                    [
                        "git",
                        "ls-files",
                        "--others",
                        "--exclude-standard",
                        "--",
                        *source_roots,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=repo_root,
                )
                untracked = [
                    line.strip()
                    for line in untracked_proc.stdout.splitlines()
                    if line.strip()
                ]
                snapshot_path = out_dir / f"source_state_{context}.zip"
                with zipfile.ZipFile(
                    snapshot_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                ) as archive:
                    archive.writestr("tracked_changes.patch", diff_proc.stdout)
                    archive.writestr(
                        "snapshot_manifest.json",
                        json.dumps(
                            {
                                "base_commit": commit,
                                "source_roots": list(source_roots),
                                "untracked_files": untracked,
                            },
                            indent=2,
                        ),
                    )
                    for relative in untracked:
                        source = repo_root / relative
                        if source.is_file():
                            archive.write(source, f"untracked/{relative}")
                source_snapshot = str(snapshot_path)
                source_snapshot_sha256 = hashlib.sha256(
                    snapshot_path.read_bytes()
                ).hexdigest()
            except Exception as exc:
                logger.warning("Could not capture dirty source snapshot: %s", exc)

        # The VQ dictionaries are inputs, not code: hash whichever are present
        # so a mismatched index is detectable after the fact.
        indices = {}
        try:
            for path in sorted(get_reference_dir().glob("patch_compressed_index*.npz")):
                h = hashlib.md5()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                indices[path.name] = h.hexdigest()
        except Exception:
            pass

        record = {
            "context": context,
            "note": note,
            "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": commit,
            "git_dirty": dirty,
            "dirty_source_snapshot": source_snapshot,
            "dirty_source_snapshot_sha256": source_snapshot_sha256,
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
            "torch": {
                "version": torch.__version__,
                "cuda_available": torch.cuda.is_available(),
                "cuda_version": torch.version.cuda,
                "device_name": (
                    torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
                ),
            },
            "reference_index_md5": indices,
            "packages": packages,
        }

        with open(dest, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

        gwpy_version = packages.get("gwpy", "NOT INSTALLED")
        logger.info(
            "Environment recorded in %s (gwpy %s, %d packages)",
            dest.name, gwpy_version, len(packages),
        )
        return dest
    except Exception as e:  # never let provenance break an analysis
        logger.warning("Could not record environment provenance: %s", e)
        return None
