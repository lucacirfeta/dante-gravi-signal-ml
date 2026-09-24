from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from src.dante_light import o3a_native_classification as nc
from src.dante_light.contracts import ContractError, canonical_json_sha256

ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = {
    "H1": {"ci_lower": 0.25, "p99": 0.375, "ci_upper": 0.5},
    "L1": {"ci_lower": 0.5, "p99": 0.625, "ci_upper": 0.75},
}


def rows():
    return [
        {
            "population": "primary_candidate",
            "ordinal": i,
            "detector": detector,
            "gps_start": 1000000 + 64 * (i % 5),
            "identity_digest": f"identity-{i}",
            "native_score": score,
            "score_float32_hex": nc._float32_hex(score),
            "image_sha256": "preserved-image",
            "extra_provenance": {"retain": True},
        }
        for i, (detector, score) in enumerate(
            (d, s) for d in ("H1", "L1") for s in (0.125, 0.25, 0.5, 0.75, 0.875)
        )
    ]


def classify(value):
    return nc.classify_rows(
        value, thresholds=THRESHOLDS, expected_counts={"H1": 5, "L1": 5}
    )


@pytest.mark.parametrize(
    "score,label",
    [
        (0.125, "BACKGROUND"),
        (0.25, "AMBIGUOUS"),
        (0.375, "AMBIGUOUS"),
        (0.5, "AMBIGUOUS"),
        (0.75, "ROBUST"),
        (np.nextafter(0.25, 0), "BACKGROUND"),
        (np.nextafter(0.5, 1), "ROBUST"),
    ],
)
def test_strict_boundaries(score, label):
    assert nc.classify_score(score, lower=0.25, upper=0.5) == label


@pytest.mark.parametrize(
    "score,lower,upper",
    [(np.nan, 0.25, 0.5), (np.inf, 0.25, 0.5), (0.5, np.nan, 0.5), (0.5, 0.7, 0.6)],
)
def test_invalid_values_fail_closed(score, lower, upper):
    with pytest.raises(ContractError):
        nc.classify_score(score, lower=lower, upper=upper)


def test_equal_endpoints_still_ambiguous():
    assert nc.classify_score(0.5, lower=0.5, upper=0.5) == "AMBIGUOUS"


def test_detector_locality_preserves_all_source_fields_and_counts():
    value = rows()
    before = copy.deepcopy(value)
    result, counts = classify(value)
    assert value == before
    assert counts == {
        "H1": {"BACKGROUND": 1, "AMBIGUOUS": 2, "ROBUST": 2},
        "L1": {"BACKGROUND": 2, "AMBIGUOUS": 2, "ROBUST": 1},
    }
    assert result[3]["native_class"] == "ROBUST"
    assert result[8]["native_class"] == "AMBIGUOUS"  # Same score, different detector.
    for source, classified in zip(value, result):
        assert {k: classified[k] for k in source} == source
    assert len(result) == sum(sum(c.values()) for c in counts.values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("ordinal", 9),
        ("detector", "V1"),
        ("population", "native_calibration"),
        ("gps_start", 1000000),
        ("gps_start", np.nan),
        ("native_score", np.inf),
        ("score_float32_hex", "bad"),
        ("native_class", "ROBUST"),
        ("taxonomy", "x"),
        ("disposition", "keep"),
        ("identity_digest", ""),
    ],
)
def test_input_corruption_rejected(field, value):
    value_rows = rows()
    value_rows[1][field] = value
    with pytest.raises(ContractError):
        classify(value_rows)


def test_missing_or_reordered_identity_rejected():
    with pytest.raises(ContractError, match="population"):
        classify(rows()[:-1])
    changed = rows()
    changed[0], changed[1] = changed[1], changed[0]
    with pytest.raises(ContractError):
        classify(changed)


def test_detector_population_and_threshold_set_rejected():
    with pytest.raises(ContractError, match="detector population"):
        nc.classify_rows(
            rows(), thresholds=THRESHOLDS, expected_counts={"H1": 4, "L1": 6}
        )
    with pytest.raises(ContractError, match="detector thresholds"):
        nc.classify_rows(
            rows(),
            thresholds={"H1": THRESHOLDS["H1"]},
            expected_counts={"H1": 5, "L1": 5},
        )


def test_real_metadata_contract_uses_approved_rule_and_all_seeds():
    c = nc.build_contract(root=ROOT)
    assert c["rule"] == nc.RULE
    assert c["boundary_class"] == "AMBIGUOUS"
    assert c["population"]["rows_by_detector"] == {"H1": 3624, "L1": 5276}
    assert all(v is False for v in c["scientific_boundary"].values())
    nc.nt._sealed(c, "contract_digest")


