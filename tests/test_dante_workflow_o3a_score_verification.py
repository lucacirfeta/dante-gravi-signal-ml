"""Retained-score tests: isolated INDEX parent, real SQLite and pure selectors."""

from __future__ import annotations

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
from src.dante_light import o3a_native_calibration_cohort as calibration
from src.dante_light import o3a_native_rescore as rescore
from src.dante_light import o3a_native_rescore_preflight as builder
from src.dante_light import o3a_raw_acquisition as acquisition
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_workflow import o3a_score_verification as verifier

ROOT = Path(__file__).resolve().parents[1]


def seal(value, field="artifact_digest"):
    body = {k: v for k, v in value.items() if k != field}
    return {**body, field: contracts.canonical_json_sha256(body)}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def read(path):
    return json.loads(path.read_bytes())


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows)
    )
    return {
        "filename": path.name,
        "sha256": file_sha256(path),
        "row_digest": contracts.canonical_json_sha256(rows),
        "row_total": len(rows),
    }


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def forbidden(*args, **kwargs):
    raise AssertionError("scientific writer/scorer/fetch or legacy verifier invoked")


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    pytest.importorskip("fcntl", reason="existing read-only flock requires POSIX/WSL")
    root = tmp_path / "repo"
    for relative in verifier._sources(ROOT):
        if relative.startswith("src/dante_light/"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
    runtime = {"runtime_environment": {"environment_digest": "a" * 64}}
    write(root / calibration.RUNTIME_REL, runtime)
    scan_dir, cohort_dir, index_dir = (
        tmp_path / name for name in ("scan", "cohort", "index")
    )
    database = scan_dir / "primary_scan.sqlite"
    database.parent.mkdir()
    inventory = {
        "urls_by_detector": {
            d: [f"https://gwosc.org/test/{d[0]}-{d}_GWOSC_O3a_4KHZ_R1-900-4096.hdf5"]
            for d in ("H1", "L1")
        }
    }
    write(root / acquisition.INVENTORY_REL, inventory)
    frames = {d: calibration._inventory_frames(inventory, d) for d in ("H1", "L1")}
    identities, scoring_rows = [], {}
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE windows(detector TEXT,gps_start INTEGER,is_candidate INTEGER,identity_digest TEXT,image_sha256 TEXT)"
        )
        connection.execute(
            "CREATE TABLE raw_frames(detector TEXT,gps_start INTEGER,gps_end INTEGER,filename TEXT,url TEXT,sha256 TEXT,size_bytes INTEGER)"
        )
        for d in frames:
            frame = frames[d][0]
            connection.execute(
                "INSERT INTO raw_frames VALUES(?,?,?,?,?,?,?)",
                (
                    d,
                    frame["gps_start"],
                    frame["gps_end"],
                    frame["filename"],
                    frame["url"],
                    "b" * 64,
                    123,
                ),
            )
            for gps in (1000, 1200, 2000, 3000, 3032):
                seed = gps == 2000
                identities.append((d, gps, seed))
                connection.execute(
                    "INSERT INTO windows VALUES(?,?,?,?,?)",
                    (d, gps, int(seed), "c" * 64, "d" * 64),
                )
                scoring_rows[(d, gps)] = {
                    "detector": d,
                    "gps_start": gps,
                    "is_candidate": seed,
                    "identity_digest": "c" * 64,
                    "expected_image_sha256": "d" * 64,
                }
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # Close the fixture connection; no transaction-sidecar repair in the verifier.
    connection.close()
    scan = seal(
        {
            "run_key": "scan-fixture",
            "database": {"filename": database.name, "sha256": file_sha256(database)},
        }
    )
    write(scan_dir / "primary_scan_summary.json", scan)
    training = [
        {"detector": d, "gps_start": gps} for d in frames for gps in (1000, 1200)
    ]
    cohort_ledger = jsonl(cohort_dir / "native_cohort.jsonl", training)
    cohort = seal({"ledger": cohort_ledger})
    write(cohort_dir / "native_cohort_summary.json", cohort)
    index = seal({"run_key": "index-fixture"})
    write(index_dir / "native_index_summary.json", index)
    cc = seal(
        {
            "parents": {
                name: {"artifact_digest": value["artifact_digest"]}
                for name, value in (
                    ("primary_scan", scan),
                    ("native_cohort", cohort),
                    ("native_index", index),
                )
            },
            "selection": {
                "target_rows_per_detector": 2,
                "block_length_rows": 2,
                "window_duration_s": 32,
                "stride_s": 32,
                "candidate_and_index_guard_start_delta_s": 128,
                "bootstrap_rows_per_detector": 2,
            },
        },
        "contract_digest",
    )
    cc["parents"]["native_cohort"]["ledger_sha256"] = cohort_ledger["sha256"]
    cc = seal(cc, "contract_digest")
    write(root / calibration.CONTRACT_REL, cc)
    monkeypatch.setattr(
        calibration,
        "load_cohort_contract",
        lambda *, root: read(root / calibration.CONTRACT_REL),
    )
    monkeypatch.setattr(
        calibration,
        "load_runtime_contract",
        lambda *, root, require_current: (
            read(root / calibration.RUNTIME_REL)
            if require_current is True
            else forbidden()
        ),
    )
    monkeypatch.setattr(
        calibration,
        "load_source_inventory",
        lambda *, root: read(root / acquisition.INVENTORY_REL),
    )
    calls = []

    def parent(**kwargs):
        calls.append({k: v for k, v in kwargs.items() if k != "evidence"})
        assert kwargs["external_root"] == index_dir
        assert kwargs["primary_external_root"] == scan_dir
        assert kwargs["cohort_external_root"] == cohort_dir
        tracked = kwargs["evidence"]
        for name, directory, filename in (
            ("scan_summary", scan_dir, "primary_scan_summary.json"),
            ("cohort_summary", cohort_dir, "native_cohort_summary.json"),
            ("index_summary", index_dir, "native_index_summary.json"),
        ):
            verifier._clean(directory)
            tracked.sealed(name, directory / filename, "artifact_digest")
        verifier.parents._pin(
            tracked, "scan_database", database, scan["database"]["sha256"]
        )
        tracked.read(
            "cohort_ledger",
            cohort_dir / cohort_ledger["filename"],
            cohort_ledger["sha256"],
        )
        return index, index_dir

    monkeypatch.setattr(verifier.index_parent, "_index_gate", parent)
    raw_frames = verifier.parents._frame_rows(database)

    def sources(detector, gps):
        return calibration._source_rows_for_context(
            detector=detector,
            gps=gps,
            frames=frames[detector],
            frame_starts=[900],
            raw_frame_rows=raw_frames,
        )

    rows, audit = calibration.select_native_calibration_rows(
        identities,
        [(r["detector"], r["gps_start"]) for r in training],
        target_rows=2,
        block_length=2,
        window_s=32,
        stride_s=32,
        guard_delta_s=128,
        context_sources=sources,
    )
    calibration_dir = calibration._run_dir(
        cc, root=root, external_root=tmp_path / "calibration"
    )
    calibration_ledger = jsonl(
        calibration_dir / "native_calibration_cohort.jsonl", rows
    )
    cal = seal(
        {
            "schema_version": calibration.SCHEMA_VERSION,
            "status": "PASS_FROZEN_O3A_NATIVE_CALIBRATION_COHORT",
            "contract_digest": cc["contract_digest"],
            "run_key": calibration_dir.name.removeprefix("native_calibration_cohort_"),
            "counts_by_detector": {"H1": 2, "L1": 2},
            "bootstrap_rows_by_detector": {"H1": 2, "L1": 2},
            "selection_audit": audit,
            "ledger": calibration_ledger,
            "scores_or_classes_read": False,
        }
    )
    write(calibration_dir / "native_calibration_summary.json", cal)
    rc = seal(
        {
            "parents": {
                name: {"artifact_digest": value["artifact_digest"]}
                for name, value in (
                    ("primary_scan", scan),
                    ("native_index", index),
                    ("native_calibration", cal),
                )
            },
            "population": {
                "calibration_rows_by_detector": {"H1": 2, "L1": 2},
                "candidate_rows_by_detector": {"H1": 1, "L1": 1},
                "bootstrap_block_length_rows": 2,
                "exact_total_rows": 6,
            },
            "execution": {"batch_size": 2},
        },
        "contract_digest",
    )
    rc["parents"]["canonical_runtime"] = {"environment_digest": "a" * 64}
    rc = seal(rc, "contract_digest")
    write(root / rescore.CONTRACT_REL, rc)
    monkeypatch.setattr(
        rescore,
        "load_rescore_contract",
        lambda *, root: read(root / rescore.CONTRACT_REL),
    )
    monkeypatch.setattr(
        rescore, "load_runtime_contract", calibration.load_runtime_contract
    )
    directory = rescore._run_dir(rc, tmp_path / "rescore")
    work, work_audit = builder.assemble_work_rows(
        scan_rows=scoring_rows,
        calibration_rows=rows,
        frames_by_detector=frames,
        raw_frame_rows=raw_frames,
        expected_calibration_rows_by_detector={"H1": 2, "L1": 2},
        bootstrap_block_length_rows=2,
    )
    ordered = sorted(
        work, key=lambda row: (row["detector"], row["gps_start"], row["population"])
    )
    manifest = jsonl(directory / "work_manifest.jsonl", ordered)
    preflight = seal(
        {
            "schema_version": rescore.SCHEMA_VERSION,
            "status": "PASS_O3A_NATIVE_RESCORE_PREFLIGHT",
            "run_key": rescore._run_key(rc),
            "contract_digest": rc["contract_digest"],
            "parent_artifact_digests": {
                n: rc["parents"][n]["artifact_digest"]
                for n in ("primary_scan", "native_index", "native_calibration")
            },
            "manifest": manifest,
            "audit": work_audit,
        },
        "preflight_digest",
    )
    write(directory / "preflight.json", preflight)
    cuda = seal(
        {
            "status": "PASS_O3A_NATIVE_RESCORE_CUDA_PREFLIGHT",
            "run_key": rescore._run_key(rc),
            "contract_digest": rc["contract_digest"],
            "work_manifest_sha256": manifest["sha256"],
            "raw_frame_sha256_replay": True,
            "image_sha256_replay": True,
            "stitched_context_replay": True,
            "finite_cuda_tokens_and_score": True,
            "score_disclosed": False,
        },
        "cuda_preflight_digest",
    )
    write(directory / "cuda_preflight.json", cuda)
    scored = []
    for position, batch in enumerate(rescore._batch_rows(ordered, 2)):
        outputs = [
            {
                **r,
                "native_score": 0.5,
                "score_float32_hex": np.float32(0.5).tobytes().hex(),
                "image_sha256": r["expected_image_sha256"],
            }
            for r in batch
        ]
        scored.extend(outputs)
        write(
            rescore._shard_path(directory, position),
            seal(
                {
                    "status": "PASS_O3A_NATIVE_SCORE_SHARD",
                    "run_key": rescore._run_key(rc),
                    "contract_digest": rc["contract_digest"],
                    "batch_index": position,
                    "input_rows_digest": contracts.canonical_json_sha256(batch),
                    "rows": outputs,
                },
                "shard_digest",
            ),
        )
    outputs = {
        name: jsonl(directory / f"{name}.jsonl", values)
        for name, values in rescore._output_groups(scored).items()
    }
    summary = seal(
        {
            "schema_version": rescore.SCHEMA_VERSION,
            "status": "PASS_COMPLETE_O3A_NATIVE_RESCORE",
            "run_key": rescore._run_key(rc),
            "contract_digest": rc["contract_digest"],
            "preflight_digest": preflight["preflight_digest"],
            "row_total": len(scored),
            "outputs": outputs,
            "gates": {
                "source_frame_hash_mismatches": 0,
                "context_failures": 0,
                "image_hash_mismatches": 0,
                "encoder_failures": 0,
                "nonfinite_scores": 0,
                "old_o4a_scores_or_thresholds_read": False,
                "threshold_or_class_computed": False,
            },
        }
    )
    write(directory / "native_rescore_summary.json", summary)
    legacy_cal, legacy_score = (
        calibration.verify_native_calibration_cohort,
        rescore.verify_native_rescore,
    )
    for module, names in (
        (
            calibration,
            (
                "_parents",
                "_expected_rows",
                "freeze_native_calibration_cohort",
                "verify_native_calibration_cohort",
                "_atomic_json",
                "_atomic_jsonl",
            ),
        ),
        (
            rescore,
            (
                "_parent_runs",
                "preflight_rescore",
                "preflight_from_verified_parents",
                "verify_native_rescore",
                "run_native_rescore",
                "cuda_preflight_rescore",
                "_write_shard",
                "_prepare_score_row",
                "_download_frame",
                "_load_scorer",
                "_score_prepared",
                "_atomic_json",
                "_atomic_jsonl",
            ),
        ),
        (builder, ("scan_scoring_identities", "preflight_from_verified_parents")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    (directory / "run.lock").write_bytes(b"preserved producer PID")
    return SimpleNamespace(
        root=root,
        scan_dir=scan_dir,
        cohort_dir=cohort_dir,
        index_dir=index_dir,
        database=database,
        calibration_dir=calibration_dir,
        rescore_dir=directory,
        calls=calls,
        cal=cal,
        rc=rc,
        rows=rows,
        ordered=ordered,
        audit=audit,
        work_audit=work_audit,
        preflight=preflight,
        scan=scan,
        index=index,
        legacy_cal=legacy_cal,
        legacy_score=legacy_score,
    )


def verify(f, stage="rescore"):
    return verifier.verify_score_evidence(
        root=f.root,
        external_root=f.calibration_dir.parent
        if stage == "calibration"
        else f.rescore_dir.parent,
        stage=stage,
        calibration_external_root=f.calibration_dir.parent
        if stage == "rescore"
        else None,
        index_external_root=f.index_dir,
        cohort_external_root=f.cohort_dir,
        primary_external_root=f.scan_dir,
    )


def test_rescore_lock_held_through_final_check(evidence, monkeypatch):
    import fcntl

    original = verifier._Evidence.unchanged
    path = evidence.rescore_dir / "run.lock"
    before = snapshot(evidence.root.parent)

    def final_check(tracked):
        with path.open("rb") as handle:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original(tracked)

    monkeypatch.setattr(verifier._Evidence, "unchanged", final_check)
    receipt = verify(evidence)
    assert "rescore_lock" in receipt["inputs"]
    assert snapshot(evidence.root.parent) == before
    with path.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)


@pytest.mark.parametrize("problem", ["missing", "busy"])
def test_rescore_lock_refused(evidence, problem):
    import fcntl

    path = evidence.rescore_dir / "run.lock"
    if problem == "missing":
        path.unlink()
        reject(evidence, match="persistent lock")
    else:
        with path.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            reject(evidence, match="persistent lock")
            fcntl.flock(handle, fcntl.LOCK_UN)


@pytest.mark.parametrize("stage", ["calibration", "rescore"])
def test_noncooperative_calibration_lock_stays_strict(evidence, stage):
    (evidence.calibration_dir / "run.lock").write_bytes(b"not approved cooperative")
    reject(evidence, stage, match="failure/lock evidence present: run.lock")


def reject(f, stage="rescore", match=None):
    before = snapshot(f.root.parent)
    with pytest.raises((ValueError, RuntimeError, OSError, KeyError), match=match):
        verify(f, stage)
    assert snapshot(f.root.parent) == before


@pytest.mark.parametrize("stage", ["calibration", "rescore"])
def test_receipt_no_mutation_and_explicit_parent_wiring(evidence, stage):
    before = snapshot(evidence.root.parent)
    result = verify(evidence, stage)
    assert snapshot(evidence.root.parent) == before
    assert result == seal(result, "receipt_digest")
    assert len(result["source_bindings"]) == 31
    assert evidence.calls[-1]["primary_external_root"] == evidence.scan_dir
    for flag in (
        "encoder_executed",
        "preprocessing_replay_executed",
        "raw_score_replay_executed",
        "source_fetch_executed",
        "threshold_fit_executed",
        "full_workflow_verified",
        "historical_evidence_mutated",
    ):
        assert result[flag] is False
    assert result["stored_score_shards_checked"] == (stage == "rescore")
    assert "native_score" not in json.dumps(result)


def test_exact_legacy_calibration_parity(evidence, monkeypatch):
    f = evidence
    monkeypatch.setattr(
        calibration,
        "_parents",
        lambda **kwargs: (f.scan_dir, f.cohort_dir, f.index_dir),
    )
    # Only the legacy parity invocation replaces its unsafe SQL accessors.
    monkeypatch.setattr(calibration, "_expected_rows", _LEGACY_EXPECTED)
    monkeypatch.setattr(
        calibration, "_scan_identity_rows", verifier.parents._identity_rows
    )
    monkeypatch.setattr(calibration, "_raw_frame_rows", verifier.parents._frame_rows)
    before = snapshot(f.root.parent)
    legacy, directory = f.legacy_cal(
        root=f.root, external_root=f.calibration_dir.parent
    )
    assert directory == f.calibration_dir and legacy == f.cal
    assert (
        verify(f, "calibration")["legacy_artifact_digest"] == legacy["artifact_digest"]
    )
    assert snapshot(f.root.parent) == before


_LEGACY_EXPECTED = calibration._expected_rows


def test_exact_legacy_rescore_and_preflight_parity(evidence, monkeypatch):
    f = evidence
    monkeypatch.setattr(
        rescore,
        "_parent_runs",
        lambda **kwargs: (
            f.scan,
            f.index,
            f.cal,
            f.scan_dir,
            f.index_dir,
            f.calibration_dir,
        ),
    )
    monkeypatch.setattr(
        rescore,
        "preflight_from_verified_parents",
        lambda **kwargs: (f.ordered, f.work_audit),
    )
    # Original preflight writer operates only on this temporary fixture.
    monkeypatch.setattr(rescore, "_atomic_json", _LEGACY_JSON)
    monkeypatch.setattr(rescore, "_atomic_jsonl", _LEGACY_JSONL)
    actual, directory = _LEGACY_PREFLIGHT(
        root=f.root, external_root=f.rescore_dir.parent
    )
    assert actual == f.preflight and directory == f.rescore_dir
    monkeypatch.setattr(
        rescore, "preflight_rescore", lambda **kwargs: (actual, directory)
    )
    before = snapshot(f.root.parent)
    legacy, legacy_dir = f.legacy_score(root=f.root, external_root=f.rescore_dir.parent)
    assert legacy_dir == directory
    assert verify(f)["legacy_artifact_digest"] == legacy["artifact_digest"]
    assert snapshot(f.root.parent) == before


_LEGACY_PREFLIGHT, _LEGACY_JSON, _LEGACY_JSONL = (
    rescore.preflight_rescore,
    rescore._atomic_json,
    rescore._atomic_jsonl,
)


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "contract_digest",
        "run_key",
        "scores_or_classes_read",
        "counts_by_detector",
        "bootstrap_rows_by_detector",
        "selection_audit",
    ],
)
def test_calibration_summary_negatives(evidence, field):
    path = evidence.calibration_dir / "native_calibration_summary.json"
    value = read(path)
    value[field] = "changed"
    write(path, seal(value))
    reject(evidence, "calibration")


