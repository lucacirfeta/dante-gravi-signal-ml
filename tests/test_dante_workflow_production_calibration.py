"""Isolated productive profile, physical coverage and no-fallback reader wiring."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.dante_workflow import production_calibration as gate
from src.dante_workflow.calibration_recovery import sealed
from src.dante_workflow.input_coverage import InputCoverageError
from src.dante_workflow.input_preflight import _hash


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "config/dante_workflow_production_calibration_v1.json"


def test_profile_pins_science_and_preserves_old_boundary():
    profile = gate.load_profile(PROFILE, _hash(PROFILE), ROOT)
    assert profile["historical_output_writes_allowed"] is False
    assert profile["historical_shard_or_threshold_reuse_allowed"] is False
    assert "score_atol" not in profile
    assert "top_k" not in profile
    assert profile["boundary"]["legacy_workflow_redirected"] is False
    assert gate.source_hashes(ROOT, profile)[
        "src/dante_workflow/production_calibration.py"
    ] == _hash(Path(gate.__file__))


@pytest.mark.parametrize(
    "fault",
    ["version", "science", "outputs", "reuse", "o4b", "scope", "sources", "parent"],
)
def test_modified_authority_refused(tmp_path, fault):
    value = json.loads(PROFILE.read_text())
    if fault == "version":
        value["schema_version"] = True
    elif fault == "science":
        value["scientific_rules"] = "retune"
    elif fault == "outputs":
        value["historical_output_writes_allowed"] = True
    elif fault == "reuse":
        value["historical_shard_or_threshold_reuse_allowed"] = True
    elif fault == "o4b":
        value["boundary"]["o4b_launch_allowed"] = True
    elif fault == "scope":
        value["boundary"]["preflight_and_provider_only"] = False
    elif fault == "sources":
        value["source_paths"].append(value["source_paths"][0])
    else:
        value["protocol_parent"]["sha256"] = "0" * 64
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(value))
    with pytest.raises(InputCoverageError):
        gate.load_profile(path, _hash(path), ROOT)


@pytest.fixture
def manifest_case(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    first = raw / "first.h5"
    first.write_bytes(b"synthetic-file")
    row = {
        "detector": "H1",
        "gps_start": 0,
        "gps_end": 10,
        "sha256": _hash(first),
        "physical_copies": [
            {
                "relative_path": "first.h5",
                "sha256": _hash(first),
                "size_bytes": first.stat().st_size,
            }
        ],
    }
    path = tmp_path / "manifest.jsonl"
    return SimpleNamespace(raw=raw, first=first, row=row, path=path)


def audit(c, rows=None, normal=None):
    c.path.write_text("\n".join(json.dumps(r) for r in (rows or [c.row])))
    return gate.inspect_manifest(
        c.path, _hash(c.path), c.raw, normal or {"H1": {(1, 3)}}
    )


def test_hashes_required_calibration_files_not_entire_primary_manifest(manifest_case):
    c = manifest_case
    other = deepcopy(c.row)
    other.update(gps_start=20, gps_end=30)
    other["physical_copies"][0]["relative_path"] = "missing-irrelevant.h5"
    result, entries, hashes = audit(c, [c.row, other])
    assert result["required_logical_span_count"] == 1
    assert result["missing_logical_span_count"] == 0
    assert result["covered_normal_unique_context_count"] == 1
    assert entries["H1"][0][2] == c.first
    assert hashes == {c.first: _hash(c.first)}


def test_absent_copy_reported_without_admitting_substitution(manifest_case):
    c = manifest_case
    c.first.unlink()
    result, entries, hashes = audit(c)
    assert result["missing_logical_span_count"] == 1
    assert result["covered_normal_unique_context_count"] == 0
    assert not entries and not hashes


def test_one_frozen_copy_suffices_but_all_existing_copies_are_checked(manifest_case):
    c = manifest_case
    copy = deepcopy(c.row["physical_copies"][0])
    copy["relative_path"] = "duplicate.h5"
    c.row["physical_copies"].append(copy)
    assert audit(c)[0]["verified_physical_copy_count"] == 1
    (c.raw / "duplicate.h5").write_bytes(b"changed-length")
    with pytest.raises(InputCoverageError, match="size|pin"):
        audit(c)


@pytest.mark.parametrize(
    "fault",
    [
        "sha",
        "size",
        "declared_sha",
        "duplicate",
        "traversal",
        "absolute",
        "backslash",
        "empty_copies",
    ],
)
def test_raw_corruption_and_escape_never_become_gap_fallback(manifest_case, fault):
    c = manifest_case
    copy = c.row["physical_copies"][0]
    if fault == "sha":
        c.first.write_bytes(b"corrupted-file")
    elif fault == "size":
        copy["size_bytes"] += 1
    elif fault == "declared_sha":
        copy["sha256"] = "0" * 64
    elif fault == "duplicate":
        c.row["physical_copies"].append(deepcopy(copy))
    elif fault == "traversal":
        copy["relative_path"] = "../first.h5"
    elif fault == "absolute":
        copy["relative_path"] = "/first.h5"
    elif fault == "backslash":
        copy["relative_path"] = "a\\first.h5"
    else:
        c.row["physical_copies"] = []
    with pytest.raises(InputCoverageError):
        audit(c)


def test_context_across_manifest_gap_not_reported_ready(manifest_case):
    c = manifest_case
    c.row["gps_end"] = 2
    result, _, _ = audit(c)
    assert result["normal_unique_context_count"] == 1
    assert result["covered_normal_unique_context_count"] == 0


def test_half_open_overlap_and_detector_locality(manifest_case):
    c = manifest_case
    result, _, _ = audit(c, normal={"H1": {(10, 12)}, "L1": {(0, 1)}})
    assert result["required_logical_span_count"] == 0
    assert result["normal_unique_context_count"] == 2
    assert result["covered_normal_unique_context_count"] == 0


@pytest.fixture
def population():
    admitted = SimpleNamespace(
        readiness={"detectors": ["H1", "L1"], "counts": {"H1": 1, "L1": 1}},
        rows={("H1", 0, 6): {}},
    )
    protocol = {
        "representation": {"analysis_duration_s": 4, "whitening_pad_s": 1},
        "calibration_population": {
            "identity_count": 2,
            "session_detector_counts": {"H1": 1, "L1": 1},
        },
    }
    rows = [
        dict(
            detector=d,
            session_id=1,
            catalog_gps_start=a,
            analysis_gps_start=a + 1,
            required_padded_interval=[a, a + 6],
            historical_hdf5=d + ".h5",
        )
        for d, a in [("H1", 0), ("L1", 10)]
    ]
    return SimpleNamespace(admitted=admitted, protocol=protocol, rows=rows)


def test_all_frozen_identities_and_exact_supplement_split(population):
    c = population
    allowed, normal, counts = gate.intervals(c.rows, c.admitted, c.protocol)
    assert allowed == {("H1", 0, 6), ("L1", 10, 16)}
    assert normal == {"L1": {(10, 16)}}
    assert counts == {"H1": 1, "L1": 1}


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "drop",
        "detector",
        "geometry",
        "nonfinite",
        "type",
        "session",
        "extra_admission",
    ],
)
def test_population_geometry_and_admission_changes_refused(population, fault):
    c = population
    if fault == "duplicate":
        c.rows.append(c.rows[0])
    elif fault == "drop":
        c.rows.pop()
    elif fault == "detector":
        c.rows[0]["detector"] = "V1"
    elif fault == "geometry":
        c.rows[0]["required_padded_interval"][1] += 1
    elif fault == "nonfinite":
        c.rows[0]["catalog_gps_start"] = float("nan")
    elif fault == "type":
        c.rows[0]["analysis_gps_start"] = True
    elif fault == "session":
        c.protocol["calibration_population"]["session_detector_counts"]["H1"] = 2
    else:
        c.admitted.rows["L1", 20, 26] = {}
    with pytest.raises(InputCoverageError):
        gate.intervals(c.rows, c.admitted, c.protocol)


@pytest.fixture
def combined_provider(tmp_path):
    import h5py

    root = tmp_path / "root"
    raw = tmp_path / "raw"
    root.mkdir()
    raw.mkdir()
    rows = []
    for index in (0, 1):
        path = raw / f"frame{index}.h5"
        with h5py.File(path, "w") as h:
            h.create_dataset(
                "Strain",
                data=np.arange(index * 8192, (index + 1) * 8192, dtype=np.float64),
            )
        rows.append(
            {
                "detector": "H1",
                "gps_start": index * 2,
                "gps_end": (index + 1) * 2,
                "sha256": _hash(path),
                "physical_copies": [
                    {
                        "relative_path": path.name,
                        "sha256": _hash(path),
                        "size_bytes": path.stat().st_size,
                    }
                ],
            }
        )
    manifest = root / "manifest.jsonl"
    manifest.write_text("\n".join(json.dumps(r) for r in rows))
    receipt = root / "admission.json"
    receipt.write_text("synthetic-admission")
    sentinel = object()
    calls = []

    def read(**kw):
        calls.append(kw)
        return sentinel

    admitted = SimpleNamespace(
        root=root,
        receipt_path=receipt,
        receipt_sha=_hash(receipt),
        rows={("L1", 20, 22): {}},
        read=read,
    )
    provider = gate.ProductionContextProvider(
        admitted=admitted,
        allowed={("H1", 1, 3), ("L1", 20, 22)},
        normal={"H1": {(1, 3)}},
        manifest_ref={"path": "manifest.jsonl", "sha256": _hash(manifest)},
        raw_root=raw,
    )
    return SimpleNamespace(
        provider=provider,
        raw=raw,
        manifest=manifest,
        receipt=receipt,
        calls=calls,
        sentinel=sentinel,
    )


def test_combined_reader_stitches_with_unchanged_legacy_slice(combined_provider):
    c = combined_provider
    result = c.provider.read(detector="H1", start=1, end=3)
    assert np.array_equal(result.series.value, np.arange(4096, 12288, dtype=np.float64))
    assert result.series.t0.value == 1
    assert result.series.sample_rate.value == 4096
    assert len(result.sources) == 2
    assert c.calls == []
    assert c.provider.read(detector="L1", start=20, end=22) is c.sentinel
    assert c.calls == [dict(detector="L1", start=20, end=22)]


@pytest.mark.parametrize(
    "detector,start,end",
    [
        ("V1", 1, 3),
        ("L1", 1, 3),
        ("H1", 0, 3),
        ("H1", True, 3),
        ("H1", 1, float("nan")),
    ],
)
def test_provider_refuses_undeclared_or_changed_keys(
    combined_provider, detector, start, end
):
    with pytest.raises(InputCoverageError, match="exact productive"):
        combined_provider.provider.read(detector=detector, start=start, end=end)


@pytest.mark.parametrize("target", ["manifest", "receipt", "frame"])
def test_reader_rechecks_pins_and_never_falls_back(combined_provider, target):
    c = combined_provider
    path = c.raw / "frame0.h5" if target == "frame" else getattr(c, target)
    path.write_bytes(b"changed")
    with pytest.raises((InputCoverageError, RuntimeError)):
        c.provider.read(detector="H1", start=1, end=3)
    assert c.calls == []


def test_independent_preflight_cli_never_overwrites_history(
    tmp_path, monkeypatch, capsys
):
    value = sealed(
        {
            "status": "BLOCKED_PRODUCTIVE_RAW_FILES",
            "profile_run_key": "f" * 64,
            "identity_count": 2,
            "counts": {"H1": 1, "L1": 1},
            "input_bytes_ready": False,
            "physical_input_audit": {"missing_logical_span_count": 1, "records": []},
        }
    )
    monkeypatch.setattr(gate, "preflight", lambda **kw: value)
    monkeypatch.setattr(
        gate,
        "load_profile",
        lambda *a: {"output_namespace": "production_calibration_v1"},
    )
    args = [
        "--repository-root",
        str(tmp_path / "repo"),
        "--profile",
        str(tmp_path / "profile"),
        "--profile-sha256",
        "0" * 64,
        "--receipt",
        str(tmp_path / "admission" / "receipt"),
        "--qualification",
        str(tmp_path / "score" / "receipt"),
        "--raw-root",
        str(tmp_path / "raw"),
        "--output-root",
        str(tmp_path / "output"),
    ]
    assert gate.main(["--stage", "preflight", *args]) == 2
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["scientific_execution_ready"] is False
    assert (
        gate.main(
            [
                "--stage",
                "verify",
                *args,
                "--expected",
                evidence["evidence"],
                "--expected-sha256",
                evidence["sha256"],
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["independent_replay"] is True
    with pytest.raises(InputCoverageError, match="already exists"):
        gate.main(["--stage", "preflight", *args])
    with pytest.raises(SystemExit):
        gate.main(["--stage", "preflight", *args[:-2], "--output-root", str(tmp_path)])


@pytest.fixture
def preflight_case(manifest_case, population, monkeypatch):
    from src.dante_workflow import adapters, schema
    from src.dante_light import o4a_corrected_runtime
    from tests.test_dante_workflow_scoring_replay import environment

    c, pop = manifest_case, population
    c.row.update(detector="L1", gps_start=10, gps_end=20)
    audit(c, normal={"L1": {(10, 16)}})
    root = c.path.parent
    protocol = deepcopy(pop.protocol)
    protocol["source_references"] = {
        "raw_manifest": {"path": c.path.name, "sha256": _hash(c.path)}
    }
    protocol["execution_parameters"] = {
        "primary_calibration": {"device": "synthetic", "batch_size": 2, "workers": 1}
    }
    protocol_path = root / "protocol.json"
    protocol_path.write_text(json.dumps(protocol))
    workflow = root / "workflow.json"
    workflow.write_text("{}")
    runtime = root / "runtime.json"
    env = environment("qualified-driver")
    runtime.write_text(json.dumps({"runtime_environment": environment()}))
    source = root / "source.py"
    source.write_text("synthetic source")
    receipt = root / "admission.json"
    receipt.write_text("synthetic receipt")
    pop.admitted.root = root
    pop.admitted.receipt_sha = _hash(receipt)
    pop.admitted.readiness["identity_count"] = 2
    parent = {"path": protocol_path.name, "sha256": _hash(protocol_path)}
    pop.admitted.receipt = {"parent": parent}
    policy_path = root / "policy.json"
    policy_path.write_text("{}")
    qp = {"path": policy_path.name, "sha256": _hash(policy_path)}
    policy = {
        "protocol_parent": parent,
        "runtime_parent": {"path": runtime.name, "sha256": _hash(runtime)},
        "boundary": {"full_calibration_or_workflow_verified": False},
    }
    qualified = sealed(
        {
            "status": "PASS_BOUNDED_FRESH_SCORING_REPLAY_ONLY",
            "policy_sha256": qp["sha256"],
            "admission_sha256": _hash(receipt),
            "record_count": 1,
            "parents": {"protocol_parent": parent},
            "boundary": policy["boundary"],
            "source_hashes": {source.name: _hash(source)},
            "runtime": env,
        }
    )
    qualified_path = root / "qualified.json"
    qualified_path.write_text(json.dumps(qualified))
    profile = {
        "protocol_parent": parent,
        "workflow_parent": {"path": workflow.name, "sha256": _hash(workflow)},
        "qualification_policy": qp,
        "qualification_sha256": _hash(qualified_path),
        "admission_sha256": _hash(receipt),
        "boundary": gate.RULES["boundary"],
    }
    profile_path = root / "profile.json"
    profile_path.write_text("{}")
    monkeypatch.setattr(gate, "load_profile", lambda *a: profile)
    monkeypatch.setattr(gate, "load_policy", lambda *a: policy)
    monkeypatch.setattr(gate, "source_hashes", lambda *a: {source.name: _hash(source)})
    monkeypatch.setattr(gate, "AdmittedContextProvider", lambda *a, **kw: pop.admitted)
    monkeypatch.setattr(schema, "load_workflow_spec", lambda *a, **kw: "synthetic")
    monkeypatch.setattr(
        adapters,
        "build_adapter",
        lambda spec: SimpleNamespace(
            iter_calibration_input_metadata=lambda *a: iter(pop.rows)
        ),
    )
    monkeypatch.setattr(
        o4a_corrected_runtime, "capture_runtime_environment", lambda device: env
    )
    return SimpleNamespace(
        c=c,
        source=source,
        env=env,
        profile=profile,
        qualified=qualified,
        qualified_path=qualified_path,
        args=dict(
            root=root,
            profile_path=profile_path,
            profile_sha=_hash(profile_path),
            receipt_path=receipt,
            qualification_path=qualified_path,
            raw_root=c.raw,
        ),
    )


def test_preflight_integrates_real_inventory_and_bound_receipts(preflight_case):
    c = preflight_case
    result = gate.preflight(**c.args)
    assert result["status"] == "PASS_PRODUCTIVE_INPUT_BYTES_ONLY"
    assert result["identity_count"] == 2
    assert result["admitted_context_count"] == 1
    assert result["physical_input_audit"]["verified_physical_copy_count"] == 1
    assert result["scientific_execution_ready"] is False
    assert result["historical_calibration_score_values_read"] is False
    assert result["verified_bounded_gate_receipt_loaded"] is True
    assert gate.preflight(**c.args) == result
    c.c.first.unlink()
    blocked = gate.preflight(**c.args)
    assert blocked["status"] == "BLOCKED_PRODUCTIVE_RAW_FILES"
    assert blocked["profile_run_key"] != result["profile_run_key"]


@pytest.mark.parametrize(
    "fault", ["status", "admission", "parent", "source", "runtime", "count"]
)
def test_qualified_runtime_receipt_cannot_be_borrowed_or_promoted(
    preflight_case, fault
):
    from tests.test_dante_workflow_scoring_replay import environment

    c = preflight_case
    if fault == "status":
        c.qualified["status"] = "UNVERIFIED"
    elif fault == "admission":
        c.qualified["admission_sha256"] = "0" * 64
    elif fault == "parent":
        c.qualified["parents"]["protocol_parent"] = {}
    elif fault == "source":
        c.qualified["source_hashes"][c.source.name] = "0" * 64
    elif fault == "runtime":
        c.qualified["runtime"] = environment("other-driver-needs-fresh-numerical-gate")
    else:
        c.qualified["record_count"] = 2
    body = dict(c.qualified)
    body.pop("digest")
    c.qualified_path.write_text(json.dumps(sealed(body)))
    c.profile["qualification_sha256"] = _hash(c.qualified_path)
    with pytest.raises(InputCoverageError):
        gate.preflight(**c.args)
