"""Synthetic matched-input transport/replay checks, never real PEM outcomes."""

import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import run_dante_o3a_l1_local_samples as runner
from src.dante_light.contracts import ContractError
from src.dante_light.o3a_l1_local_samples import auxiliary_specs, transport_intervals
from src.dante_light.o3a_o4a_common_pem_acquisition import _atomic_json, sealed_json
from src.dante_light.o3a_o4a_common_pem_aux_samples import (
    InfrastructureError,
    acquire_series,
    data_path,
)


def test_only_adjacent_accepted_contexts_merge_not_rejected_gaps():
    blocks = [
        {"eligible": True, "context_starts_gps": [0, 32, 64]},
        {"eligible": False, "context_starts_gps": [96, 128, 160]},
        {"eligible": True, "context_starts_gps": [192, 224, 256]},
    ]
    snapshot = copy.deepcopy(blocks)
    assert transport_intervals(blocks, 32) == [[0, 96], [192, 288]]
    assert blocks == snapshot


@pytest.mark.parametrize("starts", [[], [32, 0], [0, 0], [0, 16], [0.5]])
def test_transport_invalid_contexts_rejected(starts):
    with pytest.raises(ContractError):
        transport_intervals([{"eligible": True, "context_starts_gps": starts}], 32)


def test_native_specs_retain_exact_exposure_and_identity():
    specs = auxiliary_specs(
        [[0, 96], [192, 288]],
        channels=["L1:A", "L1:B"],
        rates={"L1:A": 4, "L1:B": 8},
        target_gps=1000,
    )
    assert len(specs) == 4
    assert sum(s["sample_count"] * 4 for s in specs) == 192 * 12 * 4
    assert len({s["key"] for s in specs}) == 4
    assert all(s["uses"] == [{"target_gps": 1000, "role": "background"}] for s in specs)


@pytest.mark.parametrize("fault", ["detector", "rate", "interval", "duplicate"])
def test_native_changed_geometry_fails_closed(fault):
    intervals, channels, rates = [[0, 32]], ["L1:A"], {"L1:A": 4}
    if fault == "detector":
        channels, rates = ["H1:A"], {"H1:A": 4}
    elif fault == "rate":
        rates["L1:A"] = 4.5
    elif fault == "interval":
        intervals = [[0, 0]]
    else:
        intervals *= 2
    with pytest.raises(ContractError):
        auxiliary_specs(intervals, channels=channels, rates=rates, target_gps=1000)


def test_frozen_transport_contract_disallows_interpretation():
    config = runner.load_config()
    assert config["scientific_boundary"]["local_coherence_opened"] is False
    assert config["transport"]["sample_cast_resample_filter_allowed"] is False
    assert config["transport"]["resume_on_failure_automatic"] is False


@pytest.mark.parametrize("fault", ["outcome", "cast", "parent", "run"])
def test_contract_boundary_and_parent_tampering_rejected(tmp_path, monkeypatch, fault):
    config = json.loads((runner.ROOT / runner.CONFIG_PATH).read_text())
    if fault == "outcome":
        config["scientific_boundary"]["local_coherence_opened"] = True
    elif fault == "cast":
        config["transport"]["sample_cast_resample_filter_allowed"] = True
    elif fault == "run":
        config["strain_source"]["run"] = "O4a"
    else:
        config["method"]["sha256"] = "0" * 64
    _atomic_json(tmp_path / runner.CONFIG_PATH, config)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "sha256_file", lambda _: "a" * 64)
    with pytest.raises(ContractError):
        runner.load_config()


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    channels, rates = ["L1:A"], {"L1:A": 4}
    specs = auxiliary_specs([[0, 4]], channels=channels, rates=rates, target_gps=100)
    event = auxiliary_specs(
        [[100, 104]], channels=channels, rates=rates, target_gps=100
    )[0]
    event["uses"] = [{"target_gps": 100, "role": "event"}]
    historical = tmp_path / "historical"

    def fetch(channel, *, start, end, host):
        return SimpleNamespace(
            name=channel,
            t0=SimpleNamespace(value=start),
            duration=SimpleNamespace(value=end - start),
            sample_rate=SimpleNamespace(value=4),
            value=np.arange((end - start) * 4, dtype="float32"),
            unit="count",
        )

    value = acquire_series(
        event,
        run_dir=historical,
        nds_host="synthetic",
        chunk_seconds=2,
        retries=1,
        backoff_base_s=2,
        fetch=fetch,
    )
    _atomic_json(historical / "receipts" / f"{event['key']}.json", runner.seal(value))
    before = {
        p.relative_to(historical): p.read_bytes()
        for p in historical.rglob("*")
        if p.is_file()
    }
    plan = runner.seal(
        {
            "status": "FROZEN_MATCHED_NATIVE_SAMPLE_PLAN_NO_OUTCOMES",
            "frames": [{"filename": "synthetic.hdf5"}],
            "strain_source": {"frame_duration_s": 4, "sample_rate_hz": 4},
            "spans": [{"role": "background", "detector": "L1", "interval_gps": [0, 4]}],
            "auxiliary_series": specs,
            "event_auxiliary_specs": [event],
            "event_auxiliary_parent_root": str(historical),
            "nds_host": "synthetic",
            "execution": {
                "chunk_seconds": 2,
                "fetch_retries": 1,
                "backoff_base_s": 2,
                "minimum_free_space_multiplier": 2,
            },
            "expected": {
                "control_auxiliary_sample_bytes": 64,
                "eligible_blocks": 1,
                "control_contexts": 1,
            },
        }
    )
    calls = []

    def acquire_frame(frame, *, run_dir, **kwargs):
        _atomic_json(
            run_dir / "receipts" / f"{frame['filename']}.json", runner.seal(frame)
        )
        (run_dir / "frames").mkdir(parents=True, exist_ok=True)
        (run_dir / "frames" / frame["filename"]).write_bytes(b"synthetic")

    monkeypatch.setattr(
        runner, "load_config", lambda: {"output_root": str(tmp_path / "new")}
    )
    monkeypatch.setattr(runner, "build_plan", lambda: plan)
    monkeypatch.setattr(runner, "manifest_for", lambda _: {})
    monkeypatch.setattr(runner, "acquire_frame_v2", acquire_frame)
    monkeypatch.setattr(
        runner, "verify_frame_v2", lambda *a, **k: calls.append("frame")
    )
    monkeypatch.setattr(
        runner, "produce_span_receipt", lambda **k: {"samples_sha256": "synthetic"}
    )
    monkeypatch.setattr(
        runner, "verify_background_receipt", lambda *a, **k: calls.append("span")
    )
    monkeypatch.setattr(runner, "fetch_aux", fetch)
    path = tmp_path / "new" / f"samples_{plan['receipt_digest']}"
    assert runner.main("plan", None) == 0
    return path, plan, historical, before, calls


