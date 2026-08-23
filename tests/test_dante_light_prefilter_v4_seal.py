from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from src.dante_light.contracts import ContractError, WindowIdentity
from src.dante_light.prefilter_v4_seal import (
    EMPTY_ACCESS_LOG_SHA256,
    append_access_record,
    build_confirmation_seal,
    build_identity_manifest,
    build_unlock_receipt,
    claim_confirmation_open_once,
    require_partition_authorized,
    validate_identity_manifest,
    verify_unopened_seal,
)


SHA = "a" * 64


def _row(*, cohort_id: str, gps: float, partition: str, role: str = "robust_candidate"):
    window = WindowIdentity(run="O4A", detector="H1", gps_start=gps).to_dict()
    if role == "robust_candidate":
        morphology = "DANTE_ROBUST"
        stratum = {"robustness_class": "ROBUST"}
    elif role == "background":
        morphology = "clean_background"
        stratum = {}
    else:
        raise AssertionError(role)
    return {
        "schema_version": 1,
        "cohort_id": cohort_id,
        "role": role,
        "detector": "H1",
        "morphology": morphology,
        "partition": partition,
        "partition_priority": hashlib.sha256(cohort_id.encode()).hexdigest(),
        "retention_target": role != "background",
        "source": {"kind": "frozen_test", "run": "O4A", "source_id": cohort_id},
        "stratum": stratum,
        "window": window,
    }


def _manifest():
    return build_identity_manifest(
        [
            _row(cohort_id="dev", gps=1_000_000_000.0, partition="development"),
            _row(cohort_id="confirm", gps=1_000_010_000.0, partition="confirmation"),
        ],
        protocol_reference={"path": "config/v4.json", "sha256": SHA},
        source_references=[{"path": "data/source.json", "sha256": SHA}],
        selection_code_reference={"path": "src/builder.py", "sha256": SHA},
        seed_derivation={
            "method": "sha256_canonical_json_first_64_bits_big_endian",
            "protocol_id": "v4-test",
            "purposes": ["cohort"],
            "parent_digests": [SHA],
        },
        prior_block_keys=[],
    )


def _seal(manifest):
    return build_confirmation_seal(
        manifest,
        freeze_commit="b" * 40,
        code_references={
            "split_builder": {"path": "src/builder.py", "sha256": SHA},
            "phase_extractor": {"path": "src/phase.py", "sha256": SHA},
            "seal_verifier": {"path": "scripts/verify.py", "sha256": SHA},
        },
        declared_storage_roots=[
            {
                "root_id": "repo",
                "kind": "repository_relative",
                "location": "artifacts/dante_light",
            },
            {
                "root_id": "external",
                "kind": "environment_alias",
                "location": "DANTE_L4_CACHE_ROOT",
            },
        ],
    )


def test_identity_manifest_and_unopened_seal_are_hash_bound():
    manifest = _manifest()
    seal = _seal(manifest)
    validate_identity_manifest(manifest)
    verify_unopened_seal(manifest, seal, access_log_bytes=b"")
    assert seal["initial_access_log_sha256"] == EMPTY_ACCESS_LOG_SHA256
    assert seal["claim_boundary"] == "declared_storage_and_access_ledger_only"


def test_identity_manifest_rejects_outcome_fields_and_prior_blocks():
    row = _row(cohort_id="bad", gps=1_000_000_000.0, partition="development")
    row["phase_score"] = 0.9
    with pytest.raises(ContractError, match="outcome-bearing"):
        build_identity_manifest(
            [row],
            protocol_reference={"path": "config/v4.json", "sha256": SHA},
            source_references=[],
            selection_code_reference={"path": "src/builder.py", "sha256": SHA},
            seed_derivation={
                "method": "sha256_canonical_json_first_64_bits_big_endian",
                "protocol_id": "v4-test",
                "purposes": ["cohort"],
                "parent_digests": [SHA],
            },
            prior_block_keys=[],
        )
    clean = _row(cohort_id="prior", gps=1_000_000_000.0, partition="development")
    block = f"H1:{int(1_000_000_000 // 4096)}"
    with pytest.raises(ContractError, match="overlaps a prior"):
        build_identity_manifest(
            [clean],
            protocol_reference={"path": "config/v4.json", "sha256": SHA},
            source_references=[],
            selection_code_reference={"path": "src/builder.py", "sha256": SHA},
            seed_derivation={
                "method": "sha256_canonical_json_first_64_bits_big_endian",
                "protocol_id": "v4-test",
                "purposes": ["cohort"],
                "parent_digests": [SHA],
            },
            prior_block_keys=[block],
        )


