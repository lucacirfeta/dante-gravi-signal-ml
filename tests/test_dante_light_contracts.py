from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from src.dante_light.contracts import (
    CalibrationEpochContract,
    ContractError,
    FailClosedReason,
    LightDisposition,
    LightRecord,
    PreflightState,
    RepresentationContract,
    WindowIdentity,
    evaluate_preflight,
)


ROOT = Path(__file__).resolve().parents[1]


def representation() -> RepresentationContract:
    return RepresentationContract.from_reference_manifest(
        ROOT / "config" / "reference_artifacts.json"
    )


def test_window_identity_is_stable_and_detector_aware() -> None:
    first = WindowIdentity("o4a", "l1", 1382955232.0)
    same = WindowIdentity.from_dict(first.to_dict())
    other_detector = WindowIdentity("O4A", "H1", 1382955232.0)
    assert first == same
    assert first.window_id == same.window_id
    assert first.window_id != other_detector.window_id
    assert first.run == "O4A"
    assert first.detector == "L1"


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"run": "", "detector": "L1", "gps_start": 1.0}, "run"),
        ({"run": "O4A", "detector": "LIGO", "gps_start": 1.0}, "detector"),
        ({"run": "O4A", "detector": "L1", "gps_start": math.nan}, "gps_start"),
        (
            {"run": "O4A", "detector": "L1", "gps_start": 1.0, "duration_s": 0},
            "duration_s",
        ),
    ],
)
def test_window_identity_rejects_invalid_values(kwargs, match) -> None:
    with pytest.raises(ContractError, match=match):
        WindowIdentity(**kwargs)


def test_representation_contract_matches_frozen_g0_artifacts() -> None:
    value = representation()
    assert value.variant == "idxq4-64_queryq4-64"
    assert value.sample_rate_hz == 4096
    assert value.analysis_duration_s == 32.0
    assert value.whitening_pad_s == 4.0
    assert value.query_qrange == (4, 64)
    assert value.frequency_range_hz == (20, 2048)
    assert value.image_shape == (256, 256, 3)
    assert value.colormap == "cividis"
    assert value.encoder_input_size == (518, 518)
    assert value.top_k == 68
    assert value.model_revision == "7b187bd4df8efce2cbcbbb67bd01532c19bf4c9c"
    assert value.primary_index_sha256 == (
        "9053477ed2f30ed866fc42ff32265957e6a0eb93238032359f5e45e2f032bb7c"
    )
    assert value.native_index_sha256 == (
        "0241b2a1ea2a460334f2c7ae0ab1bb62052706ea05c48443af32ae60a2488744"
    )
    assert value.to_dict()["contract_sha256"] == value.contract_sha256


def test_representation_rejects_noncanonical_pixels_and_digest() -> None:
    value = representation().to_dict(include_digest=False)
    value["image_shape"] = [224, 224, 3]
    with pytest.raises(ContractError, match="256x256x3"):
        RepresentationContract(**value)

    value = representation().to_dict(include_digest=False)
    value["native_index_sha256"] = "unknown"
    with pytest.raises(ContractError, match="SHA256"):
        RepresentationContract(**value)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (PreflightState(False, True, True, True), FailClosedReason.MISSING_CAT1),
        (PreflightState(True, False, True, True), FailClosedReason.INCOMPLETE_DATA),
        (PreflightState(True, True, False, True), FailClosedReason.STALE_INDEX),
        (
            PreflightState(True, True, True, False),
            FailClosedReason.UNKNOWN_REPRESENTATION,
        ),
        (
            PreflightState(True, True, True, True, False),
            FailClosedReason.DEPENDENCY_UNAVAILABLE,
        ),
    ],
)
def test_preflight_failure_always_becomes_scoreless_defer(state, reason) -> None:
    window = WindowIdentity("O4A", "L1", 1382955232.0)
    contract = representation()
    observed = evaluate_preflight(state)
    assert observed is reason
    record = LightRecord.deferred(window, contract, observed)
    assert record.disposition is LightDisposition.DEFER
    assert record.defer_reason is reason
    assert record.to_dict()["scores"] == {}


def test_preflight_pass_has_no_reason() -> None:
    assert evaluate_preflight(PreflightState(True, True, True, True)) is None


def test_defer_cannot_carry_score_and_other_dispositions_cannot_carry_reason() -> None:
    window = WindowIdentity("O4A", "L1", 1382955232.0)
    contract = representation()
    with pytest.raises(ContractError, match="must not contain scores"):
        LightRecord(
            window=window,
            representation_sha256=contract.contract_sha256,
            disposition=LightDisposition.DEFER,
            scores=(("native", 0.2),),
            defer_reason=FailClosedReason.MISSING_CAT1,
        )
    with pytest.raises(ContractError, match="non-DEFER"):
        LightRecord(
            window=window,
            representation_sha256=contract.contract_sha256,
            disposition=LightDisposition.ESCALATE,
            defer_reason=FailClosedReason.MISSING_CAT1,
        )


def test_epoch_fails_closed_for_noncausal_and_lookahead_use() -> None:
    contract = representation()
    window = WindowIdentity("O4A", "L1", 1382955232.0)
    historical = CalibrationEpochContract(
        epoch_id="o4a-final-bgv3",
        run="O4A",
        detector="L1",
        cutoff_gps=1389456018.0,
        threshold=0.21959366053342733,
        threshold_artifact_sha256="a" * 64,
        native_index_sha256=contract.native_index_sha256,
        causal=False,
    )
    assert historical.incompatibility(window, contract, prospective=False) is None
    assert historical.incompatibility(window, contract, prospective=True) is (
        FailClosedReason.NON_CAUSAL_EPOCH
    )

    causal = CalibrationEpochContract(
        epoch_id="o4a-past-only-test",
        run="O4A",
        detector="L1",
        cutoff_gps=1383000000.0,
        threshold=0.2,
        threshold_artifact_sha256="b" * 64,
        native_index_sha256=contract.native_index_sha256,
        causal=True,
    )
    assert causal.incompatibility(window, contract, prospective=True) is (
        FailClosedReason.CALIBRATION_LOOKAHEAD
    )
    future = WindowIdentity("O4A", "L1", 1383001000.0)
    assert causal.incompatibility(future, contract, prospective=True) is None


def test_light_vocabulary_excludes_offline_taxonomy() -> None:
    assert {item.value for item in LightDisposition}.isdisjoint(
        {"ROBUST", "AMBIGUOUS", "BACKGROUND"}
    )


def test_light_is_disabled_and_exact_by_default() -> None:
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    light = config["dante_light"]
    assert light["enabled"] is False
    assert light["engine"] == "canonical"
    assert light["prefilter"] == "none"
    assert light["fail_closed"] is True
    assert light["release_requires_public_reference_bundle"] is True
