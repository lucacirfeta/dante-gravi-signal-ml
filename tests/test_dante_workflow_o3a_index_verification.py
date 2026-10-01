"""Stored-index validation; synthetic parents, real SQLite/NPY/NPZ validators."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest

from src.dante_light import contracts, o3a_native_index as index
from src.dante_light import o4a_corrected_native_index as method
from src.dante_workflow import o3a_index_verification as verifier

ROOT = Path(__file__).resolve().parents[1]
_fixture_spec = importlib.util.spec_from_file_location(
    "index_parent_fixture_helpers",
    ROOT / "tests/test_dante_workflow_o3a_native_verification.py",
)
_fixture_helpers = importlib.util.module_from_spec(_fixture_spec)
sys.modules[_fixture_spec.name] = _fixture_helpers
_fixture_spec.loader.exec_module(_fixture_helpers)
forbidden = _fixture_helpers.forbidden
lines = _fixture_helpers.lines
read = _fixture_helpers.read
reledger = _fixture_helpers.reledger
seal = _fixture_helpers.seal
snapshot = _fixture_helpers.snapshot
write = _fixture_helpers.write


@pytest.fixture
def cohort_evidence(tmp_path, monkeypatch):
    return _fixture_helpers.evidence.__wrapped__(tmp_path, monkeypatch)


def make_index(f, rows, cohort_summary, cohort_dir):
    runtime = read(f.root / index.RUNTIME_REL)
    contract = seal(
        {
            "parents": {
                "frozen_native_cohort": {
                    "artifact_digest": cohort_summary["artifact_digest"]
                }
            },
            "representation": {"patch_tokens_per_image": 2, "embedding_dimension": 3},
            "gates": {
                "exact_cohort_counts_by_detector": cohort_summary["counts_by_detector"],
                "exact_cohort_rows": len(rows),
                "exact_patch_token_total": len(rows) * 2,
                "exact_centroid_shape": [2, 3],
                "exact_raw_sample_shape": [3, 3],
                "maximum_l2_norm_error": 2e-6,
            },
        },
        "contract_digest",
    )
    write(f.root / index.CONTRACT_REL, contract)
    key = index._run_key(contract, runtime)
    directory = f.root.parent / "index" / f"native_index_{key}"
    preflight = seal(
        {
            "status": "PASS_O3A_NATIVE_INDEX_PREFLIGHT",
            "run_key": key,
            "contract_digest": contract["contract_digest"],
            "cohort_artifact_digest": cohort_summary["artifact_digest"],
        },
        "preflight_digest",
    )
    write(directory / "preflight.json", preflight)
    replay_rows = []
    for position, row in enumerate(rows):
        tokens = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
        token_path, manifest_path = index._shard_paths(directory, position)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(token_path, tokens)
        replay = {
            "identity_digest": row["identity_digest"],
            "detector": row["detector"],
            "gps_start": row["gps_start"],
            "cohort_detector_index": row["cohort_detector_index"],
            "clean_window_sha256": row["clean_window_sha256"],
            "raw_context_values_sha256": row["raw_context"]["values_sha256"],
            "context_sources_digest": row["context_sources_digest"],
        }
        token_digest = hashlib.sha256(tokens.tobytes()).hexdigest()
        write(
            manifest_path,
            seal(
                {
                    "position": position,
                    "contract_digest": contract["contract_digest"],
                    "identity_digest": row["identity_digest"],
                    "detector": row["detector"],
                    "gps_start": row["gps_start"],
                    "replay": replay,
                    "token_file_sha256": index.file_sha256(token_path),
                    "patch_tokens_sha256": token_digest,
                },
                "shard_digest",
            ),
        )
        replay_rows.append(
            {"position": position, **replay, "patch_tokens_sha256": token_digest}
        )
    replay_path = directory / "native_index_replay.jsonl"
    replay_path.write_bytes(lines(replay_rows))
    meta = {
        "run": "O3a",
        "K": 2,
        "contract_digest": contract["contract_digest"],
        "cohort_artifact_digest": cohort_summary["artifact_digest"],
        "detector_identity_inferred": False,
    }
    npz = directory / "native_index.npz"
    centroids = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    raw_sample = np.eye(3, dtype=np.float32)
    np.savez_compressed(
        npz,
        embeddings=centroids,
        raw_embeddings_sample=raw_sample,
        labels=np.array(["BG_O3a", "BG_O3a"]),
        meta=json.dumps(meta),
    )
    write(
        directory / "native_index_summary.json",
        seal(
            {
                "status": "PASS_BUILT_O3A_NATIVE_INDEX",
                "run_key": key,
                "contract_digest": contract["contract_digest"],
                "cohort_artifact_digest": cohort_summary["artifact_digest"],
                "runtime_environment_digest": runtime["runtime_environment"][
                    "environment_digest"
                ],
                "counts_by_detector": cohort_summary["counts_by_detector"],
                "cohort_row_total": len(rows),
                "index": {
                    "filename": npz.name,
                    "sha256": index.file_sha256(npz),
                    "size_bytes": npz.stat().st_size,
                    "token_total": len(rows) * 2,
                    "centroid_bytes_sha256": hashlib.sha256(
                        centroids.tobytes()
                    ).hexdigest(),
                    "raw_sample_bytes_sha256": hashlib.sha256(
                        raw_sample.tobytes()
                    ).hexdigest(),
                },
                "replay_ledger": {
                    "filename": replay_path.name,
                    "sha256": index.file_sha256(replay_path),
                    "row_digest": contracts.canonical_json_sha256(replay_rows),
                },
            }
        ),
    )
    f.index_dir, f.index_contract = directory, contract
    f.index_cohort, f.index_cohort_dir = cohort_summary, cohort_dir
    f.runtime = runtime


@pytest.fixture
def evidence(cohort_evidence, monkeypatch):
    f = cohort_evidence
    for module in (index, method):
        target = f.root / (module.__name__.replace(".", "/") + ".py")
        shutil.copyfile(module.__file__, target)
    for row in f.rows:
        row["clean_window_sha256"] = "a" * 64
    reledger(f, shards=True)
    path = f.cohort_dir / "native_cohort_summary.json"
    value = read(path)
    value.update(row_total=len(f.rows), counts_by_detector={"H1": 2, "L1": 2})
    value["ledger"]["filename"] = "native_cohort.jsonl"
    value = seal(value)
    write(path, value)
    make_index(f, f.rows, value, f.cohort_dir)
    monkeypatch.setattr(
        index, "load_index_contract", lambda *, root: read(root / index.CONTRACT_REL)
    )

    def runtime_loader(*, root, require_current):
        assert require_current is True
        return read(root / index.RUNTIME_REL)

    monkeypatch.setattr(index, "load_runtime_contract", runtime_loader)
    f.legacy_index = index.verify_native_index
    for name in (
        "_expected_run",
        "verify_native_cohort",
        "_preprocess_context",
        "_encode_images",
        "cluster_native_tokens",
        "_write_shard",
        "_atomic_npy",
        "_atomic_json",
        "_atomic_jsonl",
        "preflight_native_index",
        "build_native_index",
        "verify_native_index",
    ):
        monkeypatch.setattr(index, name, forbidden)
    return f


def verify(f):
    return verifier.verify_index_evidence(
        root=f.root,
        external_root=f.index_dir.parent,
        cohort_external_root=f.external,
        primary_external_root=f.primary,
    )


def reject(f, match=None):
    before = snapshot(f.root.parent)
    with pytest.raises((ValueError, RuntimeError, OSError, KeyError), match=match):
        verify(f)
    assert snapshot(f.root.parent) == before


def update_summary(f, mutate):
    path = f.index_dir / "native_index_summary.json"
    value = read(path)
    mutate(value)
    write(path, seal(value))


def test_integrated_parent_chain_and_scoped_no_mutation_receipt(evidence):
    before = snapshot(evidence.root.parent)
    result = verify(evidence)
    assert snapshot(evidence.root.parent) == before
    assert result == seal(result, "receipt_digest")
    assert result["status"] == "PASS_O3A_READ_ONLY_INDEX_STORED_VALIDATION_ONLY"
    assert len(result["source_bindings"]) == 20
    assert (
        result["stored_patch_tokens_checked"]
        and result["stored_npz_numerically_checked"]
    )
    for key in (
        "raw_score_replay_executed",
        "encoder_executed",
        "preprocessing_replay_executed",
        "clustering_refit_executed",
        "threshold_fit_executed",
        "source_fetch_executed",
        "full_workflow_verified",
        "historical_evidence_mutated",
    ):
        assert result[key] is False
    assert {"scan_database", "cohort_ledger", "index_npz", "index_token:0"} <= result[
        "inputs"
    ].keys()


def test_exact_legacy_index_parity_with_frozen_cardinality_parent(
    evidence, monkeypatch
):
    # Only this independent INDEX parity test isolates the already-tested parent.
    frozen_counts = read(ROOT / index.CONTRACT_REL)["gates"][
        "exact_cohort_counts_by_detector"
    ]
    rows = []
    for detector, count in frozen_counts.items():
        for rank in range(count):
            rows.append(
                {
                    "detector": detector,
                    "gps_start": 1000 + rank,
                    "cohort_detector_index": rank,
                    "identity_digest": f"{detector}-{rank}",
                    "clean_window_sha256": "a" * 64,
                    "raw_context": {"values_sha256": "b" * 64},
                    "context_sources_digest": "c" * 64,
                }
            )
    parent_dir = evidence.root.parent / "isolated_parity_parent"
    parent_dir.mkdir()
    path = parent_dir / "native_cohort.jsonl"
    path.write_bytes(lines(rows))
    parent = seal(
        {
            "counts_by_detector": frozen_counts,
            "row_total": len(rows),
            "ledger": {"filename": path.name, "sha256": index.file_sha256(path)},
        }
    )
    make_index(evidence, rows, parent, parent_dir)
    monkeypatch.setattr(
        verifier.parents, "_cohort_gate", lambda **kwargs: (parent, parent_dir)
    )
    monkeypatch.setattr(
        index,
        "_expected_run",
        lambda **kwargs: (
            evidence.index_contract,
            evidence.runtime,
            parent,
            parent_dir,
            evidence.index_dir,
        ),
    )
    before = snapshot(evidence.root.parent)
    legacy, legacy_dir = evidence.legacy_index(
        root=evidence.root, external_root=evidence.index_dir.parent
    )
    reconstructed, directory = verifier._index_gate(
        root=evidence.root,
        external_root=evidence.index_dir.parent,
        cohort_external_root=evidence.external,
        primary_external_root=evidence.primary,
        evidence=verifier._Evidence(),
    )
    assert reconstructed == legacy and directory == legacy_dir
    assert verify(evidence)["legacy_artifact_digest"] == legacy["artifact_digest"]
    assert snapshot(evidence.root.parent) == before


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "run_key",
        "contract_digest",
        "cohort_artifact_digest",
        "runtime_environment_digest",
        "counts_by_detector",
        "cohort_row_total",
    ],
)
def test_resealed_summary_binding_negatives(evidence, field):
    update_summary(evidence, lambda value: value.__setitem__(field, "changed"))
    reject(evidence, "summary changed")


@pytest.mark.parametrize(
    "section,field",
    [
        ("index", "token_total"),
        ("index", "sha256"),
        ("index", "size_bytes"),
        ("index", "centroid_bytes_sha256"),
        ("index", "raw_sample_bytes_sha256"),
        ("replay_ledger", "sha256"),
        ("replay_ledger", "row_digest"),
    ],
)
def test_resealed_output_binding_negatives(evidence, section, field):
    update_summary(evidence, lambda value: value[section].update({field: "changed"}))
    reject(evidence)


@pytest.mark.parametrize("field", ["status", "run_key", "contract_digest"])
def test_resealed_preflight_negatives(evidence, field):
    path = evidence.index_dir / "preflight.json"
    value = read(path)
    value[field] = "changed"
    write(path, seal(value, "preflight_digest"))
    reject(evidence)


def test_index_parent_binding_rejected(evidence):
    path = evidence.root / index.CONTRACT_REL
    value = read(path)
    value["parents"]["frozen_native_cohort"]["artifact_digest"] = "changed"
    write(path, seal(value, "contract_digest"))
    reject(evidence, "parent cohort changed")


@pytest.mark.parametrize(
    "field",
    [
        "position",
        "contract_digest",
        "identity_digest",
        "detector",
        "gps_start",
        "patch_tokens_sha256",
    ],
)
def test_resealed_token_manifest_negatives(evidence, field):
    _, path = index._shard_paths(evidence.index_dir, 0)
    value = read(path)
    value[field] = "changed"
    write(path, seal(value, "shard_digest"))
    reject(evidence, "token shard changed")


@pytest.mark.parametrize(
    "field",
    [
        "identity_digest",
        "clean_window_sha256",
        "raw_context_values_sha256",
        "context_sources_digest",
        "detector",
        "gps_start",
        "cohort_detector_index",
    ],
)
def test_resealed_replay_identity_negatives(evidence, field):
    _, path = index._shard_paths(evidence.index_dir, 0)
    value = read(path)
    value["replay"][field] = "changed"
    write(path, seal(value, "shard_digest"))
    reject(evidence, "token shard changed")


@pytest.mark.parametrize(
    "kind", ["missing", "file_hash", "shape", "dtype", "nonfinite", "value_hash"]
)
def test_token_bytes_negatives(evidence, kind):
    path, manifest_path = index._shard_paths(evidence.index_dir, 0)
    if kind == "missing":
        path.unlink()
    elif kind == "file_hash":
        with path.open("ab") as stream:
            stream.write(b"changed")
    else:
        values = np.load(path)
        if kind == "shape":
            values = values[:-1]
        elif kind == "dtype":
            values = values.astype(np.float64)
        elif kind == "nonfinite":
            values[0, 0] = np.inf
        else:
            values[0, 0] = 0.5
        np.save(path, values)
        manifest = read(manifest_path)
        manifest["token_file_sha256"] = index.file_sha256(path)
        if kind != "value_hash":
            manifest["patch_tokens_sha256"] = hashlib.sha256(
                values.tobytes()
            ).hexdigest()
        write(manifest_path, seal(manifest, "shard_digest"))
    reject(evidence)


def test_replay_ledger_resealed_mismatch(evidence):
    path = evidence.index_dir / "native_index_replay.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    rows[0]["clean_window_sha256"] = "changed"
    path.write_bytes(lines(rows))
    update_summary(
        evidence,
        lambda v: v["replay_ledger"].update(
            sha256=index.file_sha256(path),
            row_digest=contracts.canonical_json_sha256(rows),
        ),
    )
    reject(evidence, "replay/shard mismatch")


@pytest.mark.parametrize(
    "kind",
    [
        "schema",
        "centroid_shape",
        "sample_shape",
        "centroid_dtype",
        "sample_dtype",
        "labels",
        "label_shape",
        "run",
        "K",
        "contract_digest",
        "cohort_artifact_digest",
        "detector_identity_inferred",
        "centroid_norm",
        "sample_norm",
        "centroid_nonfinite",
        "sample_nonfinite",
    ],
)
def test_npz_semantic_negatives_after_fixture_repin(evidence, kind):
    path = evidence.index_dir / "native_index.npz"
    with np.load(path, allow_pickle=False) as data:
        arrays = {name: data[name] for name in data.files}
    if kind == "schema":
        arrays["extra"] = np.array([1])
    elif kind == "centroid_shape":
        arrays["embeddings"] = arrays["embeddings"][:-1]
    elif kind == "sample_shape":
        arrays["raw_embeddings_sample"] = arrays["raw_embeddings_sample"][:-1]
    elif kind == "centroid_dtype":
        arrays["embeddings"] = arrays["embeddings"].astype(np.float64)
    elif kind == "sample_dtype":
        arrays["raw_embeddings_sample"] = arrays["raw_embeddings_sample"].astype(
            np.float64
        )
    elif kind == "labels":
        arrays["labels"] = np.array(["BG_O4a", "BG_O4a"])
    elif kind == "label_shape":
        arrays["labels"] = arrays["labels"][:-1]
    elif kind in {
        "centroid_norm",
        "sample_norm",
        "centroid_nonfinite",
        "sample_nonfinite",
    }:
        key = "embeddings" if kind.startswith("centroid") else "raw_embeddings_sample"
        arrays[key][0, 0] = np.inf if kind.endswith("nonfinite") else 0.5
    else:
        meta = json.loads(str(arrays["meta"].item()))
        meta[kind] = True if kind == "detector_identity_inferred" else "changed"
        arrays["meta"] = np.array(json.dumps(meta))
    np.savez_compressed(path, **arrays)
    update_summary(
        evidence,
        lambda v: v["index"].update(
            sha256=index.file_sha256(path),
            size_bytes=path.stat().st_size,
            centroid_bytes_sha256=hashlib.sha256(
                arrays["embeddings"].tobytes()
            ).hexdigest(),
            raw_sample_bytes_sha256=hashlib.sha256(
                arrays["raw_embeddings_sample"].tobytes()
            ).hexdigest(),
        ),
    )
    reject(evidence, "NPZ|normalization")


@pytest.mark.parametrize(
    "scope,name",
    [
        ("index", "failure.json"),
        ("index", "controller.lock"),
        ("index", "input.partial"),
        ("cohort", "run.lock"),
        ("scan", "failure.json"),
        ("scan", "sqlite_wal"),
    ],
)
def test_parent_and_index_failure_guards(evidence, scope, name):
    directory = {
        "index": evidence.index_dir,
        "cohort": evidence.cohort_dir,
        "scan": evidence.scan_dir,
    }[scope]
    path = (
        Path(str(evidence.database) + "-wal")
        if name == "sqlite_wal"
        else directory / name
    )
    path.write_bytes(b"preserve")
    reject(evidence)


@pytest.mark.parametrize("section", ["index", "replay_ledger"])
def test_escaping_output_path_rejected(evidence, section):
    update_summary(evidence, lambda v: v[section].update(filename="../outside"))
    reject(evidence, "unsafe evidence path")


def test_changed_source_rejected(evidence):
    path = evidence.root / index.IMPLEMENTATION_REL
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    reject(evidence, "executed helper source mismatch")


def cli():
    spec = importlib.util.spec_from_file_location(
        "index_evidence_cli", ROOT / "scripts/verify_dante_o3a_index_evidence.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("fail", [False, True])
def test_cli_stdout_only(evidence, capsys, fail):
    if fail:
        (evidence.index_dir / "failure.json").write_bytes(b"preserve")
    before = snapshot(evidence.root.parent)
    code = cli().main(
        [
            "--repository-root",
            str(evidence.root),
            "--external-root",
            str(evidence.index_dir.parent),
            "--cohort-external-root",
            str(evidence.external),
            "--primary-external-root",
            str(evidence.primary),
        ]
    )
    assert code == int(fail)
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == (
        "FAIL_CLOSED_O3A_INDEX_EVIDENCE"
        if fail
        else "PASS_O3A_READ_ONLY_INDEX_STORED_VALIDATION_ONLY"
    )
    assert snapshot(evidence.root.parent) == before


@pytest.mark.parametrize("flag", ["--run", "--repair", "--resume", "--freeze"])
def test_no_mutation_flag(flag):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts/verify_dante_o3a_index_evidence.py"),
            "--external-root",
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
    assert "unrecognized arguments" in result.stderr


def test_actual_contract_source_bindings_without_history():
    if sys.platform == "win32":
        # The frozen scientific contract is WSL-specific. Do not normalize it
        # or weaken the loader to make native Windows appear production-ready.
        frozen = read(ROOT / index.CONTRACT_REL)
        rebuilt = index.build_index_contract(root=ROOT)
        paths = {"index_root_wsl", "cohort_root_wsl"}
        assert {
            k: v for k, v in frozen.items() if k not in {"storage", "contract_digest"}
        } == {
            k: v for k, v in rebuilt.items() if k not in {"storage", "contract_digest"}
        }
        assert {k: v for k, v in frozen["storage"].items() if k not in paths} == {
            k: v for k, v in rebuilt["storage"].items() if k not in paths
        }
        assert all(frozen["storage"][key] != rebuilt["storage"][key] for key in paths)
        with pytest.raises(contracts.ContractError, match="frozen contract changed"):
            index.load_index_contract(root=ROOT)
    else:
        assert index.load_index_contract(root=ROOT)["gates"][
            "exact_cohort_counts_by_detector"
        ]
    assert len(verifier._sources(ROOT)) == 20
