from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v4 import extract_prefilter_v4_features
from src.dante_light.prefilter_v4 import PrefilterFeaturesV4
from src.dante_light.prefilter_v4_development import build_development_ledger
from src.dante_light.prefilter_v4_protocol import (
    PHASE_FEATURES,
    PrefilterProtocolV4,
    repository_reference,
    load_protocol,
)
from src.dante_light.prefilter_v4_screening import _sklearn_seed, screen_prefilter_v4
from src.dante_light.preprocessing import PreparedPrefilterFeatures


ROOT = Path(__file__).resolve().parents[1]


def _feature_config() -> dict:
    phase = json.loads(
        (ROOT / "config/dante_light_prefilter_v4_feasibility.json").read_text(encoding="utf-8")
    )["phase_probe"]
    excluded = {
        "benchmark_repetitions",
        "warmup_repetitions",
        "synthetic_control_repetitions",
        "synthetic_seed",
        "synthetic_chirp",
    }
    return {
        "features": list(PHASE_FEATURES),
        "sample_rate_hz": 4096,
        "analysis_duration_s": 32.0,
        "analysis_band_hz": [20.0, 1024.0],
        "phase_parameters": {key: value for key, value in phase.items() if key not in excluded},
    }


def test_v4_production_extractor_is_deterministic_and_schema_exact():
    config = _feature_config()
    sample_rate = config["sample_rate_hz"]
    time = np.arange(32 * sample_rate, dtype=np.float64) / sample_rate
    values = np.sin(2.0 * np.pi * (30.0 * time + 2.0 * time**2))
    first = extract_prefilter_v4_features(values, config=config)
    second = extract_prefilter_v4_features(values, config=config)
    assert tuple(first.values) == PHASE_FEATURES
    assert first == second
    assert np.all(np.isfinite(list(first.values.values())))
    with pytest.raises(ContractError, match="32 s"):
        extract_prefilter_v4_features(values[:sample_rate], config=config)


def test_v4_sklearn_seed_mapping_preserves_frozen_low_32_bits():
    seed = (7 << 32) + 12345
    assert _sklearn_seed(seed) == 12345


def _row(role: str, detector: str, morphology: str, index: int, positive: bool) -> dict:
    gps = 1_360_000_000.0 + index * 4096.0 + (0.0 if detector == "H1" else 1024.0)
    window = WindowIdentity(run="O4A", detector=detector, gps_start=gps).to_dict()
    base = 4.0 if positive else -4.0
    values = {name: base + feature_index * 0.01 for feature_index, name in enumerate(PHASE_FEATURES)}
    return {
        "schema_version": 4,
        "window": window,
        "roles": [role],
        "partition": "development",
        "detector": detector,
        "morphology": morphology,
        "retention_target": positive,
        "cohort_id": f"{role}-{detector}-{morphology}-{index}",
        "source_id": f"source-{role}-{detector}-{morphology}-{index}",
        "manifest_digest": "m" * 64,
        "feature_contract_sha256": "f" * 64,
        "strain_sha256": "s" * 64,
        "features": {"values": values},
        "timings": {"feature_extraction_s": 0.001},
        "preparation_metadata": {},
    }


def _protocol() -> PrefilterProtocolV4:
    payload = {
        "required_detectors": ["H1", "L1"],
        "required_morphologies_by_role": {
            "known_glitch": ["Blip", "KoiFish", "ScatteredLight"],
            "injection": ["BBH_30_30", "BBH_10_10", "NSBH_10_1.4"],
        },
        "cohort_contract": {
            "counts_per_detector_stratum": {
                "background": {"development": 300},
                "robust_candidate": {"development": 25},
                "known_glitch": {"development": 25},
                "injection": {"development": 35},
            }
        },
        "feature_extraction": _feature_config(),
        "development": {
            "cross_validation_folds": 5,
            "cross_validation_method": "shuffled_group_k_fold_detector_4096s_block",
            "gps_block_duration_s": 4096,
            "model": "l2_logistic_regression",
            "regularization_c": 1.0,
            "maximum_iterations": 2000,
            "class_weighting": "equal_background_and_positive_strata",
            "minimum_effective_reduction": 0.5,
            "final_calibration_method": "full_development_model_threshold_on_full_development",
            "wilson_confidence": 0.95,
            "minimum_group_n_by_role": {
                "robust_candidate": 25,
                "known_glitch": 25,
                "injection": 35,
            },
            "minimum_retention_by_role": {
                "robust_candidate": 0.9,
                "known_glitch": 0.9,
                "injection": 0.9,
            },
            "minimum_wilson_lower_by_role": {
                "robust_candidate": 0.8,
                "known_glitch": 0.8,
                "injection": 0.8,
            },
        },
        "audit": {"fraction": 0.05, "seed": 1729},
        "uncertainty": {
            "n_resamples": 20,
            "confidence": 0.95,
            "seed": 2718,
        },
        "scientific_boundary": {
            "nsbh_injection_limitation": "point-particle only",
            "does_not_establish": ["physical NSBH sensitivity"],
        },
    }
    return PrefilterProtocolV4(
        payload=payload,
        path=ROOT / "config/dante_light_prefilter_protocol_v4.json",
    )


