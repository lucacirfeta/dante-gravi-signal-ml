"""Synthetic, outcome-free checks of retained common-PEM auxiliary samples."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import run_dante_o3a_o4a_common_pem_aux_samples as runner
from src.dante_light.contracts import ContractError
from src.dante_light.o3a_o4a_common_pem_aux_samples import (
    InfrastructureError,
    acquire_series,
    data_path,
    sample_specs,
    verify_series,
)


def _series(channel: str, start: int, end: int, rate: int, *, dtype="float32"):
    return SimpleNamespace(
        t0=SimpleNamespace(value=float(start)),
        duration=SimpleNamespace(value=float(end - start)),
        sample_rate=SimpleNamespace(value=float(rate)),
        value=np.arange((end - start) * rate, dtype=dtype),
        unit="count",
        name=channel,
    )


def _spec():
    return {
        "key": "sample-one",
        "run": "O3a",
        "detector": "H1",
        "channel": "H1:TEST",
        "interval_gps": [100, 104],
        "sample_rate_hz": 4,
        "sample_count": 16,
        "uses": [{"target_gps": 100, "role": "event"}],
    }


def _acquire(tmp_path, fetch):
    return acquire_series(
        _spec(),
        run_dir=tmp_path,
        nds_host="test.local",
        chunk_seconds=2,
        retries=1,
        backoff_base_s=2,
        fetch=fetch,
    )


def test_specs_share_background_without_dropping_target_identity():
    rows = [
        {
            "run": "O3a",
            "detector": "H1",
            "target_gps": gps,
            "channels": ["H1:TEST"],
            "event_interval_gps": [gps, gps + 2],
            "background_interval_gps": [50, 60],
        }
        for gps in (100, 104)
    ]
    specs = sample_specs(rows, {"H1": {"H1:TEST": 4}})
    assert len(specs) == 3
    shared = next(item for item in specs if item["interval_gps"] == [50, 60])
    assert shared["sample_count"] == 40
    assert shared["uses"] == [
        {"target_gps": 100, "role": "background"},
        {"target_gps": 104, "role": "background"},
    ]


def test_native_chunks_are_replayed_byte_exactly(tmp_path):
    receipt = _acquire(
        tmp_path, lambda channel, *, start, end, host: _series(channel, start, end, 4)
    )
    verify_series(_spec(), receipt, run_dir=tmp_path, chunk_seconds=3)
    assert np.array_equal(
        np.load(data_path(tmp_path, _spec())),
        np.r_[np.arange(8), np.arange(8)].astype("float32"),
    )
    with data_path(tmp_path, _spec()).open("r+b") as stream:
        stream.seek(-4, 2)
        stream.write(b"xxxx")
    with pytest.raises(ContractError, match="file or receipt changed"):
        verify_series(_spec(), receipt, run_dir=tmp_path, chunk_seconds=3)


@pytest.mark.parametrize("fault", ["dtype", "rate", "start", "nonfinite", "channel"])
def test_changed_native_chunk_fails_closed(tmp_path, fault):
    def fetch(channel, *, start, end, host):
        series = _series(
            channel, start, end, 4, dtype="float64" if fault == "dtype" else "float32"
        )
        if fault == "rate":
            series.sample_rate.value = 8
        elif fault == "start":
            series.t0.value += 1
        elif fault == "nonfinite":
            series.value[0] = np.nan
        elif fault == "channel":
            series.name = "H1:OTHER"
        return series

    with pytest.raises(ContractError, match="changed or incomplete"):
        _acquire(tmp_path, fetch)
    assert not data_path(tmp_path, _spec()).exists()
    assert data_path(tmp_path, _spec()).with_suffix(".partial.npy").exists()


def test_transport_failure_preserves_partial_for_explicit_archive(tmp_path):
    def failed_fetch(channel, *, start, end, host):
        raise ConnectionError("temporary outage")

    with pytest.raises(InfrastructureError, match="transport exhausted"):
        _acquire(tmp_path, failed_fetch)
    assert not data_path(tmp_path, _spec()).exists()
    assert data_path(tmp_path, _spec()).with_suffix(".partial.npy").exists()


def test_completed_receipt_set_rejects_orphan_sample(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orphan.npy").write_bytes(b"invalid")
    with pytest.raises(ContractError, match="orphan sample file"):
        runner._check_completed(
            tmp_path, {"series": [_spec()], "execution": {"chunk_seconds": 2}}
        )


def test_contract_is_preregistered_and_not_an_outcome():
    config = json.loads((runner.ROOT / runner.CONFIG_PATH).read_text(encoding="utf-8"))
    assert config["scientific_boundary"]["five_channel_null_opened"] is False
    assert config["scientific_boundary"]["paired_pem_outcomes_opened"] is False
    assert (
        config["source_policy"]
        == "NDS2_NATIVE_FLOAT32_SAMPLES_LOCAL_REPLAY_NO_SECOND_FETCH"
    )
