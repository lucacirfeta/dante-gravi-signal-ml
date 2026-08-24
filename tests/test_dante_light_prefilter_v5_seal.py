from __future__ import annotations

import hashlib

import pytest

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v5_seal import (
    build_confirmation_seal, build_identity_manifest, build_unlock_receipt,
    validate_identity_manifest, verify_unopened_seal,
)


HEX = "a" * 64


def _reference(name: str) -> dict[str, str]:
    return {"path": name, "sha256": HEX}


def _row(partition: str, gps: float) -> dict:
    window = WindowIdentity("O4A", "H1", gps, 32.0)
    return {
        "schema_version": 1, "cohort_id": f"v5-{partition}-{gps}", "role": "background",
        "detector": "H1", "morphology": "o4a_shadow_traffic", "partition": partition,
        "partition_priority": HEX, "retention_target": False,
        "source": {"kind": "raw", "run": "O4A", "source_id": f"raw-{gps}"},
        "stratum": {"block_index": int(gps // 4096), "window_index": 0}, "window": window.to_dict(),
    }


def _manifest() -> dict:
    return build_identity_manifest(
        [_row("training", 4096.0), _row("development", 8192.0), _row("confirmation", 12288.0)],
        protocol_reference=_reference("config/protocol.json"), source_references=[_reference("config/source.json")],
        selection_code_reference=_reference("src/split.py"), seed_derivation={"method": "sha256", "seeds": {}}, prior_block_keys=[],
    )


def _seal(manifest: dict) -> dict:
    code = {name: _reference(f"src/{name}.py") for name in ("split_builder", "protocol_validator", "seal_verifier", "preprocessing", "exact_dante_runner")}
    return build_confirmation_seal(
        manifest, freeze_commit="b" * 40, code_references=code,
        declared_storage_roots=[{"root_id": "repo", "kind": "repository_relative", "location": "."}],
        protected_endpoints=["protected_stratum_retention", "teacher_fidelity", "background_routing_decisions", "paired_prefilter_costs", "paired_avoidable_exact_path_costs", "block_bootstrap_net_saving"],
    )


def test_confirmation_seal_covers_cost_benefit_and_is_unopened() -> None:
    manifest = _manifest(); seal = _seal(manifest)
    validate_identity_manifest(manifest); verify_unopened_seal(manifest, seal, access_log_bytes=b"")
    assert seal["access_entries_at_freeze"] == 0
    assert "block_bootstrap_net_saving" in seal["protected_endpoints"]


def test_confirmation_seal_rejects_nonempty_access_ledger() -> None:
    manifest = _manifest(); seal = _seal(manifest)
    with pytest.raises(ContractError, match="not empty"):
        verify_unopened_seal(manifest, seal, access_log_bytes=b"opened\n")


def test_unlock_receipt_binds_teacher_and_cost_contracts() -> None:
    manifest = _manifest(); seal = _seal(manifest)
    development = {
        "status": "READY_FOR_CONFIRMATION", "protocol_sha256": seal["protocol_reference"]["sha256"],
        "manifest_digest": seal["manifest_digest"], "model_digest": HEX, "threshold_digest": HEX,
        "teacher_contract_digest": HEX, "paired_cost_contract_digest": HEX,
        "replicate_selection_digest": HEX, "verifier_digest": HEX,
    }
    receipt = build_unlock_receipt(manifest, seal, development, access_log_bytes=b"")
    assert receipt["receipt_digest"] == canonical_json_sha256({key: value for key, value in receipt.items() if key != "receipt_digest"})
