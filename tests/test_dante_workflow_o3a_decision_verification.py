"""Frozen numerical decision replay; isolated RESCORE parent, real files/locks."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import numpy as np
import pytest

from src.dante_light import o3a_native_thresholds as nt
from src.dante_light import o3a_native_classification as nc
from src.dante_light.contracts import canonical_json_sha256, ContractError
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_workflow import o3a_decision_verification as verifier

ROOT = Path(__file__).resolve().parents[1]
POSIX = pytest.mark.skipif(
    os.name == "nt", reason="persistent-lock protocol requires POSIX/WSL"
)


def seal(body, field="artifact_digest"):
    value = {k: v for k, v in body.items() if k != field}
    return {**value, field: canonical_json_sha256(value)}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def read(path):
    return json.loads(path.read_bytes())


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def forbidden(*a, **kw):
    raise AssertionError("legacy productive verifier/writer invoked")


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    for relative in verifier._sources(ROOT):
        if relative.startswith(("src/dante_light/", "src/pipeline_v2_production/")):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
    runtime = {"runtime_environment": {"environment_digest": "a" * 64}}
    write(root / nt.RUNTIME_REL, runtime)
    parent_dir = tmp_path / "rescore" / "native_rescore_fixture"
    outputs, calibration_rows = {}, {}
    candidates = []
    for detector in ("H1", "L1"):
        rows = []
        for number in range(11):
            score = float(
                np.float32(
                    0.1 + min(number, 8) * 0.05 + (0.2 if detector == "L1" else 0)
                )
            )
            rows.append(
                {
                    "detector": detector,
                    "gps_start": 2000 + number * 32,
                    "population": "native_calibration",
                    "calibration_row_number": number,
                    "bootstrap_block_index": number // 3,
                    "identity_digest": canonical_json_sha256([detector, number]),
                    "native_score": score,
                    "score_float32_hex": nt._float32_hex(score),
                }
            )
        calibration_rows[detector] = rows
        name = "native_calibration_" + detector
        path = parent_dir / (name + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
            encoding="utf-8",
        )
        outputs[name] = {
            "filename": path.name,
            "sha256": file_sha256(path),
            "row_digest": canonical_json_sha256(rows),
            "row_total": len(rows),
        }
        for number, score in enumerate((0.05, 0.2, 0.5, 0.8, 1.0)):
            candidates.append(
                {
                    "detector": detector,
                    "gps_start": 4000 + number * 64,
                    "population": "primary_candidate",
                    "ordinal": len(candidates),
                    "identity_digest": canonical_json_sha256(
                        [detector, 4000 + number * 64]
                    ),
                    "native_score": score,
                    "score_float32_hex": nt._float32_hex(score),
                }
            )
    path = parent_dir / "primary_candidate.jsonl"
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in candidates),
        encoding="utf-8",
    )
    outputs["primary_candidate"] = {
        "filename": path.name,
        "sha256": file_sha256(path),
        "row_digest": canonical_json_sha256(candidates),
        "row_total": len(candidates),
    }
    parent = seal(
        {
            "status": "PASS_COMPLETE_O3A_NATIVE_RESCORE",
            "run_key": "fixture",
            "contract_digest": "b" * 64,
            "outputs": outputs,
        }
    )
    write(parent_dir / "native_rescore_summary.json", parent)
    receipt = {k: parent[k] for k in ("artifact_digest", "run_key", "contract_digest")}
    receipt["output_sha256"] = {
        name: value["sha256"] for name, value in outputs.items()
    }
    write(root / nt.RESCORE_REL, seal(receipt, "compact_digest"))
    contract = seal(
        {
            "parent_rescore": receipt,
            "population": {
                "rows_by_detector": {"H1": 11, "L1": 11},
                "bootstrap_rows_per_detector": 9,
                "within_block_stride_s": 32,
            },
            "method": {
                "name": "non_overlapping_block_bootstrap_p99",
                "block_length": 3,
                "bootstrap_replicates": 64,
                "bootstrap_seed": 42,
                "bootstrap_chunk_size": 7,
            },
            "references": {
                nt.RESCORE_REL: file_sha256(root / nt.RESCORE_REL),
                nt.RUNTIME_REL: file_sha256(root / nt.RUNTIME_REL),
            },
            "implementation_sources": {
                "src/dante_light/o3a_native_thresholds.py": file_sha256(
                    root / "src/dante_light/o3a_native_thresholds.py"
                )
            },
            "scientific_boundary": {
                "candidate_scores_used_for_fitting": False,
                "detector_pooling": False,
            },
            "output": {"summary_filename": "native_thresholds_summary.json"},
        },
        "contract_digest",
    )
    write(root / nt.CONTRACT_REL, contract)
    original = {
        name: getattr(nt, name)
        for name in ("_calculate", "execute_thresholds", "_lock", "_atomic_json")
    }
    original.update(
        {
            "class_execute": nc.execute,
            "class_atomic_json": nc._atomic_json,
            "class_atomic_jsonl": nc._atomic_jsonl,
        }
    )
    monkeypatch.setattr(nt, "load_threshold_contract", lambda **kw: contract)
    monkeypatch.setattr(nt, "load_runtime_contract", lambda **kw: runtime)
    monkeypatch.setattr(nt, "verify_native_rescore", lambda **kw: (parent, parent_dir))
    threshold_root = tmp_path / "thresholds"
    directory = nt._run_dir(contract, threshold_root)
    result = nt._calculate(contract, root=root, external_root=threshold_root)
    write(directory / "native_thresholds_summary.json", result)
    (directory / "run.lock").write_bytes(b"")
    compact_body = {k: v for k, v in result.items() if k != "artifact_digest"}
    compact_body.update(
        status="PASS_VERIFIED_O3A_NATIVE_THRESHOLDS",
        external_run_dir_wsl=str(directory),
        run_artifact_digest=result["artifact_digest"],
        summary_sha256=file_sha256(directory / "native_thresholds_summary.json"),
    )
    compact = seal(compact_body)
    write(root / nt.COMPACT_REL, compact)
    class_contract = seal(
        {
            "threshold_parent": {
                k: compact[k]
                for k in (
                    "artifact_digest",
                    "run_artifact_digest",
                    "contract_digest",
                    "run_key",
                )
            },
            "rescore_parent": receipt,
            "rule": nc.RULE,
            "boundary_class": "AMBIGUOUS",
            "population": {"rows_by_detector": {"H1": 5, "L1": 5}},
            "references": {nt.COMPACT_REL: file_sha256(root / nt.COMPACT_REL)},
            "implementation_sources": {
                "src/dante_light/o3a_native_classification.py": file_sha256(
                    root / "src/dante_light/o3a_native_classification.py"
                )
            },
            "scientific_boundary": {
                "global_significance_claim": False,
                "thresholds_changed": False,
            },
            "output": {
                "summary_filename": "native_classification_summary.json",
                "candidate_filename": "native_classified_candidates.jsonl",
            },
        },
        "contract_digest",
    )
    write(root / nc.CONTRACT_REL, class_contract)
    monkeypatch.setattr(nc, "load_contract", lambda **kw: class_contract)
    class_dir = nc._run_dir(class_contract, tmp_path / "classification")
    class_dir.mkdir(parents=True)
    (class_dir / "run.lock").write_bytes(b"")
    classified, counts = nc.classify_rows(
        candidates,
        thresholds=result["thresholds"],
        expected_counts=class_contract["population"]["rows_by_detector"],
    )
    output = class_dir / "native_classified_candidates.jsonl"
    output.write_bytes(
        "".join(
            json.dumps(r, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for r in classified
        ).encode()
    )
    class_result = seal(
        {
            "schema_version": 1,
            "status": "PASS_COMPLETE_O3A_NATIVE_CLASSIFICATION",
            "contract_digest": class_contract["contract_digest"],
            "run_key": class_dir.name.removeprefix("native_classification_"),
            "threshold_artifact_digest": result["artifact_digest"],
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
            "rescore_artifact_digest": parent["artifact_digest"],
            "rule": class_contract["rule"],
            "row_total": len(classified),
            "counts_by_detector_and_class": counts,
            "source_sha256": outputs["primary_candidate"]["sha256"],
            "output_sha256": file_sha256(output),
            "output_row_digest": canonical_json_sha256(classified),
            "scientific_boundary": class_contract["scientific_boundary"],
        }
    )
    write(class_dir / "native_classification_summary.json", class_result)
    class_compact = {k: v for k, v in class_result.items() if k != "artifact_digest"}
    class_compact.update(
        status="PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION",
        external_run_dir_wsl=str(class_dir),
        run_artifact_digest=class_result["artifact_digest"],
        summary_sha256=file_sha256(class_dir / "native_classification_summary.json"),
    )
    write(root / nc.COMPACT_REL, seal(class_compact))
    calls = []

    def parent_gate(**kw):
        assert kw["root"] == root
        assert kw["external_root"] == parent_dir.parent
        for name in ("calibration", "index", "cohort", "primary"):
            assert kw[name + "_external_root"] == tmp_path / name
        calls.append(kw)
        verifier.scores._clean(parent_dir)
        e = kw["evidence"]
        actual = e.sealed(
            "rescore_summary",
            parent_dir / "native_rescore_summary.json",
            "artifact_digest",
        )
        assert actual == parent
        for name, meta in outputs.items():
            e.read(
                "rescore_output:" + name, parent_dir / meta["filename"], meta["sha256"]
            )
        return actual, parent_dir

    monkeypatch.setattr(verifier.scores, "_rescore_gate", parent_gate)
    for module, names in (
        (
            nt,
            (
                "execute_thresholds",
                "_calculate",
                "_lock",
                "_atomic_json",
                "verify_native_rescore",
                "freeze_threshold_contract",
            ),
        ),
        (
            nc,
            (
                "execute",
                "_verified_inputs",
                "_atomic_json",
                "_atomic_jsonl",
                "freeze_contract",
            ),
        ),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    return SimpleNamespace(
        root=root,
        parent_dir=parent_dir,
        threshold_dir=directory,
        class_dir=class_dir,
        contract=contract,
        class_contract=class_contract,
        threshold=result,
        classification=class_result,
        parent=parent,
        candidates=candidates,
        calibration_rows=calibration_rows,
        original=original,
        calls=calls,
    )


def arguments(f, stage):
    return dict(
        root=f.root,
        stage=stage,
        external_root=f.threshold_dir.parent
        if stage == "thresholds"
        else f.class_dir.parent,
        rescore_external_root=f.parent_dir.parent,
        calibration_external_root=f.root.parent / "calibration",
        index_external_root=f.root.parent / "index",
        cohort_external_root=f.root.parent / "cohort",
        primary_external_root=f.root.parent / "primary",
        threshold_external_root=f.threshold_dir.parent
        if stage == "classification"
        else None,
    )


def verify(f, stage="classification"):
    return verifier.verify_decision_evidence(**arguments(f, stage))


def reject(f, stage="classification", match=None):
    before = snapshot(f.root.parent)
    with pytest.raises((ValueError, RuntimeError, OSError, KeyError), match=match):
        verify(f, stage)
    assert snapshot(f.root.parent) == before


@POSIX
@pytest.mark.parametrize("stage", ["thresholds", "classification"])
def test_complete_replay_stdout_receipt_no_mutation(evidence, stage):
    before = snapshot(evidence.root.parent)
    receipt = verify(evidence, stage)
    assert snapshot(evidence.root.parent) == before
    assert receipt == seal(receipt, "receipt_digest")
    assert len(receipt["source_bindings"]) == 28
    assert receipt["threshold_bootstrap_replay_executed"] is True
    assert receipt["classification_replay_executed"] == (stage == "classification")
    for key in (
        "historical_evidence_mutated",
        "full_workflow_verified",
        "encoder_executed",
        "source_fetch_executed",
        "raw_score_replay_executed",
        "global_upstream_quiescence_verified",
    ):
        assert receipt[key] is False
    assert "thresholds" not in receipt and "counts_by_detector_and_class" not in receipt
    assert len(evidence.calls) == 1


@POSIX
def test_original_threshold_calculation_and_class_execute_parity(
    evidence, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        nt, "verify_native_rescore", lambda **kw: (evidence.parent, evidence.parent_dir)
    )
    expected = evidence.original["_calculate"](
        evidence.contract,
        root=evidence.root,
        external_root=evidence.threshold_dir.parent,
    )
    assert expected == evidence.threshold
    monkeypatch.setattr(
        nc,
        "_verified_inputs",
        lambda *a, **kw: (
            evidence.candidates,
            expected,
            evidence.parent["outputs"]["primary_candidate"]["sha256"],
        ),
    )
    monkeypatch.setattr(nt, "_lock", evidence.original["_lock"])
    monkeypatch.setattr(nc, "_atomic_json", evidence.original["class_atomic_json"])
    monkeypatch.setattr(nc, "_atomic_jsonl", evidence.original["class_atomic_jsonl"])
    result, _ = evidence.original["class_execute"](
        root=tmp_path / "legacy-copy", external_root=tmp_path / "legacy-runs"
    )
    assert result == evidence.classification
    monkeypatch.setattr(nt, "verify_native_rescore", forbidden)
    assert verify(evidence)["legacy_artifact_digest"] == result["artifact_digest"]


@POSIX
@pytest.mark.parametrize(
    "stage,field",
    [
        ("thresholds", f)
        for f in (
            "status",
            "run_key",
            "contract_digest",
            "native_rescore_artifact_digest",
            "runtime_environment_digest",
            "inputs",
            "method",
            "thresholds",
            "scientific_boundary",
        )
    ]
    + [
        ("classification", f)
        for f in (
            "status",
            "run_key",
            "rule",
            "row_total",
            "counts_by_detector_and_class",
            "source_sha256",
            "output_sha256",
            "output_row_digest",
            "threshold_artifact_digest",
            "rescore_artifact_digest",
        )
    ],
)
def test_resealed_summary_changes_rejected(evidence, stage, field):
    directory = evidence.threshold_dir if stage == "thresholds" else evidence.class_dir
    path = directory / (
        "native_thresholds_summary.json"
        if stage == "thresholds"
        else "native_classification_summary.json"
    )
    value = read(path)
    value[field] = "changed"
    write(path, seal(value))
    reject(evidence, stage)


@POSIX
@pytest.mark.parametrize(
    "relative,field",
    [
        (nt.COMPACT_REL, "status"),
        (nt.COMPACT_REL, "run_artifact_digest"),
        (nt.COMPACT_REL, "external_run_dir_wsl"),
        (nc.COMPACT_REL, "summary_sha256"),
        (nc.COMPACT_REL, "thresholds"),
    ],
)
def test_resealed_compact_changes(evidence, relative, field):
    path = evidence.root / relative
    value = read(path)
    value[field] = "changed"
    write(path, seal(value))
    reject(evidence, "thresholds" if relative == nt.COMPACT_REL else "classification")


@POSIX
@pytest.mark.parametrize(
    "location,name",
    [
        (where, name)
        for where in ("threshold_dir", "class_dir")
        for name in (
            "failure.json",
            "failures.json",
            "controller.lock",
            "unfinished.partial",
            "unfinished.tmp",
        )
    ],
)
def test_failed_active_partial_rejected(evidence, location, name):
    (getattr(evidence, location) / name).write_bytes(b"marker")
    reject(evidence)


@POSIX
def test_class_output_bytes_rejected(evidence):
    path = evidence.class_dir / "native_classified_candidates.jsonl"
    payload = path.read_bytes().replace(b'"AMBIGUOUS"', b'"ROBUST"')
    path.write_bytes(payload + b" ")
    reject(evidence)


@POSIX
def test_calibration_hash_change_rejected(evidence):
    path = evidence.parent_dir / "native_calibration_H1.jsonl"
    path.write_bytes(path.read_bytes() + b" ")
    reject(evidence)


@POSIX
def test_parent_contract_changed(evidence):
    evidence.contract["parent_rescore"]["artifact_digest"] = "changed"
    write(evidence.root / nt.CONTRACT_REL, evidence.contract)
    reject(evidence)


@POSIX
def test_helper_source_changed(evidence):
    path = evidence.root / "src/pipeline_v2_production/background_calibration.py"
    path.write_bytes(path.read_bytes() + b"\n# modified fixture\n")
    reject(evidence)


@POSIX
def test_midread_summary_change(evidence, monkeypatch):
    original = nt.compute_threshold

    def altered(*a, **kw):
        result = original(*a, **kw)
        path = evidence.threshold_dir / "native_thresholds_summary.json"
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(nt, "compute_threshold", altered)
    with pytest.raises(ValueError, match="changed during verification"):
        verify(evidence)


def producer(directory):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from pathlib import Path; from src.dante_light.o3a_native_thresholds import _lock; import sys; context=_lock(Path(sys.argv[1])); context.__enter__(); context.__exit__(None,None,None)",
            str(directory),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@POSIX
def test_readonly_lock_blocks_original_producer_and_releases(tmp_path):
    directory = tmp_path / "run"
    directory.mkdir()
    (directory / "run.lock").write_bytes(b"preserved marker")
    before = snapshot(tmp_path)
    with verifier._persistent_lock(directory):
        result = producer(directory)
        assert result.returncode != 0
        assert "native threshold run already active" in result.stderr
    assert producer(directory).returncode == 0
    assert snapshot(tmp_path) == before


@POSIX
def test_busy_lock_refused_and_exception_release(tmp_path):
    import fcntl

    directory = tmp_path / "run"
    directory.mkdir()
    path = directory / "run.lock"
    path.write_bytes(b"")
    with path.open("rb") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="busy"):
            with verifier._persistent_lock(directory):
                pytest.fail("entered busy lock")
    with pytest.raises(RuntimeError, match="fixture"):
        with verifier._persistent_lock(directory):
            raise RuntimeError("fixture")
    assert producer(directory).returncode == 0


@POSIX
@pytest.mark.parametrize(
    "case", ["missing", "symlink", "hardlink", "fifo", "changed", "replaced", "deleted"]
)
def test_lock_unsafe_or_changed(tmp_path, case):
    directory = tmp_path / "run"
    directory.mkdir()
    path = directory / "run.lock"
    other = tmp_path / "other"
    other.write_bytes(b"")
    if case == "symlink":
        path.symlink_to(other)
    elif case == "hardlink":
        os.link(other, path)
    elif case == "fifo":
        os.mkfifo(path)
    elif case != "missing":
        path.write_bytes(b"")
    with pytest.raises(ValueError):
        with verifier._persistent_lock(directory):
            if case == "changed":
                path.write_bytes(b"changed")
            elif case == "replaced":
                other.replace(path)
            elif case == "deleted":
                path.unlink()


@POSIX
def test_target_filesystem_existing_lock_protocol():
    parent = os.environ.get("DANTE_LOCK_TEST_PARENT")
    if not parent:
        pytest.skip("explicit disposable target-FS test parent not supplied")
    base = Path(parent).resolve(strict=True)
    with tempfile.TemporaryDirectory(
        prefix="dante-lock-policy-", dir=base
    ) as temporary:
        directory = Path(temporary)
        assert directory.resolve().parent == base
        path = directory / "run.lock"
        path.write_bytes(b"transport-independent lock fixture")
        before = snapshot(directory)
        with verifier._persistent_lock(directory):
            result = producer(directory)
            assert result.returncode != 0
            assert "native threshold run already active" in result.stderr
        assert producer(directory).returncode == 0
        assert snapshot(directory) == before


@POSIX
def test_both_locks_held_during_calculation(evidence, monkeypatch):
    import fcntl

    original = nt.compute_threshold

    def assert_held(*a, **kw):
        for directory in (evidence.threshold_dir, evidence.class_dir):
            with (directory / "run.lock").open("rb") as handle:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return original(*a, **kw)

    monkeypatch.setattr(nt, "compute_threshold", assert_held)
    verify(evidence)


@POSIX
@pytest.mark.parametrize(
    "stage,fail",
    [(s, f) for s in ("thresholds", "classification") for f in (False, True)],
)
def test_cli_stdout_only(evidence, capsys, stage, fail):
    if fail:
        (evidence.threshold_dir / "failure.json").write_bytes(b"failure")
    spec = importlib.util.spec_from_file_location(
        "decision_cli", ROOT / "scripts/verify_dante_o3a_decision_evidence.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv = []
    for key, value in arguments(evidence, stage).items():
        if value is not None:
            argv += [
                "--repository-root" if key == "root" else "--" + key.replace("_", "-"),
                str(value),
            ]
    before = snapshot(evidence.root.parent)
    assert module.main(argv) == (1 if fail else 0)
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out)["status"].startswith(
        "FAIL_CLOSED" if fail else "PASS_O3A_READ_ONLY"
    )
    assert snapshot(evidence.root.parent) == before


@pytest.mark.parametrize(
    "stage,extra",
    [("other", None), ("classification", None), ("thresholds", Path("extra"))],
)
def test_invalid_scope_before_sources(stage, extra, monkeypatch, tmp_path):
    monkeypatch.setattr(verifier, "_sources", forbidden)
    with pytest.raises(ValueError, match="scope"):
        verifier.verify_decision_evidence(
            root=tmp_path,
            external_root=tmp_path,
            rescore_external_root=tmp_path,
            calibration_external_root=tmp_path,
            index_external_root=tmp_path,
            cohort_external_root=tmp_path,
            primary_external_root=tmp_path,
            stage=stage,
            threshold_external_root=extra,
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows-only fail-closed portability")
def test_windows_lock_protocol_refused_before_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(verifier, "_sources", forbidden)
    with pytest.raises(ValueError, match="POSIX/WSL"):
        verifier.verify_decision_evidence(
            root=tmp_path,
            stage="thresholds",
            external_root=tmp_path,
            rescore_external_root=tmp_path,
            calibration_external_root=tmp_path,
            index_external_root=tmp_path,
            cohort_external_root=tmp_path,
            primary_external_root=tmp_path,
        )


def test_pure_bootstrap_and_boundary_rules():
    method = {
        "block_length": 3,
        "bootstrap_replicates": 64,
        "bootstrap_seed": 42,
        "bootstrap_chunk_size": 7,
    }
    scores = np.asarray([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.15, 0.35])
    result = nt.compute_threshold(scores, method=method)
    assert result["n_point_rows"] == 11 and result["n_bootstrap_rows"] == 9
    assert result["point_only_tail_rows"] == 2
    assert result == nt.compute_threshold(
        scores, method=method | {"bootstrap_chunk_size": 3}
    )
    assert (
        nc.classify_score(
            result["ci_lower"], lower=result["ci_lower"], upper=result["ci_upper"]
        )
        == "AMBIGUOUS"
    )
    assert (
        nc.classify_score(
            result["ci_upper"], lower=result["ci_lower"], upper=result["ci_upper"]
        )
        == "AMBIGUOUS"
    )


@pytest.mark.parametrize(
    "flag", ["--run", "--freeze", "--repair", "--resume", "--output"]
)
def test_mutation_flags_refused(flag):
    args = [
        sys.executable,
        "-B",
        str(ROOT / "scripts/verify_dante_o3a_decision_evidence.py"),
        "--stage",
        "thresholds",
    ]
    for name in (
        "external-root",
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


def test_real_contract_loaders_without_history():
    assert len(verifier._sources(ROOT)) == 28
    if os.name == "nt":
        with pytest.raises(ContractError):
            nt.load_threshold_contract(root=ROOT)
        with pytest.raises(ContractError):
            nc.load_contract(root=ROOT)
    else:
        assert nt.load_threshold_contract(root=ROOT)["contract_digest"]
        assert nc.load_contract(root=ROOT)["contract_digest"]


def test_point_only_tail_outside_existing_interval_is_refused():
    method = {
        "block_length": 3,
        "bootstrap_replicates": 64,
        "bootstrap_seed": 42,
        "bootstrap_chunk_size": 7,
    }
    with pytest.raises(ContractError, match="interval invalid"):
        nt.compute_threshold(
            np.asarray([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.2, 1.4]),
            method=method,
        )


@POSIX
def test_only_detector_local_calibration_vectors_are_fitted(evidence, monkeypatch):
    original = nt.compute_threshold
    observed = []

    def recorded(vector, *, method):
        assert method == evidence.contract["method"]
        observed.append(vector.copy())
        return original(vector, method=method)

    monkeypatch.setattr(nt, "compute_threshold", recorded)
    verify(evidence)
    assert len(observed) == 2
    for position, detector in enumerate(("H1", "L1")):
        expected = np.asarray(
            [r["native_score"] for r in evidence.calibration_rows[detector]]
        )
        np.testing.assert_array_equal(observed[position], expected)
    assert (
        evidence.threshold["thresholds"]["H1"]["p99"]
        < evidence.threshold["thresholds"]["L1"]["p99"]
    )


@POSIX
def test_descriptor_flags_readonly_no_create_and_unsupported_lock(
    tmp_path, monkeypatch
):
    import errno
    import fcntl

    directory = tmp_path / "run"
    directory.mkdir()
    (directory / "run.lock").write_bytes(b"unchanged")
    original = os.open
    flags_seen = []

    def record(path, flags, *a, **kw):
        flags_seen.append(flags)
        return original(path, flags, *a, **kw)

    monkeypatch.setattr(os, "open", record)
    before = snapshot(tmp_path)
    with verifier._persistent_lock(directory):
        pass
    assert len(flags_seen) == 1
    assert flags_seen[0] & os.O_ACCMODE == os.O_RDONLY
    assert not flags_seen[0] & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)

    def unsupported(*a):
        raise OSError(errno.ENOTSUP, "fixture unsupported")

    monkeypatch.setattr(fcntl, "flock", unsupported)
    with pytest.raises(ValueError, match="unsupported"):
        with verifier._persistent_lock(directory):
            pytest.fail("entered unsupported lock")
    assert snapshot(tmp_path) == before


@POSIX
def test_lock_replaced_between_stat_and_open(tmp_path, monkeypatch):
    directory = tmp_path / "run"
    directory.mkdir()
    path = directory / "run.lock"
    path.write_bytes(b"")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"new")
    original = os.open

    def replace_then_open(filename, flags, *a, **kw):
        replacement.replace(path)
        return original(filename, flags, *a, **kw)

    monkeypatch.setattr(os, "open", replace_then_open)
    with pytest.raises(ValueError, match="replaced during open"):
        with verifier._persistent_lock(directory):
            pytest.fail("entered replaced lock")


@POSIX
@pytest.mark.parametrize("stage", ["thresholds", "classification"])
def test_full_gate_failure_releases_lock(evidence, stage):
    import fcntl

    directory = evidence.threshold_dir if stage == "thresholds" else evidence.class_dir
    path = directory / (
        "native_thresholds_summary.json"
        if stage == "thresholds"
        else "native_classification_summary.json"
    )
    path.write_bytes(b"invalid")
    reject(evidence, stage)
    for held_directory in (evidence.threshold_dir, evidence.class_dir):
        with (held_directory / "run.lock").open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)


@POSIX
@pytest.mark.parametrize("stage", ["thresholds", "classification"])
def test_full_gate_busy_marker_refused_without_mutation(evidence, stage):
    import fcntl

    directory = evidence.threshold_dir if stage == "thresholds" else evidence.class_dir
    with (directory / "run.lock").open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reject(evidence, stage, "busy")


@POSIX
def test_replaced_lock_cannot_emit_receipt(evidence, monkeypatch):
    original = verifier._Evidence.unchanged

    def replaced(instance):
        original(instance)
        other = evidence.root.parent / "new-lock"
        other.write_bytes(b"")
        other.replace(evidence.class_dir / "run.lock")

    monkeypatch.setattr(verifier._Evidence, "unchanged", replaced)
    with pytest.raises(ValueError, match="lock changed"):
        verify(evidence)


@POSIX
def test_escaping_summary_path_refused(evidence):
    evidence.contract["output"]["summary_filename"] = "../outside.json"
    write(evidence.root / nt.CONTRACT_REL, evidence.contract)
    reject(evidence, "thresholds", "unsafe")
