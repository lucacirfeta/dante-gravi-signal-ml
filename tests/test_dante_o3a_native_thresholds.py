from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from src.dante_light import o3a_native_thresholds as nt
from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[1]
METHOD = {
    "bootstrap_replicates": 201,
    "bootstrap_seed": 42,
    "bootstrap_chunk_size": 50,
    "block_length": 3,
}


def rows(detector="H1"):
    values = [0.1, 0.2, 0.3, 0.15, 0.25, 0.35, 0.2, 0.3, 0.5, 0.48, 0.49]
    return [
        {
            "population": "native_calibration",
            "detector": detector,
            "gps_start": 1000000 + 64 * i,
            "calibration_row_number": i,
            "bootstrap_block_index": i // 3,
            "identity_digest": f"identity-{detector}-{i}",
            "native_score": float(np.float32(values[i])),
            "score_float32_hex": nt._float32_hex(values[i]),
        }
        for i in range(11)
    ]


def validate(value):
    return nt.validate_score_rows(
        value, detector="H1", count=11, block_length=3, stride=64
    )


def test_metadata_freeze_matches_approved_native_method():
    contract = nt.build_threshold_contract(root=ROOT)
    assert (
        contract["method"] == json.loads((ROOT / nt.METHOD_REL).read_text())["method"]
    )
    assert contract["population"]["rows_by_detector"] == {"H1": 5000, "L1": 5000}
    assert contract["population"]["bootstrap_rows_per_detector"] == 4998
    assert contract["scientific_boundary"]["candidate_scores_used_for_fitting"] is False
    assert contract["scientific_boundary"]["classification_performed"] is False
    nt._sealed(contract, "contract_digest")


def test_frozen_contract_rejects_resealed_source_drift(tmp_path, monkeypatch):
    value = {"sources": {"file": "before"}}
    value["contract_digest"] = canonical_json_sha256(value)
    monkeypatch.setattr(nt, "build_threshold_contract", lambda **kw: value)
    nt.freeze_threshold_contract(root=tmp_path)
    assert nt.load_threshold_contract(root=tmp_path) == value
    changed = copy.deepcopy(value)
    changed["sources"]["file"] = "after"
    body = {k: v for k, v in changed.items() if k != "contract_digest"}
    changed["contract_digest"] = canonical_json_sha256(body)
    monkeypatch.setattr(nt, "build_threshold_contract", lambda **kw: changed)
    with pytest.raises(ContractError, match="source changed"):
        nt.load_threshold_contract(root=tmp_path)
    with pytest.raises(ContractError):
        nt.freeze_threshold_contract(root=tmp_path)


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("detector", "L1"),
        ("population", "primary_candidate"),
        ("calibration_row_number", 7),
        ("bootstrap_block_index", 9),
        ("gps_start", 1000000),
        ("gps_start", 1000001),
        ("gps_start", float("nan")),
        ("native_score", float("nan")),
        ("score_float32_hex", "00"),
    ],
)
def test_row_corruption_rejected(field, replacement):
    value = rows()
    value[1][field] = replacement
    with pytest.raises(ContractError, match="identity/order/score"):
        validate(value)


def test_count_order_and_tail_geometry():
    with pytest.raises(ContractError, match="count"):
        validate(rows()[:-1])
    value = rows()
    value[10]["gps_start"] += 12  # Point-only tail need not form a full block.
    score, audit = validate(value)
    assert len(score) == audit["row_total"] == 11
    value[9], value[10] = value[10], value[9]
    with pytest.raises(ContractError):
        validate(value)


def test_exact_block_oracle_tail_and_chunk_invariance():
    values = np.array([0.1, 0.2, 0.3, 0.15, 0.25, 0.35, 0.2, 0.3, 0.5, 0.48, 0.49])
    rng = np.random.default_rng(METHOD["bootstrap_seed"])
    blocks = values[:9].reshape(3, 3)
    distribution = np.array(
        [
            np.percentile(blocks[rng.integers(0, 3, size=3)].ravel(), 99)
            for _ in range(METHOD["bootstrap_replicates"])
        ]
    )
    result = nt.compute_threshold(values, method=METHOD)
    assert result["p99"] == np.percentile(values, 99)
    assert result["p99"] != np.percentile(values[:9], 99)
    assert result["ci_lower"] == np.percentile(distribution, 2.5)
    assert result["ci_upper"] == np.percentile(distribution, 97.5)
    assert result["point_only_tail_rows"] == 2
    assert result["n_bootstrap_rows"] == 9
    assert result["ci_width"] == result["ci_upper"] - result["ci_lower"]
    assert result["ci_width_fraction_of_p99"] == result["ci_width"] / result["p99"]
    assert (
        nt.compute_threshold(values, method={**METHOD, "bootstrap_chunk_size": 1})
        == result
    )


def test_degenerate_interval_preserves_native_method_not_new_precision_gate():
    result = nt.compute_threshold(np.zeros(11), method=METHOD)
    assert result["ci_width"] == 0
    assert result["ci_width_fraction_of_p99"] is None


