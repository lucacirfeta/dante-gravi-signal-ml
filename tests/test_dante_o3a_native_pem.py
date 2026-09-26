"""Fail-closed input tests for the O3a-only diagnostic PEM stage."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_contract import ROOT
from src.dante_light.o3a_native_pem import (
    DEFAULT_EXTERNAL_ROOT,
    _check_sources,
    _event_strain,
    _measure_event,
    _sealed,
    _verify_event,
    load_contract,
    preflight_inputs,
)


def test_frozen_contract_is_o3a_only_with_excluded_channels() -> None:
    contract = load_contract(root=ROOT)
    assert contract["scientific_boundary"]["o4a_comparison_performed"] is False
    assert contract["scientific_boundary"]["global_significance_claim"] is False
    assert contract["population"]["exact_total"] == sum(
        contract["population"][bucket]["total"]
        for bucket in ("primary", "diagnostic")
    )
    active = set(contract["channels"]["H1"] + contract["channels"]["L1"])
    assert active.isdisjoint(contract["channels"]["explicitly_excluded"])


def test_changed_contract_seal_is_rejected() -> None:
    contract = load_contract(root=ROOT)
    mutated = deepcopy(contract)
    mutated["scientific_boundary"]["o4a_comparison_performed"] = True
    with pytest.raises(ContractError, match="contract_digest seal changed"):
        _sealed(mutated, "contract_digest")


def test_source_coverage_fails_closed_on_gap_or_wrong_inventory() -> None:
    contract = load_contract(root=ROOT)
    parent = json.loads(
        (ROOT / contract["parents"]["coincidence_contract"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    pad = int(parent["measurement"]["whitening_pad_s"])
    duration = int(parent["measurement"]["segment_duration_s"])
    gps = 123456
    frame = {
        "detector": "H1",
        "filename": "H-H1_GWOSC_O3a_4KHZ_R1-123400-4096.hdf5",
        "gps_start": gps - pad,
        "gps_end": gps + duration + pad,
        "url": "https://example.test/official.hdf5",
    }
    source = {
        **frame,
        "used_interval_gps": [gps - pad, gps + duration + pad],
        "sha256": "a" * 64,
        "size_bytes": 1,
    }
    inventory = {frame["filename"]: frame}
    _check_sources([source], detector="H1", gps=gps, pad=pad, duration=duration, inventory_frames=inventory)
    with pytest.raises(ContractError, match="incomplete"):
        _check_sources(
            [{**source, "used_interval_gps": [gps - pad, gps + duration + pad - 1]}],
            detector="H1", gps=gps, pad=pad, duration=duration,
            inventory_frames=inventory,
        )
    with pytest.raises(ContractError, match="identity changed"):
        _check_sources(
            [source], detector="H1", gps=gps, pad=pad, duration=duration,
            inventory_frames={},
        )


def test_real_parent_preflight_selects_only_frozen_o3a_shortlist() -> None:
    if not DEFAULT_EXTERNAL_ROOT.is_dir():
        pytest.skip("external O3a evidence is not mounted")
    preflight, targets, exclusion = preflight_inputs(root=ROOT)
    contract = load_contract(root=ROOT)
    assert preflight["status"] == "PASS_O3A_NATIVE_PEM_INPUT_PREFLIGHT"
    assert len(targets) == contract["population"]["exact_total"]
    assert len(exclusion) == contract["population"]["candidate_exclusion_total"]
    assert preflight["strain_opened"] is False
    assert preflight["pem_outcomes_opened"] is False
    assert {target["native_class"] for target in targets} == {
        contract["population"][bucket]["class"]
        for bucket in ("primary", "diagnostic")
    }


def test_uncalibrated_event_is_not_a_negative(tmp_path) -> None:
    contract = load_contract(root=ROOT)
    target = {
        "population": "primary",
        "detector": "H1",
        "gps_start": 123456,
    }
    body = {
        "target": target,
        "candidate_exclusion_digest": "d" * 64,
        "scientific_interpretation": "PEM_DIAGNOSTIC_ONLY_NOT_ASTROPHYSICAL_CONFIRMATION",
        "channels": [
            {"aux_channel": channel, "data_available": False, "max_coherence": None}
            for channel in contract["channels"]["H1"]
        ],
        "calibration": None,
        "verdict_tier": "UNCALIBRATED",
        "verdict_time_shift": "UNCALIBRATED",
        "cmax_observed": None,
        "top_channel": None,
        "threshold_time_shift_q99": None,
        "threshold_zero_lag_q99": None,
    }
    event = {**body, "event_digest": canonical_json_sha256(body)}
    _verify_event(
        event, target=target, run_dir=tmp_path,
        exclusion_digest="d" * 64, contract=contract,
    )
    body["verdict_time_shift"] = "NO_CORRELATION"
    event = {**body, "event_digest": canonical_json_sha256(body)}
    with pytest.raises(ContractError, match="counted as negative"):
        _verify_event(
            event, target=target, run_dir=tmp_path,
            exclusion_digest="d" * 64, contract=contract,
        )


def test_raw_event_context_replays_frozen_hash(tmp_path, monkeypatch) -> None:
    import h5py
    import src.dante_light.o3a_native_pem as pem

    contract = load_contract(root=ROOT)
    parent = json.loads(
        (ROOT / contract["parents"]["coincidence_contract"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    rate = int(parent["measurement"]["sample_rate_hz"])
    pad = int(parent["measurement"]["whitening_pad_s"])
    duration = int(parent["measurement"]["segment_duration_s"])
    gps = 123456
    raw = np.random.default_rng(42).normal(size=(duration + 2 * pad) * rate).astype(np.float64)
    cache = tmp_path / "transient_raw" / "H1"
    cache.mkdir(parents=True)
    with h5py.File(cache / "frame.hdf5", "w") as handle:
        handle.create_dataset("strain/Strain", data=raw)
    monkeypatch.setattr(pem, "_download_frame", lambda **_kwargs: None)
    target = {
        "detector": "H1",
        "gps_start": gps,
        "raw_context_sha256": hashlib.sha256(raw.tobytes()).hexdigest(),
        "context_sources": [{
            "filename": "frame.hdf5",
            "gps_start": gps - pad,
            "gps_end": gps + duration + pad,
            "used_interval_gps": [gps - pad, gps + duration + pad],
            "sha256": "a" * 64,
        }],
    }
    series, central_sha = _event_strain(target, run_dir=tmp_path, contract=contract)
    assert len(series) == duration * rate
    assert central_sha == hashlib.sha256(raw[pad * rate : (pad + duration) * rate].tobytes()).hexdigest()
    with pytest.raises(ContractError, match="did not replay"):
        _event_strain(
            {**target, "raw_context_sha256": "b" * 64},
            run_dir=tmp_path, contract=contract,
        )


def test_synthetic_event_calibration_and_verifier_fail_closed(tmp_path, monkeypatch) -> None:
    import src.dante_light.o3a_native_pem as pem
    from src.pipeline_v2_production import pem_coherence_analysis, pem_null_calibration

    contract = load_contract(root=ROOT)
    channels = contract["channels"]["H1"]
    target = {"population": "primary", "detector": "H1", "gps_start": 123456}
    exclusion = [float(target["gps_start"])]
    exclusion_digest = canonical_json_sha256(exclusion)
    monkeypatch.setattr(pem, "_event_strain", lambda *_args, **_kwargs: (object(), "c" * 64))
    monkeypatch.setattr(pem_coherence_analysis, "fetch_auxiliary_data", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        pem_coherence_analysis,
        "calculate_coherence_and_plot",
        lambda _strain, _aux, channel, *_args, **_kwargs: {
            "max_coherence": 0.9 if channel == channels[-1] else 0.5,
            "peak_freq": 50.0,
        },
    )

    def fake_calibrate(_detector, _gps, tested, **kwargs):
        calibration = {
            "detector": "H1",
            "run": "O3a",
            "event_gps": target["gps_start"],
            "candidate_exclusion_digest": exclusion_digest,
            "candidate_exclusion_population": contract["population"]["candidate_exclusion_total"],
            "channels": tested,
            "alpha_family_wise": contract["measurement"]["alpha_family_wise"],
            "n_windows": contract["measurement"]["minimum_clean_windows"],
            "threshold_fw": 0.7,
            "zero_lag_control": {"q99": 0.8},
        }
        path = kwargs["pem_dir"] / f"null_calibration_H1_{target['gps_start']}.json"
        path.write_text(json.dumps(calibration), encoding="utf-8")
        return calibration

    monkeypatch.setattr(pem_null_calibration, "calibrate_event", fake_calibrate)
    event = _measure_event(
        target, run_dir=tmp_path, exclusion=exclusion,
        exclusion_digest=exclusion_digest, contract=contract,
    )
    assert event["verdict_tier"] == "COUPLED"
    _verify_event(
        event, target=target, run_dir=tmp_path,
        exclusion_digest=exclusion_digest, contract=contract,
    )
    calibration = tmp_path / event["calibration"]["filename"]
    calibration.write_text("{}", encoding="utf-8")
    with pytest.raises(ContractError, match="calibration file changed"):
        _verify_event(
            event, target=target, run_dir=tmp_path,
            exclusion_digest=exclusion_digest, contract=contract,
        )
