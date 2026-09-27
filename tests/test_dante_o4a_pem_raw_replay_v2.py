"""Regression for the single approved O4a PEM archive-URL correction."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_o4a_common_pem_contract_v2 import (
    load_contract as load_common_v2,
    validate_contract as validate_common_v2,
)
from src.dante_light.o4a_pem_raw_replay import load_contract as load_raw_v1
from src.dante_light.o4a_pem_raw_replay_v2 import (
    _run_key,
    archive_url,
    load_contract as load_raw_v2,
    validate_contract as validate_raw_v2,
)

ROOT = Path(__file__).resolve().parents[1]


def _resign(value: dict) -> dict:
    changed = deepcopy(value)
    changed.pop("contract_digest")
    value["contract_digest"] = canonical_json_sha256(changed)
    return value


def test_v2_is_url_only_and_common_parent_remains_valid() -> None:
    raw = load_raw_v2(ROOT)
    previous = load_raw_v1(ROOT)
    assert raw["historical_targets"] == previous["historical_targets"]
    assert raw["provenance_policy"] == previous["provenance_policy"]
    assert raw["output"] == previous["output"]
    assert {
        key: value
        for key, value in raw["source"].items()
        if key != "manifest_download_url_policy"
    } == previous["source"]
    assert load_common_v2(root=ROOT)["status"].endswith("NO_COMPARATIVE_RESULTS")


@pytest.mark.parametrize("detector", ["H1", "L1"])
def test_manifest_path_maps_to_official_archive_url(detector: str) -> None:
    frame = {
        "detector": detector,
        "gps_start": 1368195072,
        "relative_path": f"{detector}/1367343104/{detector[0]}-{detector}_GWOSC_O4a_4KHZ_R1-1368195072-4096.hdf5",
    }
    assert archive_url(frame, load_raw_v2(ROOT)["source"]) == (
        "https://gwosc.org/archive/data/O4a_4KHZ_R1/1367343104/"
        f"{detector[0]}-{detector}_GWOSC_O4a_4KHZ_R1-1368195072-4096.hdf5"
    )


@pytest.mark.parametrize(
    "path",
    [
        "L1/1367343104/H-H1_GWOSC_O4a_4KHZ_R1-1368195072-4096.hdf5",
        "H1/1367343104/extra/H-H1_GWOSC_O4a_4KHZ_R1-1368195072-4096.hdf5",
        "H1/1367343104/H-H1_GWOSC_O4a_4KHZ_R1-1368199168-4096.hdf5",
        "H1/not-an-epoch/H-H1_GWOSC_O4a_4KHZ_R1-1368195072-4096.hdf5",
    ],
)
def test_malformed_manifest_path_fails_closed(path: str) -> None:
    frame = {"detector": "H1", "gps_start": 1368195072, "relative_path": path}
    with pytest.raises(ContractError, match="URL|path"):
        archive_url(frame, load_raw_v2(ROOT)["source"])


def test_resigned_scientific_raw_change_is_rejected() -> None:
    contract = load_raw_v2(ROOT)
    contract["source"]["sample_rate_hz"] = 16384
    with pytest.raises(ContractError, match="more than URL mapping"):
        validate_raw_v2(_resign(contract), root=ROOT)


def test_resigned_common_scope_change_is_rejected() -> None:
    contract = load_common_v2(root=ROOT)
    contract["approved_change"]["target_manifest_and_numeric_gates_unchanged"] = False
    with pytest.raises(ContractError, match="correction scope"):
        validate_common_v2(_resign(contract), root=ROOT)


def test_v1_failed_run_key_cannot_be_reused_by_v2() -> None:
    previous = load_raw_v1(ROOT)
    current = load_raw_v2(ROOT)
    snapshot = (
        Path("E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/raw_replay")
        / "raw_replay_4b72598116a88db262762a48fd11135f00ad0ede8968f7ec0dae116e038084be"
    )
    assert previous["contract_digest"] != current["contract_digest"]
    assert _run_key(
        current, "531912260ea45cd5265198f7a1990a8a89f69ffa98abca8a21930140e332b7ba"
    ) != snapshot.name.removeprefix("raw_replay_")


def test_v2_contract_bytes_are_signed() -> None:
    for path in (
        "config/dante_o3a_o4a_pem_raw_replay_v2.json",
        "config/dante_o3a_o4a_common_pem_v2.json",
    ):
        value = json.loads((ROOT / path).read_text(encoding="utf-8"))
        digest = value.pop("contract_digest")
        assert canonical_json_sha256(value) == digest
