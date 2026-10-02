"""Profile-specific metadata coverage, with no raw or numerical science work."""

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
from src.dante_workflow.input_coverage import (
    InputCoverageBinding,
    InputCoverageError,
    _number,
    _read,
    inspect_input_coverage,
)
from src.dante_workflow.input_preflight import (
    InputPreflightBinding,
    InputPreflightError,
)
from src.dante_workflow.schema import (
    FileReference,
    canonical_json_sha256,
    load_workflow_spec,
)


ROOT = Path(__file__).resolve().parents[1]


def test_lossy_integer_conversion_is_not_exact_coverage():
    with pytest.raises(InputCoverageError, match="must not round"):
        _number(2**53 + 1)


def test_read_error_remains_fail_closed(tmp_path):
    with pytest.raises(InputCoverageError, match="cannot be read"):
        _read(tmp_path / "absent")


def _jsonl_sha(rows):
    return hashlib.sha256(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
            for row in rows
        ).encode()
    ).hexdigest()


@pytest.fixture
def fixture(tmp_path):
    (tmp_path / "config").mkdir()
    spans = [{"d": "H1", "start": 0, "end": 30}, {"d": "V1", "start": 0, "end": 30}]
    rows = [
        {
            "d": d,
            "start": 5,
            "duration": 10,
            "context": [3, 18],
            "identity": "frozen-source",
        }
        for d in ("H1", "V1")
    ]
    input_binding = InputPreflightBinding(
        "input",
        "contract_digest",
        {
            "analysis_duration_s": ("geometry", "duration"),
            "left_context_s": ("geometry", "left"),
            "right_context_s": ("geometry", "right"),
        },
        {"raw_manifest": ("inputs", "manifest")},
    )
    coverage_binding = InputCoverageBinding(
        "DECLARED_PRIMARY_WINDOWS",
        "FROZEN_PROFILE_SPECIFIC_SELECTION",
        ("expected", "counts"),
        ("expected", "digest"),
        {"selector": ("inputs", "selector")},
        {
            "detector": ("d",),
            "analysis_start": ("start",),
            "duration": ("duration",),
            "context_interval": ("context",),
        },
        {"detector": ("d",), "start": ("start",), "end": ("end",)},
    )
    selector = tmp_path / "config/selector.txt"
    selector.write_bytes(b"frozen selector bytes")
    payload = {
        "geometry": {"duration": 10, "left": 2, "right": 3},
        "inputs": {},
        "expected": {},
    }
    spec = SimpleNamespace(contract_digest="a" * 64, scientific_configs={})
    adapter = SimpleNamespace(
        spec=spec,
        observing_run="synthetic",
        detectors=("H1", "V1"),
        input_preflight_binding=lambda: input_binding,
        input_coverage_binding=lambda: coverage_binding,
        iter_input_coverage=lambda root: iter(rows),
    )

    def freeze():
        manifest = tmp_path / "config/manifest.jsonl"
        manifest.write_text(
            "".join(json.dumps(row) + "\n" for row in spans), encoding="utf-8"
        )
        payload["inputs"] = {
            "manifest": {
                "path": "config/manifest.jsonl",
                "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            },
            "selector": {
                "path": "config/selector.txt",
                "sha256": hashlib.sha256(selector.read_bytes()).hexdigest(),
            },
        }
        payload["expected"] = {
            "counts": {
                d: sum(row["d"] == d for row in rows) for d in adapter.detectors
            },
            "digest": _jsonl_sha(rows),
        }
        payload.pop("contract_digest", None)
        payload["contract_digest"] = canonical_json_sha256(payload)
        contract = tmp_path / "config/input.json"
        contract.write_text(json.dumps(payload), encoding="utf-8")
        spec.scientific_configs = {
            "input": FileReference(
                "config/input.json", hashlib.sha256(contract.read_bytes()).hexdigest()
            )
        }

    freeze()
    return SimpleNamespace(
        root=tmp_path,
        spec=spec,
        adapter=adapter,
        payload=payload,
        rows=rows,
        spans=spans,
        selector=selector,
        freeze=freeze,
        input_binding=input_binding,
        coverage_binding=coverage_binding,
    )


def test_exact_half_open_edges_and_locality_are_metadata_only(fixture):
    fixture.spans[:] = [
        {"d": d, "start": 3, "end": 18} for d in fixture.adapter.detectors
    ]
    fixture.freeze()
    result = inspect_input_coverage(fixture.spec, fixture.adapter, root=fixture.root)
    assert result["status"] == "PASS_PRIMARY_SCAN_MANIFEST_COVERAGE_ONLY"
    assert result["counts"] == {"H1": 1, "V1": 1}
    assert result["identity_jsonl_sha256"] == _jsonl_sha(fixture.rows)
    assert result["exact_gps_manifest_coverage_checked"] is True
    for field in (
        "scientific_execution_ready",
        "live_coverage_checked",
        "physical_raw_files_checked",
        "raw_samples_checked",
        "calibration_coverage_checked",
        "dq_flag_eligibility_checked",
        "runtime_equivalence_checked",
        "writer_exclusion_established",
        "additional_dq_filter_applied",
    ):
        assert result[field] is False
    assert result["selection_policy"] == "FROZEN_PROFILE_SPECIFIC_SELECTION"
    assert not (fixture.root / "workflow").exists()


@pytest.mark.parametrize(
    "spans",
    [
        [(3, 8), (8, 18)],
        [(8, 18), (3, 10)],
        [(3, 18), (5, 9)],
    ],
)
def test_stitch_and_overlap_use_union_not_containers(fixture, spans):
    fixture.spans[:] = [
        {"d": d, "start": start, "end": end}
        for d in fixture.adapter.detectors
        for start, end in spans
    ]
    fixture.freeze()
    assert (
        inspect_input_coverage(fixture.spec, fixture.adapter, root=fixture.root)[
            "blockers"
        ]
        == []
    )


@pytest.mark.parametrize("spans", [[(3, 8), (8.001, 18)], [(3.001, 18)], [(3, 17.999)]])
def test_real_gap_and_incomplete_boundaries_never_round_or_skip(fixture, spans):
    fixture.spans[:] = [
        {"d": d, "start": start, "end": end}
        for d in fixture.adapter.detectors
        for start, end in spans
    ]
    fixture.freeze()
    with pytest.raises(InputCoverageError, match="complete manifest"):
        inspect_input_coverage(fixture.spec, fixture.adapter, root=fixture.root)


def test_another_detector_cannot_fill_context_hole(fixture):
    fixture.spans[:] = [
        {"d": "H1", "start": 0, "end": 10},
        {"d": "V1", "start": 0, "end": 30},
    ]
    fixture.freeze()
    with pytest.raises(InputCoverageError, match="coverage"):
        inspect_input_coverage(fixture.spec, fixture.adapter, root=fixture.root)


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "reordered",
        "wrong_detector",
        "missing",
        "identity_changed",
        "wrong_duration",
        "wrong_left",
        "wrong_right",
        "infinite",
        "string",
        "boolean",
    ],
)
def test_provider_row_corruption_is_not_new_population(fixture, change):
    if change == "duplicate":
        fixture.rows.insert(1, deepcopy(fixture.rows[0]))
    elif change == "reordered":
        fixture.rows.reverse()
    elif change == "wrong_detector":
        fixture.rows[0]["d"] = "L1"
    elif change == "missing":
        fixture.rows.pop()
    elif change == "identity_changed":
        fixture.rows[0]["identity"] = "changed"
    elif change == "wrong_duration":
        fixture.rows[0]["duration"] = 11
    elif change == "wrong_left":
        fixture.rows[0]["context"][0] = 2
    elif change == "wrong_right":
        fixture.rows[0]["context"][1] = 19
    else:
        fixture.rows[0]["start"] = {
            "infinite": float("inf"),
            "string": "5",
            "boolean": True,
        }[change]
    with pytest.raises(InputCoverageError):
        inspect_input_coverage(fixture.spec, fixture.adapter, root=fixture.root)


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_selector_bytes_are_checked_before_provider(fixture, change):
    if change == "missing":
        fixture.selector.unlink()
    else:
        fixture.selector.write_bytes(b"changed")
    fixture.adapter.iter_input_coverage = lambda root: pytest.fail(
        "unsafe selector was invoked"
    )
    with pytest.raises(InputPreflightError, match="SHA mismatch|absent"):
        inspect_input_coverage(fixture.spec, fixture.adapter, root=fixture.root)


