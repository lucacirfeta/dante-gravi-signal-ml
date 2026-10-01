"""Retained original coincidence parity; main taxonomy ancestry isolated explicitly."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from src.dante_light import o3a_native_coincidence as old
from src.dante_light import o3a_native_classification as nc
from src.dante_light import o3a_native_calibration_cohort as calibration
from src.dante_light import o3a_native_taxonomy as tx
from src.dante_light.contracts import canonical_json_sha256, ContractError
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_workflow import o3a_coincidence_verification as verifier

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
    raise AssertionError("productive verifier, fetch or measurement invoked")


@pytest.fixture
def evidence(tmp_path, monkeypatch, request):
    linked = bool(getattr(request, "param", False))
    root = tmp_path / "repo"
    for relative in verifier._sources(ROOT):
        if relative.startswith(("src/dante_light/", "src/pipeline_v2_production/")):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, path)
    rows = [
        {
            "detector": d,
            "gps_start": gps,
            "native_class": cls,
            "native_score": score,
            "identity_digest": f"{d}-{gps}",
            "image_sha256": f"img-{d}-{gps}",
        }
        for d, gps, cls, score in (
            ("H1", 100, "ROBUST", 0.9),
            ("H1", 200, "BACKGROUND", 0.1),
            ("L1", 300, "AMBIGUOUS", 0.5),
            ("L1", 400, "ROBUST", 0.95),
        )
    ]
    class_dir = tmp_path / "classification" / "native_classification_fixture"
    class_dir.mkdir(parents=True)
    (class_dir / "run.lock").write_bytes(b"")
    class_path = class_dir / "native_classified_candidates.jsonl"
    class_path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
    )
    classified = seal(
        {
            "status": "PASS_COMPLETE_O3A_NATIVE_CLASSIFICATION",
            "run_key": "fixture",
            "output_sha256": file_sha256(class_path),
            "output_row_digest": canonical_json_sha256(rows),
        }
    )
    write(class_dir / "native_classification_summary.json", classified)
    class_contract = seal(
        {
            "output": {"candidate_filename": class_path.name},
            "references": {},
            "implementation_sources": {},
        },
        "contract_digest",
    )
    write(root / nc.CONTRACT_REL, class_contract)
    compact = seal(
        {
            **classified,
            "status": "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION",
            "run_artifact_digest": classified["artifact_digest"],
            "summary_sha256": file_sha256(
                class_dir / "native_classification_summary.json"
            ),
            "external_run_dir_wsl": str(class_dir),
        }
    )
    write(root / nc.COMPACT_REL, compact)
    database = tmp_path / "primary" / "primary_scan_fixture" / "primary_scan.sqlite"
    database.parent.mkdir(parents=True)
    inventory = seal(
        {
            "urls_by_detector": {
                d: [f"https://gwosc.org/{d[0]}-{d}_GWOSC_O3a_4KHZ_R1-0-4096.hdf5"]
                for d in ("H1", "L1")
            }
        },
        "inventory_digest",
    )
    write(root / old.INVENTORY_REL, inventory)
    frames = {d: old._inventory_frames(inventory, d) for d in ("H1", "L1")}
    h1 = {**frames["H1"][0], "detector": "H1", "sha256": "a" * 64, "size_bytes": 100}
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE raw_frames(detector TEXT,gps_start INTEGER,gps_end INTEGER,filename TEXT,url TEXT,sha256 TEXT,size_bytes INTEGER)"
        )
        connection.execute(
            "INSERT INTO raw_frames VALUES(?,?,?,?,?,?,?)",
            tuple(
                h1[k]
                for k in (
                    "detector",
                    "gps_start",
                    "gps_end",
                    "filename",
                    "url",
                    "sha256",
                    "size_bytes",
                )
            ),
        )
        if linked:
            connection.execute(
                "CREATE TABLE windows(detector TEXT,gps_start INTEGER,identity_digest TEXT,image_sha256 TEXT,mil_vector BLOB,is_candidate INTEGER)"
            )
            angles = np.deg2rad([0, 35, 70, 180])
            vectors = np.asarray([[np.cos(a), np.sin(a)] for a in angles], dtype="<f4")
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
    primary = seal(
        {
            "run_key": "fixture",
            "database": {"filename": database.name, "sha256": file_sha256(database)},
        }
    )
    write(database.parent / "primary_scan_summary.json", primary)
    write(root / old.PRIMARY_REL, primary)
    taxonomy_dir = tmp_path / "taxonomy" / "native_taxonomy_fixture"
    taxonomy_dir.mkdir(parents=True)
    (taxonomy_dir / "run.lock").write_bytes(b"")
    taxonomy_summary = seal(
        {"status": "PASS_COMPLETE_O3A_NATIVE_TAXONOMY", "run_key": "fixture"}
    )
    write(taxonomy_dir / "native_taxonomy_summary.json", taxonomy_summary)
    if not linked:
        write(
            root / old.TAXONOMY_REL,
            seal({"status": "PASS_VERIFIED_O3A_NATIVE_TAXONOMY"}),
        )
    if linked:
        taxonomy_contract = seal(
            {
                "parent_primary_scan": primary,
                "parent_native_classification": compact,
                "runtime_environment_digest": "r" * 64,
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
                "pre_registered_expectation": {
                    "prediction": "SINGLE_LINKAGE_CHAINING_DOMINANT_FAMILY_EXPECTED",
                    "acceptance_cutoff": None,
                },
                "scientific_boundary": {"global_significance_claim": False},
                "references": {},
                "implementation_sources": {},
                "output": {
                    "summary_filename": "native_taxonomy_summary.json",
                    "taxonomy_filename": "native_taxonomy.jsonl",
                },
            },
            "contract_digest",
        )
        write(root / tx.CONTRACT_REL, taxonomy_contract)
        monkeypatch.setattr(tx, "load_contract", lambda **kw: taxonomy_contract)
        monkeypatch.setattr(
            tx, "_verified_sources", lambda *a, **kw: (database, copy.deepcopy(rows))
        )
        tx.execute(root=root, external_root=taxonomy_dir.parent)
        taxonomy_summary, taxonomy_dir = tx.execute(
            root=root, external_root=taxonomy_dir.parent, verify=True
        )
    runtime = {"runtime_environment": {"environment_digest": "r" * 64}}
    write(root / old.RUNTIME_REL, runtime)
    parents = {}
    for name, relative in (
        ("native_classification", nc.COMPACT_REL),
        ("native_taxonomy", tx.COMPACT_REL),
        ("primary_scan", old.PRIMARY_REL),
        ("o3a_source_inventory", old.INVENTORY_REL),
        ("o3a_runtime", old.RUNTIME_REL),
    ):
        value = json.loads((root / relative).read_text())
        parents[name] = {"path": relative, "sha256": file_sha256(root / relative)}
        if "artifact_digest" in value:
            parents[name]["artifact_digest"] = value["artifact_digest"]
    contract = seal(
        {
            "parents": parents,
            "implementation_sources": {
                "src/dante_light/o3a_native_coincidence.py": file_sha256(
                    root / "src/dante_light/o3a_native_coincidence.py"
                )
            },
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
            "population": {
                "exact_counts": {
                    "primary": {"H1": 1, "L1": 1, "total": 2},
                    "diagnostic": {"H1": 0, "L1": 1, "total": 1},
                    "excluded": {"H1": 1, "L1": 0, "total": 1},
                }
            },
            "measurement": {
                "whitening_pad_s": 4,
                "segment_duration_s": 32,
                "null_shifts_s": [1, 2, 4, 8, -1, -2, -4, -8],
                "threshold_quantile_percent": 99.0,
                "threshold_quantile_method": "linear",
            },
            "execution": {"batch_size": 2, "raw_cache_limit_bytes": 1000},
            "pre_registered_limitation": {
                "global_look_elsewhere_control": False,
                "no_post_hoc_retuning": True,
            },
            "scientific_boundary": {
                "diagnostic_only": True,
                "global_significance_claim": False,
            },
        },
        "contract_digest",
    )
    write(root / old.CONTRACT_REL, contract)
    monkeypatch.setattr(old, "load_contract", lambda **kw: contract)
    monkeypatch.setattr(old, "load_runtime_contract", lambda **kw: runtime)
    monkeypatch.setattr(old, "load_source_inventory", lambda **kw: inventory)
    monkeypatch.setattr(calibration, "load_source_inventory", lambda **kw: inventory)
    monkeypatch.setattr(nc, "load_contract", lambda **kw: class_contract)
    original_preflight = old._preflight_details
    # Exact original preflight on disposable SQLite and class evidence, compared
    # later against the immutable replacement; no measurement/transport involved.
    legacy_root = tmp_path / "legacy_parents"
    shutil.copytree(class_dir, legacy_root / class_dir.name)
    shutil.copytree(database.parent, legacy_root / database.parent.name)
    preflight, plans, seeds = original_preflight(
        root=root, external_root=legacy_root, contract=contract
    )
    key = old._run_key(contract, preflight)
    external = tmp_path / "coincidence"
    directory = external / ("native_coincidence_" + key)
    directory.mkdir(parents=True)
    (directory / "run.lock").write_bytes(b"")
    write(directory / "preflight.json", preflight)
    receipt = seal(
        {
            "status": "PINNED_O3A_COINCIDENCE_NEW_RAW",
            "frames": {
                "L1|" + frames["L1"][0]["filename"]: {
                    "sha256": "b" * 64,
                    "size_bytes": 120,
                    "url": frames["L1"][0]["url"],
                }
            },
        },
        "receipt_digest",
    )
    write(directory / "new_source_frame_receipt.json", receipt)
    pinned_plans = copy.deepcopy(plans)
    old._pin_new_frames(
        pinned_plans, run_dir=directory, contract=contract, allow_download=False
    )
    batches = old._batch_seed_rows(seeds, contract["execution"]["batch_size"])
    plan_map = {(p["detector"], p["gps_start"]): p for p in pinned_plans}
    plan_batches = [old._batch_plan_rows(batch, plan_map) for batch in batches]
    last_use, sources = old._frame_dependency_order(plan_batches)
    cache_plan = old._cache_plan(
        plan_batches=plan_batches,
        last_use=last_use,
        sources=sources,
        initially_cached={tuple(k.split("|", 1)) for k in receipt["frames"]},
        contract=contract,
        source_plan_pinned_digest=canonical_json_sha256(pinned_plans),
        ordered_seed_digest=preflight["seed_population_digest"],
    )
    write(directory / "cache_plan.json", cache_plan)
    for number, batch in enumerate(batches):
        events = []
        for seed in batch:
            null = [0.1, 0.2] if seed["native_class"] == "ROBUST" else [0.8, 0.9]
            cc = max(null)  # Exact equality must remain NOT exceeded.
            events.append(
                {
                    "detector": seed["detector"],
                    "gps_start": seed["gps_start"],
                    "seed_identity_digest": seed["identity_digest"],
                    "seed_native_score": seed["native_score"],
                    "seed_native_class": seed["native_class"],
                    "population": "primary"
                    if seed["native_class"] == "ROBUST"
                    else "diagnostic",
                    "partner_class_consulted": False,
                    "measurement_status": "MEASURED",
                    "cc_onsource": cc,
                    "cc_null_values": null,
                    "n_null": len(null),
                    "cc_null_max": max(null),
                    "cc_null_mean": float(np.mean(null)),
                    "per_event_null_exceeded": False,
                }
            )
        old._write_shard(directory, number, batch, events, contract, key)
    summary = old._finish(
        run_dir=directory,
        preflight=preflight,
        plans=pinned_plans,
        seed_batches=batches,
        contract=contract,
        run_key=key,
        cache_plan_digest=cache_plan["cache_plan_digest"],
    )
    monkeypatch.setattr(
        old,
        "_preflight_details",
        lambda **kw: (
            copy.deepcopy(preflight),
            copy.deepcopy(plans),
            copy.deepcopy(seeds),
        ),
    )
    legacy_verify = old.verify_native_coincidence
    assert legacy_verify(root=root, external_root=external)[0] == summary
    calls = []
    arguments = {
        "root": root,
        "external_root": external,
        "taxonomy_external_root": taxonomy_dir.parent,
        "classification_external_root": class_dir.parent,
        **{
            name + "_external_root": tmp_path / name
            for name in ("threshold", "rescore", "calibration", "index", "cohort")
        },
        "primary_external_root": database.parent.parent,
    }

    def parent_gate(
        *,
        root,
        external_root,
        classification_external_root,
        threshold_external_root,
        parent_arguments,
        evidence,
        stack,
    ):
        assert (
            root == arguments["root"]
            and external_root == arguments["taxonomy_external_root"]
        )
        assert classification_external_root == arguments["classification_external_root"]
        assert threshold_external_root == arguments["threshold_external_root"]
        assert parent_arguments["external_root"] == arguments["rescore_external_root"]
        for name in ("calibration", "index", "cohort", "primary"):
            assert (
                parent_arguments[name + "_external_root"]
                == arguments[name + "_external_root"]
            )
        if not linked:
            stack.enter_context(verifier.decisions._persistent_lock(taxonomy_dir))
        stack.enter_context(verifier.decisions._persistent_lock(class_dir))
        evidence.read("taxonomy_lock", taxonomy_dir / "run.lock")
        evidence.read("classification_lock", class_dir / "run.lock")
        evidence.sealed(
            "classification_summary",
            class_dir / "native_classification_summary.json",
            "artifact_digest",
        )
        evidence.sealed(
            "scan_summary",
            database.parent / "primary_scan_summary.json",
            "artifact_digest",
        )
        verifier.decisions.scores.parents._pin(
            evidence, "scan_database", database, primary["database"]["sha256"]
        )
        calls.append(True)
        return taxonomy_summary, taxonomy_dir

    if linked:

        def classification_gate(
            *,
            root,
            external_root,
            threshold_external_root,
            parent_arguments,
            evidence,
            stack,
        ):
            parent_gate(
                root=root,
                external_root=arguments["taxonomy_external_root"],
                classification_external_root=external_root,
                threshold_external_root=threshold_external_root,
                parent_arguments=parent_arguments,
                evidence=evidence,
                stack=stack,
            )
            return classified, class_dir

        monkeypatch.setattr(
            verifier.decisions, "_classification_gate", classification_gate
        )
        for name in (
            "execute",
            "_verified_sources",
            "_candidate_rows",
            "_atomic_json",
            "_atomic_jsonl",
        ):
            monkeypatch.setattr(tx, name, forbidden)
    else:
        monkeypatch.setattr(verifier.taxonomy, "_taxonomy_gate", parent_gate)
    for name in (
        "verify_native_coincidence",
        "run_native_coincidence",
        "freeze_contract",
        "archive_infrastructure_failure",
        "_atomic_json",
        "_atomic_jsonl",
        "_download_frame",
        "_read_context",
        "_measure_batch",
        "_load_scorer",
        "preflight_sources",
        "_preflight_details",
    ):
        monkeypatch.setattr(old, name, forbidden)
    return SimpleNamespace(
        root=root,
        args=arguments,
        directory=directory,
        class_dir=class_dir,
        taxonomy_dir=taxonomy_dir,
        contract=contract,
        summary=summary,
        database=database,
        primary=primary,
        classified=classified,
        class_contract=class_contract,
        rows=rows,
        preflight=preflight,
        plans=plans,
        seeds=seeds,
        calls=calls,
        original_preflight=original_preflight,
        legacy_root=legacy_root,
    )


@POSIX
def test_exact_legacy_reconstruction_no_mutations_or_outcome_disclosure(evidence):
    before = snapshot(evidence.root.parent)
    result = verifier.verify_coincidence_evidence(**evidence.args)
    assert result["legacy_artifact_digest"] == evidence.summary["artifact_digest"]
    assert (
        result["status"] == "PASS_O3A_READ_ONLY_COINCIDENCE_RETAINED_LEDGER_REPLAY_ONLY"
    )
    assert result["retained_null_ledger_replay_executed"] is True
    assert len(result["source_bindings"]) == 39
    for flag in (
        "historical_evidence_mutated",
        "raw_score_replay_executed",
        "raw_correlation_replay_executed",
        "preprocessing_replay_executed",
        "encoder_executed",
        "source_fetch_executed",
        "full_workflow_verified",
        "global_upstream_quiescence_verified",
    ):
        assert result[flag] is False
    assert "event_summary" not in result and "primary_null_p99" not in result
    assert evidence.calls == [True]
    assert snapshot(evidence.root.parent) == before


@POSIX
def test_immutable_preflight_parity_and_primary_only_null(evidence):
    from contextlib import ExitStack

    from src.dante_workflow.o3a_initial_verification import _Evidence

    tracked = _Evidence()
    with ExitStack() as stack:
        verifier.taxonomy._taxonomy_gate(
            root=evidence.root,
            external_root=evidence.args["taxonomy_external_root"],
            classification_external_root=evidence.args["classification_external_root"],
            threshold_external_root=evidence.args["threshold_external_root"],
            parent_arguments={
                "external_root": evidence.args["rescore_external_root"],
                **{
                    k: v
                    for k, v in evidence.args.items()
                    if k
                    in (
                        "calibration_external_root",
                        "index_external_root",
                        "cohort_external_root",
                        "primary_external_root",
                    )
                },
            },
            evidence=tracked,
            stack=stack,
        )
        assert verifier._preflight(evidence.root, evidence.contract, tracked) == (
            evidence.preflight,
            evidence.plans,
            evidence.seeds,
        )
    assert evidence.summary["event_summary"]["primary_null_p99"] == 0.2
    assert (
        evidence.summary["event_summary"]["primary"]["primary_threshold_exceeded"] == 0
    )
    assert (
        evidence.summary["event_summary"]["diagnostic"]["primary_threshold_exceeded"]
        == 1
    )


def reject(evidence, match=None):
    before = snapshot(evidence.root.parent)
    with pytest.raises((ValueError, KeyError, TypeError, OSError), match=match):
        verifier.verify_coincidence_evidence(**evidence.args)
    assert snapshot(evidence.root.parent) == before


@POSIX
@pytest.mark.parametrize(
    "field",
    [
        "status",
        "schema_version",
        "run_key",
        "contract_digest",
        "preflight_digest",
        "source_plan_pinned_digest",
        "cache_plan_digest",
        "runtime_environment_digest",
        "population",
        "measurement",
        "pre_registered_limitation",
        "event_summary",
        "outputs",
        "gates",
        "extra",
    ],
)
def test_resealed_full_summary_drift_refused(evidence, field):
    changed = copy.deepcopy(evidence.summary)
    changed[field] = "altered"
    write(evidence.directory / "native_coincidence_summary.json", seal(changed))
    reject(evidence, "full summary")


@POSIX
@pytest.mark.parametrize(
    "field",
    [
        "status",
        "run_artifact_digest",
        "summary_sha256",
        "external_run_dir_wsl",
        "event_summary",
        "scientific_boundary",
        "pre_registered_limitation",
        "outputs",
        "extra",
    ],
)
def test_resealed_compact_drift_refused(evidence, field):
    path = evidence.root / old.COMPACT_REL
    value = json.loads(path.read_text())
    value[field] = "altered"
    write(path, seal(value))
    reject(evidence)


@POSIX
@pytest.mark.parametrize(
    "field",
    [
        "seed_native_score",
        "seed_identity_digest",
        "gps_start",
        "seed_native_class",
        "population",
        "partner_class_consulted",
        "partner_class",
        "measurement_status",
        "cc_null_max",
        "cc_null_mean",
        "cc_null_values",
        "n_null",
        "per_event_null_exceeded",
    ],
)
def test_resealed_shard_drift_refused(evidence, field):
    path = evidence.directory / "event_shards/batch_00000.json"
    value = json.loads(path.read_text())
    value["rows"][0][field] = [] if field == "cc_null_values" else "altered"
    write(path, seal(value, "shard_digest"))
    reject(evidence)


@POSIX
@pytest.mark.parametrize(
    "marker",
    [
        "failure.json",
        "failures.json",
        "controller.lock",
        "scratch.part",
        "scratch.partial",
        "scratch.tmp",
        "transient_raw/H1/frame.hdf5",
    ],
)
def test_failure_partial_or_cache_refused(evidence, marker):
    path = evidence.directory / marker
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"preserve")
    reject(evidence)


@POSIX
@pytest.mark.parametrize(
    "filename",
    [
        "run.lock",
        "preflight.json",
        "new_source_frame_receipt.json",
        "cache_plan.json",
        "event_shards/batch_00001.json",
        "native_coincidence_summary.json",
        "native_coincidence_robust.jsonl",
        "native_coincidence_ambiguous.jsonl",
        "raw_source_receipt.jsonl",
    ],
)
def test_missing_evidence_refused(evidence, filename):
    (evidence.directory / filename).unlink()
    reject(evidence)


@POSIX
@pytest.mark.parametrize(
    "filename",
    [
        "native_coincidence_robust.jsonl",
        "native_coincidence_ambiguous.jsonl",
        "raw_source_receipt.jsonl",
    ],
)
def test_output_bytes_changed_refused(evidence, filename):
    with (evidence.directory / filename).open("ab") as stream:
        stream.write(b" ")
    reject(evidence, "hash mismatch")


@POSIX
def test_resealed_cache_schedule_refused(evidence):
    path = evidence.directory / "cache_plan.json"
    value = json.loads(path.read_text())
    value["peak_bytes"] += 1
    write(path, seal(value, "cache_plan_digest"))
    reject(evidence, "cache plan")


@POSIX
def test_resealed_pinned_url_refused(evidence):
    path = evidence.directory / "new_source_frame_receipt.json"
    value = json.loads(path.read_text())
    next(iter(value["frames"].values()))["url"] += "changed"
    write(path, seal(value, "receipt_digest"))
    reject(evidence, "URL")


@POSIX
def test_source_changed_refused(evidence):
    with (evidence.root / "src/dante_light/o3a_native_coincidence.py").open(
        "ab"
    ) as stream:
        stream.write(b"# drift\n")
    reject(evidence, "source mismatch")


@POSIX
@pytest.mark.parametrize("sidecar", ["-wal", "-shm", "-journal"])
def test_database_sidecar_refused_without_repair(evidence, sidecar):
    Path(str(evidence.database) + sidecar).write_bytes(b"preserve")
    reject(evidence, "sidecar")


@POSIX
def test_busy_lock_refused_and_parent_locks_released(evidence):
    import fcntl

    with (evidence.directory / "run.lock").open("rb") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reject(evidence, "busy")
    for directory in (evidence.taxonomy_dir, evidence.class_dir, evidence.directory):
        with verifier.decisions._persistent_lock(directory):
            pass


@POSIX
def test_all_locks_held_through_numerical_reconstruction(evidence, monkeypatch):
    import fcntl

    original = old._event_summary

    def checked(*a, **kw):
        for directory in (
            evidence.taxonomy_dir,
            evidence.class_dir,
            evidence.directory,
        ):
            with (directory / "run.lock").open("rb") as stream:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return original(*a, **kw)

    monkeypatch.setattr(old, "_event_summary", checked)
    verifier.verify_coincidence_evidence(**evidence.args)


@POSIX
def test_mid_read_shard_change_caught_by_final_rehash(evidence, monkeypatch):
    original = old._event_summary

    def changed(*a, **kw):
        result = original(*a, **kw)
        with (evidence.directory / "event_shards/batch_00000.json").open(
            "ab"
        ) as stream:
            stream.write(b" ")
        return result

    monkeypatch.setattr(old, "_event_summary", changed)
    with pytest.raises(ValueError, match="changed during verification"):
        verifier.verify_coincidence_evidence(**evidence.args)


@POSIX
def test_cli_success_and_refusal(evidence, capsys):
    spec = importlib.util.spec_from_file_location(
        "coincidence_cli", ROOT / "scripts/verify_dante_o3a_coincidence_evidence.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = []
    for key, value in evidence.args.items():
        args.extend(
            [
                "--repository-root" if key == "root" else "--" + key.replace("_", "-"),
                str(value),
            ]
        )
    assert module.main(args) == 0
    assert (
        json.loads(capsys.readouterr().out)["retained_null_ledger_replay_executed"]
        is True
    )
    (evidence.directory / "failure.json").write_bytes(b"preserve")
    assert module.main(args) == 1
    assert (
        json.loads(capsys.readouterr().out)["status"]
        == "FAIL_CLOSED_O3A_COINCIDENCE_EVIDENCE"
    )


@pytest.mark.parametrize(
    "flag",
    [
        "--run",
        "--verify",
        "--resume",
        "--download",
        "--archive-infrastructure-failure",
        "--output",
    ],
)
def test_cli_refuses_productive_flags(flag):
    spec = importlib.util.spec_from_file_location(
        "coincidence_cli", ROOT / "scripts/verify_dante_o3a_coincidence_evidence.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = []
    for name in (
        "external-root",
        "taxonomy-external-root",
        "classification-external-root",
        "threshold-external-root",
        "rescore-external-root",
        "calibration-external-root",
        "index-external-root",
        "cohort-external-root",
        "primary-external-root",
    ):
        args += ["--" + name, "."]
    with pytest.raises(SystemExit) as error:
        module.main([*args, flag])
    assert error.value.code == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows-only refusal")
def test_windows_refuses_before_sources_or_evidence(monkeypatch):
    monkeypatch.setattr(verifier, "_sources", forbidden)
    arguments = {
        k: ROOT
        for k in (
            "root",
            "external_root",
            "taxonomy_external_root",
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
        verifier.verify_coincidence_evidence(**arguments)


def test_actual_frozen_contract_sources_without_history():
    assert len(verifier._sources(ROOT)) == 39
    if os.name == "nt":
        with pytest.raises(ContractError):
            old.load_contract(root=ROOT)
    else:
        assert old.load_contract(root=ROOT)["contract_digest"]


@POSIX
@pytest.mark.parametrize("evidence", [True], indirect=True)
def test_linked_actual_taxonomy_replay_classification_ancestry_isolated(evidence):
    before = snapshot(evidence.root.parent)
    result = verifier.verify_coincidence_evidence(**evidence.args)
    assert "taxonomy_output" in result["inputs"]
    assert "taxonomy_summary" in result["inputs"]
    assert (
        result["taxonomy_replay_executed"]
        and result["retained_null_ledger_replay_executed"]
    )
    assert snapshot(evidence.root.parent) == before


@POSIX
@pytest.mark.parametrize(
    "bad", ["../escape.json", "/absolute.json", "C:/absolute.json"]
)
def test_parent_path_cannot_escape_root(evidence, bad):
    evidence.contract["parents"]["native_taxonomy"]["path"] = bad
    write(evidence.root / old.CONTRACT_REL, evidence.contract)
    reject(evidence, "relative|unsafe")


@POSIX
def test_duplicate_key_shard_refused_by_strict_read(evidence):
    path = evidence.directory / "event_shards/batch_00000.json"
    payload = path.read_text()
    path.write_text('{"status":"duplicate",' + payload[1:], encoding="utf-8")
    reject(evidence, "duplicate")


@POSIX
def test_unavailable_shard_and_output_remain_consistent(evidence, monkeypatch):
    path = evidence.directory / "event_shards/batch_00001.json"
    value = json.loads(path.read_text())
    row = value["rows"][0]
    row.update(
        measurement_status="PARTNER_DATA_UNAVAILABLE",
        cc_onsource=None,
        cc_null_values=[],
        cc_null_max=None,
        n_null=0,
        per_event_null_exceeded=None,
        unavailable_reason="synthetic coverage limit",
    )
    write(path, seal(value, "shard_digest"))
    # Altering an internally valid retained measurement without changing its
    # completed output is still refused; no unavailable is interpreted negative.
    reject(evidence, "hash mismatch")


@POSIX
def test_cache_created_mid_replay_refused(evidence, monkeypatch):
    original = old._event_summary

    def changed(*a, **kw):
        value = original(*a, **kw)
        path = evidence.directory / "transient_raw/frame.hdf5"
        path.parent.mkdir()
        path.write_bytes(b"unexpected")
        return value

    monkeypatch.setattr(old, "_event_summary", changed)
    with pytest.raises(ValueError, match="cache"):
        verifier.verify_coincidence_evidence(**evidence.args)
