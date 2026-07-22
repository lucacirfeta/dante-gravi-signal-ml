"""The patch grid maps row->time and col->frequency, and nothing may swap them.

`gwpy`'s ``Spectrogram.value`` is ``(n_times, n_frequencies)`` -- a 32 s
Q-transform gives shape ``(1000, 500)`` against ``len(times) == 1000``. The
array reaches the encoder unchanged, so for patch index ``p`` on the 37x37 grid:

    row = p // 37  ->  TIME
    col = p % 37   ->  FREQUENCY

Both axes are 256 px after resizing, so a transposition produces no shape error
and no exception -- it silently returns a time derived from frequency content
and a band derived from timing. That is exactly what happened: `_patch_time_band`
localized the L1 singleton at 3.03 s in 199-1226 Hz when the feature it had
selected sits at 24.65 s in 20-66 Hz, and the mistake reached a published
analysis. These tests exist so it cannot happen silently again.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.pipeline_v2_production.coincidence_physical import (
    PATCH_GRID, SEGMENT_LENGTH, SPEC_FRANGE, _patch_time_band,
)

pytestmark = pytest.mark.smoke


def _indices(time_cells: list[int], freq_cells: list[int]) -> np.ndarray:
    """Patch indices at the cartesian product of given time and frequency cells."""
    return np.array([t * PATCH_GRID + f for t in time_cells for f in freq_cells],
                    dtype=np.int64)


def test_late_low_frequency_feature_is_localized_late_and_low() -> None:
    """A feature at the end of the window, at low frequency, reads back as such.

    Mirrors the real L1 singleton: ~30 Hz ringing in the last third of the
    window. Under the transposed mapping this returns ~2.6 s and a kHz band.
    """
    idx = _indices(time_cells=[28, 29, 30, 31, 32], freq_cells=[2, 3, 4])
    t_off, f_lo, f_hi = _patch_time_band(idx)

    assert t_off > 0.75 * SEGMENT_LENGTH, (
        f"feature placed in the last quarter of the window came back at "
        f"{t_off:.2f} s of {SEGMENT_LENGTH} s -- time and frequency are swapped"
    )
    assert f_hi < 100.0, (
        f"low-frequency feature came back as {f_lo:.0f}-{f_hi:.0f} Hz -- "
        "time and frequency are swapped"
    )


def test_early_high_frequency_feature_is_localized_early_and_high() -> None:
    """The mirror case, so a double swap cannot pass both tests."""
    idx = _indices(time_cells=[1, 2, 3], freq_cells=[30, 31, 32, 33])
    t_off, f_lo, f_hi = _patch_time_band(idx)

    assert t_off < 0.25 * SEGMENT_LENGTH, (
        f"feature at the start of the window came back at {t_off:.2f} s"
    )
    assert f_lo > 200.0, (
        f"high-frequency feature came back as {f_lo:.0f}-{f_hi:.0f} Hz"
    )


def test_time_offset_tracks_the_time_cell_only() -> None:
    """Moving a feature in frequency must not move it in time."""
    offsets = [
        _patch_time_band(_indices([20], [f, f + 1, f + 2]))[0]
        for f in (2, 15, 30)
    ]
    assert max(offsets) - min(offsets) < 1e-9, (
        f"t_off changed with frequency: {offsets} -- the axes are coupled"
    )
    expected = (20 + 0.5) / PATCH_GRID * SEGMENT_LENGTH
    assert abs(offsets[0] - expected) < 1e-6


def test_band_stays_inside_the_effective_frange() -> None:
    """The band never exceeds the frequency span the Q-transform truly produces."""
    for cells in ([0, 1], [18, 19], [35, 36]):
        _, f_lo, f_hi = _patch_time_band(_indices([10], cells))
        assert SPEC_FRANGE[0] <= f_lo < f_hi <= SPEC_FRANGE[1], (
            f"band {f_lo:.1f}-{f_hi:.1f} Hz outside {SPEC_FRANGE}"
        )