@pytest.mark.parametrize(
    "field",
    [
        "gps_start",
        "gps_end",
        "row_number",
        "bootstrap_block_index",
        "plan_priority_rank",
        "context_sources_digest",
        "native_score",
    ],
)
def test_calibration_ledger_resealed_negatives(evidence, field):
    rows = [dict(row) for row in evidence.rows]
    rows[0][field] = "changed"
    output = jsonl(evidence.calibration_dir / "native_calibration_cohort.jsonl", rows)
    path = evidence.calibration_dir / "native_calibration_summary.json"
    value = read(path)
    value["ledger"] = output
    write(path, seal(value))
    reject(evidence, "calibration")


@pytest.mark.parametrize(
    "field",
    ["status", "run_key", "contract_digest", "preflight_digest", "row_total", "gates"],
)
def test_rescore_summary_negatives(evidence, field):
    path = evidence.rescore_dir / "native_rescore_summary.json"
    value = read(path)
    value[field] = "changed"
    write(path, seal(value))
    reject(evidence)


@pytest.mark.parametrize(
    "field", ["status", "batch_index", "input_rows_digest", "contract_digest"]
)
def test_rescore_shard_header_negatives(evidence, field):
    path = rescore._shard_path(evidence.rescore_dir, 0)
    value = read(path)
    value[field] = "changed"
    write(path, seal(value, "shard_digest"))
    reject(evidence)


