"""Synthetic source-freeze and output-seal tests for paired PEM execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light import o3a_o4a_common_pem_execution as execution
from src.pipeline_v2_production.pem_null_calibration import tier_verdict


def _fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    target = {"population": "primary", "detector": "H1", "gps_start": 100}
    channels = [f"H1:SYNTH_{index}" for index in range(5)]
    exclusion = [1.0, 2.0]
    common = {
        "runs": {
            "O3a": {
                "candidate_exclusion": {
                    "digest": canonical_json_sha256(exclusion),
                    "expected_count": len(exclusion),
                }
            }
        },
        "method": {
            "channels": {"H1": channels},
            "measurement": {"alpha_family_wise": 0.01, "minimum_clean_windows": 60},
        },
    }
    plan = execution._seal(
        {
            "status": execution.PLAN_STATUS,
            "source_sha256": {
                name: sha256_file(execution.ROOT / name)
                for name in execution.SOURCE_FILES
            },
            "background_spans": {
                "O3a": [
                    {
                        "detector": "H1",
                        "gps_start": 100,
                        "interval_gps": [200, 14600],
                    }
                ]
            },
        }
    )
    context = {
        "paths": {
            "output": tmp_path,
            "auxiliary_samples": tmp_path / "sealed_aux",
            "background_spans": tmp_path / "sealed_spans",
            "background_acquisition": tmp_path / "sealed_frames",
        },
        "inputs": {"O3a": {"targets": [target], "exclusion": exclusion}},
        "common": common,
        "config": {
            "execution_transport": {
                "O3a": {"aux_fetch_retries": 3, "aux_fetch_backoff_base_s": 2}
            }
        },
    }
    monkeypatch.setattr(execution, "build_plan", lambda **kwargs: (plan, context))
    monkeypatch.setattr(
        execution, "load_o3a_contract", lambda **kwargs: {"execution": {}}
    )
    monkeypatch.setattr(execution, "_purge_transient", lambda *args, **kwargs: None)
    execution._atomic_json(execution._plan_path(context["paths"], plan), plan)
    calls = []

    def fake_measure(target, **kwargs):
        calls.append(target)
        null_path = kwargs["run_dir"] / "null_calibration_H1_100.json"
        calibration = {
            "channels": channels,
            "m_channels": 5,
            "candidate_exclusion_digest": common["runs"]["O3a"]["candidate_exclusion"][
                "digest"
            ],
            "candidate_exclusion_population": 2,
            "alpha_family_wise": 0.01,
            "n_windows": 60,
            "background_span": [200, 14600],
            "threshold_fw": 0.7,
            "zero_lag_control": {"q99": 0.8},
        }
        null_path.write_text(json.dumps(calibration), encoding="utf-8")
        rows = [
            {
                "aux_channel": channel,
                "data_available": True,
                "max_coherence": (index + 1) / 10,
            }
            for index, channel in enumerate(channels)
        ]
        return {
            "run": "O3a",
            "target": target,
            "candidate_exclusion_digest": calibration["candidate_exclusion_digest"],
            "channels": rows,
            "calibration": {
                "filename": null_path.name,
                "sha256": sha256_file(null_path),
            },
            "top_channel": channels[-1],
            "cmax_observed": 0.5,
            "threshold_time_shift_q99": 0.7,
            "threshold_zero_lag_q99": 0.8,
            "verdict_time_shift": "NO_CORRELATION",
            "verdict_tier": tier_verdict(0.5, 0.7, 0.8),
            "scientific_interpretation": "PEM_DIAGNOSTIC_ONLY_NOT_ASTROPHYSICAL_CONFIRMATION",
        }

    monkeypatch.setattr(execution, "measure_event", fake_measure)
    return plan, target, calls


def test_separate_run_receipts_and_standalone_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan, target, calls = _fixture(monkeypatch, tmp_path)
    summary, run_dir = execution.run_one(run="O3a")
    assert summary["status"] == execution.COMPLETE_STATUS
    assert summary["plan_digest"] == plan["receipt_digest"]
    assert calls == [target]
    verified, same_dir = execution.verify_one(run="O3a")
    assert same_dir == run_dir
    assert verified["status"] == execution.VERIFIED_STATUS
    assert execution.run_one(run="O3a")[0]["status"] == execution.VERIFIED_STATUS
    assert calls == [target]


def test_changed_null_and_failure_stop_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fixture(monkeypatch, tmp_path)
    _, run_dir = execution.run_one(run="O3a")
    null_path = next((run_dir / "events").glob("*/null_calibration_*.json"))
    null_path.write_text(null_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ContractError, match="receipt or null changed"):
        execution.verify_one(run="O3a")


def test_existing_controller_lock_prevents_duplicate_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan, _, calls = _fixture(monkeypatch, tmp_path)
    run_dir = tmp_path / f"common_pem_O3a_{execution._run_key(plan, 'O3a')}"
    run_dir.mkdir()
    (run_dir / "controller.lock").write_text("synthetic", encoding="utf-8")
    with pytest.raises(ContractError, match="already active or stale"):
        execution.run_one(run="O3a")
    assert calls == []
    assert (run_dir / "controller.lock").exists()


def test_changed_frozen_source_fails_before_measurement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan, _, calls = _fixture(monkeypatch, tmp_path)
    original = execution.sha256_file

    def changed(path: Path) -> str:
        if path == execution.ROOT / execution.SOURCE_FILES[0]:
            return "0" * 64
        return original(path)

    monkeypatch.setattr(execution, "sha256_file", changed)
    with pytest.raises(ContractError, match="source changed during execution"):
        execution.run_one(run="O3a")
    run_dir = tmp_path / f"common_pem_O3a_{execution._run_key(plan, 'O3a')}"
    assert not (run_dir / "controller.lock").exists()
    assert (run_dir / "failure.json").exists()
    assert calls == []
