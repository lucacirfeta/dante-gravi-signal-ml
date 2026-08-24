from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from gwpy.timeseries import TimeSeries

from src.dante_light.contracts import FailClosedReason, WindowIdentity
from src.dante_light.executor import DeferredWindow
import src.dante_light.prefilter_v5_development as development_module
from src.dante_light.prefilter_v5_development_contract import (
    build_development_contract,
    validate_development_contract,
)
from src.dante_light.prefilter_v5_screening import (
    _audit_selected,
    _bootstrap_mean_lower,
    _select_detector_threshold,
)


ROOT = Path(__file__).resolve().parents[1]


def _code_paths() -> dict[str, Path]:
    return {
        "development_contract": ROOT / "src/dante_light/prefilter_v5_development_contract.py",
        "development_evaluator": ROOT / "src/dante_light/prefilter_v5_development.py",
        "development_waveforms": ROOT / "src/dante_light/prefilter_v5_waveforms.py",
        "development_screening": ROOT / "src/dante_light/prefilter_v5_screening.py",
        "development_cli": ROOT / "scripts/run_dante_light_prefilter_v5_development.py",
        "development_verifier": ROOT / "scripts/verify_dante_light_prefilter_v5_development.py",
        "injection_reconstruction": ROOT / "src/dante_light/prefilter_v5_injections.py",
        "student_architectures": ROOT / "src/dante_light/prefilter_v4_student.py",
        "student_training": ROOT / "src/dante_light/prefilter_v5_training.py",
        "teacher": ROOT / "src/dante_light/prefilter_v5_teacher.py",
    }


def test_v5_development_contract_freezes_approved_audit_before_access() -> None:
    contract = build_development_contract(root=ROOT, code_paths=_code_paths())
    checked = validate_development_contract(contract, root=ROOT)
    assert checked["approved_design"]["audit_stream"]["fraction"] == 0.05
    assert checked["development_access_at_freeze"] == []
    assert checked["confirmation_access_at_freeze"] == []
    assert checked["o4b_access_at_freeze"] == []
    assert isinstance(checked["audit_seed_uint64"], int)


def test_v5_audit_stream_is_deterministic_and_identity_specific() -> None:
    first = [_audit_selected(1234, 0.05, f"window-{index}") for index in range(1000)]
    second = [_audit_selected(1234, 0.05, f"window-{index}") for index in range(1000)]
    changed = [_audit_selected(4321, 0.05, f"window-{index}") for index in range(1000)]
    assert first == second
    assert first != changed
    assert 25 <= sum(first) <= 75


def _row(role: str, morphology: str, index: int) -> dict:
    return {
        "role": role,
        "morphology": morphology,
        "retention_target": role != "background",
        "gps_block": f"H1:{index}",
        "window": {"window_id": f"window-{role}-{morphology}-{index}"},
    }


def test_v5_threshold_selection_never_aggregates_away_weak_morphology() -> None:
    rows = []
    predictions = []
    for index in range(100):
        rows.append(_row("background", "shadow", index))
        predictions.append(float(index) / 100.0)
    for index in range(60):
        rows.append(_row("known_glitch", "Blip", 100 + index))
        predictions.append(2.0 + index / 100.0)
    for index in range(60):
        rows.append(_row("known_glitch", "KoiFish", 200 + index))
        predictions.append(1.5 + index / 100.0)
    # The weak morphology constrains the threshold independently.
    for index in range(60):
        rows.append(_row("known_glitch", "ScatteredLight", 300 + index))
        predictions.append(0.8 + index / 100.0)
    point = _select_detector_threshold(
        rows,
        np.asarray(predictions),
        audit=np.zeros(len(rows), dtype=bool),
        confidence=0.95,
        minimum_point=0.9,
        minimum_lower=0.8,
    )
    assert point is not None
    assert point["protected_retention"]["known_glitch|ScatteredLight"]["pass"] is True
    assert all(item["pass"] for item in point["protected_retention"].values())


def test_v5_cost_uncertainty_resamples_detector_gps_blocks_not_rows() -> None:
    rows = [
        {"gps_block": "H1:1"},
        {"gps_block": "H1:1"},
        {"gps_block": "H1:2"},
        {"gps_block": "H1:2"},
    ]
    values = np.asarray([1.0, 1.0, -1.0, -1.0])
    first = _bootstrap_mean_lower(
        rows,
        values,
        n_resamples=100,
        confidence=0.95,
        seed=9,
        quantile_method="linear",
    )
    second = _bootstrap_mean_lower(
        rows,
        values,
        n_resamples=100,
        confidence=0.95,
        seed=9,
        quantile_method="linear",
    )
    assert first == second
    assert first[1][0] <= 0.0 <= first[1][1]


def test_v5_development_design_declares_diagnostic_shortcuts_not_hidden_gates() -> None:
    design = json.loads(
        (ROOT / "config/dante_light_prefilter_v5_development_design.json").read_text(
            encoding="utf-8"
        )
    )
    assert design["shortcut_controls"]["role"] == "diagnostic_only_no_unfrozen_pass_fail_threshold"
    assert design["replicates"]["favorable_seed_selection_allowed"] is False


def test_v5_remote_strain_is_cached_only_inside_open_development_run(
    tmp_path: Path, monkeypatch
) -> None:
    window = WindowIdentity(run="O3B", detector="H1", gps_start=1_264_000_000.0)
    representation = SimpleNamespace(
        whitening_pad_s=4.0,
        sample_rate_hz=4096,
    )
    values = np.zeros(40 * 4096, dtype=np.float64)
    fetched = TimeSeries(values, sample_rate=4096, t0=window.gps_start - 4.0)
    calls = {"remote": 0}

    def local_miss(*args, **kwargs):
        raise DeferredWindow(FailClosedReason.DEPENDENCY_UNAVAILABLE)

    def remote_fetch(*args, **kwargs):
        calls["remote"] += 1
        return fetched

    monkeypatch.setattr(development_module, "_fetch_teacher_strain", local_miss)
    from src.core import data_loader

    monkeypatch.setattr(data_loader, "fetch_strain_data", remote_fetch)
    cache = tmp_path / "development_run" / "raw_strain_cache"
    first, first_meta = development_module._fetch_development_strain(
        window, representation=representation, raw_cache_dir=cache
    )
    second, second_meta = development_module._fetch_development_strain(
        window, representation=representation, raw_cache_dir=cache
    )
    assert calls["remote"] == 1
    assert np.array_equal(first.value, second.value)
    assert first_meta["strain_source"] == "gwosc_fetched_into_development_run_cache"
    assert second_meta["strain_source"] == "development_run_cache"
    assert first_meta["raw_cache_file_sha256"] == second_meta["raw_cache_file_sha256"]
