from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_identity import (
    ARTIFACT_STATUS,
    build_identity_artifact,
    compact_raw_manifest,
    coverage_by_block,
    hash_raw_files,
    load_identity_config,
    load_quarantine_record,
    parse_raw_file,
    prior_o4a_blocks,
    sha256_stream,
    validate_identity_artifact,
    validate_identity_config,
    validate_hdf5_metadata,
    validate_raw_rows,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/dante_light_prefilter_v5_identity_audit.json"
ARTIFACT_PATH = ROOT / "artifacts/dante_light/prefilter_l4_v5_design/identity_audit_v5.json"
MANIFEST_PATH = ROOT / "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl"


def test_config_is_strictly_identity_only_and_v3_alias_is_exact() -> None:
    config = load_identity_config(CONFIG_PATH)
    prior_blocks, sources = prior_o4a_blocks(ROOT, config)
    assert prior_blocks
    assert [source["protocol_version"] for source in sources] == ["v1", "v2", "v4"]
    assert config["protocol_aliases"]["v3"]["reuses_split_protocol_version"] == "v2"
    quarantine = load_quarantine_record(ROOT, config["known_raw_quarantine_reference"])
    assert len(quarantine["files"]) == 10
    assert quarantine["recoverable"] is True
    assert all(
        config["scientific_boundary"][key] is False
        for key in (
            "may_assign_v5_partitions",
            "may_freeze_v5",
            "may_read_confirmation_outcomes",
            "may_read_development_outcomes",
            "may_read_feature_values",
            "may_read_o4b",
            "may_read_strain_arrays",
            "may_read_teacher_scores",
        )
    )


def test_config_rejects_protected_access() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["scientific_boundary"]["may_read_teacher_scores"] = True
    body = dict(config)
    body.pop("config_digest")
    config["config_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="protected or promotable"):
        validate_identity_config(config)


def test_raw_hash_cache_and_duplicate_contract(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    first = raw_root / "H1_4096_8192.hdf5"
    second_dir = raw_root / "copy"
    second_dir.mkdir()
    second = second_dir / first.name
    first.write_bytes(b"identical")
    second.write_bytes(b"identical")
    identities = [parse_raw_file(raw_root, first), parse_raw_file(raw_root, second)]
    cache_path = tmp_path / "cache" / "hashes.json"
    rows = hash_raw_files(raw_root, identities, cache_path=cache_path, checkpoint_every=1)
    validate_raw_rows(rows, detectors=("H1", "L1"))
    compact = compact_raw_manifest(rows)
    assert len(compact) == 1
    assert compact[0]["copy_count"] == 2
    assert compact[0]["sha256"] == sha256_stream(first)

    original_stat = second.stat()
    second.write_bytes(b"different")
    os.utime(second, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    identities = [parse_raw_file(raw_root, first), parse_raw_file(raw_root, second)]
    rows = hash_raw_files(raw_root, identities, cache_path=cache_path, checkpoint_every=1)
    with pytest.raises(ContractError, match="conflicting duplicate"):
        validate_raw_rows(rows, detectors=("H1", "L1"))


def test_coverage_merges_overlapping_unaligned_files() -> None:
    rows = [
        {"detector": "H1", "gps_start": 1000, "gps_end": 5096},
        {"detector": "H1", "gps_start": 4096, "gps_end": 8192},
        {"detector": "L1", "gps_start": 0, "gps_end": 2304},
    ]
    coverage = coverage_by_block(rows, block_duration_s=4096)
    assert coverage == {"H1:0": 3096, "H1:1": 4096, "L1:0": 2304}


def test_hdf5_metadata_validation_does_not_require_strain_reads(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    numpy = pytest.importorskip("numpy")
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    path = raw_root / "H1_0_1.hdf5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("Strain", data=numpy.zeros(4, dtype=numpy.float64))
    row = {
        "duration_s": 1,
        "physical_copies": [{"relative_path": path.name}],
    }
    validate_hdf5_metadata(raw_root, [row], sample_rate_hz=4)

    with h5py.File(path, "w") as handle:
        handle.create_dataset("Strain", data=numpy.zeros(3, dtype=numpy.float64))
    with pytest.raises(ContractError, match="Strain shape"):
        validate_hdf5_metadata(raw_root, [row], sample_rate_hz=4)


def test_committed_identity_artifact_is_structurally_recomputable() -> None:
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    validate_identity_artifact(artifact, root=ROOT, manifest_path=MANIFEST_PATH)
    assert artifact["status"] == ARTIFACT_STATUS
    assert artifact["scientific_boundary"]["eligible_for_v5_freeze"] is False
    assert artifact["scientific_boundary"]["teacher_scores_used"] == []
    assert artifact["scientific_boundary"]["confirmation_outcomes_used"] == []
    assert artifact["scientific_boundary"]["o4b_used"] == []
    assert artifact["capacity"]["fresh_fully_covered_block_count"] > 0
    assert artifact["raw_mirror"]["all_physical_files_content_hashed"] is True
    assert artifact["raw_mirror"]["all_files_rehashed_in_artifact_generation_run"] is True
    assert artifact["raw_mirror"]["all_duplicate_spans_byte_identical"] is True
    assert artifact["raw_mirror"]["all_unique_spans_hdf5_metadata_valid"] is True
    assert artifact["raw_mirror"]["hdf5_validation_read_strain_values"] is False