@pytest.mark.parametrize(
    "field",
    [
        "identity_digest",
        "image_sha256",
        "native_score",
        "score_float32_hex",
        "class",
        "threshold",
    ],
)
def test_rescore_row_negatives(evidence, field):
    path = rescore._shard_path(evidence.rescore_dir, 0)
    value = read(path)
    value["rows"][0][field] = "changed"
    write(path, seal(value, "shard_digest"))
    reject(evidence)


@pytest.mark.parametrize("field", ["status", "audit", "parent_artifact_digests"])
def test_rescore_preflight_reconstruction_negatives(evidence, field):
    path = evidence.rescore_dir / "preflight.json"
    value = read(path)
    value[field] = "changed"
    write(path, seal(value, "preflight_digest"))
    reject(evidence)


@pytest.mark.parametrize(
    "name",
    [
        "failure.json",
        "controller.lock",
        "input.partial",
        "transient_raw/raw.hdf5",
        "cuda_preflight.json",
    ],
)
def test_rescore_missing_or_active_evidence(evidence, name):
    path = evidence.rescore_dir / name
    if name == "cuda_preflight.json":
        path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preserve")
    reject(evidence)


def test_sql_sidecar_rejected(evidence):
    Path(str(evidence.database) + "-wal").write_bytes(b"preserve")
    reject(evidence)


