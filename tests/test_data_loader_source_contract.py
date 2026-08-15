from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from gwpy.timeseries import TimeSeries

from src.core import data_loader


def test_remote_only_bypasses_matching_local_mirror(tmp_path, monkeypatch) -> None:
    detector = "H1"
    start = 1368980864
    end = 1368980904
    local = tmp_path / f"{detector}_{start}_{end}.hdf5"
    TimeSeries(
        np.zeros((end - start) * 4096), sample_rate=4096, t0=start
    ).write(local, format="hdf5", path="strain")
    monkeypatch.setattr(data_loader, "_DATA_DIRECTORIES", [Path(tmp_path)])
    data_loader._LOCAL_BLOCK_INDEX.clear()
    calls: list[tuple[str, int, int]] = []

    def public_fetch(ifo, gps_start, gps_end, **_kwargs):
        calls.append((ifo, gps_start, gps_end))
        return TimeSeries(
            np.ones((gps_end - gps_start) * 4096),
            sample_rate=4096,
            t0=gps_start,
        )

    monkeypatch.setattr(TimeSeries, "fetch_open_data", public_fetch)
    monkeypatch.setattr(data_loader.time, "sleep", lambda _seconds: None)
    result = data_loader.fetch_strain_data(
        detector, start, end, remote_only=True
    )
    assert calls == [(detector, start, end)]
    assert np.all(result.value == 1.0)


def test_strain_source_modes_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        data_loader.fetch_strain_data(
            "H1", 1368980864, 1368980904, local_only=True, remote_only=True
        )
