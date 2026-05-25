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

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


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

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

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

    # File handler — only when a path is provided
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

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
    """Filter that only permits logs with level >= WARNING or having session_key = True."""
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
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