def test_escaping_output_rejected(evidence):
    path = evidence.rescore_dir / "native_rescore_summary.json"
    value = read(path)
    value["outputs"]["primary_candidate"]["filename"] = "../outside"
    write(path, seal(value))
    reject(evidence)


def test_resealed_output_mismatch(evidence):
    path = evidence.rescore_dir / "primary_candidate.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    rows[0]["native_score"] = 0.7
    output = jsonl(path, rows)
    summary_path = evidence.rescore_dir / "native_rescore_summary.json"
    value = read(summary_path)
    value["outputs"]["primary_candidate"] = output
    write(summary_path, seal(value))
    reject(evidence, match="output ledger changed")


@pytest.mark.parametrize("stage", ["calibration", "rescore"])
@pytest.mark.parametrize("fail", [False, True])
def test_cli_stdout(evidence, stage, capsys, fail):
    spec = importlib.util.spec_from_file_location(
        "score_evidence_cli", ROOT / "scripts/verify_dante_o3a_score_evidence.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = [
        "--stage",
        stage,
        "--repository-root",
        str(evidence.root),
        "--external-root",
        str(
            evidence.calibration_dir.parent
            if stage == "calibration"
            else evidence.rescore_dir.parent
        ),
        "--index-external-root",
        str(evidence.index_dir),
        "--cohort-external-root",
        str(evidence.cohort_dir),
        "--primary-external-root",
        str(evidence.scan_dir),
    ]
    if stage == "rescore":
        args += ["--calibration-external-root", str(evidence.calibration_dir.parent)]
    if fail:
        directory = (
            evidence.calibration_dir if stage == "calibration" else evidence.rescore_dir
        )
        (directory / "failure.json").write_bytes(b"preserve")
    before = snapshot(evidence.root.parent)
    assert module.main(args) == int(fail)
    result = json.loads(capsys.readouterr().out)
    if fail:
        assert result["status"] == "FAIL_CLOSED_O3A_SCORE_EVIDENCE"
    else:
        assert result["stage"] == stage
    assert snapshot(evidence.root.parent) == before


