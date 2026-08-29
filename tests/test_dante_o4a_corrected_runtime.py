from __future__ import annotations

import copy
import hashlib
import json
import platform
import subprocess

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_runtime import (
    OUTPUT_REL,
    ROOT,
    load_canonical_runtime_contract,
    validate_canonical_runtime_contract,
)
from src.dante_light.prefilter_v5_protocol import repository_reference


def test_corrected_runtime_contract_is_self_consistent_and_wsl_frozen() -> None:
    contract = load_canonical_runtime_contract(root=ROOT)
    assert contract["status"] == "FROZEN_CANONICAL_WSL_CUDA_RUNTIME"
    assert contract["runtime_environment"]["operating_system"]["wsl"] is True
    assert contract["runtime_environment"]["cuda_device"]["request"] == "cuda"
    assert contract["scientific_boundary"]["score_tolerance_changed"] is False
    assert contract["scientific_boundary"]["cross_environment_shard_reuse_allowed"] is False


def test_corrected_runtime_contract_fails_closed_on_environment_change() -> None:
    contract = load_canonical_runtime_contract(root=ROOT)
    changed = copy.deepcopy(contract)
    changed["runtime_environment"]["packages"]["torch"] = "different"
    body = dict(changed)
    body.pop("contract_digest")
    changed["contract_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="environment digest mismatch"):
        validate_canonical_runtime_contract(changed, root=ROOT)


def test_corrected_runtime_rejects_noncanonical_current_host() -> None:
    is_wsl = platform.system() == "Linux" and "microsoft" in platform.release().lower()
    if is_wsl:
        load_canonical_runtime_contract(root=ROOT, require_current=True, device="cuda")
    else:
        with pytest.raises(ContractError, match="STOP_ENVIRONMENT_MISMATCH"):
            load_canonical_runtime_contract(root=ROOT, require_current=True, device="cuda")


def test_corrected_protocol_hash_inputs_are_lf_portable() -> None:
    for relative in (
        "config.yaml",
        "config/reference_artifacts.json",
        OUTPUT_REL,
    ):
        attribute = subprocess.check_output(
            ["git", "check-attr", "eol", "--", relative], cwd=ROOT, text=True
        ).strip()
        assert attribute.endswith(": eol: lf")
        reference = repository_reference(ROOT, ROOT / relative)
        tracked = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{relative}"],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        expected = (
            hashlib.sha256(
                subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT)
            ).hexdigest()
            if tracked
            else hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        )
        assert reference["sha256"] == expected


def test_saved_runtime_contract_json_matches_loader() -> None:
    path = ROOT / OUTPUT_REL
    assert json.loads(path.read_text(encoding="utf-8")) == load_canonical_runtime_contract(
        root=ROOT
    )
