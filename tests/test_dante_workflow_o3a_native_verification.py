"""Synthetic, scaled contracts only; real SQLite/NPY and inherited validators."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from src.dante_light import contracts
from src.dante_light import o3a_native_cohort as cohort
from src.dante_light import o3a_primary_scan as scan
from src.dante_light import o3a_population_geometry as geometry
from src.dante_light import o3a_raw_acquisition as acquisition
from src.dante_light import o3a_raw_download as raw
from src.dante_workflow import o3a_native_verification as verifier

ROOT = Path(__file__).resolve().parents[1]


def seal(body, name="artifact_digest"):
    body = {k: v for k, v in body.items() if k != name}
    return {**body, name: contracts.canonical_json_sha256(body)}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def read(path):
    return json.loads(path.read_bytes())


def lines(rows):
    return b"".join((json.dumps(r, sort_keys=True) + "\n").encode() for r in rows)


def snapshot(directory):
    return {
        str(p.relative_to(directory)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in directory.rglob("*")
        if p.is_file()
    }


def forbidden(*args, **kwargs):
    raise AssertionError("writer/scorer/fetch or historical verifier invoked")


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    pytest.importorskip("fcntl", reason="existing read-only flock requires POSIX/WSL")
    root, external, primary = tmp_path / "repo", tmp_path / "cohort", tmp_path / "scan"
    for relative in verifier._sources(ROOT):
        if relative.startswith("src/dante_light/"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
    runtime = {"runtime_environment": {"environment_digest": "a" * 64}}
    write(root / scan.RUNTIME_REL, runtime)
    population = {
        "identities": [[d, gps] for d in ("H1", "L1") for gps in (1000, 1200, 2000)]
    }
    write(root / geometry.MANIFEST_REL, population)
    inventory = {
        "urls_by_detector": {
            d: [f"https://gwosc.org/test/{d[0]}-{d}_GWOSC_O3a_4KHZ_R1-900-4096.hdf5"]
            for d in ("H1", "L1")
        }
    }
    write(root / acquisition.INVENTORY_REL, inventory)
    contract = seal(
        {
            "thresholds": {"values": {"H1": 0.25, "L1": 0.25}},
            "parents": {"threshold_artifact": {"artifact_digest": "b" * 64}},
            "population": {
                "counts_by_detector": {"H1": 3, "L1": 3},
                "required_source_frames": {"total_count": 2},
                "identity_stream_sha256": "c" * 64,
            },
            "representation": {"top_k": 1},
            "storage": {"transient_raw_subdirectory": "transient_raw"},
            "execution": {"device": "cuda"},
            "ci_asymmetry_annotation": {},
            "scientific_boundary": {"synthetic_fixture_only": True},
        },
        "contract_digest",
    )
    write(root / scan.CONTRACT_REL, contract)
    env = runtime["runtime_environment"]["environment_digest"]
    key = scan._run_key(contract, environment_digest=env)
    scan_dir = primary / f"primary_scan_{key}"
    preflight = seal(
        {
            "status": "PASS_O3A_PRIMARY_SCAN_PREFLIGHT",
            "run_key": key,
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": env,
            "candidate_outcome_disclosed": False,
            "finite_score_observed": True,
            "token_shape": [1, 2, 3],
        },
        "preflight_digest",
    )
    write(scan_dir / "preflight.json", preflight)
    identity = scan._run_identity(
        contract,
        run_key=key,
        environment_digest=env,
        preflight_digest=preflight["preflight_digest"],
    )
    database = scan_dir / "primary_scan.sqlite"
    connection = scan._open_database(database, identity=identity)
    frames = {}
    for detector in ("H1", "L1"):
        frame = acquisition._inventory_frames(inventory, detector)[0]
        frame = {
            **frame,
            "detector": detector,
            "sha256": "d" * 64,
            "size_bytes": 123,
            "retained_calibration_raw": False,
        }
        scan._insert_frame(connection, frame)
        frames[(detector, frame["filename"])] = frame
        for gps, score in ((1000, -1.0), (1200, 0.25), (2000, 1.0)):
            tensors = (
                (
                    np.array([1, 0, 0], dtype=np.float32).tobytes(),
                    np.array([0], dtype=np.int32).tobytes(),
                    np.array([1, 0], dtype=np.float32).tobytes(),
                )
                if score > 0.25
                else (None, None, None)
            )
            connection.execute(
                "INSERT INTO windows VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    detector,
                    gps,
                    score,
                    np.float32(score).tobytes().hex(),
                    int(score > 0.25),
                    scan._identity_digest(detector, gps),
                    "e" * 64,
                    *tensors,
                ),
            )
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    summary = seal(
        {
            "schema_version": scan.SCHEMA_VERSION,
            "status": "PASS_COMPLETE_O3A_PRIMARY_SCAN",
            "run_key": key,
            "contract_digest": contract["contract_digest"],
            "threshold_artifact_digest": "b" * 64,
            "preflight_digest": preflight["preflight_digest"],
            "window_counts": {"H1": 3, "L1": 3},
            "window_total": 6,
            "candidate_counts": {"H1": 1, "L1": 1},
            "candidate_total": 2,
            "raw_frame_count": 2,
            "database": {
                "filename": database.name,
                "sha256": raw.file_sha256(database),
                "size_bytes": database.stat().st_size,
            },
            "invalid_or_silent_drop_count": 0,
            "ci_asymmetry_annotation": {},
            "scientific_boundary": contract["scientific_boundary"],
        }
    )
    write(scan_dir / "primary_scan_summary.json", summary)
    cohort_contract = seal(
        {
            "parents": {
                "primary_scan_compact_evidence": {
                    "artifact_digest": summary["artifact_digest"]
                }
            },
            "selection": {
                "target_rows_per_detector": 2,
                "candidate_guard_start_delta_s": 128,
                "minimum_same_detector_separation_s": 96,
            },
            "preprocessing": {
                "analysis_duration_s": 32,
                "whitening_pad_s": 4,
                "sample_rate_hz": 4096,
            },
        },
        "contract_digest",
    )
    write(root / cohort.CONTRACT_REL, cohort_contract)
    cohort_key = cohort._run_key(cohort_contract, environment_digest=env)
    cohort_dir = external / f"native_cohort_{cohort_key}"
    rows = []
    for detector in ("H1", "L1"):
        detector_frames = acquisition._inventory_frames(inventory, detector)
        for rank, gps in enumerate((1000, 1200)):
            context = cohort_dir / f"raw_context/{detector}_{gps}.npy"
            context.parent.mkdir(parents=True, exist_ok=True)
            values = np.zeros(40 * 4096, dtype=np.float64)
            np.save(context, values)
            sources = cohort._source_rows_for_context(
                detector=detector,
                gps=gps,
                frames=detector_frames,
                frame_starts=[900],
                raw_frame_rows=frames,
            )
            shard = seal(
                {
                    "detector": detector,
                    "gps_start": gps,
                    "proposal_rank": rank,
                    "priority": f"{detector}{rank}",
                    "quality_disposition": "PASS_CLEAN",
                    "raw_context": {
                        "relative_path": context.relative_to(cohort_dir).as_posix(),
                        "file_sha256": raw.file_sha256(context),
                        "values_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                    },
                    "context_sources": sources,
                    "context_sources_digest": contracts.canonical_json_sha256(sources),
                },
                "shard_digest",
            )
            write(cohort._shard_path(cohort_dir, shard), shard)
            rows.append(
                {
                    **shard,
                    "cohort_detector_index": rank,
                    "identity_digest": scan._identity_digest(detector, gps),
                }
            )
    proposals = cohort_dir / "proposals.jsonl"
    proposals.write_bytes(lines(rows))
    cohort_preflight = seal(
        {
            "status": "PASS_O3A_NATIVE_COHORT_PREFLIGHT",
            "run_key": cohort_key,
            "contract_digest": cohort_contract["contract_digest"],
            "proposal_manifest": {
                "filename": proposals.name,
                "sha256": raw.file_sha256(proposals),
                "row_digest": cohort._proposal_digest(rows),
            },
        },
        "preflight_digest",
    )
    write(cohort_dir / "preflight.json", cohort_preflight)
    ledger = cohort_dir / "native_cohort.jsonl"
    ledger.write_bytes(lines(rows))
    write(
        cohort_dir / "native_cohort_summary.json",
        seal(
            {
                "status": "PASS_FROZEN_O3A_NATIVE_COHORT",
                "run_key": cohort_key,
                "contract_digest": cohort_contract["contract_digest"],
                "preflight_digest": cohort_preflight["preflight_digest"],
                "primary_scan_artifact_digest": summary["artifact_digest"],
                "ledger": {
                    "sha256": raw.file_sha256(ledger),
                    "row_digest": contracts.canonical_json_sha256(rows),
                },
            }
        ),
    )
    calls = []

    def runtime_loader(*, root, require_current):
        assert require_current is True
        calls.append("current_runtime")
        return read(root / scan.RUNTIME_REL)

    def role_iterator(value, role):
        assert role == "primary_scan_geometric_universe"
        yield from ((d, int(gps)) for d, gps in value["identities"])

    for module in (scan, cohort):
        monkeypatch.setattr(module, "load_runtime_contract", runtime_loader)
        monkeypatch.setattr(
            module,
            "load_source_inventory",
            lambda *, root: read(root / acquisition.INVENTORY_REL),
        )
    monkeypatch.setattr(
        scan, "load_scan_contract", lambda *, root: read(root / scan.CONTRACT_REL)
    )
    monkeypatch.setattr(
        cohort, "load_cohort_contract", lambda *, root: read(root / cohort.CONTRACT_REL)
    )
    monkeypatch.setattr(
        scan,
        "load_identity_universes",
        lambda *, root: read(root / geometry.MANIFEST_REL),
    )
    monkeypatch.setattr(scan, "iter_role_identities", role_iterator)
    legacy_scan, legacy_cohort = scan.verify_primary_scan, cohort.verify_native_cohort
    for module, names in (
        (
            scan,
            (
                "_atomic_json",
                "_download_frame",
                "preflight_primary_scan",
                "run_primary_scan",
                "verify_primary_scan",
            ),
        ),
        (
            cohort,
            (
                "_atomic_json",
                "_atomic_jsonl",
                "_atomic_npy",
                "_quality_check_values",
                "preflight_native_cohort",
                "verify_primary_scan",
                "verify_native_cohort",
            ),
        ),
        (acquisition, ("_default_url_fetcher",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    for directory in (scan_dir, cohort_dir):
        (directory / "run.lock").write_bytes(b"preserved producer PID")
    return SimpleNamespace(
        root=root,
        external=external,
        primary=primary,
        scan_dir=scan_dir,
        cohort_dir=cohort_dir,
        database=database,
        rows=rows,
        calls=calls,
        legacy_scan=legacy_scan,
        legacy_cohort=legacy_cohort,
        monkeypatch=monkeypatch,
    )


def verify(f, stage="cohort"):
    return verifier.verify_native_evidence(
        root=f.root,
        external_root=f.primary if stage == "scan" else f.external,
        stage=stage,
        primary_external_root=f.primary if stage == "cohort" else None,
    )


@pytest.mark.parametrize("stage", ["scan", "cohort"])
def test_native_locks_held_through_final_binding_check(evidence, monkeypatch, stage):
    import fcntl

    original = verifier._Evidence.unchanged
    directories = [evidence.scan_dir]
    if stage == "cohort":
        directories.append(evidence.cohort_dir)
    before = snapshot(evidence.root.parent)

    def final_check(tracked):
        for directory in directories:
            with (directory / "run.lock").open("rb") as handle:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original(tracked)

    monkeypatch.setattr(verifier._Evidence, "unchanged", final_check)
    receipt = verify(evidence, stage)
    assert snapshot(evidence.root.parent) == before
    for directory in directories:
        with (directory / "run.lock").open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
    assert "scan_lock" in receipt["inputs"]
    assert ("cohort_lock" in receipt["inputs"]) is (stage == "cohort")


@pytest.mark.parametrize("which", ["scan", "cohort"])
@pytest.mark.parametrize("problem", ["missing", "busy", "symlink", "hardlink"])
def test_native_parent_lock_refusal_and_release(evidence, which, problem):
    import fcntl

    directory = evidence.scan_dir if which == "scan" else evidence.cohort_dir
    path = directory / "run.lock"
    if problem == "missing":
        path.unlink()
    elif problem == "symlink":
        target = directory / "original_lock"
        path.rename(target)
        path.symlink_to(target)
    elif problem == "hardlink":
        import os

        os.link(path, directory / "alias_lock")
    if problem == "busy":
        with path.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            reject_unchanged(evidence, match="persistent lock")
            fcntl.flock(handle, fcntl.LOCK_UN)
    else:
        reject_unchanged(evidence, match="persistent lock")
    other = evidence.cohort_dir if which == "scan" else evidence.scan_dir
    with (other / "run.lock").open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)


@pytest.mark.parametrize("which", ["scan", "cohort"])
def test_native_lock_replacement_cannot_emit_receipt(evidence, monkeypatch, which):
    original = verifier._Evidence.unchanged
    directory = evidence.scan_dir if which == "scan" else evidence.cohort_dir

    def replaced(tracked):
        original(tracked)
        replacement = directory / "replacement"
        replacement.write_bytes((directory / "run.lock").read_bytes())
        replacement.replace(directory / "run.lock")

    monkeypatch.setattr(verifier._Evidence, "unchanged", replaced)
    with pytest.raises(verifier.InitialEvidenceError, match="persistent lock changed"):
        verify(evidence)


def reledger(f, *, shards=False):
    if shards:
        for index, row in enumerate(f.rows):
            shard = seal(
                {
                    k: v
                    for k, v in row.items()
                    if k not in {"cohort_detector_index", "identity_digest"}
                },
                "shard_digest",
            )
            f.rows[index] = {**row, **shard}
            write(cohort._shard_path(f.cohort_dir, row), shard)
    ledger = f.cohort_dir / "native_cohort.jsonl"
    ledger.write_bytes(lines(f.rows))
    path = f.cohort_dir / "native_cohort_summary.json"
    value = read(path)
    value["ledger"] = {
        "sha256": raw.file_sha256(ledger),
        "row_digest": contracts.canonical_json_sha256(f.rows),
    }
    write(path, seal(value))


def select(f, field, value):
    path = f.root / cohort.CONTRACT_REL
    contract = read(path)
    contract["selection"][field] = value
    contract = seal(contract, "contract_digest")
    write(path, contract)
    env = read(f.root / scan.RUNTIME_REL)["runtime_environment"]["environment_digest"]
    key = cohort._run_key(contract, environment_digest=env)
    new_directory = f.external / f"native_cohort_{key}"
    f.cohort_dir.rename(new_directory)
    f.cohort_dir = new_directory
    path = f.cohort_dir / "preflight.json"
    preflight = read(path)
    preflight.update(run_key=key, contract_digest=contract["contract_digest"])
    preflight = seal(preflight, "preflight_digest")
    write(path, preflight)
    path = f.cohort_dir / "native_cohort_summary.json"
    summary = read(path)
    summary.update(
        run_key=key,
        contract_digest=contract["contract_digest"],
        preflight_digest=preflight["preflight_digest"],
    )
    write(path, seal(summary))


def sql(f, statement, parameters=()):
    with sqlite3.connect(f.database) as connection:
        connection.execute(statement, parameters)
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    path = f.scan_dir / "primary_scan_summary.json"
    summary = read(path)
    summary["database"]["sha256"] = raw.file_sha256(f.database)
    summary["database"]["size_bytes"] = f.database.stat().st_size
    write(path, seal(summary))


def reject_unchanged(f, *, stage="cohort", match=None):
    before = snapshot(f.root.parent)
    with pytest.raises((ValueError, RuntimeError, OSError, sqlite3.Error), match=match):
        verify(f, stage)
    assert snapshot(f.root.parent) == before


@pytest.mark.parametrize("stage", ["scan", "cohort"])
def test_scoped_receipt_and_no_mutations(evidence, stage):
    before = snapshot(evidence.root.parent)
    result = verify(evidence, stage)
    assert snapshot(evidence.root.parent) == before
    assert result["status"] == f"PASS_O3A_READ_ONLY_{stage.upper()}_RECONSTRUCTION_ONLY"
    assert result == seal(result, "receipt_digest")
    assert len(result["source_bindings"]) == 17
    assert evidence.calls
    assert result["retained_context_samples_checked"] is (stage == "cohort")
    for field in (
        "historical_evidence_mutated",
        "raw_score_replay_executed",
        "encoder_executed",
        "threshold_fit_executed",
        "source_fetch_executed",
        "full_workflow_verified",
    ):
        assert result[field] is False
    assert "candidate_counts" not in result and "score" not in result


@pytest.mark.parametrize("stage", ["scan", "cohort"])
def test_exact_legacy_parity_on_temporary_evidence(evidence, stage):
    result = verify(evidence, stage)
    if stage == "scan":
        legacy, directory = evidence.legacy_scan(
            root=evidence.root, external_root=evidence.primary
        )
    else:
        with evidence.monkeypatch.context() as patch:
            patch.setattr(cohort, "verify_primary_scan", evidence.legacy_scan)
            legacy, directory = evidence.legacy_cohort(
                root=evidence.root,
                external_root=evidence.external,
                primary_external_root=evidence.primary,
            )
    assert legacy["artifact_digest"] == result["legacy_artifact_digest"]
    assert str(directory) == result["run_dir"]
    gate = verifier._scan_gate if stage == "scan" else verifier._cohort_gate
    # Legacy mode=ro may create sidecars. These belong ONLY to this temporary fixture.
    for suffix in ("-wal", "-shm"):
        Path(str(evidence.database) + suffix).unlink(missing_ok=True)
    kwargs = dict(
        root=evidence.root,
        external_root=evidence.primary if stage == "scan" else evidence.external,
        evidence=verifier._Evidence(),
    )
    if stage == "cohort":
        kwargs["primary_external_root"] = evidence.primary
    with ExitStack() as stack:
        reconstructed, _ = gate(**kwargs, stack=stack)
    assert reconstructed == legacy


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("stage", ["scan", "cohort"])
def test_transaction_sidecars_fail_closed(evidence, suffix, stage):
    Path(str(evidence.database) + suffix).write_bytes(b"")
    reject_unchanged(evidence, stage=stage, match="transaction sidecar")


def test_immutable_connection_cannot_write_or_create_sidecars(evidence):
    before = snapshot(evidence.scan_dir)
    with verifier.immutable_database(evidence.database) as connection:
        assert connection.execute("SELECT count(*) FROM windows").fetchone() == (6,)
        # Immutable connections disable journaling internally without changing
        # the actual persistent WAL-mode header bytes.
        assert evidence.database.read_bytes()[18:20] == b"\x02\x02"
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM windows")
        assert snapshot(evidence.scan_dir) == before
    assert snapshot(evidence.scan_dir) == before


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_sidecar_appearing_during_read_rejected(evidence, suffix):
    with pytest.raises(ValueError, match="transaction sidecar"):
        with verifier.immutable_database(evidence.database):
            Path(str(evidence.database) + suffix).write_bytes(b"")


def test_database_signature_change_rejected(evidence):
    import os

    with pytest.raises(ValueError, match="changed during"):
        with verifier.immutable_database(evidence.database):
            stat = evidence.database.stat()
            os.utime(
                evidence.database, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000)
            )


def test_legacy_mode_ro_creates_sidecars_on_temporary_database(evidence):
    assert not Path(str(evidence.database) + "-wal").exists()
    connection = sqlite3.connect(evidence.database.as_uri() + "?mode=ro", uri=True)
    try:
        assert connection.execute("SELECT count(*) FROM windows").fetchone() == (6,)
        assert Path(str(evidence.database) + "-wal").is_file()
        assert Path(str(evidence.database) + "-shm").is_file()
    finally:
        connection.close()


@pytest.mark.parametrize("missing", ["database", "context", "proposal", "shard"])
def test_missing_inputs_fail_without_creating_replacement(evidence, missing):
    row = evidence.rows[0]
    path = {
        "database": evidence.database,
        "context": evidence.cohort_dir / row["raw_context"]["relative_path"],
        "proposal": evidence.cohort_dir / "proposals.jsonl",
        "shard": cohort._shard_path(evidence.cohort_dir, row),
    }[missing]
    path.unlink()
    reject_unchanged(evidence)
    assert not path.exists()


@pytest.mark.parametrize("which", ["scan", "cohort"])
@pytest.mark.parametrize("field", ["preflight_digest", "run_key", "contract_digest"])
def test_preflight_seal_and_binding_negatives(evidence, which, field):
    directory = evidence.scan_dir if which == "scan" else evidence.cohort_dir
    path = directory / "preflight.json"
    value = read(path)
    value[field] = "f" * 64
    write(
        path, value if field == "preflight_digest" else seal(value, "preflight_digest")
    )
    reject_unchanged(evidence)


def test_validly_resealed_scan_summary_still_must_reconstruct(evidence):
    path = evidence.scan_dir / "primary_scan_summary.json"
    summary = read(path)
    summary["candidate_total"] += 1
    write(path, seal(summary))
    reject_unchanged(evidence, stage="scan", match="summary is stale")


def test_cohort_parent_artifact_mismatch(evidence):
    path = evidence.cohort_dir / "native_cohort_summary.json"
    summary = read(path)
    summary["primary_scan_artifact_digest"] = "f" * 64
    write(path, seal(summary))
    reject_unchanged(evidence, match="primary parent changed")


def test_proposal_hash_checked_before_legacy_loader(evidence, monkeypatch):
    path = evidence.cohort_dir / "proposals.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    monkeypatch.setattr(cohort, "_load_preflight", forbidden)
    reject_unchanged(evidence, match="hash mismatch: cohort_proposals")


def test_runtime_gate_failure_propagates_without_writes(evidence, monkeypatch):
    def reject(**kwargs):
        assert kwargs["require_current"] is True
        raise ValueError("current runtime differs from frozen environment")

    monkeypatch.setattr(cohort, "load_runtime_contract", reject)
    reject_unchanged(evidence, match="current runtime differs")


@pytest.mark.parametrize(
    "statement,parameters,match",
    [
        ("DELETE FROM windows WHERE detector='L1' AND gps_start=2000", (), "truncated"),
        ("UPDATE windows SET is_candidate=1 WHERE gps_start=1200", (), "row contract"),
        (
            "UPDATE windows SET score_float32_hex='bad' WHERE gps_start=1000",
            (),
            "row contract",
        ),
        (
            "UPDATE windows SET identity_digest='bad' WHERE gps_start=1000",
            (),
            "row contract",
        ),
        ("UPDATE windows SET mil_vector=NULL WHERE gps_start=2000", (), "row contract"),
        (
            "UPDATE windows SET mil_vector=x'01' WHERE gps_start=2000",
            (),
            "tensor shape",
        ),
        (
            "UPDATE windows SET top_k_indices=x'01' WHERE gps_start=2000",
            (),
            "tensor shape",
        ),
        (
            "UPDATE windows SET patch_anomaly_scores=x'01' WHERE gps_start=2000",
            (),
            "tensor shape",
        ),
        (
            "UPDATE windows SET mil_vector=x'01' WHERE gps_start=1000",
            (),
            "row contract",
        ),
        (
            "UPDATE metadata SET value='{}' WHERE key='run_identity'",
            (),
            "database identity",
        ),
        ("DELETE FROM raw_frames WHERE detector='H1'", (), "ledger is incomplete"),
        (
            "UPDATE raw_frames SET url='bad' WHERE detector='L1'",
            (),
            "provenance changed",
        ),
        ("UPDATE raw_frames SET sha256='bad' WHERE detector='L1'", (), "SHA-256"),
        ("UPDATE raw_frames SET size_bytes=0 WHERE detector='L1'", (), "ledger row"),
        (
            "UPDATE raw_frames SET retained_calibration_raw=2 WHERE detector='L1'",
            (),
            "ledger row",
        ),
        (
            "INSERT INTO windows SELECT detector,3000,primary_score,score_float32_hex,is_candidate,identity_digest,image_sha256,mil_vector,top_k_indices,patch_anomaly_scores FROM windows WHERE detector='L1' AND gps_start=2000",
            (),
            "extra rows",
        ),
    ],
)
def test_scan_semantic_negatives_after_synthetic_repin(
    evidence, statement, parameters, match
):
    sql(evidence, statement, parameters)
    reject_unchanged(evidence, stage="scan", match=match)


@pytest.mark.parametrize("which", ["scan", "cohort"])
@pytest.mark.parametrize(
    "name",
    ["failure.json", "controller.lock", "failures.json", "bad.partial", "bad.tmp"],
)
def test_failure_lock_partial_rejected(evidence, which, name):
    directory = evidence.scan_dir if which == "scan" else evidence.cohort_dir
    (directory / name).write_bytes(b"preserve")
    reject_unchanged(evidence, match="failure/active|partial")


@pytest.mark.parametrize("which", ["scan", "cohort"])
def test_transient_cache_rejected(evidence, which):
    directory = evidence.scan_dir if which == "scan" else evidence.cohort_dir
    transient = directory / "transient_raw" / "detector"
    transient.mkdir(parents=True)
    (transient / "raw.hdf5").write_bytes(b"preserve")
    reject_unchanged(evidence, match="transient")


@pytest.mark.parametrize("which", ["scan", "cohort"])
def test_summary_seal_rejected(evidence, which):
    path = (
        evidence.scan_dir / "primary_scan_summary.json"
        if which == "scan"
        else evidence.cohort_dir / "native_cohort_summary.json"
    )
    value = read(path)
    value["artifact_digest"] = "f" * 64
    write(path, value)
    reject_unchanged(evidence, match="seal mismatch")


def test_database_hash_rejected_before_open(evidence, monkeypatch):
    with evidence.database.open("ab") as stream:
        stream.write(b"altered")
    monkeypatch.setattr(verifier, "immutable_database", forbidden)
    reject_unchanged(evidence, stage="scan", match="hash mismatch")


def test_cohort_guard_inclusive_boundary(evidence):
    select(evidence, "candidate_guard_start_delta_s", 1000)
    reject_unchanged(evidence, match="candidate guard")


def test_cohort_separation_exact_boundary_and_below(evidence):
    select(evidence, "minimum_same_detector_separation_s", 200)
    verify(evidence)
    select(evidence, "minimum_same_detector_separation_s", 201)
    reject_unchanged(evidence, match="separation")


@pytest.mark.parametrize(
    "kind", ["candidate", "duplicate", "count", "quality", "source", "ledger_shard"]
)
def test_cohort_ledger_negatives(evidence, kind):
    if kind == "candidate":
        evidence.rows[1]["gps_start"] = 2000
    elif kind == "duplicate":
        evidence.rows[1] = dict(evidence.rows[0])
    elif kind == "count":
        evidence.rows.pop()
    elif kind == "quality":
        evidence.rows[0]["quality_disposition"] = "EXCESS_POWER_VETO"
    elif kind == "source":
        evidence.rows[0]["context_sources"][0]["used_interval_gps"][0] += 1
    else:
        evidence.rows[0]["arbitrary_new_field"] = True
    reledger(evidence, shards=kind == "source")
    reject_unchanged(evidence)


@pytest.mark.parametrize(
    "kind", ["file_hash", "value_hash", "shape", "dtype", "nonfinite", "escape"]
)
def test_context_negatives(evidence, kind):
    row = evidence.rows[0]
    path = evidence.cohort_dir / row["raw_context"]["relative_path"]
    if kind == "file_hash":
        with path.open("ab") as stream:
            stream.write(b"changed")
    elif kind == "value_hash":
        row["raw_context"]["values_sha256"] = "f" * 64
    elif kind == "escape":
        row["raw_context"]["relative_path"] = "../outside.npy"
    else:
        values = np.load(path)
        if kind == "shape":
            values = values[:-1]
        elif kind == "dtype":
            values = values.astype(np.float32)
        else:
            values[0] = np.inf
        np.save(path, values)
        row["raw_context"]["file_sha256"] = raw.file_sha256(path)
        row["raw_context"]["values_sha256"] = hashlib.sha256(
            values.tobytes()
        ).hexdigest()
    reledger(evidence, shards=kind != "file_hash")
    reject_unchanged(evidence)


def test_proposal_path_checked_before_legacy_loader(evidence, monkeypatch):
    path = evidence.cohort_dir / "preflight.json"
    value = read(path)
    value["proposal_manifest"]["filename"] = "../outside.jsonl"
    write(path, seal(value, "preflight_digest"))
    monkeypatch.setattr(cohort, "_load_preflight", forbidden)
    reject_unchanged(evidence, match="unsafe evidence path")


def test_changed_executed_source_rejected(evidence):
    path = evidence.root / "src/dante_light/o3a_primary_scan.py"
    path.write_bytes(path.read_bytes() + b"\n# changed fixture\n")
    reject_unchanged(evidence, match="executed helper source mismatch")


def test_mid_read_input_change_rejected(evidence, monkeypatch):
    original = verifier._frame_rows

    def change(path):
        rows = original(path)
        target = evidence.cohort_dir / "proposals.jsonl"
        target.write_bytes(target.read_bytes() + b"\n")
        return rows

    monkeypatch.setattr(verifier, "_frame_rows", change)
    with pytest.raises(
        ValueError, match="changed during verification: cohort_proposals"
    ):
        verify(evidence)


def cli():
    spec = importlib.util.spec_from_file_location(
        "native_evidence_cli", ROOT / "scripts/verify_dante_o3a_native_evidence.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("stage", ["scan", "cohort"])
def test_cli_success_is_stdout_only(evidence, capsys, stage):
    args = [
        "--stage",
        stage,
        "--repository-root",
        str(evidence.root),
        "--external-root",
        str(evidence.primary if stage == "scan" else evidence.external),
    ]
    if stage == "cohort":
        args += ["--primary-external-root", str(evidence.primary)]
    before = snapshot(evidence.root.parent)
    assert cli().main(args) == 0
    assert json.loads(capsys.readouterr().out)["stage"] == stage
    assert snapshot(evidence.root.parent) == before


def test_cli_failure_preserves_evidence(evidence, capsys):
    (evidence.scan_dir / "failure.json").write_bytes(b"preserve")
    before = snapshot(evidence.root.parent)
    assert (
        cli().main(
            [
                "--stage",
                "scan",
                "--repository-root",
                str(evidence.root),
                "--external-root",
                str(evidence.primary),
            ]
        )
        == 1
    )
    assert (
        json.loads(capsys.readouterr().out)["status"]
        == "FAIL_CLOSED_O3A_NATIVE_EVIDENCE"
    )
    assert snapshot(evidence.root.parent) == before


@pytest.mark.parametrize(
    "stage,primary", [("cohort", None), ("scan", Path("unused")), ("index", None)]
)
def test_unsupported_scope_rejected_before_read(evidence, stage, primary):
    with pytest.raises(ValueError):
        verifier.verify_native_evidence(
            root=evidence.root,
            external_root=evidence.external,
            stage=stage,
            primary_external_root=primary,
        )


@pytest.mark.parametrize("flag", ["--run", "--freeze", "--repair", "--resume"])
def test_cli_has_no_mutation_flag(flag):
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts/verify_dante_o3a_native_evidence.py"),
            "--stage",
            "scan",
            "--external-root",
            "unused",
            flag,
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "unrecognized arguments" in completed.stderr


def test_real_inherited_contracts_still_load_without_history():
    assert scan.load_scan_contract(root=ROOT)["contract_digest"]
    assert cohort.load_cohort_contract(root=ROOT)["contract_digest"]
    assert len(verifier._sources(ROOT)) == 17
