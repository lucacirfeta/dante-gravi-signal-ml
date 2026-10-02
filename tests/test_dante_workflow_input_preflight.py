"""Generic metadata binding regressions, without raw or scientific execution."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.dante_workflow import cli
from src.dante_workflow.adapters.base import StageAdapter
from src.dante_workflow.input_preflight import (
    InputPreflightBinding,
    InputPreflightError,
    inspect_input_binding,
)
from src.dante_workflow.schema import FileReference, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture(tmp_path):
    (tmp_path / "config").mkdir()
    data = tmp_path / "config/manifest.json"
    data.write_bytes(b'{"metadata_only":true}')
    payload = {
        "geometry": {"analysis": 17, "context": 3},
        "inputs": {
            "raw": {
                "path": "config/manifest.json",
                "sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
            }
        },
        "outcome_not_for_reporting": 123,
    }
    binding = InputPreflightBinding(
        "input",
        "contract_digest",
        {"analysis": ("geometry", "analysis"), "context": ("geometry", "context")},
        {"raw": ("inputs", "raw")},
    )
    spec = SimpleNamespace(contract_digest="a" * 64, scientific_configs={})
    adapter = SimpleNamespace(
        spec=spec,
        observing_run="synthetic",
        detectors=("H1", "V1"),
        input_preflight_binding=lambda: binding,
    )

    def freeze(value=None, *, text=None):
        body = deepcopy(payload if value is None else value)
        body.pop("contract_digest", None)
        body["contract_digest"] = canonical_json_sha256(body)
        path = tmp_path / "config/input.json"
        path.write_text(
            text if text is not None else json.dumps(body), encoding="utf-8"
        )
        spec.scientific_configs = {
            "input": FileReference(
                "config/input.json", hashlib.sha256(path.read_bytes()).hexdigest()
            )
        }
        return body

    freeze()
    return SimpleNamespace(
        root=tmp_path,
        data=data,
        payload=payload,
        binding=binding,
        spec=spec,
        adapter=adapter,
        freeze=freeze,
    )


@pytest.mark.parametrize(
    "run,detectors", [("O2", ("V1",)), ("O3a", ("H1", "L1")), ("O4a", ("L1",))]
)
def test_common_inspector_uses_only_explicit_adapter_fields(fixture, run, detectors):
    fixture.adapter.observing_run = run
    fixture.adapter.detectors = detectors
    result = inspect_input_binding(fixture.spec, fixture.adapter, root=fixture.root)
    assert result["status"] == "PASS_INPUT_CONTRACT_BINDING_ONLY"
    assert result["observing_run"] == run
    assert result["detectors"] == list(detectors)
    assert result["declarations"]["analysis"]["value"] == 17
    assert result["declarations"]["context"]["value"] == 3
    assert "outcome_not_for_reporting" not in json.dumps(result)
    for key in (
        "scientific_execution_ready",
        "exact_gps_coverage_checked",
        "dq_eligibility_checked",
        "raw_samples_checked",
        "runtime_equivalence_checked",
        "writer_exclusion_established",
    ):
        assert result[key] is False
    assert result["remaining_gates"]
    assert not (fixture.root / "ledger.json").exists()


def test_binding_selectors_are_immutable(fixture):
    with pytest.raises(TypeError):
        fixture.binding.declarations["context"] = ("other",)


@pytest.mark.parametrize("pointer", [(), [], ("",), (17,), "geometry"])
def test_invalid_selector_not_silently_normalized(pointer):
    with pytest.raises(InputPreflightError):
        InputPreflightBinding(
            "input", "contract_digest", {"geometry": pointer}, {"raw": ("input",)}
        )


def test_absent_adapter_mapping_is_blocked(fixture):
    fixture.adapter.input_preflight_binding = lambda: None
    result = inspect_input_binding(fixture.spec, fixture.adapter, root=fixture.root)
    assert result["status"] == "BLOCKED_INPUT_CONTRACT_BINDING"
    assert result["blockers"] == ["MISSING_AUDITED_INPUT_BINDING"]
    assert StageAdapter.input_preflight_binding(fixture.adapter) is None


@pytest.mark.parametrize("change", ["missing", "altered"])
def test_manifest_drift_is_a_hard_error(fixture, change):
    if change == "missing":
        fixture.data.unlink()
    else:
        fixture.data.write_bytes(b"altered")
    with pytest.raises(InputPreflightError, match="absent|SHA mismatch"):
        inspect_input_binding(fixture.spec, fixture.adapter, root=fixture.root)


@pytest.mark.parametrize(
    "path",
    ["../outside.json", "/outside.json", "C:/outside.json", "config\\manifest.json"],
)
def test_even_resigned_contract_cannot_escape_checkout(fixture, path):
    fixture.payload["inputs"]["raw"]["path"] = path
    fixture.freeze()
    with pytest.raises(InputPreflightError, match="path"):
        inspect_input_binding(fixture.spec, fixture.adapter, root=fixture.root)


@pytest.mark.parametrize(
    "change",
    [
        "missing_declaration",
        "unknown_reference_field",
        "bad_hash",
        "wrong_seal",
        "duplicate",
        "nan",
        "contract_bytes",
        "unbound_contract",
        "wrong_adapter",
    ],
)
def test_contract_invalidity_never_becomes_scoped_pass(fixture, change):
    if change == "missing_declaration":
        del fixture.payload["geometry"]["context"]
        fixture.freeze()
    elif change == "unknown_reference_field":
        fixture.payload["inputs"]["raw"]["ignored"] = True
        fixture.freeze()
    elif change == "bad_hash":
        fixture.payload["inputs"]["raw"]["sha256"] = "X" * 64
        fixture.freeze()
    elif change == "wrong_seal":
        fixture.freeze(
            text=json.dumps({**fixture.payload, "contract_digest": "0" * 64})
        )
    elif change == "duplicate":
        fixture.freeze(text='{"geometry":{},"geometry":{}}')
    elif change == "nan":
        fixture.freeze(text='{"number":NaN}')
    elif change == "contract_bytes":
        (fixture.root / "config/input.json").write_bytes(b"altered")
    elif change == "unbound_contract":
        fixture.spec.scientific_configs = {}
    else:
        fixture.adapter.spec = object()
    with pytest.raises(InputPreflightError):
        inspect_input_binding(fixture.spec, fixture.adapter, root=fixture.root)


def test_input_contract_change_during_inspection_is_rejected(fixture, monkeypatch):
    from src.dante_workflow import input_preflight

    original = input_preflight._hash

    def change_on_input(path):
        result = original(path)
        if path == fixture.data:
            (fixture.root / "config/input.json").write_bytes(b"changed mid-inspection")
        return result

    monkeypatch.setattr(input_preflight, "_hash", change_on_input)
    with pytest.raises(InputPreflightError, match="changed during"):
        inspect_input_binding(fixture.spec, fixture.adapter, root=fixture.root)


def test_internal_symlink_not_admitted(fixture):
    link = fixture.root / "config/link.json"
    try:
        link.symlink_to(fixture.data)
    except OSError:
        pytest.skip("symlinks unavailable on this host")
    fixture.payload["inputs"]["raw"]["path"] = "config/link.json"
    fixture.freeze()
    with pytest.raises(InputPreflightError, match="symlinks"):
        inspect_input_binding(fixture.spec, fixture.adapter, root=fixture.root)


def test_real_cli_binding_does_not_construct_worker_or_ledger(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli, "_orchestrator", lambda args: pytest.fail("no workflow state")
    )
    cache = tmp_path / "must-not-exist"
    assert (
        cli.main(
            [
                "input-readiness",
                "--repository-root",
                str(ROOT),
                "--observing-run",
                "O4a",
                "--detectors",
                "H1",
                "L1",
                "--cache-root",
                str(cache),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PASS_INPUT_CONTRACT_BINDING_ONLY"
    assert result["declarations"]["population_scope"]["value"] is True
    assert result["exact_gps_coverage_checked"] is False
    assert len(result["inputs"]) == 5
    assert not cache.exists()


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--observing-run", "O3a", "--detectors", "H1", "L1"],
        ["--observing-run", "O2", "--detectors", "V1"],
        ["--observing-run", "O4a", "--detectors", "V1"],
        [
            "--observing-run",
            "O4a",
            "--detectors",
            "H1",
            "L1",
            "--expected-run-key",
            "invalid",
        ],
    ],
)
def test_cli_invalid_selection_has_no_fallback_or_state(tmp_path, args, capsys):
    cache = tmp_path / "must-not-exist"
    assert (
        cli.main(
            [
                "input-readiness",
                "--repository-root",
                str(ROOT),
                "--cache-root",
                str(cache),
                *args,
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "WORKFLOW_ERROR"
    assert not cache.exists()
