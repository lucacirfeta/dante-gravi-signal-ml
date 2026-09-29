"""Fail-closed transport tests for the already verified native PEM samples."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light import o3a_o4a_common_pem_aux_reader as reader_module
from src.pipeline_v2_production import pem_null_calibration as null_core


def _sealed(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({**body, "receipt_digest": canonical_json_sha256(body)}),
        encoding="utf-8",
    )


def _fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    run: str = "O3a",
    detector: str = "H1",
):
    root = tmp_path / "source"
    root.mkdir()
    monkeypatch.setattr(reader_module, "ROOT", root)
    config = {
        "parent_availability_run_key": "a" * 64,
        "parent_availability_summary_digest": "b" * 64,
    }
    for name in reader_module.SOURCE_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config) if name == reader_module.CONFIG_PATH else "frozen",
            encoding="utf-8",
        )
    run_dir = tmp_path / "o3a_o4a_common_pem_v1" / "aux_samples"
    channels = [f"{detector}:SYNTH_{i}" for i in range(5)]
    specs = []
    for role, (left, right) in (
        ("event", (100, 132)),
        ("background", (200, 232)),
    ):
        for channel in channels:
            identity = {
                "run": run,
                "detector": detector,
                "channel": channel,
                "interval_gps": [left, right],
            }
            spec = {
                "key": canonical_json_sha256(identity),
                **identity,
                "sample_rate_hz": 1024,
                "sample_count": 32768,
                "uses": [{"target_gps": 100, "role": role}],
            }
            specs.append(spec)
    plan = {
        "status": "FROZEN_AUX_NATIVE_SAMPLE_PLAN_ONLY",
        "contract_digest": canonical_json_sha256(config),
        "parent_plan_digest": config["parent_availability_run_key"],
        "parent_summary_digest": config["parent_availability_summary_digest"],
        "source_sha256": {
            path: sha256_file(root / path) for path in reader_module.SOURCE_FILES
        },
        "nds_host": "synthetic.invalid",
        "execution": {"chunk_seconds": 8},
        "series": specs,
        "expected_sample_bytes": len(specs) * 32768 * 4,
    }
    plan_digest = canonical_json_sha256(plan)
    run_dir = run_dir / f"aux_samples_{plan_digest}"
    _sealed(run_dir / "plan.json", plan)
    summary = {
        "status": "PASS_AUX_NATIVE_SAMPLES_COMPLETE_ONLY",
        "plan_digest": plan_digest,
        "series_count": len(specs),
        "expected_sample_bytes": plan["expected_sample_bytes"],
    }
    _sealed(run_dir / "summary.json", summary)
    (root / reader_module.BINDING_PATH).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract_id": "dante-o3a-o4a-common-pem-aux-input-binding-v1",
                "status": "FROZEN_TRANSPORT_INPUT_ONLY_NO_PEM_OUTCOMES",
                "parent_aux_samples_run_key": plan_digest,
                "parent_aux_samples_summary_digest": canonical_json_sha256(summary),
                "parent_aux_availability_run_key": config[
                    "parent_availability_run_key"
                ],
                "transport_policy": "VERIFIED_NATIVE_FLOAT32_LOCAL_ONLY_NO_NDS2_FALLBACK",
                "scientific_boundary": {
                    "historical_coherence_and_null_core_unchanged": True,
                    "five_channel_null_opened": False,
                    "paired_pem_outcomes_opened": False,
                    "global_significance_claim": False,
                },
            }
        ),
        encoding="utf-8",
    )
    for spec in specs:
        values = np.arange(spec["sample_count"], dtype=np.float32)
        file_path = run_dir / "data" / f"{spec['key']}.npy"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(file_path, values)
        _sealed(
            run_dir / "receipts" / f"{spec['key']}.json",
            {
                "status": "PASS_AUX_NATIVE_SAMPLES_ONLY",
                "spec": spec,
                "file": file_path.name,
                "file_sha256": sha256_file(file_path),
                "samples_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                "file_size_bytes": file_path.stat().st_size,
                "dtype": "float32",
                "unit": "ct",
            },
        )
    return run_dir, channels, specs


@pytest.mark.parametrize("run,detector", [("O3a", "H1"), ("O4a", "L1")])
def test_exact_local_series_and_no_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run: str, detector: str
) -> None:
    run_dir, channels, _ = _fixture(monkeypatch, tmp_path, run=run, detector=detector)
    reader = reader_module.VerifiedAuxiliaryReader(
        run_dir, run=run, detector=detector, target_gps=100, channels=channels
    )
    series = reader.fetch(channels[0], start=100, end=132, host="synthetic.invalid")
    assert series.t0.value == 100
    assert series.sample_rate.value == 1024
    np.testing.assert_array_equal(series.value, np.arange(32768, dtype=np.float32))
    with patch.object(null_core.TimeSeries, "fetch", side_effect=reader.fetch):
        with patch.object(null_core, "NULL_CACHE", tmp_path / "historic_cache"):
            background = null_core._fetch_aux_block(
                channels[0], 200, 232, "synthetic.invalid", max_fs=512
            )
    assert background.sample_rate.value == 512


def test_wrong_target_interval_and_host_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir, channels, _ = _fixture(monkeypatch, tmp_path)
    reader = reader_module.VerifiedAuxiliaryReader(
        run_dir, run="O3a", detector="H1", target_gps=100, channels=channels
    )
    with pytest.raises(ContractError, match="not frozen"):
        reader.fetch(channels[0], start=100, end=133, host="synthetic.invalid")
    with pytest.raises(ContractError, match="source request changed"):
        reader.fetch(channels[0], start=100, end=132, host="other.invalid")
    with pytest.raises(ContractError, match="not frozen"):
        reader.fetch("H1:UNAPPROVED", start=100, end=132, host="synthetic.invalid")


def test_changed_samples_and_missing_role_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir, channels, specs = _fixture(monkeypatch, tmp_path)
    reader = reader_module.VerifiedAuxiliaryReader(
        run_dir, run="O3a", detector="H1", target_gps=100, channels=channels
    )
    path = run_dir / "data" / f"{specs[0]['key']}.npy"
    data = np.load(path, mmap_mode="r+")
    data[0] = -1
    data.flush()
    with pytest.raises(ContractError, match="file or receipt changed"):
        reader.fetch(channels[0], start=100, end=132, host="synthetic.invalid")
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    plan["series"][-1]["uses"] = [{"target_gps": 999, "role": "background"}]
    plan.pop("receipt_digest")
    _sealed(run_dir / "plan.json", plan)
    with pytest.raises(ContractError):
        reader_module.VerifiedAuxiliaryReader(
            run_dir, run="O3a", detector="H1", target_gps=100, channels=channels
        )


def test_changed_parent_binding_is_rejected_before_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir, channels, _ = _fixture(monkeypatch, tmp_path)
    path = reader_module.ROOT / reader_module.BINDING_PATH
    binding = json.loads(path.read_text(encoding="utf-8"))
    binding["parent_aux_samples_summary_digest"] = "0" * 64
    path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(ContractError, match="parent seal changed"):
        reader_module.VerifiedAuxiliaryReader(
            run_dir, run="O3a", detector="H1", target_gps=100, channels=channels
        )