@pytest.mark.parametrize("change", ["manifest", "selector", "contract"])
def test_mid_replay_file_changes_are_rejected(fixture, change):
    def provider(root):
        yield from fixture.rows
        path = {
            "manifest": root / "config/manifest.jsonl",
            "selector": fixture.selector,
            "contract": root / "config/input.json",
        }[change]
        path.write_bytes(b"changed after consumption")

    fixture.adapter.iter_input_coverage = provider
    with pytest.raises(InputPreflightError, match="mismatch"):
        inspect_input_coverage(fixture.spec, fixture.adapter, root=fixture.root)


@pytest.mark.parametrize(
    "change", ["invalid_span", "empty_manifest", "extra_detector", "missing_detector"]
)
def test_resigned_manifest_cannot_hide_missing_or_wrong_coverage(fixture, change):
    if change == "invalid_span":
        fixture.spans[0]["end"] = fixture.spans[0]["start"]
    elif change == "empty_manifest":
        fixture.spans.clear()
    elif change == "extra_detector":
        fixture.spans.append({"d": "L1", "start": 0, "end": 30})
    else:
        fixture.spans.pop()
    fixture.freeze()
    with pytest.raises(InputCoverageError):
        inspect_input_coverage(fixture.spec, fixture.adapter, root=fixture.root)


