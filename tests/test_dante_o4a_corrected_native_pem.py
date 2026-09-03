from __future__ import annotations

import json

import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o4a_corrected_native_pem import (
    ROOT,
    load_native_pem_contract,
    select_pem_targets,
    validate_native_pem_contract,
)
from src.pipeline_v2_production import pem_null_calibration


def _coincidence_row(population: str, detector: str, gps: float) -> dict:
    native_class = "ROBUST" if population == "primary" else "AMBIGUOUS"
    return {
        "population": population,
        "detector": detector,
        "gps_start": gps,
        "measurement_status": "MEASURED",
        "seed_native_class": native_class,
        "seed_native_score": 0.5,
        "seed_identity_digest": f"identity-{detector}-{gps}",
        "seed_image_sha256": "a" * 64,
        "seed_raw_context_sha256": "b" * 64,
        "seed_context_sources": [],
        "cc_onsource": 0.25,
        "exceeds_primary_threshold": True,
    }


def _population() -> tuple[list[dict], list[dict]]:
    primary = [
        *[_coincidence_row("primary", "H1", 1_000_000 + i * 32) for i in range(3)],
        *[_coincidence_row("primary", "L1", 2_000_000 + i * 32) for i in range(6)],
    ]
    diagnostic = [
        *[_coincidence_row("diagnostic", "H1", 3_000_000 + i * 32) for i in range(31)],
        *[_coincidence_row("diagnostic", "L1", 4_000_000 + i * 32) for i in range(25)],
    ]
    return primary, diagnostic


def test_frozen_native_pem_contract_validates() -> None:
    contract = load_native_pem_contract(ROOT)
    assert contract["population"]["exact_total"] == 65
    assert contract["scientific_boundary"]["shortlist_is_globally_significant"] is False
    assert contract["scientific_boundary"]["future_global_null_required"] is True


def test_contract_rejects_global_significance_claim() -> None:
    path = ROOT / "config/dante_o4a_corrected_native_pem_v1.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    contract["scientific_boundary"]["shortlist_is_globally_significant"] = True
    with pytest.raises(ContractError, match="digest mismatch"):
        validate_native_pem_contract(contract, root=ROOT)


def test_exact_pooled_threshold_shortlist_is_selected_and_separated() -> None:
    contract = load_native_pem_contract(ROOT)
    primary, diagnostic = _population()
    primary.append({**_coincidence_row("primary", "H1", 9_000_000), "exceeds_primary_threshold": False})
    targets = select_pem_targets(primary, diagnostic, contract=contract)
    assert len(targets) == 65
    assert sum(row["population"] == "primary" for row in targets) == 9
    assert sum(row["population"] == "diagnostic" for row in targets) == 56
    assert {row["native_class"] for row in targets if row["population"] == "primary"} == {"ROBUST"}
    assert {row["native_class"] for row in targets if row["population"] == "diagnostic"} == {"AMBIGUOUS"}


def test_shortlist_rejects_changed_exact_count() -> None:
    contract = load_native_pem_contract(ROOT)
    primary, diagnostic = _population()
    with pytest.raises(ContractError, match="diagnostic count changed"):
        select_pem_targets(primary, diagnostic[:-1], contract=contract)


def test_native_candidate_exclusion_override_avoids_legacy_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pem_null_calibration,
        "_candidate_gps",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy taxonomy read")),
    )
    monkeypatch.setattr(
        pem_null_calibration,
        "get_segments",
        lambda *_args, **_kwargs: [(0, 20_000)],
    )
    start, end, windows = pem_null_calibration._pick_background_span(
        "H1",
        30_000,
        14_400,
        "O4a",
        candidate_gps=np.asarray([], dtype=np.float64),
    )
    assert (start, end) == (0, 14_400)
    assert len(windows) >= 60


def test_checkpoint_records_exact_language_and_global_null_future_work() -> None:
    text = (ROOT / "docs/DANTE_O4A_CORRECTED_PEM_CHECKPOINT_V1.md").read_text(
        encoding="utf-8"
    )
    assert "pooled-null-threshold exceeders selected for PEM follow-up" in text
    assert "globally significant physical coincidences" in text
    assert "global null for the complete selection pipeline remains mandatory" in text


def test_banned_high_fpr_channels_are_absent() -> None:
    contract = load_native_pem_contract(ROOT)
    active = set(contract["channels"]["H1"] + contract["channels"]["L1"])
    banned = set(contract["channels"]["explicitly_excluded"])
    assert active.isdisjoint(banned)