def test_source_or_resealed_contract_drift_rejected(tmp_path, monkeypatch):
    value = {"contract_digest": "before"}
    monkeypatch.setattr(nc, "build_contract", lambda **kw: value)
    nc.freeze_contract(root=tmp_path)
    assert nc.load_contract(root=tmp_path) == value
    monkeypatch.setattr(nc, "build_contract", lambda **kw: {"contract_digest": "after"})
    with pytest.raises(ContractError, match="source changed"):
        nc.load_contract(root=tmp_path)
    with pytest.raises(ContractError):
        nc.freeze_contract(root=tmp_path)


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    c = {
        "contract_digest": "synthetic",
        "rule": nc.RULE,
        "population": {"rows_by_detector": {"H1": 5, "L1": 5}},
        "rescore_parent": {"artifact_digest": "rescore"},
        "scientific_boundary": {"global_significance_claim": False},
        "output": {
            "summary_filename": "summary.json",
            "candidate_filename": "rows.jsonl",
        },
    }
    threshold = {
        "artifact_digest": "threshold",
        "runtime_environment_digest": "runtime",
        "thresholds": THRESHOLDS,
    }
    monkeypatch.setattr(nc, "load_contract", lambda **kw: c)
    monkeypatch.setattr(
        nc, "_verified_inputs", lambda *a, **kw: (rows(), threshold, "source-sha")
    )
    return tmp_path, c


def test_deterministic_replay_and_compact_gate(synthetic):
    root, c = synthetic
    first, directory = nc.execute(root=root, external_root=root / "runs")
    assert not (root / nc.COMPACT_REL).exists()
    replay, _ = nc.execute(root=root, external_root=root / "runs", verify=True)
    assert first == replay
    compact = json.loads((root / nc.COMPACT_REL).read_text())
    nc.nt._sealed(compact, "artifact_digest")
    assert compact["status"] == "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION"
    assert compact["run_artifact_digest"] == first["artifact_digest"]


@pytest.mark.parametrize("target", ["summary", "output"])
def test_divergent_output_or_resealed_summary_preserved(synthetic, target):
    root, c = synthetic
    _, directory = nc.execute(root=root, external_root=root / "runs")
    path = (
        directory
        / c["output"][
            "summary_filename" if target == "summary" else "candidate_filename"
        ]
    )
    if target == "summary":
        value = json.loads(path.read_text())
        value.pop("artifact_digest")
        value["counts_by_detector_and_class"]["H1"]["ROBUST"] += 1
        value["artifact_digest"] = canonical_json_sha256(value)
        path.write_text(json.dumps(value))
    else:
        value = path.read_text().replace(
            '"native_class":"ROBUST"', '"native_class":"BACKGROUND"', 1
        )
        path.write_text(value)
    altered = path.read_bytes()
    with pytest.raises(ContractError, match="replay changed"):
        nc.execute(root=root, external_root=root / "runs", verify=True)
    assert path.read_bytes() == altered
    assert (directory / "failure.json").exists()
    assert not (root / nc.COMPACT_REL).exists()
    with pytest.raises(ContractError, match="failure requires review"):
        nc.execute(root=root, external_root=root / "runs")


def test_missing_evidence_and_lock(synthetic):
    root, c = synthetic
    with pytest.raises(ContractError, match="evidence missing"):
        nc.execute(root=root, external_root=root / "runs", verify=True)
    directory = nc._run_dir(c, root / "runs")
    with nc.nt._lock(directory):
        with pytest.raises(ContractError, match="already active"):
            nc.execute(root=root, external_root=root / "runs")
    assert not (directory / "failure.json").exists()


def test_parent_and_candidate_hash_gate(tmp_path, monkeypatch):
    summary = {
        "artifact_digest": "threshold",
        "native_rescore_artifact_digest": "rescore",
    }
    receipt = {"status": "PASS_VERIFIED_O3A_NATIVE_THRESHOLDS"}
    receipt["artifact_digest"] = canonical_json_sha256(receipt)
    c = {
        "threshold_parent": {
            "artifact_digest": receipt["artifact_digest"],
            "run_artifact_digest": "threshold",
        },
        "rescore_parent": {
            "artifact_digest": "rescore",
            "run_key": "key",
            "output_sha256": {"primary_candidate": "wrong"},
        },
    }
    nc._atomic_json(tmp_path / nc.nt.COMPACT_REL, receipt)
    monkeypatch.setattr(nc.nt, "execute_thresholds", lambda **kw: (summary, tmp_path))
    parent = tmp_path / "native_rescore_key"
    parent.mkdir()
    (parent / "primary_candidate.jsonl").write_text("{}\n")
    with pytest.raises(ContractError, match="input hash changed"):
        nc._verified_inputs(c, root=tmp_path, external_root=tmp_path)
    c["threshold_parent"]["run_artifact_digest"] = "wrong"
    with pytest.raises(ContractError, match="verified parent changed"):
        nc._verified_inputs(c, root=tmp_path, external_root=tmp_path)
