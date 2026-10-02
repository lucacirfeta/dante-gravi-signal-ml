"""Calibration metadata/byte gate without numerical score or raw measurement."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.dante_workflow import cli
from src.dante_workflow.adapters.base import StageAdapter
from src.dante_workflow.adapters.o4a_corrected import O4aCorrectedAdapter
from src.dante_workflow.calibration_inputs import (
    CalibrationInputBinding,
    inspect_calibration_inputs,
)
from src.dante_workflow.input_preflight import (
    InputPreflightBinding,
    InputPreflightError,
)
from src.dante_workflow.schema import (
    canonical_json_sha256,
    load_workflow_spec,
)
from tests.test_dante_workflow_input_coverage import fixture as _coverage_fixture

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture(tmp_path):
    return _coverage_fixture.__wrapped__(tmp_path)


@pytest.fixture
def calibrated(fixture):
    parent = ("calibration",)
    binding = CalibrationInputBinding(
        inventory=parent + ("inventory",),
        inventory_digest=parent + ("inventory_digest",),
        inventory_count=parent + ("source_count",),
        identity_count=parent + ("count",),
        expected_coverage=parent + ("coverage",),
        expected_contexts=parent + ("contexts",),
        expected_sessions=parent + ("sessions",),
        references=fixture.coverage_binding.references,
    )
    inventory = []
    rows = []
    for d in fixture.adapter.detectors:
        path = fixture.root / ("config/" + d + ".h5")
        path.write_bytes(b"synthetic source bytes " + d.encode())
        inventory.append(
            {
                "path": path.relative_to(fixture.root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        rows.append(
            {
                "detector": d,
                "session_id": 1,
                "catalog_gps_start": 5,
                "analysis_gps_start": 5,
                "required_padded_interval": [3, 18],
                "historical_context_disposition": "SYNTHETIC_FROZEN",
                "historical_hdf5": inventory[-1]["path"],
            }
        )
    fixture.adapter.input_coverage_binding = lambda: fixture.coverage_binding
    fixture.adapter.calibration_input_binding = lambda: binding
    fixture.adapter.iter_calibration_input_metadata = lambda root, payload: iter(rows)
    fixture.input_binding = InputPreflightBinding(
        "input",
        "contract_digest",
        {**fixture.input_binding.declarations, "sample_rate_hz": ("geometry", "rate")},
        fixture.input_binding.references,
    )
    fixture.adapter.input_preflight_binding = lambda: fixture.input_binding
    fixture.payload["geometry"]["rate"] = 2
    fixture.payload["calibration"] = {
        "inventory": inventory,
        "inventory_digest": canonical_json_sha256(inventory),
        "source_count": len(inventory),
        "count": len(rows),
        "coverage": {d + "/complete_single_file": 1 for d in fixture.adapter.detectors},
        "contexts": {d + "/SYNTHETIC_FROZEN": 1 for d in fixture.adapter.detectors},
        "sessions": {d: 1 for d in fixture.adapter.detectors},
    }
    fixture.freeze()
    return SimpleNamespace(
        base=fixture, rows=rows, binding=binding, inventory=inventory
    )


def inspect(c, **kw):
    return inspect_calibration_inputs(
        c.base.spec, c.base.adapter, root=c.base.root, **kw
    )


def make_missing(c):
    c.base.spans[0]["end"] = 10
    c.base.payload["calibration"]["coverage"] = {
        "H1/not_complete_in_frozen_local_manifest": 1,
        "V1/complete_single_file": 1,
    }
    c.base.freeze()


def receipt(c):
    directory = c.base.root / "acquired"
    directory.mkdir()
    raw = directory / "raw.h5"
    raw.write_bytes(b"synthetic not numerical")
    record = {
        "detector": "H1",
        "gps_start": 3,
        "gps_end": 18,
        "relative_path": "raw.h5",
        "file_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        "sample_rate_hz": 2,
        "sample_count": 30,
        "size_bytes": raw.stat().st_size,
    }
    contract = c.base.spec.scientific_configs["input"]
    value = {
        "schema_version": 1,
        "status": "COMPLETE_CONTENT_ADDRESSED_INPUTS",
        "protocol_digest": c.base.payload["contract_digest"],
        "protocol_reference": {"path": contract.path, "sha256": contract.sha256},
        "record_count": 1,
        "records": [record],
        "record_digest": canonical_json_sha256([record]),
        "network_fetch_was_outcome_blind": True,
        "scores_or_labels_accessed_during_fetch": [],
    }
    path = directory / "acquisition.json"

    def write():
        value.pop("manifest_digest", None)
        value["record_count"] = len(value["records"])
        value["record_digest"] = canonical_json_sha256(value["records"])
        value["manifest_digest"] = canonical_json_sha256(value)
        path.write_text(json.dumps(value))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return path, value, write, raw


def test_complete_local_inventory_is_scoped_not_score_or_raw_proof(calibrated):
    result = inspect(calibrated)
    assert result["status"] == "PASS_CALIBRATION_DECLARED_INPUTS_ONLY"
    assert result["identity_count"] == 2
    assert result["counts"] == {"H1": 1, "V1": 1}
    for name in (
        "score_values_read",
        "historical_full_row_digest_checked",
        "raw_samples_checked",
        "scientific_execution_ready",
        "native_calibration_checked",
        "runtime_equivalence_checked",
        "writer_exclusion_established",
    ):
        assert result[name] is False
    assert not (calibrated.base.root / "workflow").exists()


def test_missing_interval_blocks_without_pinned_acquisition(calibrated):
    make_missing(calibrated)
    assert inspect(calibrated)["status"] == "BLOCKED_CALIBRATION_SUPPLEMENT_REQUIRED"


def test_pinned_receipt_covers_exact_missing_interval_only(calibrated):
    make_missing(calibrated)
    path, value, write, raw = receipt(calibrated)
    result = inspect(calibrated, acquisition_manifest=path, acquisition_sha256=write())
    assert result["status"] == "PASS_CALIBRATION_DECLARED_INPUTS_ONLY"
    assert result["missing_manifest_intervals"] == 1
    assert result["acquisition_receipt"]["record_count"] == 1
    assert result["raw_samples_checked"] is False


@pytest.mark.parametrize(
    "change",
    [
        "pin",
        "parent",
        "status",
        "empty",
        "duplicate",
        "foreign",
        "bounds",
        "escape",
        "bytes",
        "rate",
        "samples",
        "size",
        "score_access",
    ],
)
def test_acquisition_corruption_refuses_even_resigned_receipt(calibrated, change):
    make_missing(calibrated)
    path, value, write, raw = receipt(calibrated)
    if change == "parent":
        value["protocol_digest"] = "changed"
    elif change == "status":
        value["status"] = "FAILED"
    elif change == "empty":
        value["records"] = []
    elif change == "duplicate":
        value["records"].append(deepcopy(value["records"][0]))
    elif change == "foreign":
        value["records"][0]["detector"] = "V1"
    elif change == "bounds":
        value["records"][0]["gps_start"] = 3.001
    elif change == "escape":
        value["records"][0]["relative_path"] = "../config/H1.h5"
    elif change == "bytes":
        raw.write_bytes(b"altered")
    elif change == "rate":
        value["records"][0]["sample_rate_hz"] = 4
    elif change == "samples":
        value["records"][0]["sample_count"] = 31
    elif change == "size":
        value["records"][0]["size_bytes"] += 1
    elif change == "score_access":
        value["scores_or_labels_accessed_during_fetch"] = ["score"]
    sha = write()
    with pytest.raises(InputPreflightError):
        inspect(
            calibrated,
            acquisition_manifest=path,
            acquisition_sha256="a" * 64 if change == "pin" else sha,
        )


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "missing",
        "foreign",
        "context",
        "catalog",
        "source",
        "score_field",
        "source_bytes",
        "inventory_digest",
    ],
)
def test_calibration_identity_inventory_or_geometry_change_is_not_allowed(
    calibrated, change
):
    if change == "duplicate":
        calibrated.rows.append(deepcopy(calibrated.rows[0]))
    elif change == "missing":
        calibrated.rows.pop()
    elif change == "foreign":
        calibrated.rows[0]["detector"] = "L1"
    elif change == "context":
        calibrated.rows[0]["required_padded_interval"][0] = 2
    elif change == "catalog":
        calibrated.rows[0]["catalog_gps_start"] = "5"
    elif change == "source":
        calibrated.rows[0]["historical_hdf5"] = "other.h5"
    elif change == "score_field":
        calibrated.rows[0]["score"] = 1
    elif change == "source_bytes":
        (calibrated.base.root / calibrated.inventory[0]["path"]).write_bytes(b"changed")
    else:
        calibrated.base.payload["calibration"]["inventory_digest"] = "a" * 64
        calibrated.base.freeze()
    with pytest.raises(InputPreflightError):
        inspect(calibrated)


def test_deny_default_and_immutable_binding(calibrated):
    calibrated.base.adapter.calibration_input_binding = lambda: None
    assert inspect(calibrated)["status"] == "BLOCKED_CALIBRATION_INPUTS"
    assert StageAdapter.calibration_input_binding(calibrated.base.adapter) is None
    assert (
        StageAdapter.iter_calibration_input_metadata(
            calibrated.base.adapter, calibrated.base.root, {}
        )
        is None
    )
    with pytest.raises(TypeError):
        calibrated.binding.references["new"] = ("x",)
    with pytest.raises(InputPreflightError):
        replace(calibrated.binding, identity_count=[])


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--observing-run", "O3a", "--detectors", "H1", "L1"],
        ["--observing-run", "O4a", "--detectors", "V1"],
    ],
)
def test_cli_unbound_scope_does_not_construct_orchestrator(args, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "_orchestrator", lambda args: pytest.fail("no state/worker")
    )
    assert (
        cli.main(["calibration-readiness", "--repository-root", str(ROOT), *args]) == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "WORKFLOW_ERROR"


def test_cli_explicit_receipt_is_routed_without_state(monkeypatch, tmp_path, capsys):
    seen = []
    monkeypatch.setattr(
        cli, "_orchestrator", lambda args: pytest.fail("no state/worker")
    )
    monkeypatch.setattr(
        cli,
        "inspect_calibration_inputs",
        lambda spec, adapter, **kw: (
            seen.append(kw) or {"status": "SCOPED_FIXTURE", "blockers": []}
        ),
    )
    path = tmp_path / "receipt"
    assert (
        cli.main(
            [
                "calibration-readiness",
                "--repository-root",
                str(ROOT),
                "--observing-run",
                "O4a",
                "--detectors",
                "H1",
                "L1",
                "--acquisition-manifest",
                str(path),
                "--acquisition-sha256",
                "a" * 64,
            ]
        )
        == 0
    )
    assert seen[0]["acquisition_manifest"] == path
    assert seen[0]["acquisition_sha256"] == "a" * 64
    capsys.readouterr()


def test_real_adapter_reads_gps_and_shape_but_never_score_values(monkeypatch, tmp_path):
    from src.dante_light import o4a_corrected_protocol as original

    source = tmp_path / "7/novelties_7_H1.h5"
    source.parent.mkdir()
    source.touch()

    class Scores:
        shape = (1,)

        def __array__(self, *args, **kw):
            pytest.fail("score values must never be read")

    class Handle:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __getitem__(self, key):
            return original.np.array([5.0]) if key.endswith("gps_times") else Scores()

    monkeypatch.setattr(original.h5py, "File", lambda *args, **kw: Handle())
    monkeypatch.setattr(original, "_calibration_files", lambda root: [source])
    monkeypatch.setattr(original, "_historical_calibration_spans", lambda root: {})
    monkeypatch.setattr(
        original,
        "_historical_calibration_geometry",
        lambda **kw: {
            "analysis_gps_start": 5,
            "required_padded_interval": [1, 41],
            "historical_context_disposition": "FROZEN",
        },
    )
    monkeypatch.setattr(
        original,
        "iter_calibration_identities",
        lambda *a, **kw: pytest.fail("legacy reader accesses score values"),
    )
    spec = load_workflow_spec(
        ROOT / "config/dante_workflow_productization_v1.json", root=ROOT
    )
    adapter = O4aCorrectedAdapter(spec)
    monkeypatch.setattr(adapter, "_input_protocol", lambda root: original)
    rows = list(
        adapter.iter_calibration_input_metadata(
            tmp_path,
            {
                "calibration_population": {
                    "source_hdf5_references": [
                        {"path": source.relative_to(tmp_path).as_posix()}
                    ]
                }
            },
        )
    )
    assert len(rows) == 1 and "historical_score_float32_hex" not in rows[0]