def test_default_coverage_capability_remains_blocked(fixture):
    fixture.adapter.input_coverage_binding = lambda: None
    result = inspect_input_coverage(fixture.spec, fixture.adapter, root=fixture.root)
    assert result["blockers"] == ["MISSING_AUDITED_COVERAGE_BINDING"]
    assert result["exact_gps_manifest_coverage_checked"] is False
    assert StageAdapter.input_coverage_binding(fixture.adapter) is None
    assert StageAdapter.iter_input_coverage(fixture.adapter, fixture.root) is None


def test_binding_selectors_require_complete_immutable_fields(fixture):
    with pytest.raises(TypeError):
        fixture.coverage_binding.window_fields["duration"] = ("other",)
    with pytest.raises(InputCoverageError):
        replace(fixture.coverage_binding, expected_counts=[])
    with pytest.raises(InputCoverageError):
        replace(fixture.coverage_binding, window_fields={"duration": ("duration",)})


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--observing-run", "O3a", "--detectors", "H1", "L1"],
        ["--observing-run", "O2", "--detectors", "V1"],
        ["--observing-run", "O4a", "--detectors", "V1"],
    ],
)
def test_cli_blocked_profiles_never_construct_worker(
    tmp_path, args, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "_orchestrator", lambda args: pytest.fail("no state"))
    assert (
        cli.main(
            [
                "coverage-readiness",
                "--repository-root",
                str(ROOT),
                "--cache-root",
                str(tmp_path / "absent"),
                *args,
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "WORKFLOW_ERROR"
    assert not (tmp_path / "absent").exists()


def test_cli_routes_to_common_coverage_inspector_without_orchestrator(
    monkeypatch, tmp_path, capsys
):
    seen = []
    monkeypatch.setattr(cli, "_orchestrator", lambda args: pytest.fail("no state"))

    def inspector(spec, adapter, *, root):
        seen.append((adapter.observing_run, root))
        return {
            "status": "PASS_PRIMARY_SCAN_MANIFEST_COVERAGE_ONLY",
            "blockers": [],
            "scientific_execution_ready": False,
        }

    monkeypatch.setattr(cli, "inspect_input_coverage", inspector)
    assert (
        cli.main(
            [
                "coverage-readiness",
                "--repository-root",
                str(ROOT),
                "--observing-run",
                "O4a",
                "--detectors",
                "H1",
                "L1",
                "--cache-root",
                str(tmp_path / "absent"),
            ]
        )
        == 0
    )
    assert seen == [("O4a", ROOT)]
    assert json.loads(capsys.readouterr().out)["scientific_execution_ready"] is False
    assert not (tmp_path / "absent").exists()


def test_o4a_reuses_original_selector_but_not_protocol_rebuild(monkeypatch):
    try:
        from src.dante_light import o4a_corrected_protocol as original
    except ImportError:
        pytest.skip("existing scientific environment unavailable")
    sentinel = iter([{"metadata": "only"}])
    seen = []
    monkeypatch.setattr(
        original, "iter_scan_identities", lambda root: seen.append(root) or sentinel
    )
    monkeypatch.setattr(
        original,
        "build_corrected_protocol",
        lambda *a, **kw: pytest.fail("no runtime/calibration rebuild"),
    )
    spec = load_workflow_spec(
        ROOT / "config/dante_workflow_productization_v1.json", root=ROOT
    )
    adapter = O4aCorrectedAdapter(spec)
    assert adapter.iter_input_coverage(ROOT) is sentinel
    assert seen == [ROOT]
    assert "NO_NEW_DQ_FILTER" in adapter.input_coverage_binding().selection_policy
    with pytest.raises(InputCoverageError, match="another checkout"):
        adapter.iter_input_coverage(ROOT / "nonexistent-checkout")
