"""Scaled synthetic evidence; no historical data or scientific score replay."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from src.dante_light import contracts, o3a_initial_calibration as calibration
from src.dante_light import o3a_initial_calibration_acceptance as acceptance
from src.dante_light import o3a_initial_thresholds as thresholds
from src.dante_light import o3a_raw_acquisition as acquisition
from src.dante_light import o3a_raw_download as raw
from src.dante_light import (
    o3a_native_contract,
    o3a_population_geometry,
    o3a_scale_adequacy,
)
from src.dante_workflow import o3a_initial_verification as verifier

ROOT = Path(__file__).resolve().parents[1]


def seal(body, name="artifact_digest"):
    body = {key: value for key, value in body.items() if key != name}
    return {**body, name: contracts.canonical_json_sha256(body)}


def write_json(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, sort_keys=True, allow_nan=False), encoding="utf-8")


def load(path):
    return json.loads(path.read_bytes())


def snapshot(directory):
    return {
        str(p.relative_to(directory)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in directory.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    root, raw_root, external = tmp_path / "repo", tmp_path / "raw", tmp_path / "cache"
    for module in (
        contracts,
        calibration,
        thresholds,
        acceptance,
        acquisition,
        raw,
        o3a_native_contract,
        o3a_population_geometry,
        o3a_scale_adequacy,
    ):
        destination = root / (module.__name__.replace(".", "/") + ".py")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(module.__file__, destination)
    entry = root / raw.ENTRYPOINT_REL
    entry.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / raw.ENTRYPOINT_REL, entry)
    frames, records, metadata = [], [], []
    for detector in ("H1", "L1"):
        item = {
            "detector": detector,
            "filename": f"{detector}.hdf5",
            "target_relative_path": f"{detector}/{detector}.hdf5",
            "gps_start": 1000,
            "gps_end": 1001,
            "duration_s": 1,
            "url": f"https://example.invalid/{detector}.hdf5",
        }
        path = raw_root / item["target_relative_path"]
        path.parent.mkdir(parents=True)
        with h5py.File(path, "w") as handle:
            values = handle.create_dataset(
                "strain/Strain", shape=(acquisition.SAMPLE_RATE_HZ,), dtype="f8"
            )
            values.attrs["Xspacing"] = 1 / acquisition.SAMPLE_RATE_HZ
        size = path.stat().st_size
        records.append(
            {
                **raw._record_base(item),
                **raw.validate_hdf5_metadata(path, item),
                "size_bytes": size,
                "sha256": raw.file_sha256(path),
            }
        )
        frames.append(item)
        metadata.append(
            {
                "detector": detector,
                "filename": item["filename"],
                "content_length_bytes": size,
            }
        )
    plan = seal(
        {
            "detectors": ["H1", "L1"],
            "detector_plans": {
                d: {"source_frames": [f for f in frames if f["detector"] == d]}
                for d in ("H1", "L1")
            },
        },
        "acquisition_digest",
    )
    write_json(root / raw.ACQUISITION_REL, plan)
    key = raw._run_key(plan, root)
    raw_dir = raw_root / "runs" / f"raw_download_{key}"
    preflight = seal(
        {
            "status": "PASS_O3A_RAW_DOWNLOAD_PREFLIGHT",
            "run_key": key,
            "acquisition_digest": plan["acquisition_digest"],
            "acquisition_file_sha256": raw.file_sha256(root / raw.ACQUISITION_REL),
            "implementation_sources": raw._source_hashes(root),
            "raw_root": str(raw_root),
            "expected_file_count": len(frames),
            "source_metadata": metadata,
            "expected_download_bytes": sum(
                row["content_length_bytes"] for row in metadata
            ),
        },
        "preflight_digest",
    )
    write_json(raw_dir / "preflight.json", preflight)
    raw_ledger = raw_dir / "verified_files.jsonl"
    raw_ledger.write_bytes(verifier._jsonl_bytes(records))
    manifest = raw_root / "manifests" / f"o3a_raw_{key}.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(verifier._jsonl_bytes(raw.build_raw_manifest_rows(records)))
    raw_summary = seal(
        {
            "schema_version": raw.SCHEMA_VERSION,
            "status": "PASS_VERIFIED_RAW_DOWNLOAD",
            "run_key": key,
            "acquisition_digest": plan["acquisition_digest"],
            "preflight_digest": preflight["preflight_digest"],
            "expected_file_count": len(frames),
            "verified_file_count": len(records),
            "failure_count": 0,
            "failures": [],
            "verified_ledger": {
                "path": str(raw_ledger),
                "sha256": raw.file_sha256(raw_ledger),
            },
            "raw_manifest": {
                "path": str(manifest),
                "sha256": raw.file_sha256(manifest),
            },
            "strain_values_inspected": False,
            "scoring_executed": False,
        }
    )
    write_json(raw_dir / "summary.json", raw_summary)
    contract = seal(
        {
            "method_parity": {"sample_rate_hz": acquisition.SAMPLE_RATE_HZ},
            "verified_raw_input": {
                "download_run_key": key,
                "download_summary_path": str(raw_dir / "summary.json"),
                "download_summary_sha256": raw.file_sha256(raw_dir / "summary.json"),
                "download_artifact_digest": raw_summary["artifact_digest"],
                "manifest_relative_to_raw_root": str(
                    manifest.relative_to(raw_root)
                ).replace("\\", "/"),
                "manifest_sha256": raw.file_sha256(manifest),
                "verified_file_count": len(frames),
            },
            "parents": {"canonical_runtime": {"environment_digest": "a" * 64}},
            "execution": {"fixture": True},
            "population": {
                "candidate_rows_per_block": 17,
                "bootstrap_rows_per_detector": 17,
                "point_estimate_rows_per_detector": 19,
                "point_only_tail_rows_per_detector": 2,
                "provisional_block_count": 4,
            },
        },
        "contract_digest",
    )
    write_json(root / acceptance.CONTRACT_REL, contract)
    acceptance_key = acceptance._run_key(contract)
    acceptance_dir = external / f"initial_calibration_acceptance_{acceptance_key}"
    selected = {
        d: [
            {
                "stratum_index": i,
                "first_gps_start": 1000 + i * 1088,
                "candidate_rank_in_stratum": 0,
                "selection_priority_sha256": "b" * 64,
                "output_row_count": 17 if i == 0 else 2,
            }
            for i in range(2)
        ]
        for d in ("H1", "L1")
    }
    calibration_plan = seal(
        {
            "detectors": ["H1", "L1"],
            "selection": {"window_stride_s": 64},
            "detector_plans": {d: {"selected_blocks": selected[d]} for d in selected},
        },
        "plan_digest",
    )
    write_json(root / acceptance.CALIBRATION_PLAN_REL, calibration_plan)
    accepted_rows = []
    for detector, blocks in selected.items():
        for block in blocks:
            identity = acceptance._block_identity(detector, block, 64)
            rows = [
                {
                    "detector": detector,
                    "analysis_gps_start": gps,
                    "context_interval_gps": [gps - 4, gps + 36],
                    "raw_sources": [],
                    "image_sha256": "c" * 64,
                    "primary_score": float(index - 3),
                    "primary_score_float32_hex": np.float32(index - 3).tobytes().hex(),
                }
                for index, gps in enumerate(identity["analysis_gps_starts"])
            ]
            shard = seal(
                {
                    "schema_version": 1,
                    "status": "PASS_BLOCK_ATOMIC_ACCEPTANCE",
                    "run_key": acceptance_key,
                    "block_identity": identity,
                    "rows": rows,
                    "failures": [],
                    "score_value_or_class_used_for_acceptance": False,
                    "threshold_fitted": False,
                },
                "shard_digest",
            )
            write_json(
                acceptance_dir
                / "shards"
                / f"{detector}_stratum_{block['stratum_index']:03d}.json",
                shard,
            )
            for index, row in enumerate(rows[: block["output_row_count"]]):
                accepted_rows.append(
                    {
                        **row,
                        "stratum_index": block["stratum_index"],
                        "block_selection_priority_sha256": identity[
                            "selection_priority_sha256"
                        ],
                        "bootstrap_eligible": block["stratum_index"] == 0,
                        "point_only_tail": block["stratum_index"] == 1 and index < 2,
                    }
                )
    accepted_ledger = acceptance_dir / "initial_calibration_accepted.jsonl"
    accepted_ledger.write_bytes(verifier._jsonl_bytes(accepted_rows))
    accepted_summary = seal(
        {
            "schema_version": acceptance.SCHEMA_VERSION,
            "status": "PASS_VERIFIED_O3A_INITIAL_CALIBRATION_ACCEPTANCE",
            "run_key": acceptance_key,
            "contract_digest": contract["contract_digest"],
            "raw_manifest_sha256": raw.file_sha256(manifest),
            "total_blocks": 4,
            "passed_blocks": 4,
            "failed_block_count": 0,
            "accepted_point_rows_by_detector": {"H1": 19, "L1": 19},
            "accepted_bootstrap_rows_by_detector": {"H1": 17, "L1": 17},
            "accepted_ledger": {
                "path": str(accepted_ledger),
                "sha256": raw.file_sha256(accepted_ledger),
            },
            "threshold_fitted": False,
            "classification_executed": False,
            "candidate_outcomes_reviewed": False,
            "score_value_or_class_used_for_acceptance": False,
        }
    )
    write_json(acceptance_dir / "summary.json", accepted_summary)
    threshold_contract = seal(
        {
            "parents": {
                "acceptance_run": {
                    "summary_path": str(acceptance_dir / "summary.json"),
                    "summary_sha256": raw.file_sha256(acceptance_dir / "summary.json"),
                    "artifact_digest": accepted_summary["artifact_digest"],
                    "run_key": acceptance_key,
                    "ledger_path": str(accepted_ledger),
                    "ledger_sha256": raw.file_sha256(accepted_ledger),
                }
            }
        },
        "contract_digest",
    )
    write_json(root / thresholds.CONTRACT_REL, threshold_contract)
    # Only validated-contract loaders are replaced for scaled fixture geometry.
    # File equality, hashes, seals, identities and actual legacy checks are real.
    monkeypatch.setattr(
        acceptance,
        "load_acceptance_contract",
        lambda *, root: load(root / acceptance.CONTRACT_REL),
    )
    monkeypatch.setattr(
        raw, "load_acquisition_plan", lambda *, root: load(root / raw.ACQUISITION_REL)
    )
    monkeypatch.setattr(
        acceptance,
        "load_initial_calibration_plan",
        lambda *, root: load(root / acceptance.CALIBRATION_PLAN_REL),
    )
    monkeypatch.setattr(
        thresholds,
        "load_threshold_contract",
        lambda *, root: load(root / thresholds.CONTRACT_REL),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("productive/network/writer hook called")

    for module in (acceptance, raw, thresholds):
        for name in (
            "_atomic_json",
            "_atomic_jsonl",
            "execute_acceptance",
            "execute_download",
            "_build_scorer",
            "write_preflight",
            "_default_head",
            "run_initial_thresholds",
        ):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(raw.requests.sessions.Session, "request", forbidden)
    return SimpleNamespace(
        root=root,
        raw_root=raw_root,
        external=external,
        tmp=tmp_path,
        raw_dir=raw_dir,
        acceptance_dir=acceptance_dir,
        raw_ledger=raw_ledger,
        manifest=manifest,
        accepted_ledger=accepted_ledger,
    )


def invoke(evidence, stage):
    arguments = {"root": evidence.root, "raw_root": evidence.raw_root}
    if stage == "acceptance":
        return verifier.verify_acceptance_evidence(
            **arguments, external_root=evidence.external
        )
    return verifier.verify_raw_evidence(**arguments)


@pytest.mark.parametrize("stage", ["raw", "acceptance"])
def test_scoped_receipt_preserves_all_input_bytes_and_mtimes(evidence, stage):
    before = snapshot(evidence.tmp)
    value = invoke(evidence, stage)
    assert snapshot(evidence.tmp) == before
    assert value["verification_level"] == (
        "INTEGRITY" if stage == "raw" else "RECONSTRUCTION"
    )
    assert value == seal(value, "receipt_digest")
    for field in (
        "historical_evidence_mutated",
        "raw_score_replay_executed",
        "encoder_executed",
        "threshold_fit_executed",
        "source_fetch_executed",
        "full_workflow_verified",
    ):
        assert value[field] is False
    assert len(value["executed_sources"]) == 11
    if stage == "raw":
        assert value["verified_file_count"] == 2
        assert value["stored_score_values_read"] is False
    else:
        assert value["counts_by_detector"] == {"H1": 19, "L1": 19}
        assert value["bootstrap_rows_by_detector"] == {"H1": 17, "L1": 17}
        assert value["parent_raw_file_bytes_replayed"] is False


@pytest.mark.parametrize("stage", ["raw", "acceptance"])
@pytest.mark.parametrize(
    "name",
    ["failure.json", "failures.json", "controller.lock", "run.lock", "unfinished.tmp"],
)
def test_failure_lock_partial_rejected_without_writes(evidence, stage, name):
    directory = evidence.raw_dir if stage == "raw" else evidence.acceptance_dir
    (directory / name).write_text("preserve", encoding="utf-8")
    before = snapshot(evidence.tmp)
    with pytest.raises(verifier.InitialEvidenceError):
        invoke(evidence, stage)
    assert snapshot(evidence.tmp) == before


@pytest.mark.parametrize("target", ["raw_ledger", "manifest", "accepted_ledger"])
def test_changed_evidence_fails_closed(evidence, target):
    getattr(evidence, target).write_bytes(b"altered")
    before = snapshot(evidence.tmp)
    with pytest.raises(verifier.InitialEvidenceError, match="hash mismatch"):
        invoke(evidence, "acceptance")
    assert snapshot(evidence.tmp) == before


@pytest.mark.parametrize("change", ["bytes", "missing", "partial"])
def test_raw_file_integrity_is_not_just_manifest_integrity(evidence, change):
    path = evidence.raw_root / "H1/H1.hdf5"
    if change == "bytes":
        with h5py.File(path, "r+") as handle:
            handle["strain/Strain"][0] = 123
    elif change == "missing":
        path.unlink()
    else:
        path.with_suffix(".hdf5.part").write_bytes(b"unfinished")
    before = snapshot(evidence.tmp)
    with pytest.raises(verifier.InitialEvidenceError):
        invoke(evidence, "raw")
    assert snapshot(evidence.tmp) == before


@pytest.mark.parametrize(
    "change",
    [
        "seal",
        "identity",
        "nonfinite",
        "encoding",
        "boundary",
        "missing",
        "extra",
        "rows",
    ],
)
def test_shard_validation_and_population_are_required(evidence, change):
    path = evidence.acceptance_dir / "shards/H1_stratum_000.json"
    value = load(path)
    if change == "seal":
        value["shard_digest"] = "a" * 64
    elif change == "identity":
        value["block_identity"]["detector"] = "L1"
    elif change == "nonfinite":
        path.write_text(
            path.read_text().replace('"primary_score": -3.0', '"primary_score": NaN')
        )
    elif change == "encoding":
        value["rows"][0]["primary_score_float32_hex"] = "0" * 8
    elif change == "boundary":
        value["threshold_fitted"] = True
    elif change == "missing":
        path.unlink()
    elif change == "extra":
        write_json(path.with_name("extra.json"), value)
    elif change == "rows":
        value["rows"][0]["image_sha256"] = "e" * 64
    if change not in {"nonfinite", "missing", "extra"}:
        write_json(path, value if change == "seal" else seal(value, "shard_digest"))
    before = snapshot(evidence.tmp)
    with pytest.raises((verifier.InitialEvidenceError, contracts.ContractError)):
        invoke(evidence, "acceptance")
    assert snapshot(evidence.tmp) == before


def test_raw_score_rerun_is_not_claimed_by_acceptance(evidence):
    # Acceptance reconstructs stored evidence only, even if local raw bytes are unavailable.
    (evidence.raw_root / "H1/H1.hdf5").unlink()
    value = invoke(evidence, "acceptance")
    assert value["parent_raw_file_bytes_replayed"] is False
    assert value["raw_score_replay_executed"] is False
    with pytest.raises(verifier.InitialEvidenceError):
        invoke(evidence, "raw")


@pytest.mark.parametrize(
    "module", [raw, o3a_native_contract, o3a_population_geometry, o3a_scale_adequacy]
)
def test_changed_helper_source_rejected_before_checks(evidence, module):
    relative = module.__name__.replace(".", "/") + ".py"
    (evidence.root / relative).write_text("changed")
    with pytest.raises(
        verifier.InitialEvidenceError, match="executed helper source mismatch"
    ):
        invoke(evidence, "raw")


@pytest.mark.parametrize(
    "reference", ["../outside", "H1\\frame.hdf5", "C:/frame.hdf5", "/frame.hdf5", ""]
)
def test_unsafe_relative_paths_fail(evidence, reference):
    with pytest.raises(verifier.InitialEvidenceError):
        verifier._existing(evidence.raw_root, reference)


def test_symlink_escape_rejected(evidence):
    target = evidence.tmp / "outside"
    target.write_bytes(b"data")
    try:
        (evidence.raw_root / "escape").symlink_to(target)
    except OSError:
        pytest.skip("symlink creation requires platform privilege")
    with pytest.raises(verifier.InitialEvidenceError, match="escaping"):
        verifier._existing(evidence.raw_root, "escape")


@pytest.mark.parametrize("payload", [b'{"a":1,"a":2}', b'{"a":NaN}', b"[]"])
def test_strict_json_rejects_ambiguous_evidence(payload):
    with pytest.raises(verifier.InitialEvidenceError):
        verifier._json(payload)


def test_receipt_detects_mid_check_evidence_change(evidence, monkeypatch):
    original = verifier._receipt

    def altered(*args, **kwargs):
        evidence.manifest.write_bytes(b"changed during verification")
        return original(*args, **kwargs)

    monkeypatch.setattr(verifier, "_receipt", altered)
    with pytest.raises(verifier.InitialEvidenceError, match="changed during"):
        invoke(evidence, "raw")


def cli_module(monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location(
        "o3a_initial_evidence_cli",
        ROOT / "scripts/verify_dante_o3a_initial_evidence.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("stage", ["raw", "acceptance"])
def test_cli_wired_to_real_scoped_functions(evidence, stage, capsys, monkeypatch):
    module = cli_module(monkeypatch)
    arguments = [
        "--stage",
        stage,
        "--repository-root",
        str(evidence.root),
        "--raw-root",
        str(evidence.raw_root),
    ]
    if stage == "acceptance":
        arguments += ["--external-root", str(evidence.external)]
    before = snapshot(evidence.tmp)
    assert module.main(arguments) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["status"].endswith("_ONLY")
    assert snapshot(evidence.tmp) == before


def test_cli_failure_returns_nonzero_and_no_historical_failure_file(
    evidence, capsys, monkeypatch
):
    module = cli_module(monkeypatch)
    evidence.manifest.unlink()
    before = snapshot(evidence.tmp)
    assert (
        module.main(
            [
                "--stage",
                "raw",
                "--repository-root",
                str(evidence.root),
                "--raw-root",
                str(evidence.raw_root),
            ]
        )
        == 1
    )
    assert (
        json.loads(capsys.readouterr().out)["status"]
        == "FAIL_CLOSED_O3A_INITIAL_EVIDENCE"
    )
    assert snapshot(evidence.tmp) == before


@pytest.mark.parametrize(
    "args",
    [
        ["--stage", "acceptance", "--raw-root", "unused"],
        ["--stage", "raw", "--raw-root", "unused", "--external-root", "unused"],
    ],
)
def test_cli_rejects_inapplicable_arguments(args):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts/verify_dante_o3a_initial_evidence.py"),
            *args,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert (
        "requires --external-root" in result.stderr
        or "does not accept --external-root" in result.stderr
    )


def test_real_legacy_contract_loaders_still_bind_unchanged_sources():
    # Real local contracts/sources only, no historical data or numeric outcome reads.
    value = acceptance.load_acceptance_contract(root=ROOT)
    parent = thresholds.load_threshold_contract(root=ROOT)
    assert (
        parent["parents"]["acceptance_contract"]["contract_digest"]
        == value["contract_digest"]
    )
    assert (
        raw.load_acquisition_plan(root=ROOT)["acquisition_digest"]
        == value["parents"]["raw_acquisition_plan"]["acquisition_digest"]
    )


def repin_synthetic_raw_summary(evidence, summary):
    """Fixture-only repinning to reach semantic checks, never production repair."""
    summary = seal(summary)
    path = evidence.raw_dir / "summary.json"
    write_json(path, summary)
    contract_path = evidence.root / acceptance.CONTRACT_REL
    contract = load(contract_path)
    parent = contract["verified_raw_input"]
    parent["download_summary_sha256"] = raw.file_sha256(path)
    parent["download_artifact_digest"] = summary["artifact_digest"]
    write_json(contract_path, seal(contract, "contract_digest"))


@pytest.mark.parametrize(
    "change", ["seal", "status", "source", "count", "duplicate", "size", "root"]
)
def test_preflight_semantics_required_even_with_resealed_fixture(evidence, change):
    path = evidence.raw_dir / "preflight.json"
    value = load(path)
    if change == "status":
        value["status"] = "FAILED"
    elif change == "source":
        value["implementation_sources"][raw.IMPLEMENTATION_REL] = "a" * 64
    elif change == "count":
        value["expected_file_count"] += 1
    elif change == "duplicate":
        value["source_metadata"].append(value["source_metadata"][0])
    elif change == "size":
        value["expected_download_bytes"] += 1
    elif change == "root":
        value["raw_root"] = str(evidence.external)
    value = seal(value, "preflight_digest")
    if change == "seal":
        value["preflight_digest"] = "0" * 64
    write_json(path, value)
    summary = load(evidence.raw_dir / "summary.json")
    summary["preflight_digest"] = value["preflight_digest"]
    repin_synthetic_raw_summary(evidence, summary)
    before = snapshot(evidence.tmp)
    with pytest.raises(verifier.InitialEvidenceError):
        invoke(evidence, "raw")
    assert snapshot(evidence.tmp) == before


@pytest.mark.parametrize("change", ["reordered", "duplicate", "metadata", "manifest"])
def test_exact_raw_population_not_only_its_declared_hash(evidence, change):
    summary = load(evidence.raw_dir / "summary.json")
    if change == "manifest":
        rows = [
            json.loads(line) for line in evidence.manifest.read_bytes().splitlines()
        ]
        rows.reverse()
        evidence.manifest.write_bytes(verifier._jsonl_bytes(rows))
        summary["raw_manifest"]["sha256"] = raw.file_sha256(evidence.manifest)
        contract_path = evidence.root / acceptance.CONTRACT_REL
        contract = load(contract_path)
        contract["verified_raw_input"]["manifest_sha256"] = summary["raw_manifest"][
            "sha256"
        ]
        write_json(contract_path, seal(contract, "contract_digest"))
    else:
        rows = [
            json.loads(line) for line in evidence.raw_ledger.read_bytes().splitlines()
        ]
        if change == "reordered":
            rows.reverse()
        elif change == "duplicate":
            rows[1] = rows[0]
        else:
            rows[0]["sample_count"] += 1
        evidence.raw_ledger.write_bytes(verifier._jsonl_bytes(rows))
        summary["verified_ledger"]["sha256"] = raw.file_sha256(evidence.raw_ledger)
    repin_synthetic_raw_summary(evidence, summary)
    before = snapshot(evidence.tmp)
    with pytest.raises(verifier.InitialEvidenceError):
        invoke(evidence, "raw")
    assert snapshot(evidence.tmp) == before


def test_duplicate_calibration_identity_rejected(evidence):
    path = evidence.root / acceptance.CALIBRATION_PLAN_REL
    plan = load(path)
    blocks = plan["detector_plans"]["H1"]["selected_blocks"]
    blocks[1] = blocks[0]
    write_json(path, seal(plan, "plan_digest"))
    with pytest.raises(
        verifier.InitialEvidenceError, match="duplicate acceptance block"
    ):
        invoke(evidence, "acceptance")


def test_sealed_reference_translation_never_rebases_to_another_root():
    assert verifier._reference("E:/frozen/evidence") == verifier._reference(
        "/mnt/e/frozen/evidence"
    )
    assert verifier._reference("E:/frozen/evidence") != verifier._reference(
        "E:/replacement/evidence"
    )
    with pytest.raises(verifier.InitialEvidenceError, match="absolute"):
        verifier._reference("relative/evidence")
