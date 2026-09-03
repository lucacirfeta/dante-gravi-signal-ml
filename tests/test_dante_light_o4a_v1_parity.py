from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o4a_v1_parity import build_parity_freeze, validate_parity_freeze


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/dante_light_o4a_v1_parity_contract.json"
HEADER = ROOT / "config/dante_light_o4a_v1_parity_manifest.json"


def _stored() -> tuple[dict, dict, list[dict], list[dict]]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    header = json.loads(HEADER.read_text(encoding="utf-8"))
    entries = [json.loads(line) for line in (ROOT / header["entries_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    missing = [json.loads(line) for line in (ROOT / header["missing_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    return contract, header, entries, missing


def test_frozen_o4a_v1_parity_corpus_is_current_and_complete() -> None:
    stored = _stored()
    validate_parity_freeze(*stored, root=ROOT)
    assert stored == build_parity_freeze(ROOT)
    contract, header, entries, missing = stored
    assert header["counts"]["entries"] == 10_429
    assert header["counts"]["covered_by_raw_mirror"] == 10_260
    assert header["counts"]["missing_from_raw_mirror"] == 169
    assert header["counts"]["recoverable_by_verified_local_stitch"] == 162
    assert header["counts"]["requires_gwosc_fetch"] == 7
    assert header["counts"]["missing_by_detector_and_class"] == {
        "H1/AMBIGUOUS": 18, "H1/ROBUST": 60,
        "L1/AMBIGUOUS": 43, "L1/ROBUST": 48,
    }
    assert contract["scientific_boundary"]["establishes_full_o4a_discovery_sensitivity"] is False
    assert len(entries) == 10_429 and len(missing) == 169


def test_historical_routing_semantics_are_not_conflated_with_dsd_class() -> None:
    _, header, entries, _ = _stored()
    assert header["counts"]["light_disposition"] == {"ESCALATE": 6984, "ROUTINE": 3445}
    assert header["counts"]["escalated_by_class"] == {"AMBIGUOUS": 619, "ROBUST": 6365}
    assert all(row["expected"]["light_disposition"] == "ROUTINE" for row in entries if row["expected"]["offline_class"] == "BACKGROUND")


def test_parity_validation_fails_closed_on_entry_tampering() -> None:
    contract, header, entries, missing = _stored()
    entries[0]["expected"]["published_native_score"] += 1e-3
    with pytest.raises(ContractError, match="differs"):
        validate_parity_freeze(contract, header, entries, missing, root=ROOT)