@pytest.mark.parametrize("flag", ["--run", "--repair", "--resume", "--freeze"])
def test_mutation_option_rejected(flag):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts/verify_dante_o3a_score_evidence.py"),
            "--stage",
            "rescore",
            "--external-root",
            "unused",
            "--index-external-root",
            "unused",
            "--cohort-external-root",
            "unused",
            "--primary-external-root",
            "unused",
            flag,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


def test_actual_source_and_contract_loaders_without_history():
    assert len(verifier._sources(ROOT)) == 31
    if sys.platform == "win32":
        frozen = read(ROOT / calibration.CONTRACT_REL)
        rebuilt = calibration.build_cohort_contract(root=ROOT)
        assert {
            k: v for k, v in frozen.items() if k not in {"execution", "contract_digest"}
        } == {
            k: v
            for k, v in rebuilt.items()
            if k not in {"execution", "contract_digest"}
        }
        assert {k: v for k, v in frozen["execution"].items() if k != "root_wsl"} == {
            k: v for k, v in rebuilt["execution"].items() if k != "root_wsl"
        }
        assert frozen["execution"]["root_wsl"] != rebuilt["execution"]["root_wsl"]
        with pytest.raises(
            contracts.ContractError, match="native-calibration frozen contract changed"
        ):
            calibration.load_cohort_contract(root=ROOT)
        with pytest.raises(
            contracts.ContractError, match="native-index frozen contract changed"
        ):
            rescore.load_rescore_contract(root=ROOT)
    else:
        assert calibration.load_cohort_contract(root=ROOT)["contract_digest"]
        assert rescore.load_rescore_contract(root=ROOT)["contract_digest"]


