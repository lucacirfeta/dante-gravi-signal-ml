"""Fail-closed v2 addendum for the O3a/O4a PEM input-only freeze."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_o4a_common_pem_contract import (
    ROOT,
    _verified,
    load_contract as load_v1_common_contract,
)
from src.dante_light.o4a_pem_raw_replay_v2 import load_contract as load_raw_v2_contract

CONTRACT_REL = Path("config/dante_o3a_o4a_common_pem_v2.json")
SOURCE_PATHS = {
    "common_v2_adapter": "src/dante_light/o3a_o4a_common_pem_contract_v2.py",
    "raw_replay_v2_adapter": "src/dante_light/o4a_pem_raw_replay_v2.py",
    "raw_replay_v2_cli": "scripts/run_dante_o4a_pem_raw_replay_v2.py",
}
APPROVED_CHANGE = {
    "scope": "GWOSC_MANIFEST_PATH_TO_PUBLIC_DOWNLOAD_URL_ONLY",
    "manifest_path_example": "H1/1367343104/H-H1_GWOSC_O4a_4KHZ_R1-1368195072-4096.hdf5",
    "download_path_example": "1367343104/H-H1_GWOSC_O4a_4KHZ_R1-1368195072-4096.hdf5",
    "target_manifest_and_numeric_gates_unchanged": True,
    "failed_v1_run_preserved": True,
}


def validate_contract(contract: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    body = dict(contract)
    digest = body.pop("contract_digest", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("common PEM v2 addendum digest changed")
    if (
        body.get("schema_version") != 2
        or body.get("contract_id") != "dante-o3a-o4a-common-pem-v2"
        or body.get("status") != "FROZEN_INPUTS_URL_CORRECTION_NO_COMPARATIVE_RESULTS"
        or body.get("approved_change") != APPROVED_CHANGE
        or set(body)
        != {
            "schema_version",
            "contract_id",
            "status",
            "parent_input_freeze",
            "raw_replay_contract",
            "source_references",
            "approved_change",
        }
    ):
        raise ContractError("common PEM v2 correction scope changed")
    parent = body["parent_input_freeze"]
    if (
        parent["path"] != "config/dante_o3a_o4a_common_pem_v1.json"
        or _verified(root, parent) != root / parent["path"]
    ):
        raise ContractError("common PEM v2 parent path changed")
    v1 = load_v1_common_contract(root=root)
    if parent["contract_digest"] != v1["contract_digest"]:
        raise ContractError("common PEM v2 parent digest changed")
    raw_ref = body["raw_replay_contract"]
    if (
        raw_ref["path"] != "config/dante_o3a_o4a_pem_raw_replay_v2.json"
        or _verified(root, raw_ref) != root / raw_ref["path"]
    ):
        raise ContractError("common PEM v2 raw replay contract path changed")
    raw = load_raw_v2_contract(root)
    if raw["historical_targets"]["sha256"] != v1["runs"]["O4a"]["targets"]["sha256"]:
        raise ContractError("common PEM v2 O4a target identity changed")
    refs = body["source_references"]
    if set(refs) != set(SOURCE_PATHS):
        raise ContractError("common PEM v2 source set changed")
    for name, path in SOURCE_PATHS.items():
        if refs[name]["path"] != path or _verified(root, refs[name]) != root / path:
            raise ContractError("common PEM v2 source path changed")
    return contract


def load_contract(*, root: Path = ROOT) -> dict[str, Any]:
    return validate_contract(
        json.loads((root / CONTRACT_REL).read_text(encoding="utf-8")), root=root
    )