def test_invalid_interval_stops(monkeypatch):
    monkeypatch.setattr(
        nt,
        "block_bootstrap_p99_ci",
        lambda *a, **kw: {"p99": 0.5, "ci_lower": 0.6, "ci_upper": 0.8},
    )
    with pytest.raises(ContractError, match="interval invalid"):
        nt.compute_threshold(np.zeros(11), method=METHOD)


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    parent_dir = tmp_path / "parent"
    parent_dir.mkdir()
    outputs, hashes = {}, {}
    for detector in ("H1", "L1"):
        name = "native_calibration_" + detector
        value = rows(detector)
        # H1 and L1 deliberately differ; fitting must remain detector-local.
        for row in value:
            if detector == "L1":
                row["native_score"] = float(np.float32(row["native_score"] + 0.2))
                row["score_float32_hex"] = nt._float32_hex(row["native_score"])
        path = parent_dir / (name + ".jsonl")
        path.write_text("\n".join(json.dumps(r) for r in value))
        hashes[name] = nt.file_sha256(path)
        outputs[name] = {
            "filename": path.name,
            "row_digest": canonical_json_sha256(value),
        }
    parent = {
        "artifact_digest": "parent-artifact",
        "run_key": "parent-key",
        "contract_digest": "parent-contract",
        "output_sha256": hashes,
    }
    contract = {
        "contract_digest": "test-contract",
        "parent_rescore": parent,
        "population": {
            "rows_by_detector": {"H1": 11, "L1": 11},
            "bootstrap_rows_per_detector": 9,
            "within_block_stride_s": 64,
        },
        "method": METHOD,
        "scientific_boundary": {"classification_performed": False},
        "output": {"summary_filename": "native_thresholds_summary.json"},
    }
    monkeypatch.setattr(nt, "load_threshold_contract", lambda **kw: contract)
    monkeypatch.setattr(
        nt,
        "load_runtime_contract",
        lambda **kw: {"runtime_environment": {"environment_digest": "runtime"}},
    )
    monkeypatch.setattr(
        nt,
        "verify_native_rescore",
        lambda **kw: ({**parent, "outputs": outputs}, parent_dir),
    )
    return tmp_path, contract, parent_dir


def test_execution_and_independent_verification_do_not_fit_candidates(synthetic):
    root, contract, parent = synthetic
    # No candidate file exists. Parent integrity is mocked, fitting isn't.
    result, directory = nt.execute_thresholds(root=root, external_root=root / "runs")
    assert not (root / nt.COMPACT_REL).exists()
    replay, _ = nt.execute_thresholds(
        root=root, external_root=root / "runs", verify=True
    )
    assert replay == result
    assert replay["thresholds"]["H1"]["p99"] < replay["thresholds"]["L1"]["p99"]
    compact = json.loads((root / nt.COMPACT_REL).read_text())
    nt._sealed(compact, "artifact_digest")
    assert compact["run_artifact_digest"] == result["artifact_digest"]
    assert compact["status"] == "PASS_VERIFIED_O3A_NATIVE_THRESHOLDS"


def test_resealed_summary_tamper_is_not_overwritten(synthetic):
    root, contract, parent = synthetic
    _, directory = nt.execute_thresholds(root=root, external_root=root / "runs")
    path = directory / contract["output"]["summary_filename"]
    changed = json.loads(path.read_text())
    changed["thresholds"]["H1"]["p99"] = -1
    changed.pop("artifact_digest")
    changed["artifact_digest"] = canonical_json_sha256(changed)
    path.write_text(json.dumps(changed))
    before = path.read_bytes()
    with pytest.raises(ContractError, match="deterministic replay"):
        nt.execute_thresholds(root=root, external_root=root / "runs", verify=True)
    assert path.read_bytes() == before
    assert (directory / "failure.json").exists()
    assert not (root / nt.COMPACT_REL).exists()
    with pytest.raises(ContractError, match="failure requires review"):
        nt.execute_thresholds(root=root, external_root=root / "runs")


def test_changed_input_fails_without_compact(synthetic):
    root, contract, parent = synthetic
    with (parent / "native_calibration_H1.jsonl").open("a") as stream:
        stream.write("\n{}")
    with pytest.raises(ContractError, match="input changed"):
        nt.execute_thresholds(root=root, external_root=root / "runs")
    assert not (root / nt.COMPACT_REL).exists()


def test_missing_summary_and_singleton_lock(synthetic):
    root, contract, parent = synthetic
    external = root / "runs"
    with pytest.raises(ContractError, match="summary missing"):
        nt.execute_thresholds(root=root, external_root=external, verify=True)
    directory = nt._run_dir(contract, external)
    with nt._lock(directory):
        with pytest.raises(ContractError, match="already active"):
            nt.execute_thresholds(root=root, external_root=external)
    assert not (directory / "failure.json").exists()