@pytest.mark.parametrize(
    "field",
    [
        "raw_frame_sha256_replay",
        "image_sha256_replay",
        "stitched_context_replay",
        "finite_cuda_tokens_and_score",
        "score_disclosed",
    ],
)
def test_cuda_receipt_resealed_negatives(evidence, field):
    path = evidence.rescore_dir / "cuda_preflight.json"
    value = read(path)
    value[field] = not value[field]
    write(path, seal(value, "cuda_preflight_digest"))
    reject(evidence)


@pytest.mark.parametrize(
    "field", ["ordinal", "context_sources_digest", "expected_image_sha256"]
)
def test_work_manifest_resealed_negative(evidence, field):
    rows = [dict(row) for row in evidence.ordered]
    rows[0][field] = "changed"
    manifest = jsonl(evidence.rescore_dir / "work_manifest.jsonl", rows)
    path = evidence.rescore_dir / "preflight.json"
    value = read(path)
    value["manifest"] = manifest
    write(path, seal(value, "preflight_digest"))
    reject(evidence, match="work population changed")


@pytest.mark.parametrize("module", [calibration, rescore, builder])
def test_changed_helper_source(evidence, module):
    path = evidence.root / (module.__name__.replace(".", "/") + ".py")
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    reject(evidence, match="executed helper source mismatch")


