from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o4a_corrected_native_coincidence import (
    ROOT,
    _anchor_check,
    _context_plan,
    load_native_coincidence_contract,
    measure_physical_arrays,
    primary_null_threshold,
    split_seed_populations,
    validate_native_coincidence_contract,
)


def _row(detector: str, gps: float, native_class: str) -> dict:
    return {
        "detector": detector,
        "gps_start": gps,
        "native_class": native_class,
        "native_score": 0.5,
        "identity_digest": f"identity-{detector}-{gps}",
        "image_sha256": "a" * 64,
    }


def _population_rows() -> list[dict]:
    rows = []
    gps = 1_000_000.0
    counts = {
        "H1": {"ROBUST": 2090, "AMBIGUOUS": 672, "BACKGROUND": 1958},
        "L1": {"ROBUST": 3316, "AMBIGUOUS": 1672, "BACKGROUND": 1234},
    }
    for detector, by_class in counts.items():
        for native_class, count in by_class.items():
            for _ in range(count):
                rows.append(_row(detector, gps, native_class))
                gps += 4.0
    return rows


def test_frozen_contract_validates() -> None:
    contract = load_native_coincidence_contract(ROOT)
    assert contract["population"]["primary_seed_class"] == "ROBUST"
    assert contract["population"]["partner_class_read"] is False
    assert contract["scientific_boundary"]["symmetric_robust_and_required"] is False


def test_contract_rejects_symmetric_robust_and() -> None:
    path = ROOT / "config/dante_o4a_corrected_native_coincidence_v1.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    contract["scientific_boundary"]["symmetric_robust_and_required"] = True
    with pytest.raises(ContractError, match="digest mismatch"):
        validate_native_coincidence_contract(contract, root=ROOT)


def test_seed_population_is_exact_and_partner_independent() -> None:
    contract = load_native_coincidence_contract(ROOT)
    primary, diagnostic = split_seed_populations(_population_rows(), contract=contract)
    assert len(primary) == 5406
    assert len(diagnostic) == 2344
    assert {row["native_class"] for row in primary} == {"ROBUST"}
    assert {row["native_class"] for row in diagnostic} == {"AMBIGUOUS"}
    assert all("partner_class" not in row for row in [*primary, *diagnostic])


def test_seed_population_rejects_changed_count() -> None:
    contract = load_native_coincidence_contract(ROOT)
    with pytest.raises(ContractError, match="count changed"):
        split_seed_populations(_population_rows()[:-1], contract=contract)


def test_primary_threshold_ignores_diagnostic_population() -> None:
    contract = load_native_coincidence_contract(ROOT)
    primary = [
        {"measurement_status": "MEASURED", "cc_null_max": float(value)}
        for value in range(1, 101)
    ]
    threshold = primary_null_threshold(primary, measurement=contract["measurement"])
    diagnostic = [
        {"measurement_status": "MEASURED", "cc_null_max": 1_000_000.0}
    ]
    assert threshold == pytest.approx(99.01)
    assert primary_null_threshold(primary, measurement=contract["measurement"]) == threshold
    assert diagnostic[0]["cc_null_max"] > threshold


def test_physical_measurement_recovers_identical_strain() -> None:
    contract = load_native_coincidence_contract(ROOT)
    rng = np.random.default_rng(42)
    clean = rng.normal(size=32 * 4096)
    top_k = np.concatenate(
        [18 * 37 + np.arange(37), 19 * 37 + np.arange(31)]
    ).astype(np.int32)
    result = measure_physical_arrays(
        clean,
        clean.copy(),
        top_k,
        top_k.copy(),
        measurement=contract["measurement"],
    )
    assert result["cc_onsource"] > 0.999
    assert result["patch_iou"] == 1.0
    assert result["n_null"] == 8
    assert result["per_event_null_exceeded"] is True


def test_physical_measurement_uses_primary_localization_only() -> None:
    contract = load_native_coincidence_contract(ROOT)
    rng = np.random.default_rng(7)
    candidate = rng.normal(size=32 * 4096)
    partner = candidate.copy()
    candidate_top_k = np.concatenate(
        [18 * 37 + np.arange(37), 19 * 37 + np.arange(31)]
    ).astype(np.int32)
    unrelated_partner_top_k = np.arange(68, dtype=np.int32)
    result = measure_physical_arrays(
        candidate,
        partner,
        candidate_top_k,
        unrelated_partner_top_k,
        measurement=contract["measurement"],
    )
    assert result["cc_onsource"] > 0.999
    assert result["patch_iou"] == 0.0


def test_context_plan_stitches_and_partner_can_be_unavailable(tmp_path: Path) -> None:
    first = (tmp_path / "a.hdf5").resolve()
    second = (tmp_path / "b.hdf5").resolve()
    first.touch()
    second.touch()

    class Manifest:
        entries = (
            (96.0, 120.0, first),
            (120.0, 160.0, second),
        )
        expected_sha256 = {first: "a" * 64, second: "b" * 64}

    stitched = _context_plan(Manifest(), detector="H1", gps=100.0, pad_s=4.0)
    assert [row["used_interval"] for row in stitched] == [
        [96.0, 120.0],
        [120.0, 136.0],
    ]
    assert _context_plan(Manifest(), detector="L1", gps=200.0, pad_s=4.0) == []


def test_historical_anchor_uses_analysis_window_not_feature_peak() -> None:
    rows = [_row("L1", 1382955232.0, "ROBUST")]
    result = _anchor_check(rows)
    assert result["catalog_gps"] == 1382955228.0
    assert result["analysis_window_gps"] == 1382955232.0
    assert result["localized_feature_gps"] == 1382955253.17
    assert result["included_in_primary_seed_population"] is True
