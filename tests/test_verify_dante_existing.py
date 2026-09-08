from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts import verify_dante_existing
from src.dante_light.contracts import ContractError


def test_wrapper_rejects_scientific_run_selector() -> None:
    with pytest.raises(ContractError, match="selector is not allowlisted"):
        verify_dante_existing._validate_verifier_argv(
            ["scripts/run_dante_o4a_native_thresholds.py", "--stage", "run"]
        )


def test_wrapper_rejects_unlisted_script() -> None:
    with pytest.raises(ContractError, match="not allowlisted"):
        verify_dante_existing._validate_verifier_argv(
            ["scripts/verify_dante_light_release.py", "--stage", "operational"]
        )


def test_wrapper_supplies_frozen_identity_only_during_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen_environment = {
        "environment_digest": "a" * 64,
        "cuda_device": {"request": "cuda"},
    }
    original_capture = verify_dante_existing.runtime_contract.capture_runtime_environment
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        verify_dante_existing.runtime_contract,
        "load_canonical_runtime_contract",
        lambda **_kwargs: {"runtime_environment": copy.deepcopy(frozen_environment)},
    )

    def fake_run_path(path: str, *, run_name: str) -> None:
        observed["path"] = Path(path).name
        observed["run_name"] = run_name
        observed["environment"] = (
            verify_dante_existing.runtime_contract.capture_runtime_environment("cuda")
        )

    monkeypatch.setattr(verify_dante_existing.runpy, "run_path", fake_run_path)
    assert (
        verify_dante_existing.run_existing_verifier(
            ["scripts/run_dante_o4a_native_thresholds.py", "--stage", "verify"]
        )
        == 0
    )
    assert observed == {
        "path": "run_dante_o4a_native_thresholds.py",
        "run_name": "__main__",
        "environment": frozen_environment,
    }
    assert (
        verify_dante_existing.runtime_contract.capture_runtime_environment
        is original_capture
    )
