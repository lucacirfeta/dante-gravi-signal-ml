"""Fail-closed input tests for the O3a-only diagnostic PEM stage."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_native_contract import ROOT
from src.dante_light.o3a_native_pem import (
    DEFAULT_EXTERNAL_ROOT,
    _check_sources,
    _sealed,
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
