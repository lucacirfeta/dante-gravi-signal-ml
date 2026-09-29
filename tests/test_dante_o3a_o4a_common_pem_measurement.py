"""Synthetic fail-closed tests for the paired five-channel PEM measurement."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light import o3a_o4a_common_pem_measurement as common


def _case() -> tuple[dict, dict]:
    channels = [f"H1:SYNTHETIC_{index}" for index in range(5)]
    exclusions = {"O3a": [1.0, 2.0], "O4a": [3.0, 4.0, 5.0]}
    comparison = {
        "method": {
            "channels": {"H1": channels},
            "measurement": {
                "event_window_s": 32,
                "coherence_fftlength_s": 2.0,
                "frequency_band_hz": [20.0, 500.0],
                "background_block_s": 14400.0,
                "alpha_family_wise": 0.01,
                "bootstrap_resamples": 200,
                "seed": 42,
                "minimum_clean_windows": 60,
            },
        },
        "runs": {
            run: {
                "candidate_exclusion": {
                    "expected_count": len(values),
                    "digest": canonical_json_sha256(values),
                }
            }
            for run, values in exclusions.items()
        },
    }
    return comparison, exclusions


def _execution() -> dict:
    return {
        "nds_host": "synthetic.invalid",
        "aux_fetch_retries": 1,
        "aux_fetch_backoff_base_s": 2,
        "ephemeral_background_cache_purged": True,
    }


def _series(*, start: int = 100, end: int = 132, rate: int = 1024):
    return SimpleNamespace(
        t0=SimpleNamespace(value=start),
        duration=SimpleNamespace(value=end - start),
        sample_rate=SimpleNamespace(value=rate),
        value=np.ones((end - start) * rate),
    )


def _install_success_mocks(monkeypatch: pytest.MonkeyPatch, calls: list[dict]) -> None:
    monkeypatch.setattr(common, "fetch_auxiliary_data", lambda *args: _series())

    def coherence(*args, **kwargs):
        return {
            "max_coherence": 0.1 * (int(args[2].rsplit("_", 1)[1]) + 1),
            "peak_freq": 40.0,
        }

    monkeypatch.setattr(common, "calculate_coherence_and_plot", coherence)

    def calibration(detector, gps, channels, **kwargs):
        calls.append(
            {
                "detector": detector,
                "gps": gps,
                "channels": channels,
                "run": kwargs["run"],
                "n_boot": kwargs["n_boot"],
                "seed": kwargs["seed"],
                "candidate_gps": kwargs["candidate_gps"].tolist(),
            }
        )
        result = {
            "detector": detector,
            "run": kwargs["run"],
            "event_gps": gps,
            "channels": channels,
            "m_channels": len(channels),
            "candidate_exclusion_population": len(kwargs["candidate_gps"]),
            "candidate_exclusion_digest": kwargs["candidate_exclusion_digest"],
            "alpha_family_wise": kwargs["alpha"],
            "n_windows": 60,
            "background_span": [0, 14400],
            "threshold_fw": 0.7,
            "zero_lag_control": {"q99": 0.8},
        }
        path = kwargs["pem_dir"] / f"null_calibration_{detector}_{int(gps)}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        return result

    monkeypatch.setattr(common, "calibrate_event", calibration)


def test_public_measurement_binds_verified_local_auxiliary_reader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comparison, exclusions = _case()
    bindings: list[dict] = []

    class LocalOnly:
        def __init__(self, path, **kwargs):
            bindings.append({"path": path, **kwargs})

        def fetch(self, *args, **kwargs):
            raise AssertionError("synthetic wrapper must not fetch")

    def measure(*args, **kwargs):
        assert kwargs["auxiliary_fetch"].__self__.__class__ is LocalOnly
        return {"status": "SYNTHETIC_ONLY"}

    monkeypatch.setattr(common, "VerifiedAuxiliaryReader", LocalOnly)
    monkeypatch.setattr(common, "_measure_event", measure)
    result = common.measure_event(
        {"detector": "H1", "gps_start": 100},
        run="O3a",
        comparison=comparison,
        execution=_execution(),
        run_dir=tmp_path,
        auxiliary_run_dir=tmp_path / "sealed_parent",
        candidate_exclusion_gps=exclusions["O3a"],
        strain_reader=lambda: (_series(), "a" * 64),
        background_strain_reader=lambda det, start, end: _series(start=start, end=end),
    )
    assert result["status"] == "SYNTHETIC_ONLY"
    assert bindings == [
        {
            "path": tmp_path / "sealed_parent",
            "run": "O3a",
            "detector": "H1",
            "target_gps": 100,
            "channels": comparison["method"]["channels"]["H1"],
        }
    ]


@pytest.mark.parametrize("run", ["O3a", "O4a"])
def test_same_five_channel_core_with_run_specific_exclusion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run: str
) -> None:
    comparison, exclusions = _case()
    calls: list[dict] = []
    _install_success_mocks(monkeypatch, calls)
    event = common._measure_event(
        {"detector": "H1", "gps_start": 100},
        run=run,
        comparison=comparison,
        execution=_execution(),
        run_dir=tmp_path,
        auxiliary_fetch=lambda **kwargs: _series(),
        candidate_exclusion_gps=exclusions[run],
        strain_reader=lambda: (_series(), "a" * 64),
        background_strain_reader=lambda det, start, end: _series(start=start, end=end),
    )
    assert [row["aux_channel"] for row in event["channels"]] == comparison["method"][
        "channels"
    ]["H1"]
    assert event["calibration"]["channels"] == comparison["method"]["channels"]["H1"]
    assert event["strain_window_sha256"] == "a" * 64
    assert (
        event["scientific_interpretation"]
        == "PEM_DIAGNOSTIC_ONLY_NOT_ASTROPHYSICAL_CONFIRMATION"
    )
    assert calls == [
        {
            "detector": "H1",
            "gps": 100.0,
            "channels": comparison["method"]["channels"]["H1"],
            "run": run,
            "n_boot": 200,
            "seed": 42,
            "candidate_gps": exclusions[run],
        }
    ]


def test_missing_event_channel_fails_before_null(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comparison, exclusions = _case()
    calls: list[dict] = []
    _install_success_mocks(monkeypatch, calls)
    monkeypatch.setattr(
        common,
        "fetch_auxiliary_data",
        lambda channel, *_: None if channel.endswith("_2") else _series(),
    )
    with pytest.raises(ContractError, match="event auxiliary channel unavailable"):
        common._measure_event(
            {"detector": "H1", "gps_start": 100},
            run="O3a",
            comparison=comparison,
            execution=_execution(),
            run_dir=tmp_path,
            auxiliary_fetch=lambda **kwargs: _series(),
            candidate_exclusion_gps=exclusions["O3a"],
            strain_reader=lambda: (_series(), "a" * 64),
            background_strain_reader=lambda det, start, end: _series(
                start=start, end=end
            ),
        )
    assert calls == []


def test_incomplete_five_channel_background_null_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comparison, exclusions = _case()
    calls: list[dict] = []
    _install_success_mocks(monkeypatch, calls)
    original = common.calibrate_event

    def incomplete(*args, **kwargs):
        result = original(*args, **kwargs)
        result["channels"] = result["channels"][:-1]
        result["m_channels"] = 4
        return result

    monkeypatch.setattr(common, "calibrate_event", incomplete)
    with pytest.raises(ContractError, match="background null is incomplete"):
        common._measure_event(
            {"detector": "H1", "gps_start": 100},
            run="O4a",
            comparison=comparison,
            execution=_execution(),
            run_dir=tmp_path,
            auxiliary_fetch=lambda **kwargs: _series(),
            candidate_exclusion_gps=exclusions["O4a"],
            strain_reader=lambda: (_series(), "a" * 64),
            background_strain_reader=lambda det, start, end: _series(
                start=start, end=end
            ),
        )
    assert len(calls) == 1


def test_changed_exclusion_fails_before_strain_read(tmp_path: Path) -> None:
    comparison, _ = _case()
    opened = False

    def strain_reader():
        nonlocal opened
        opened = True
        return _series(), "a" * 64

    with pytest.raises(ContractError, match="exclusion ledger changed"):
        common._measure_event(
            {"detector": "H1", "gps_start": 100},
            run="O3a",
            comparison=comparison,
            execution=_execution(),
            run_dir=tmp_path,
            auxiliary_fetch=lambda **kwargs: _series(),
            candidate_exclusion_gps=[1.0, 3.0],
            strain_reader=strain_reader,
            background_strain_reader=lambda det, start, end: _series(
                start=start, end=end
            ),
        )
    assert not opened


def test_duplicate_detector_channel_fails_before_strain_read(tmp_path: Path) -> None:
    comparison, exclusions = _case()
    comparison["method"]["channels"]["H1"][4] = comparison["method"]["channels"]["H1"][
        0
    ]
    with pytest.raises(ContractError, match="detector-channel set is invalid"):
        common._measure_event(
            {"detector": "H1", "gps_start": 100},
            run="O3a",
            comparison=comparison,
            execution=_execution(),
            run_dir=tmp_path,
            auxiliary_fetch=lambda **kwargs: _series(),
            candidate_exclusion_gps=exclusions["O3a"],
            strain_reader=lambda: (_series(), "a" * 64),
            background_strain_reader=lambda det, start, end: _series(
                start=start, end=end
            ),
        )


@pytest.mark.parametrize(
    "auxiliary",
    [
        _series(end=131),
        _series(rate=0),
    ],
)
def test_partial_or_invalid_rate_event_auxiliary_fails_before_null(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, auxiliary
) -> None:
    comparison, exclusions = _case()
    calls: list[dict] = []
    _install_success_mocks(monkeypatch, calls)
    monkeypatch.setattr(common, "fetch_auxiliary_data", lambda *args: auxiliary)
    with pytest.raises(ContractError, match="incomplete or invalid coverage"):
        common._measure_event(
            {"detector": "H1", "gps_start": 100},
            run="O3a",
            comparison=comparison,
            execution=_execution(),
            run_dir=tmp_path,
            auxiliary_fetch=lambda **kwargs: _series(),
            candidate_exclusion_gps=exclusions["O3a"],
            strain_reader=lambda: (_series(), "a" * 64),
            background_strain_reader=lambda det, start, end: _series(
                start=start, end=end
            ),
        )
    assert calls == []


def test_historical_low_rate_auxiliary_remains_eligible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comparison, exclusions = _case()
    calls: list[dict] = []
    _install_success_mocks(monkeypatch, calls)
    monkeypatch.setattr(common, "fetch_auxiliary_data", lambda *args: _series(rate=512))
    result = common._measure_event(
        {"detector": "H1", "gps_start": 100},
        run="O3a",
        comparison=comparison,
        execution=_execution(),
        run_dir=tmp_path,
        auxiliary_fetch=lambda **kwargs: _series(),
        candidate_exclusion_gps=exclusions["O3a"],
        strain_reader=lambda: (_series(), "a" * 64),
        background_strain_reader=lambda det, start, end: _series(start=start, end=end),
    )
    assert len(result["channels"]) == 5
    assert len(calls) == 1


def test_preexisting_event_cache_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comparison, exclusions = _case()
    calls: list[dict] = []
    _install_success_mocks(monkeypatch, calls)
    cache = tmp_path / "event_aux_cache"
    cache.mkdir()
    (cache / "stale.hdf5").write_bytes(b"unverified")
    with pytest.raises(ContractError, match="cache is not fresh"):
        common._measure_event(
            {"detector": "H1", "gps_start": 100},
            run="O4a",
            comparison=comparison,
            execution=_execution(),
            run_dir=tmp_path,
            auxiliary_fetch=lambda **kwargs: _series(),
            candidate_exclusion_gps=exclusions["O4a"],
            strain_reader=lambda: (_series(), "a" * 64),
            background_strain_reader=lambda det, start, end: _series(
                start=start, end=end
            ),
        )
    assert calls == []


def test_background_reader_and_cache_are_scoped_and_restored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comparison, exclusions = _case()
    calls: list[dict] = []
    _install_success_mocks(monkeypatch, calls)
    original = common.calibrate_event
    old_reader = common.null_core.fetch_strain_data
    old_cache = common.null_core.NULL_CACHE
    observed: list[Path] = []

    def inspect(detector, gps, channels, **kwargs):
        observed.append(common.null_core.NULL_CACHE)
        series = common.null_core.fetch_strain_data(detector, 100, 132)
        assert series.t0.value + series.duration.value == 132
        return original(detector, gps, channels, **kwargs)

    monkeypatch.setattr(common, "calibrate_event", inspect)
    common._measure_event(
        {"detector": "H1", "gps_start": 100},
        run="O3a",
        comparison=comparison,
        execution=_execution(),
        run_dir=tmp_path,
        auxiliary_fetch=lambda **kwargs: _series(),
        candidate_exclusion_gps=exclusions["O3a"],
        strain_reader=lambda: (_series(), "a" * 64),
        background_strain_reader=lambda det, start, end: _series(start=start, end=end),
    )
    assert observed == [tmp_path / "background_aux_cache"]
    assert common.null_core.fetch_strain_data is old_reader
    assert common.null_core.NULL_CACHE == old_cache


def test_partial_background_strain_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comparison, exclusions = _case()
    calls: list[dict] = []
    _install_success_mocks(monkeypatch, calls)

    def inspect(*args, **kwargs):
        common.null_core.fetch_strain_data("H1", 100, 132)
        raise AssertionError("unreachable")

    monkeypatch.setattr(common, "calibrate_event", inspect)
    with pytest.raises(ContractError, match="background strain.*coverage"):
        common._measure_event(
            {"detector": "H1", "gps_start": 100},
            run="O3a",
            comparison=comparison,
            execution=_execution(),
            run_dir=tmp_path,
            auxiliary_fetch=lambda **kwargs: _series(),
            candidate_exclusion_gps=exclusions["O3a"],
            strain_reader=lambda: (_series(), "a" * 64),
            background_strain_reader=lambda det, start, end: _series(
                start=start, end=end - 1
            ),
        )


def test_background_auxiliary_preserves_historical_low_rate_and_rejects_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comparison, exclusions = _case()
    _install_success_mocks(monkeypatch, [])
    channel = comparison["method"]["channels"]["H1"][0]
    monkeypatch.setattr(
        common.null_core,
        "_fetch_aux_block",
        lambda *args, **kwargs: _series(start=100, end=132, rate=512),
    )

    def inspect(*args, **kwargs):
        auxiliary = common.null_core._fetch_aux_block(
            channel, 100, 132, "synthetic.invalid", max_fs=1024
        )
        assert auxiliary.sample_rate.value == 512
        with pytest.raises(ContractError, match="source changed"):
            common.null_core._fetch_aux_block(
                channel, 100, 132, "different.invalid", max_fs=1024
            )
        raise RuntimeError("stop synthetic null")

    monkeypatch.setattr(common, "calibrate_event", inspect)
    with pytest.raises(RuntimeError, match="stop synthetic null"):
        common._measure_event(
            {"detector": "H1", "gps_start": 100},
            run="O3a",
            comparison=comparison,
            execution=_execution(),
            run_dir=tmp_path,
            auxiliary_fetch=lambda **kwargs: _series(),
            candidate_exclusion_gps=exclusions["O3a"],
            strain_reader=lambda: (_series(), "a" * 64),
            background_strain_reader=lambda det, start, end: _series(
                start=start, end=end
            ),
        )
    monkeypatch.setattr(
        common.null_core,
        "_fetch_aux_block",
        lambda *args, **kwargs: _series(start=100, end=131, rate=512),
    )
    with pytest.raises(ContractError, match="background auxiliary.*coverage"):
        common._measure_event(
            {"detector": "H1", "gps_start": 100},
            run="O3a",
            comparison=comparison,
            execution=_execution(),
            run_dir=tmp_path,
            auxiliary_fetch=lambda **kwargs: _series(),
            candidate_exclusion_gps=exclusions["O3a"],
            strain_reader=lambda: (_series(), "a" * 64),
            background_strain_reader=lambda det, start, end: _series(
                start=start, end=end
            ),
        )


def test_event_and_null_fetch_only_through_supplied_auxiliary_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from gwpy.timeseries import TimeSeries
    from src.pipeline_v2_production import pem_coherence_analysis as event_core

    comparison, exclusions = _case()
    calls: list[dict] = []
    _install_success_mocks(monkeypatch, calls)
    monkeypatch.setattr(common, "fetch_auxiliary_data", event_core.fetch_auxiliary_data)
    monkeypatch.setattr(event_core.time, "sleep", lambda _: None)
    source_calls: list[tuple[str, int, int, str]] = []

    def local_source(channel: str, *, start: int, end: int, host: str):
        assert channel in comparison["method"]["channels"]["H1"]
        assert (start, end) in ((100, 132), (200, 232))
        assert host == "synthetic.invalid"
        source_calls.append((channel, start, end, host))
        return TimeSeries(
            np.ones((end - start) * 1024, dtype=np.float32),
            t0=start,
            sample_rate=1024,
            name=channel,
        )

    original_calibration = common.calibrate_event

    def calibration_with_local_reads(detector, gps, channels, **kwargs):
        for channel in channels:
            auxiliary = common.null_core._fetch_aux_block(
                channel, 200, 232, kwargs["nds_host"], max_fs=1024
            )
            assert auxiliary.sample_rate.value == 1024
        for path in common.null_core.NULL_CACHE.glob("*.npz"):
            path.unlink()
        return original_calibration(detector, gps, channels, **kwargs)

    monkeypatch.setattr(common, "calibrate_event", calibration_with_local_reads)
    common._measure_event(
        {"detector": "H1", "gps_start": 100},
        run="O3a",
        comparison=comparison,
        execution=_execution(),
        run_dir=tmp_path,
        auxiliary_fetch=local_source,
        candidate_exclusion_gps=exclusions["O3a"],
        strain_reader=lambda: (_series(), "a" * 64),
        background_strain_reader=lambda det, start, end: _series(start=start, end=end),
    )
    assert len(source_calls) == 10
    assert {call[1:] for call in source_calls} == {
        (100, 132, "synthetic.invalid"),
        (200, 232, "synthetic.invalid"),
    }
