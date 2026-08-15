from __future__ import annotations

import hashlib

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, LightDisposition, RepresentationContract, WindowIdentity
from src.dante_light.drift import DriftContract, DriftState, evaluate_score_block
from src.dante_light.epoch import REQUIRED_GATES, verified_epoch_from_promotion
from src.dante_light.prefilter import (
    PrefilterContract,
    extract_excess_energy_features,
)


REPRESENTATION = RepresentationContract.from_reference_manifest(
    "config/reference_artifacts.json"
)


def test_research_prefilter_extracts_finite_features_but_cannot_route() -> None:
    rng = np.random.default_rng(42)
    quiet = rng.normal(0.0, 1.0, 4096 * 2)
    transient = quiet.copy()
    transient[4000] += 40.0
    quiet_features = extract_excess_energy_features(quiet)
    transient_features = extract_excess_energy_features(transient)
    assert transient_features.crest_factor > quiet_features.crest_factor

    contract = PrefilterContract("research-v1", "research_only", 10.0, 0.1, 0.1, 42)
    assert contract.would_escalate(transient_features)
    with pytest.raises(ContractError, match="research-only"):
        contract.route(WindowIdentity("O4A", "H1", 1000), transient_features)


def test_promoted_prefilter_has_deterministic_audit_sampling() -> None:
    contract = PrefilterContract("fixture", "promoted", 100.0, 1.0, 0.5, 7)
    windows = [WindowIdentity("O4A", "L1", 1000 + index) for index in range(50)]
    first = [contract.audit_selected(window) for window in windows]
    second = [contract.audit_selected(window) for window in windows]
    assert first == second
    assert 5 < sum(first) < 45
    dispositions = [
        contract.route(
            window,
            extract_excess_energy_features(np.ones(4096, dtype=np.float64)),
        )
        for window in windows
    ]
    assert set(dispositions) == {
        LightDisposition.AUDIT_SAMPLE,
        LightDisposition.NOT_ESCALATED,
    }


def promotion_payload(tmp_path):
    artifact = tmp_path / "evidence.json"
    artifact.write_text("{}\n", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return {
        "epoch": {
            "epoch_id": "o4b-causal-h1-v1",
            "run": "O4B",
            "detector": "H1",
            "cutoff_gps": 2000.0,
            "threshold": 0.2,
            "threshold_artifact_sha256": "b" * 64,
            "native_index_sha256": REPRESENTATION.native_index_sha256,
            "causal": True,
        },
        "promotion_evidence": {
            "detector": "H1",
            "run": "O4B",
            "calibration_start_gps": 1000.0,
            "calibration_end_gps": 2000.0,
            "evaluation_start_gps": 3000.0,
            "evaluation_end_gps": 4000.0,
            "gates": {gate: "PASS" for gate in REQUIRED_GATES},
            "artifacts": [{"path": artifact.name, "sha256": digest}],
        },
    }


def test_epoch_promotion_requires_temporal_separation_hashes_and_all_gates(tmp_path) -> None:
    payload = promotion_payload(tmp_path)
    epoch = verified_epoch_from_promotion(
        payload, representation=REPRESENTATION, root=tmp_path
    )
    assert epoch.causal is True

    overlapping = promotion_payload(tmp_path)
    overlapping["promotion_evidence"]["evaluation_start_gps"] = 1999.0
    with pytest.raises(ContractError, match="overlap"):
        verified_epoch_from_promotion(
            overlapping, representation=REPRESENTATION, root=tmp_path
        )

    failed = promotion_payload(tmp_path)
    failed["promotion_evidence"]["gates"]["injection_replay"] = "FAIL"
    with pytest.raises(ContractError, match="not PASS"):
        verified_epoch_from_promotion(
            failed, representation=REPRESENTATION, root=tmp_path
        )

    tampered = promotion_payload(tmp_path)
    (tmp_path / "evidence.json").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ContractError, match="SHA256 mismatch"):
        verified_epoch_from_promotion(
            tampered, representation=REPRESENTATION, root=tmp_path
        )


def test_drift_monitor_freezes_on_shift_or_insufficient_evidence() -> None:
    contract = DriftContract(
        detector="H1",
        reference_median=0.10,
        reference_mad=0.01,
        median_shift_limit_mad=5.0,
        tail_threshold=0.20,
        tail_rate_limit=0.05,
        minimum_block_size=64,
    )
    insufficient = evaluate_score_block(np.full(20, 0.10), contract)
    assert insufficient.state is DriftState.INSUFFICIENT
    assert insufficient.freeze_adaptation is True

    stable = evaluate_score_block(np.linspace(0.08, 0.12, 128), contract)
    assert stable.state is DriftState.OK
    assert stable.freeze_adaptation is False

    shifted = evaluate_score_block(np.full(128, 0.25), contract)
    assert shifted.state is DriftState.ALERT
    assert shifted.freeze_adaptation is True

    contaminated = np.full(128, 0.10)
    contaminated[:10] = 0.30
    tail_alert = evaluate_score_block(contaminated, contract)
    assert tail_alert.state is DriftState.ALERT