def test_runtime_parent_digest_changed(evidence):
    path = evidence.root / rescore.CONTRACT_REL
    value = read(path)
    value["parents"]["canonical_runtime"]["environment_digest"] = "changed"
    write(path, seal(value, "contract_digest"))
    reject(evidence, match="runtime changed")


def test_midread_preflight_mutation_detected(evidence, monkeypatch):
    original = rescore._gather_outputs
    path = evidence.rescore_dir / "preflight.json"
    before = snapshot(evidence.root.parent)

    def change(**kwargs):
        rows = original(**kwargs)
        path.write_bytes(path.read_bytes() + b"\n")
        return rows

    monkeypatch.setattr(rescore, "_gather_outputs", change)
    with pytest.raises(ValueError, match="evidence changed during verification"):
        verify(evidence)
    after = snapshot(evidence.root.parent)
    assert set(after) == set(before)
    changed = str(path.relative_to(evidence.root.parent))
    assert {k: v for k, v in after.items() if k != changed} == {
        k: v for k, v in before.items() if k != changed
    }


@pytest.mark.parametrize(
    "case", ["valid", "detector", "seed", "identity", "image", "duplicate"]
)
def test_scoring_identity_reader_legacy_parity(tmp_path, case):
    path = tmp_path / "identities.sqlite"
    row = ["H1", 1000, 0, "a" * 64, "b" * 64]
    if case in {"detector", "seed", "identity", "image"}:
        position = {"detector": 0, "seed": 2, "identity": 3, "image": 4}[case]
        row[position] = 2 if case == "seed" else "bad"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE windows(detector TEXT,gps_start INTEGER,is_candidate INTEGER,identity_digest TEXT,image_sha256 TEXT)"
        )
        connection.execute("INSERT INTO windows VALUES(?,?,?,?,?)", row)
        if case == "duplicate":
            connection.execute("INSERT INTO windows VALUES(?,?,?,?,?)", row)
    connection.close()
    before = snapshot(tmp_path)
    if case == "valid":
        assert verifier._scoring_identities(path) == builder.scan_scoring_identities(
            path
        )
    else:
        for reader in (verifier._scoring_identities, builder.scan_scoring_identities):
            with pytest.raises(
                contracts.ContractError, match="identity ledger is invalid"
            ):
                reader(path)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "stage,extra", [("other", None), ("rescore", None), ("calibration", Path("extra"))]
)
def test_invalid_scope_before_sources(stage, extra, monkeypatch):
    monkeypatch.setattr(verifier, "_sources", forbidden)
    with pytest.raises(ValueError, match="scope|extra calibration root"):
        verifier.verify_score_evidence(
            root=Path("unused"),
            external_root=Path("unused"),
            index_external_root=Path("unused"),
            cohort_external_root=Path("unused"),
            primary_external_root=Path("unused"),
            stage=stage,
            calibration_external_root=extra,
        )


def test_missing_score_shard(evidence):
    rescore._shard_path(evidence.rescore_dir, 0).unlink()
    reject(evidence)