def test_development_confirmation_block_overlap_fails_closed():
    with pytest.raises(ContractError, match="share a detector/GPS block"):
        build_identity_manifest(
            [
                _row(cohort_id="dev", gps=1_000_000_000.0, partition="development"),
                _row(cohort_id="confirm", gps=1_000_000_032.0, partition="confirmation"),
            ],
            protocol_reference={"path": "config/v4.json", "sha256": SHA},
            source_references=[],
            selection_code_reference={"path": "src/builder.py", "sha256": SHA},
            seed_derivation={
                "method": "sha256_canonical_json_first_64_bits_big_endian",
                "protocol_id": "v4-test",
                "purposes": ["cohort"],
                "parent_digests": [SHA],
            },
            prior_block_keys=[],
        )


def test_unopened_seal_rejects_access_or_outcome_records():
    manifest = _manifest()
    seal = _seal(manifest)
    with pytest.raises(ContractError, match="access log"):
        verify_unopened_seal(manifest, seal, access_log_bytes=b"opened\n")
    with pytest.raises(ContractError, match="already exist"):
        verify_unopened_seal(
            manifest,
            seal,
            access_log_bytes=b"",
            observed_outcome_records=[{"cohort_id": "confirm", "score": 0.2}],
        )


def test_confirmation_requires_ready_hash_bound_receipt():
    manifest = _manifest()
    seal = _seal(manifest)
    development = {
        "status": "READY_FOR_CONFIRMATION",
        "protocol_sha256": SHA,
        "manifest_digest": manifest["manifest_digest"],
        "phase_extractor_sha256": SHA,
        "model_digest": "c" * 64,
        "threshold_digest": "d" * 64,
        "verifier_digest": "e" * 64,
    }
    receipt = build_unlock_receipt(manifest, seal, development, access_log_bytes=b"")
    require_partition_authorized("development")
    require_partition_authorized("confirmation", seal=seal, unlock_receipt=receipt)
    with pytest.raises(ContractError, match="requires"):
        require_partition_authorized("confirmation")
    with pytest.raises(ContractError, match="cannot authorize O4b"):
        require_partition_authorized("o4b")
    bad = deepcopy(development)
    bad["status"] = "V4_NOT_READY"
    with pytest.raises(ContractError, match="did not authorize"):
        build_unlock_receipt(manifest, seal, bad, access_log_bytes=b"")


def test_access_log_is_append_only_and_hash_chained(tmp_path):
    path = tmp_path / "confirmation_access.jsonl"
    first = append_access_record(path, {"action": "UNLOCK", "seal_digest": "f" * 64})
    second = append_access_record(path, {"action": "EXTRACT", "cohort_id": "confirm"})
    assert first["sequence"] == 0
    assert second["sequence"] == 1
    assert second["previous_digest"] == first["record_digest"]
    tampered = path.read_text(encoding="utf-8").replace("UNLOCK", "DELETE")
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(ContractError, match="digest mismatch"):
        append_access_record(path, {"action": "RETRY"})


def test_confirmation_open_claim_is_one_shot(tmp_path):
    manifest = _manifest()
    seal = _seal(manifest)
    development = {
        "status": "READY_FOR_CONFIRMATION",
        "protocol_sha256": SHA,
        "manifest_digest": manifest["manifest_digest"],
        "phase_extractor_sha256": SHA,
        "model_digest": "c" * 64,
        "threshold_digest": "d" * 64,
        "verifier_digest": "e" * 64,
    }
    receipt = build_unlock_receipt(manifest, seal, development, access_log_bytes=b"")
    path = tmp_path / "access.jsonl"
    claim_confirmation_open_once(path, seal=seal, unlock_receipt=receipt)
    with pytest.raises(ContractError, match="already opened"):
        claim_confirmation_open_once(path, seal=seal, unlock_receipt=receipt)
