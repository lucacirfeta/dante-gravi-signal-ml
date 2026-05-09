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


def get_device() -> str:
    """Return the best available compute device: ``'cuda'``, ``'mps'``, or ``'cpu'``.

    Used by :class:`~src.encoder.DINOv2Encoder` to automatically select
    hardware acceleration when available.

    Returns:
        Device string compatible with ``torch.device()``.
    """
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


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
