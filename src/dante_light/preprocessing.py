"""Canonical, score-preserving window preparation for DANTE-Light."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time

import numpy as np

from src.dante_light.contracts import FailClosedReason, WindowIdentity
from src.dante_light.executor import DeferredWindow


@dataclass(frozen=True, slots=True)
class PreparedWindow:
    image: np.ndarray
    strain_sha256: str
    image_sha256: str
    timings: dict[str, float]


def stage_canonical_strain(
    window: WindowIdentity,
    *,
    local_only: bool,
    remote_only: bool = False,
) -> dict[str, float | int | str]:
    """Make public strain available before executor submission.

    This stage deliberately performs no whitening, rendering, scoring, or
    outcome-dependent selection.  It only verifies that the complete frozen
    input window (including whitening context) is retrievable and finite.  A
    subsequent canonical preparation must reproduce the same strain digest.
    """
    from src.core.data_loader import fetch_strain_data

    start = window.gps_start
    end = start + window.duration_s
    began = time.perf_counter()
    strain = fetch_strain_data(
        window.detector,
        start - 4.0,
        end + 4.0,
        local_only=local_only,
        remote_only=remote_only,
    )
    elapsed = time.perf_counter() - began
    actual_start = float(strain.t0.value)
    actual_end = actual_start + float(strain.duration.value)
    tolerance = 1.0 / float(strain.sample_rate.value)
    if actual_start > start - 4.0 + tolerance or actual_end < end + 4.0 - tolerance:
        raise RuntimeError("staged strain does not cover the frozen window")
    values = np.ascontiguousarray(strain.value)
    if not np.all(np.isfinite(values)):
        raise RuntimeError("staged strain contains non-finite samples")
    return {
        "window_id": window.window_id,
        "duration_s": elapsed,
        "samples": int(values.size),
        "sample_rate_hz": float(strain.sample_rate.value),
        "strain_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
    }


def prepare_canonical_window(
    window: WindowIdentity,
    *,
    local_only: bool,
    remote_only: bool = False,
) -> PreparedWindow:
    import matplotlib.pyplot as plt
    from src.core.data_loader import fetch_strain_data
    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )

    stages: dict[str, float] = {}
    start = window.gps_start
    end = start + window.duration_s
    began = time.perf_counter()
    try:
        strain = fetch_strain_data(
            window.detector,
            start - 4.0,
            end + 4.0,
            local_only=local_only,
            remote_only=remote_only,
        )
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise DeferredWindow(FailClosedReason.DEPENDENCY_UNAVAILABLE) from exc
    stages["data_read_s"] = time.perf_counter() - began
    actual_start = float(strain.t0.value)
    actual_end = actual_start + float(strain.duration.value)
    tolerance = 1.0 / float(strain.sample_rate.value)
    if actual_start > start - 4.0 + tolerance or actual_end < end + 4.0 - tolerance:
        raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
    if not np.all(np.isfinite(strain.value)):
        raise DeferredWindow(FailClosedReason.NONFINITE_INPUT)
    strain_sha256 = hashlib.sha256(
        np.ascontiguousarray(strain.value).tobytes()
    ).hexdigest()

    began = time.perf_counter()
    whitened, padding = whiten_context(strain, start, end, pad=4.0)
    clean = extract_clean_subwindow(whitened, start, end)
    stages["whitening_s"] = time.perf_counter() - began
    if padding["left"] or padding["right"]:
        raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
    if abs(float(clean.duration.value) - window.duration_s) > tolerance:
        raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)

    began = time.perf_counter()
    spectrogram = generate_qtransform(clean, save_path=None, cmap="cividis")
    stages["q_transform_s"] = time.perf_counter() - began
    began = time.perf_counter()
    rgba = plt.get_cmap("cividis")(spectrogram)
    image = (rgba[:, :, :3] * 255).astype(np.uint8)
    stages["rendering_s"] = time.perf_counter() - began
    if image.shape != (256, 256, 3) or not np.all(np.isfinite(image)):
        raise DeferredWindow(FailClosedReason.NONFINITE_INPUT)
    return PreparedWindow(
        image=image,
        strain_sha256=strain_sha256,
        image_sha256=hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest(),
        timings=stages,
    )