def test_run_and_offline_verifier_preserve_historical_event(transport, monkeypatch):
    path, plan, historical, before, calls = transport
    assert runner.main("run", str(path)) == 0
    monkeypatch.setattr(
        runner, "fetch_aux", lambda *a, **k: pytest.fail("verify must never fetch")
    )
    assert runner.main("verify", str(path)) == 0
    assert calls == ["frame", "span", "frame", "span"]
    assert {
        p.relative_to(historical): p.read_bytes()
        for p in historical.rglob("*")
        if p.is_file()
    } == before
    assert sealed_json(path / "summary.json")["local_pem_outcomes_opened"] is False
    assert not (path / "controller.lock").exists()
    with pytest.raises(ContractError, match="already terminal"):
        runner.main("run", str(path))
    with pytest.raises(ContractError, match="run key"):
        runner.main("verify", str(path.parent / "wrong"))
    assert plan["expected"]["eligible_blocks"] == 1


@pytest.mark.parametrize(
    "fault", ["sample", "orphan", "partial", "lock", "summary", "event"]
)
def test_verifier_rejects_mutation_and_incomplete_sets(transport, fault):
    path, plan, historical, _, _ = transport
    runner.main("run", str(path))
    if fault == "sample":
        data_path(path / "auxiliary", plan["auxiliary_series"][0]).write_bytes(
            b"corrupt"
        )
    elif fault == "orphan":
        (path / "auxiliary" / "data" / "orphan.npy").write_bytes(b"orphan")
    elif fault == "partial":
        (path / "orphan.partial").write_bytes(b"partial")
    elif fault == "lock":
        (path / "controller.lock").write_text("active")
    elif fault == "event":
        data_path(historical, plan["event_auxiliary_specs"][0]).write_bytes(b"corrupt")
    else:
        value = sealed_json(path / "summary.json")
        value.pop("receipt_digest")
        value["control_context_count"] = 2
        _atomic_json(path / "summary.json", runner.seal(value))
    with pytest.raises(ContractError):
        runner.main("verify", str(path))


@pytest.mark.parametrize("kind", ["infrastructure", "structural"])
def test_failure_preserved_no_automatic_resume(transport, monkeypatch, kind):
    path, _, _, _, _ = transport
    error = (
        InfrastructureError("outage")
        if kind == "infrastructure"
        else ContractError("changed native dtype")
    )

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(runner, "acquire_series", fail)
    with pytest.raises(type(error)):
        runner.main("run", str(path))
    failure = sealed_json(path / "failure.json")
    assert failure["status"] == (
        "FAILED_INFRASTRUCTURE"
        if kind == "infrastructure"
        else "FAILED_STRUCTURAL_OR_PROVENANCE_REQUIRES_REVIEW"
    )
    before = (path / "failure.json").read_bytes()
    assert not (path / "controller.lock").exists()
    with pytest.raises(ContractError, match="no automatic resume"):
        runner.main("run", str(path))
    assert (path / "failure.json").read_bytes() == before