def _write_ledger(tmp_path: Path, role: str, rows: list[dict], protocol: PrefilterProtocolV4) -> Path:
    feature_hash = canonical_json_sha256(protocol.payload["feature_extraction"])
    for row in rows:
        row["feature_contract_sha256"] = feature_hash
    rows_path = tmp_path / f"{role}_features_v4_development.jsonl"
    rows_path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    import hashlib

    ledger = {
        "schema_version": 4,
        "status": "complete",
        "scientific_mode": "v4_frozen_development_only_feature_extraction",
        "role": role,
        "selection_partitions": ["development"],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
        "outcome_fields_used_for_feature_extraction": [],
        "protocol": repository_reference(ROOT, protocol.path),
        "manifest_digest": "m" * 64,
        "feature_contract_sha256": feature_hash,
        "row_count": len(rows),
        "expected_full_row_count": len(rows),
        "rows_path": rows_path.name,
        "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
        "selection_limit": None,
    }
    ledger["ledger_digest"] = canonical_json_sha256(ledger)
    path = tmp_path / f"{role}_feature_ledger_v4_development.json"
    path.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_v4_screening_uses_only_primary_and_keeps_confirmation_sealed(tmp_path):
    protocol = _protocol()
    rows_by_role: dict[str, list[dict]] = {role: [] for role in (
        "background", "robust_candidate", "known_glitch", "injection"
    )}
    serial = 0
    for detector in ("H1", "L1"):
        for _ in range(300):
            rows_by_role["background"].append(_row("background", detector, "clean_background", serial, False)); serial += 1
        for _ in range(25):
            rows_by_role["robust_candidate"].append(_row("robust_candidate", detector, "unknown", serial, True)); serial += 1
        for morphology in ("Blip", "KoiFish", "ScatteredLight"):
            for _ in range(25):
                rows_by_role["known_glitch"].append(_row("known_glitch", detector, morphology, serial, True)); serial += 1
        for morphology in ("BBH_30_30", "BBH_10_10", "NSBH_10_1.4"):
            for _ in range(35):
                rows_by_role["injection"].append(_row("injection", detector, morphology, serial, True)); serial += 1
    ledgers = {
        role: _write_ledger(tmp_path, role, rows, protocol)
        for role, rows in rows_by_role.items()
    }
    result = screen_prefilter_v4(ledgers=ledgers, protocol=protocol)
    assert result["status"] == "READY_FOR_CONFIRMATION"
    assert result["screening"]["primary_feature_set"] == "phase_primary"
    assert result["screening"]["feature_subset_selection_allowed"] is False
    assert result["confirmation_values_used"] == []
    assert result["o4b_outcomes_used"] == []
    assert result["routing_enabled"] is False
    assert result["next_stage"].startswith("await_explicit_authorization")


def test_v4_concurrent_ledger_preserves_successes_and_retries_same_identities(tmp_path):
    protocol = load_protocol(ROOT / "config/dante_light_prefilter_protocol_v4.json")
    split = ROOT / "config/dante_light_prefilter_splits_v4.json"
    calls = 0

    def flaky(task):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic transient")
        return PreparedPrefilterFeatures(
            features=PrefilterFeaturesV4({name: 0.1 for name in PHASE_FEATURES}),
            strain_sha256="a" * 64,
            timings={"feature_extraction_s": 0.001},
        )

    with pytest.raises(ContractError, match="1 unresolved rows"):
        build_development_ledger(
            root=ROOT,
            split_path=split,
            protocol=protocol,
            role="background",
            output_dir=tmp_path,
            prepare=flaky,
            workers=2,
            limit=2,
        )
    partial = tmp_path / "background_features_v4_development.partial.jsonl"
    assert len(partial.read_text(encoding="utf-8").splitlines()) == 1
    assert (tmp_path / "background_failures_v4_development.json").is_file()

    def stable(task):
        return PreparedPrefilterFeatures(
            features=PrefilterFeaturesV4({name: 0.2 for name in PHASE_FEATURES}),
            strain_sha256="b" * 64,
            timings={"feature_extraction_s": 0.001},
        )

    ledger = build_development_ledger(
        root=ROOT,
        split_path=split,
        protocol=protocol,
        role="background",
        output_dir=tmp_path,
        prepare=stable,
        workers=2,
        limit=2,
    )
    assert ledger["row_count"] == 2
    assert ledger["status"] == "smoke_only"
    assert not partial.exists()
    assert not (tmp_path / "background_failures_v4_development.json").exists()
