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
    if 1126051217 <= gps <= 1137254417:
        return "O1"
    elif 1164556817 <= gps <= 1187733618:
        return "O2"
    elif 1238166018 <= gps <= 1253977218:
        return "O3a"
    elif 1256655618 <= gps <= 1269363618:
        return "O3b"
    elif 1368973312 <= gps <= 1389452418:
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
