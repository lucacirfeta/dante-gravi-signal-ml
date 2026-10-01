"""Actual frozen MIL/clustering parity; isolated classification parent only."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from src.dante_light import o3a_native_taxonomy as tx
from src.dante_light import o3a_native_classification as nc
from src.dante_light import o4a_corrected_native_taxonomy as old
from src.dante_light.contracts import canonical_json_sha256, ContractError
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_workflow import o3a_taxonomy_verification as verifier

ROOT = Path(__file__).resolve().parents[1]
POSIX = pytest.mark.skipif(os.name == "nt", reason="persistent locks require POSIX/WSL")


def seal(value, field="artifact_digest"):
    body = {k: v for k, v in value.items() if k != field}
    return {**body, field: canonical_json_sha256(body)}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def forbidden(*a, **kw):
    raise AssertionError("legacy productive verifier/writer invoked")


@pytest.fixture
def mil(tmp_path):
    # Two H1 and two L1, distinct GPS; mixed classes must ALL enter morphology.
    rows = [
        {
            "detector": detector,
            "gps_start": gps,
            "identity_digest": f"id-{detector}-{gps}",
            "image_sha256": f"image-{detector}-{gps}",
            "native_class": native_class,
            "native_score": score,
        }
        for detector, gps, native_class, score in (
            ("H1", 100, "ROBUST", 0.9),
            ("H1", 200, "BACKGROUND", 0.1),
            ("L1", 300, "AMBIGUOUS", 0.5),
            ("L1", 400, "ROBUST", 0.95),
        )
    ]
    angles = np.deg2rad([0, 35, 70, 180])
    vectors = np.asarray([[np.cos(a), np.sin(a)] for a in angles], dtype="<f4")
    path = tmp_path / "primary_scan.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE windows(detector TEXT,gps_start INTEGER,"
            "identity_digest TEXT,image_sha256 TEXT,mil_vector BLOB,is_candidate INTEGER)"
        )
        connection.executemany(
            "INSERT INTO windows VALUES(?,?,?,?,?,1)",
            [
                (
                    r["detector"],
                    r["gps_start"],
                    r["identity_digest"],
                    r["image_sha256"],
                    v.tobytes(),
                )
                for r, v in zip(rows, vectors, strict=True)
            ],
        )
    contract = {
        "taxonomy": {
            "representation": "o3a_primary_scan_mil_v1",
            "distance_threshold": 0.25,
            "linkage": "single",
            "flat_cluster_criterion": "distance",
        },
        "gates": {
            "vector_dim": 2,
            "vector_blob_bytes": 8,
            "exact_total_rows": 4,
            "exact_rows_by_detector": {"H1": 2, "L1": 2},
        },
    }
    return SimpleNamespace(path=path, rows=rows, vectors=vectors, contract=contract)


def test_immutable_reader_and_original_numerical_builder_parity(mil):
    before = snapshot(mil.path.parent)
    bases, vectors, hashes = verifier._candidate_rows(mil.path, mil.rows, mil.contract)
    legacy = old._load_primary_mil_rows(
        mil.path, classified_rows=mil.rows, contract=mil.contract
    )
    assert bases == legacy[0] == mil.rows
    np.testing.assert_array_equal(vectors, legacy[1])
    assert hashes == legacy[2]
    rows, metrics = tx.build_taxonomy_rows(
        bases, vectors, hashes, contract=mil.contract
    )
    assert (rows, metrics) == tx.build_taxonomy_rows(*legacy, contract=mil.contract)
    assert [r["global_family_id"] for r in rows] == ["Family_01"] * 3 + [
        "Singleton_400"
    ]
    assert metrics["max_family_size"] == 3
    assert [r["native_class"] for r in rows] == [r["native_class"] for r in mil.rows]
    assert snapshot(mil.path.parent) == before


@pytest.mark.parametrize(
    "change",
    [
        "identity",
        "image",
        "gps",
        "detector",
        "missing",
        "order",
        "duplicate",
        "prior_family",
        "prior_taxonomy",
        "prior_taxonomy_family",
        "null",
        "bytes",
        "nan",
        "zero",
        "infinite",
        "count",
        "dimension",
    ],
)
def test_reader_refusals_match_original(mil, change):
    rows = copy.deepcopy(mil.rows)
    contract = copy.deepcopy(mil.contract)
    if change in {"identity", "image", "gps", "detector"}:
        key = {
            "identity": "identity_digest",
            "image": "image_sha256",
            "gps": "gps_start",
            "detector": "detector",
        }[change]
        rows[0][key] = -1 if change == "gps" else "altered"
    elif change == "missing":
        rows.pop()
    elif change == "order":
        rows.reverse()
    elif change == "duplicate":
        with sqlite3.connect(mil.path) as connection:
            connection.execute("UPDATE windows SET gps_start=100 WHERE detector='H1'")
        rows[1]["gps_start"] = 100
    elif change.startswith("prior_"):
        rows[0][
            {
                "prior_family": "global_family_id",
                "prior_taxonomy": "taxonomy",
                "prior_taxonomy_family": "taxonomy_family",
            }[change]
        ] = "prior"
    elif change == "count":
        contract["gates"]["exact_rows_by_detector"] = {"H1": 1, "L1": 3}
    elif change == "dimension":
        contract["gates"]["vector_dim"] = 3
    else:
        value = {
            "null": None,
            "bytes": b"bad",
            "nan": np.asarray([np.nan, 1], dtype="<f4").tobytes(),
            "zero": np.zeros(2, dtype="<f4").tobytes(),
            "infinite": np.asarray([np.inf, 1], dtype="<f4").tobytes(),
        }[change]
        with sqlite3.connect(mil.path) as connection:
            connection.execute(
                "UPDATE windows SET mil_vector=? WHERE gps_start=100", (value,)
            )
    before = snapshot(mil.path.parent)
    for call in (
        lambda: verifier._candidate_rows(mil.path, rows, contract),
        lambda: old._load_primary_mil_rows(
            mil.path, classified_rows=rows, contract=contract
        ),
    ):
        with pytest.raises(ContractError):
            call()
    assert snapshot(mil.path.parent) == before


@pytest.mark.parametrize("sidecar", ["-wal", "-shm", "-journal"])
def test_sqlite_sidecars_refused_without_repair(mil, sidecar):
    Path(str(mil.path) + sidecar).write_bytes(b"unverified")
    before = snapshot(mil.path.parent)
    with pytest.raises(ValueError, match="sidecar"):
        verifier._candidate_rows(mil.path, mil.rows, mil.contract)
    assert snapshot(mil.path.parent) == before


def test_wal_mode_without_sidecars_does_not_create_them(mil):
    with sqlite3.connect(mil.path) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    before = snapshot(mil.path.parent)
    verifier._candidate_rows(mil.path, mil.rows, mil.contract)
    assert snapshot(mil.path.parent) == before


def test_scores_do_not_enter_clustering(mil):
    bases, vectors, hashes = verifier._candidate_rows(mil.path, mil.rows, mil.contract)
    rows, metrics = tx.build_taxonomy_rows(
        bases, vectors, hashes, contract=mil.contract
    )
    changed = [{**r, "native_score": -1000.0 + i} for i, r in enumerate(bases)]
    other, other_metrics = tx.build_taxonomy_rows(
        changed, vectors, hashes, contract=mil.contract
    )
    assert metrics == other_metrics
    assert [r["global_family_id"] for r in rows] == [
        r["global_family_id"] for r in other
    ]
    assert [r["native_score"] for r in other] == [r["native_score"] for r in changed]


@pytest.fixture
def evidence(tmp_path, mil, monkeypatch):
    root = tmp_path / "repo"
    for relative in verifier._sources(ROOT):
        if relative.startswith(("src/dante_light/", "src/pipeline_v2_production/")):
            dest = root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, dest)
    class_dir = tmp_path / "classification" / "native_classification_fixture"
    class_dir.mkdir(parents=True)
    (class_dir / "run.lock").write_bytes(b"")
    threshold_dir = tmp_path / "thresholds" / "native_thresholds_fixture"
    threshold_dir.mkdir(parents=True)
    (threshold_dir / "run.lock").write_bytes(b"")
    class_path = class_dir / "primary_candidate.jsonl"
    class_path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in mil.rows),
        encoding="utf-8",
    )
    counts = {
        det: {
            cls: sum(
                r["detector"] == det and r["native_class"] == cls for r in mil.rows
            )
            for cls in ("BACKGROUND", "AMBIGUOUS", "ROBUST")
        }
        for det in ("H1", "L1")
    }
    class_summary = seal(
        {
            "status": "PASS_COMPLETE_O3A_NATIVE_CLASSIFICATION",
            "run_key": "fixture",
            "contract_digest": "b" * 64,
            "output_sha256": file_sha256(class_path),
            "output_row_digest": canonical_json_sha256(mil.rows),
            "row_total": 4,
            "counts_by_detector_and_class": counts,
        }
    )
    class_summary_path = class_dir / "native_classification_summary.json"
    write(class_summary_path, class_summary)
    compact = seal(
        {
            **class_summary,
            "status": "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION",
            "run_artifact_digest": class_summary["artifact_digest"],
            "summary_sha256": file_sha256(class_summary_path),
            "external_run_dir_wsl": str(class_dir),
        }
    )
    write(root / nc.COMPACT_REL, compact)
    primary_dir = tmp_path / "primary" / "primary_scan_fixture"
    primary_dir.mkdir(parents=True)
    database = primary_dir / "primary_scan.sqlite"
    shutil.copyfile(mil.path, database)
    primary = seal(
        {
            "status": "PASS_COMPLETE_O3A_PRIMARY_SCAN",
            "run_key": "fixture",
            "contract_digest": "c" * 64,
            "database": {
                "filename": database.name,
                "sha256": file_sha256(database),
                "size_bytes": database.stat().st_size,
            },
            "candidate_counts": {"H1": 2, "L1": 2},
            "candidate_total": 4,
        }
    )
    write(primary_dir / "primary_scan_summary.json", primary)
    class_contract = seal(
        {
            "references": {nc.COMPACT_REL: file_sha256(root / nc.COMPACT_REL)},
            "implementation_sources": {},
            "output": {"candidate_filename": class_path.name},
        },
        "contract_digest",
    )
    write(root / nc.CONTRACT_REL, class_contract)
    method_path = root / tx.O4A_METHOD_REL
    write(method_path, seal({"taxonomy": mil.contract["taxonomy"]}, "contract_digest"))
    contract = seal(
        {
            **mil.contract,
            "parent_primary_scan": {
                k: primary[k]
                for k in (
                    "artifact_digest",
                    "contract_digest",
                    "run_key",
                    "database",
                    "candidate_counts",
                    "candidate_total",
                )
            },
            "parent_native_classification": {
                k: compact[k]
                for k in (
                    "artifact_digest",
                    "contract_digest",
                    "run_key",
                    "run_artifact_digest",
                    "summary_sha256",
                    "output_sha256",
                    "output_row_digest",
                    "row_total",
                    "counts_by_detector_and_class",
                )
            },
            "runtime_environment_digest": "r" * 64,
            "pre_registered_expectation": {
                "prediction": "SINGLE_LINKAGE_CHAINING_DOMINANT_FAMILY_EXPECTED",
                "acceptance_cutoff": None,
                "discrepancy_policy": "REPORT_WITHOUT_RETUNING_METHOD",
            },
            "references": {
                nc.CONTRACT_REL: file_sha256(root / nc.CONTRACT_REL),
                nc.COMPACT_REL: file_sha256(root / nc.COMPACT_REL),
                tx.O4A_METHOD_REL: file_sha256(method_path),
            },
            "implementation_sources": {
                "src/dante_light/o3a_native_taxonomy.py": file_sha256(
                    root / "src/dante_light/o3a_native_taxonomy.py"
                )
            },
            "scientific_boundary": {
                "taxonomy_is_not_physical_coincidence": True,
                "global_significance_claim": False,
            },
            "output": {
                "summary_filename": "native_taxonomy_summary.json",
                "taxonomy_filename": "native_taxonomy.jsonl",
            },
        },
        "contract_digest",
    )
    write(root / tx.CONTRACT_REL, contract)
    monkeypatch.setattr(tx, "load_contract", lambda **kw: contract)
    monkeypatch.setattr(nc, "load_contract", lambda **kw: class_contract)
    original_execute = tx.execute
    original_writers = (tx._atomic_json, tx._atomic_jsonl)
    monkeypatch.setattr(
        tx, "_verified_sources", lambda *a, **kw: (database, copy.deepcopy(mil.rows))
    )
    external = tmp_path / "taxonomy"
    tx.execute(root=root, external_root=external)
    summary, directory = tx.execute(root=root, external_root=external, verify=True)
    arguments = dict(
        root=root,
        external_root=external,
        classification_external_root=class_dir.parent,
        threshold_external_root=threshold_dir.parent,
        rescore_external_root=tmp_path / "rescore",
        calibration_external_root=tmp_path / "calibration",
        index_external_root=tmp_path / "index",
        cohort_external_root=tmp_path / "cohort",
        primary_external_root=primary_dir.parent,
    )
    calls = []

    def parent_gate(
        *,
        root,
        external_root,
        threshold_external_root,
        parent_arguments,
        evidence,
        stack,
    ):
        assert root == arguments["root"]
        assert external_root == arguments["classification_external_root"]
        assert threshold_external_root == arguments["threshold_external_root"]
        assert parent_arguments == {
            "external_root": arguments["rescore_external_root"],
            **{
                k: arguments[k]
                for k in (
                    "calibration_external_root",
                    "index_external_root",
                    "cohort_external_root",
                    "primary_external_root",
                )
            },
        }
        calls.append(True)
        for label, run_dir in (
            ("classification", class_dir),
            ("threshold", threshold_dir),
        ):
            stack.enter_context(verifier.decisions._persistent_lock(run_dir))
            evidence.read(label + "_lock", run_dir / "run.lock")
        evidence.sealed("classification_summary", class_summary_path, "artifact_digest")
        evidence.sealed(
            "scan_summary", primary_dir / "primary_scan_summary.json", "artifact_digest"
        )
        verifier.decisions.scores.parents._pin(
            evidence, "scan_database", database, primary["database"]["sha256"]
        )
        return class_summary, class_dir

    monkeypatch.setattr(verifier.decisions, "_classification_gate", parent_gate)
    for module, names in (
        (
            tx,
            (
                "execute",
                "_verified_sources",
                "_candidate_rows",
                "_atomic_json",
                "_atomic_jsonl",
                "freeze_contract",
            ),
        ),
        (nc, ("execute",)),
        (tx.ps, ("verify_primary_scan",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    return SimpleNamespace(
        root=root,
        args=arguments,
        contract=contract,
        directory=directory,
        summary=summary,
        class_summary=class_summary,
        compact=compact,
        database=database,
        primary=primary,
        class_dir=class_dir,
        threshold_dir=threshold_dir,
        calls=calls,
        original_execute=original_execute,
        original_writers=original_writers,
        rows=mil.rows,
    )


@POSIX
def test_exact_legacy_execute_summary_and_scoped_receipt(evidence):
    before = snapshot(evidence.root.parent)
    result = verifier.verify_taxonomy_evidence(**evidence.args)
    assert result["legacy_artifact_digest"] == evidence.summary["artifact_digest"]
    assert result["status"] == "PASS_O3A_READ_ONLY_TAXONOMY_DETERMINISTIC_REPLAY_ONLY"
    assert result["taxonomy_replay_executed"] is True
    assert result["threshold_bootstrap_replay_executed"] is True
    assert result["classification_replay_executed"] is True
    for field in (
        "historical_evidence_mutated",
        "raw_score_replay_executed",
        "encoder_executed",
        "source_fetch_executed",
        "full_workflow_verified",
        "global_upstream_quiescence_verified",
    ):
        assert result[field] is False
    assert len(result["source_bindings"]) == 34
    assert evidence.calls == [True]
    assert "family_metrics" not in result and "counts_by_detector" not in result
    assert seal(result, "receipt_digest") == result
    assert snapshot(evidence.root.parent) == before


def reject(evidence, match=None):
    before = snapshot(evidence.root.parent)
    with pytest.raises((ValueError, OSError, KeyError), match=match):
        verifier.verify_taxonomy_evidence(**evidence.args)
    assert snapshot(evidence.root.parent) == before


@POSIX
@pytest.mark.parametrize(
    "field",
    [
        "run_key",
        "contract_digest",
        "runtime_environment_digest",
        "parent_primary_scan_artifact_digest",
        "parent_native_classification_artifact_digest",
        "taxonomy",
        "pre_registered_expectation",
        "row_total",
        "counts_by_detector",
        "counts_by_native_class",
        "family_metrics",
        "largest_family_fraction",
        "family_id_count",
        "source_database_sha256",
        "source_classification_sha256",
        "output_sha256",
        "output_row_digest",
        "scientific_boundary",
        "unexpected",
    ],
)
def test_resealed_summary_semantic_changes_refused(evidence, field):
    value = dict(evidence.summary)
    value[field] = "altered"
    write(evidence.directory / "native_taxonomy_summary.json", seal(value))
    reject(evidence, "deterministic replay")


@POSIX
@pytest.mark.parametrize(
    "field",
    [
        "status",
        "run_artifact_digest",
        "summary_sha256",
        "taxonomy",
        "family_metrics",
        "external_run_dir_wsl",
        "unexpected",
    ],
)
def test_resealed_compact_changes_refused(evidence, field):
    path = evidence.root / tx.COMPACT_REL
    value = json.loads(path.read_bytes())
    value[field] = (
        str(evidence.directory.parent / "wrong")
        if field == "external_run_dir_wsl"
        else "altered"
    )
    write(path, seal(value))
    reject(evidence, "compact")


@POSIX
@pytest.mark.parametrize(
    "marker",
    [
        "failure.json",
        "failures.json",
        "controller.lock",
        "part.partial",
        "part.tmp",
        "part.part",
    ],
)
def test_stage_markers_refused(evidence, marker):
    (evidence.directory / marker).write_bytes(b"preserved")
    reject(evidence, "failure/active|partial")


@POSIX
def test_classified_output_change_refused(evidence):
    with (evidence.class_dir / "primary_candidate.jsonl").open("ab") as stream:
        stream.write(b" \n")
    reject(evidence, "hash mismatch")


@POSIX
@pytest.mark.parametrize(
    "filename", ["native_taxonomy.jsonl", "native_taxonomy_summary.json", "run.lock"]
)
def test_missing_stage_file_refused(evidence, filename):
    (evidence.directory / filename).unlink()
    reject(evidence)


@POSIX
def test_output_bytes_change_refused(evidence):
    with (evidence.directory / "native_taxonomy.jsonl").open("ab") as stream:
        stream.write(b"\n")
    reject(evidence, "hash mismatch")


@POSIX
@pytest.mark.parametrize(
    "parent", ["parent_primary_scan", "parent_native_classification"]
)
def test_resealed_parent_identity_change_refused(evidence, parent):
    evidence.contract[parent]["run_key"] = "wrong"
    evidence.contract.update(seal(evidence.contract, "contract_digest"))
    write(evidence.root / tx.CONTRACT_REL, evidence.contract)
    rekeyed = tx._run_dir(evidence.contract, evidence.args["external_root"])
    evidence.directory.rename(rekeyed)
    evidence.directory = rekeyed
    reject(evidence, "parent changed")


@POSIX
def test_source_changed_refused(evidence):
    path = evidence.root / "src/dante_light/o3a_native_taxonomy.py"
    with path.open("ab") as stream:
        stream.write(b"\n# altered\n")
    reject(evidence, "source mismatch")


@POSIX
def test_mid_read_input_change_refused(evidence, monkeypatch):
    actual = tx.build_taxonomy_rows

    def changed(*a, **kw):
        result = actual(*a, **kw)
        with (evidence.class_dir / "primary_candidate.jsonl").open("ab") as stream:
            stream.write(b"\n")
        return result

    monkeypatch.setattr(tx, "build_taxonomy_rows", changed)
    with pytest.raises(ValueError, match="changed during"):
        verifier.verify_taxonomy_evidence(**evidence.args)


@POSIX
def test_parent_and_taxonomy_locks_held_during_numerical_builder(evidence, monkeypatch):
    import fcntl

    actual = tx.build_taxonomy_rows

    def held(*a, **kw):
        for directory in (
            evidence.directory,
            evidence.class_dir,
            evidence.threshold_dir,
        ):
            with (directory / "run.lock").open("rb") as stream:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return actual(*a, **kw)

    monkeypatch.setattr(tx, "build_taxonomy_rows", held)
    verifier.verify_taxonomy_evidence(**evidence.args)
    for directory in (evidence.directory, evidence.class_dir, evidence.threshold_dir):
        with (directory / "run.lock").open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


@POSIX
def test_busy_stage_refused_and_error_releases_parent_locks(evidence):
    import fcntl

    with (evidence.directory / "run.lock").open("rb") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reject(evidence, "busy")
    (evidence.directory / "native_taxonomy.jsonl").write_bytes(b"altered")
    reject(evidence, "hash mismatch")
    for directory in (evidence.directory, evidence.class_dir, evidence.threshold_dir):
        with (directory / "run.lock").open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


@POSIX
def test_replaced_lock_refused_at_exit(evidence, monkeypatch):
    actual = verifier._Evidence.unchanged

    def changed(instance):
        actual(instance)
        other = evidence.directory / "other"
        other.write_bytes(b"")
        other.replace(evidence.directory / "run.lock")

    monkeypatch.setattr(verifier._Evidence, "unchanged", changed)
    with pytest.raises(ValueError, match="lock changed"):
        verifier.verify_taxonomy_evidence(**evidence.args)


@POSIX
def test_singleton_id_collision_refused(evidence, monkeypatch):
    actual = tx.build_taxonomy_rows

    def collision(*a, **kw):
        rows, metrics = actual(*a, **kw)
        for row in rows[:2]:
            row.update(global_family_id="Singleton_100", morphology_family_size=1)
        return rows, metrics

    monkeypatch.setattr(tx, "build_taxonomy_rows", collision)
    reject(evidence, "singleton IDs collide")


@POSIX
def test_cli_fixture_success_and_refusal(evidence, capsys):
    path = ROOT / "scripts/verify_dante_o3a_taxonomy_evidence.py"
    spec = importlib.util.spec_from_file_location("taxonomy_cli_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = []
    for key, value in evidence.args.items():
        args += [
            "--repository-root" if key == "root" else "--" + key.replace("_", "-"),
            str(value),
        ]
    before = snapshot(evidence.root.parent)
    assert module.main(args) == 0
    assert json.loads(capsys.readouterr().out)["taxonomy_replay_executed"] is True
    assert snapshot(evidence.root.parent) == before
    (evidence.directory / "failure.json").write_bytes(b"preserve")
    before = snapshot(evidence.root.parent)
    assert module.main(args) == 1
    assert (
        json.loads(capsys.readouterr().out)["status"]
        == "FAIL_CLOSED_O3A_TAXONOMY_EVIDENCE"
    )
    assert snapshot(evidence.root.parent) == before


@pytest.mark.parametrize(
    "flag", ["--run", "--freeze", "--repair", "--resume", "--output"]
)
def test_mutation_flags_refused(flag):
    args = [
        sys.executable,
        "-B",
        str(ROOT / "scripts/verify_dante_o3a_taxonomy_evidence.py"),
    ]
    for name in (
        "external-root",
        "classification-external-root",
        "threshold-external-root",
        "rescore-external-root",
        "calibration-external-root",
        "index-external-root",
        "cohort-external-root",
        "primary-external-root",
    ):
        args += ["--" + name, str(ROOT)]
    result = subprocess.run(args + [flag], capture_output=True, text=True)
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows refusal test")
def test_windows_refusal_before_source_or_evidence_reads(monkeypatch):
    monkeypatch.setattr(verifier, "_sources", forbidden)
    arguments = {
        k: ROOT
        for k in (
            "root",
            "external_root",
            "classification_external_root",
            "threshold_external_root",
            "rescore_external_root",
            "calibration_external_root",
            "index_external_root",
            "cohort_external_root",
            "primary_external_root",
        )
    }
    with pytest.raises(ValueError, match="POSIX/WSL"):
        verifier.verify_taxonomy_evidence(**arguments)


def test_actual_frozen_taxonomy_contract_load_without_history():
    assert len(verifier._sources(ROOT)) == 34
    if os.name == "nt":
        with pytest.raises(ContractError):
            tx.load_contract(root=ROOT)
    else:
        assert tx.load_contract(root=ROOT)["contract_digest"]


@POSIX
def test_taxonomy_links_actual_threshold_classification_replay(tmp_path, monkeypatch):
    # Reuse scaled 08.10 evidence; only RESCORE ancestry remains isolated here.
    from collections import Counter

    spec = importlib.util.spec_from_file_location(
        "decision_fixture_linked",
        ROOT / "tests/test_dante_workflow_o3a_decision_verification.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parent = module.evidence.__wrapped__(tmp_path, monkeypatch)
    root = parent.root
    for relative in (
        "src/dante_light/o3a_native_taxonomy.py",
        "src/dante_light/o4a_corrected_native_taxonomy.py",
    ):
        shutil.copyfile(ROOT / relative, root / relative)
    rows = [
        json.loads(line)
        for line in (
            parent.class_dir / parent.class_contract["output"]["candidate_filename"]
        )
        .read_bytes()
        .splitlines()
    ]
    primary_dir = tmp_path / "primary" / "primary_scan_linked"
    primary_dir.mkdir(parents=True)
    database = primary_dir / "primary_scan.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE windows(detector TEXT,gps_start INTEGER,identity_digest TEXT,image_sha256 TEXT,mil_vector BLOB,is_candidate INTEGER)"
        )
        # The scaled upstream fixture has no image column in its classified rows;
        # NULL matches its missing field under the unchanged original reader.
        connection.executemany(
            "INSERT INTO windows VALUES(?,?,?,?,?,1)",
            [
                (
                    r["detector"],
                    r["gps_start"],
                    r["identity_digest"],
                    None,
                    np.asarray([1, 0], dtype="<f4").tobytes(),
                )
                for r in rows
            ],
        )
    primary = seal(
        {
            "status": "PASS_COMPLETE_O3A_PRIMARY_SCAN",
            "run_key": "linked",
            "contract_digest": "p" * 64,
            "candidate_counts": {"H1": 5, "L1": 5},
            "candidate_total": 10,
            "database": {
                "filename": database.name,
                "sha256": file_sha256(database),
                "size_bytes": database.stat().st_size,
            },
        }
    )
    primary_path = primary_dir / "primary_scan_summary.json"
    write(primary_path, primary)
    class_compact = json.loads((root / nc.COMPACT_REL).read_bytes())
    contract = seal(
        {
            "taxonomy": {
                "representation": "o3a_primary_scan_mil_v1",
                "distance_threshold": 0.25,
                "linkage": "single",
                "flat_cluster_criterion": "distance",
            },
            "gates": {
                "vector_dim": 2,
                "vector_blob_bytes": 8,
                "exact_total_rows": 10,
                "exact_rows_by_detector": {"H1": 5, "L1": 5},
            },
            "parent_primary_scan": primary,
            "parent_native_classification": {
                k: class_compact[k]
                for k in (
                    "artifact_digest",
                    "contract_digest",
                    "run_key",
                    "run_artifact_digest",
                    "summary_sha256",
                    "output_sha256",
                    "output_row_digest",
                    "row_total",
                    "counts_by_detector_and_class",
                )
            },
            "runtime_environment_digest": parent.classification[
                "runtime_environment_digest"
            ],
            "pre_registered_expectation": {
                "prediction": "SINGLE_LINKAGE_CHAINING_DOMINANT_FAMILY_EXPECTED",
                "acceptance_cutoff": None,
            },
            "references": {nc.COMPACT_REL: file_sha256(root / nc.COMPACT_REL)},
            "implementation_sources": {
                "src/dante_light/o3a_native_taxonomy.py": file_sha256(
                    root / "src/dante_light/o3a_native_taxonomy.py"
                )
            },
            "scientific_boundary": {"global_significance_claim": False},
            "output": {
                "summary_filename": "native_taxonomy_summary.json",
                "taxonomy_filename": "native_taxonomy.jsonl",
            },
        },
        "contract_digest",
    )
    write(root / tx.CONTRACT_REL, contract)
    monkeypatch.setattr(tx, "load_contract", lambda **kw: contract)
    bases, vectors, hashes = verifier._candidate_rows(database, rows, contract)
    output_rows, metrics = tx.build_taxonomy_rows(
        bases, vectors, hashes, contract=contract
    )
    external = tmp_path / "taxonomy"
    directory = tx._run_dir(contract, external)
    directory.mkdir(parents=True)
    (directory / "run.lock").write_bytes(b"")
    output = directory / "native_taxonomy.jsonl"
    output.write_text(
        "".join(
            json.dumps(r, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for r in output_rows
        ),
        encoding="utf-8",
    )
    body = {
        "schema_version": 1,
        "status": "PASS_COMPLETE_O3A_NATIVE_TAXONOMY",
        "contract_digest": contract["contract_digest"],
        "run_key": directory.name.removeprefix("native_taxonomy_"),
        "runtime_environment_digest": contract["runtime_environment_digest"],
        "parent_primary_scan_artifact_digest": primary["artifact_digest"],
        "parent_native_classification_artifact_digest": class_compact[
            "artifact_digest"
        ],
        "taxonomy": contract["taxonomy"],
        "pre_registered_expectation": contract["pre_registered_expectation"],
        "row_total": len(output_rows),
        "counts_by_detector": dict(
            sorted(Counter(r["detector"] for r in output_rows).items())
        ),
        "counts_by_native_class": dict(
            sorted(Counter(r["native_class"] for r in output_rows).items())
        ),
        "family_metrics": metrics,
        "largest_family_fraction": metrics["max_family_size"] / len(output_rows),
        "family_id_count": len({r["global_family_id"] for r in output_rows}),
        "source_database_sha256": file_sha256(database),
        "source_classification_sha256": class_compact["output_sha256"],
        "output_sha256": file_sha256(output),
        "output_row_digest": canonical_json_sha256(output_rows),
        "scientific_boundary": contract["scientific_boundary"],
    }
    summary = seal(body)
    summary_path = directory / "native_taxonomy_summary.json"
    write(summary_path, summary)
    write(
        root / tx.COMPACT_REL,
        seal(
            {
                **body,
                "status": "PASS_VERIFIED_O3A_NATIVE_TAXONOMY",
                "external_run_dir_wsl": str(directory),
                "run_artifact_digest": summary["artifact_digest"],
                "summary_sha256": file_sha256(summary_path),
            }
        ),
    )
    isolated = verifier.decisions.scores._rescore_gate
    calls = []

    def with_scan(**kw):
        result = isolated(**kw)
        e = kw["evidence"]
        e.sealed("scan_summary", primary_path, "artifact_digest")
        verifier.decisions.scores.parents._pin(
            e, "scan_database", database, primary["database"]["sha256"]
        )
        return result

    actual_compute = tx.nt.compute_threshold
    actual_classify = nc.classify_rows

    def record_compute(vector, *, method):
        calls.append("threshold")
        return actual_compute(vector, method=method)

    def record_classify(*a, **kw):
        calls.append("classification")
        return actual_classify(*a, **kw)

    monkeypatch.setattr(verifier.decisions.scores, "_rescore_gate", with_scan)
    monkeypatch.setattr(tx.nt, "compute_threshold", record_compute)
    monkeypatch.setattr(nc, "classify_rows", record_classify)
    for name in (
        "execute",
        "_verified_sources",
        "_candidate_rows",
        "_atomic_json",
        "_atomic_jsonl",
    ):
        monkeypatch.setattr(tx, name, forbidden)
    arguments = module.arguments(parent, "classification")
    arguments.pop("stage")
    arguments["classification_external_root"] = arguments.pop("external_root")
    arguments["external_root"] = external
    before = snapshot(tmp_path)
    result = verifier.verify_taxonomy_evidence(**arguments)
    assert result["taxonomy_replay_executed"] is True
    assert calls == ["threshold", "threshold", "classification"]
    assert len(parent.calls) == 1
    assert snapshot(tmp_path) == before
