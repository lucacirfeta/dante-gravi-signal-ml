"""Multi-run administrative selection, without data access or scientific jobs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.dante_workflow import cli
from src.dante_workflow.adapters import AdapterError, O4aCorrectedAdapter, build_adapter
from src.dante_workflow.run_profiles import (
    DEFAULT_REGISTRY_RELATIVE,
    RunProfileError,
    load_run_registry,
    validate_run_registry,
)
from src.dante_workflow.schema import canonical_json_sha256, load_workflow_spec


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dante_workflow_productization_v1.json"


def _payload():
    return json.loads((ROOT / DEFAULT_REGISTRY_RELATIVE).read_text(encoding="utf-8"))


def _resign(payload):
    body = deepcopy(payload)
    body.pop("registry_digest", None)
    payload["registry_digest"] = canonical_json_sha256(body)
    return payload


def _run(payload, name):
    return next(profile for profile in payload["runs"] if profile["name"] == name)


def test_catalogue_is_immutable_and_distinguishes_public_data_from_execution():
    registry = load_run_registry(ROOT / DEFAULT_REGISTRY_RELATIVE, root=ROOT)
    assert set(registry.profiles) == {
        "S5",
        "S6",
        "O1",
        "O2",
        "O3a",
        "O3b",
        "O4a",
        "O4b",
    }
    with pytest.raises(TypeError):
        registry.profiles["O5"] = registry.profiles["O4a"]
    assert (
        registry.describe()["scope"]
        == "PUBLIC_STRAIN_CATALOGUE_NOT_COVERAGE_OR_VALIDATION"
    )


@pytest.mark.parametrize("run", ["O2", "O3a", "O3b", "O4b"])
def test_virgo_available_does_not_mean_scientific_workflow_ready(run):
    registry = load_run_registry(ROOT / DEFAULT_REGISTRY_RELATIVE, root=ROOT)
    result = registry.readiness(run, ["V1"])
    assert result["public_strain_detectors"] == ["V1"]
    assert result["status"] == "BLOCKED_RUN_PROFILE"
    assert "MISSING_DETECTOR_METHOD_CONTRACT" in result["blockers"]
    assert result["scientific_execution_ready"] is False
    assert result["live_coverage_checked"] is False
    with pytest.raises(RunProfileError, match="blocked"):
        registry.resolve_workflow(run, ["V1"])


@pytest.mark.parametrize("run", ["S5", "S6", "O1", "O4a"])
def test_unavailable_virgo_is_rejected(run):
    registry = load_run_registry(ROOT / DEFAULT_REGISTRY_RELATIVE, root=ROOT)
    with pytest.raises(RunProfileError, match="not published"):
        registry.readiness(run, ["V1"])


@pytest.mark.parametrize("detectors", [[], ["H1", "H1"], ["H2"], ["K1"], ["Virgo"]])
def test_invalid_detector_selection_is_not_inferred_or_silently_reduced(detectors):
    registry = load_run_registry(ROOT / DEFAULT_REGISTRY_RELATIVE, root=ROOT)
    with pytest.raises(RunProfileError):
        registry.readiness("O3a", detectors)


def test_unknown_run_does_not_fall_back_to_o4a():
    registry = load_run_registry(ROOT / DEFAULT_REGISTRY_RELATIVE, root=ROOT)
    with pytest.raises(RunProfileError, match="unknown observing run"):
        registry.resolve_workflow("O5", ["H1", "L1"])


def test_o3a_has_bound_method_but_no_productized_adapter():
    registry = load_run_registry(ROOT / DEFAULT_REGISTRY_RELATIVE, root=ROOT)
    result = registry.readiness("o3a", ["L1", "H1"])
    assert result["observing_run"] == "O3a"
    assert result["blockers"] == ["MISSING_WORKFLOW_ADAPTER_CONTRACT"]
    assert result["method_contract"]["contract_digest"] == (
        "fb29f22ffc5a796843383d6ed48032879b1b44252b46a93163e7db2eec157a7d"
    )


def test_o4a_profile_binding_is_not_a_scientific_preflight():
    registry = load_run_registry(ROOT / DEFAULT_REGISTRY_RELATIVE, root=ROOT)
    result = registry.readiness("O4a", ["L1", "H1"])
    assert result["status"] == "PASS_RUN_PROFILE_BINDING_ONLY"
    assert result["blockers"] == []
    assert result["scientific_execution_ready"] is False
    assert result["remaining_gates"]
    assert registry.resolve_workflow("O4a", ["H1", "L1"]) == CONFIG
    result = registry.readiness("O4a", ["H1"])
    assert "DETECTOR_SELECTION_DIFFERS_FROM_FROZEN_WORKFLOW" in result["blockers"]


@pytest.mark.parametrize(
    "mutation", ["unknown_field", "duplicate_run", "invalid_scope", "invalid_schema"]
)
def test_registry_schema_is_strict_even_if_resigned(mutation):
    payload = _payload()
    if mutation == "unknown_field":
        payload["thresholds"] = {"V1": 1}
    elif mutation == "duplicate_run":
        payload["runs"].append(deepcopy(payload["runs"][0]))
    elif mutation == "invalid_scope":
        _run(payload, "O4a")["public_strain_detectors"].append("H2")
    else:
        payload["schema_version"] = True
    with pytest.raises(RunProfileError):
        validate_run_registry(_resign(payload), root=ROOT)


def test_unsigned_catalogue_change_is_rejected():
    payload = _payload()
    _run(payload, "O4a")["public_strain_detectors"].append("V1")
    with pytest.raises(RunProfileError, match="digest mismatch"):
        validate_run_registry(payload, root=ROOT)


@pytest.mark.parametrize(
    "path",
    ["../outside.json", "/absolute.json", "C:/outside.json", "config\\unsafe.json"],
)
def test_binding_paths_cannot_escape_checkout(path):
    payload = _payload()
    _run(payload, "O3a")["method_contract"]["path"] = path
    with pytest.raises(RunProfileError, match="path"):
        validate_run_registry(_resign(payload), root=ROOT)


def test_method_detector_scope_must_match_frozen_parent():
    payload = _payload()
    _run(payload, "O3a")["method_contract"]["detectors"].append("V1")
    with pytest.raises(RunProfileError, match="detector scope"):
        validate_run_registry(_resign(payload), root=ROOT)


def test_cannot_bind_o4a_adapter_to_another_observing_run():
    payload = _payload()
    _run(payload, "O3a")["workflow_contract"] = deepcopy(
        _run(payload, "O4a")["workflow_contract"]
    )
    with pytest.raises(RunProfileError, match="adapter observing run"):
        validate_run_registry(_resign(payload), root=ROOT)


def test_parent_method_digest_drift_is_rejected():
    payload = _payload()
    _run(payload, "O3a")["method_contract"]["contract_digest"] = "0" * 64
    with pytest.raises(RunProfileError, match="parent contract digest"):
        validate_run_registry(_resign(payload), root=ROOT)


def test_unknown_adapter_is_rejected_not_translated_to_o4a():
    spec = load_workflow_spec(CONFIG, root=ROOT)
    with pytest.raises(AdapterError, match="unsupported workflow adapter"):
        build_adapter(replace(spec, adapter="unknown_native"))


def test_direct_o4a_adapter_also_rejects_another_contract():
    spec = load_workflow_spec(CONFIG, root=ROOT)
    with pytest.raises(AdapterError, match="requires the o4a_corrected contract"):
        O4aCorrectedAdapter(replace(spec, adapter="unknown_native"))


def test_unknown_adapter_cli_error_is_structured_and_creates_no_state(
    monkeypatch, tmp_path, capsys
):
    spec = load_workflow_spec(CONFIG, root=ROOT)
    monkeypatch.setattr(
        cli,
        "load_workflow_spec",
        lambda *args, **kwargs: replace(spec, adapter="unknown_native"),
    )
    cache = tmp_path / "must-not-exist"
    assert (
        cli.main(["plan", "--repository-root", str(ROOT), "--cache-root", str(cache)])
        == 1
    )
    assert json.loads(capsys.readouterr().out)["error_type"] == "AdapterError"
    assert not cache.exists()


def test_registry_duplicate_json_fields_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(RunProfileError, match="duplicate JSON field"):
        load_run_registry(path, root=ROOT)


def test_o4a_workflow_contract_digest_drift_is_rejected():
    payload = _payload()
    _run(payload, "O4a")["workflow_contract"]["contract_digest"] = "0" * 64
    with pytest.raises(RunProfileError, match="parent contract digest"):
        validate_run_registry(_resign(payload), root=ROOT)


def test_explicit_config_cannot_override_profile_without_creating_state(
    tmp_path, capsys
):
    cache = tmp_path / "must-not-exist"
    assert (
        cli.main(
            [
                "plan",
                "--repository-root",
                str(ROOT),
                "--observing-run",
                "O4a",
                "--detectors",
                "H1",
                "L1",
                "--config",
                str(tmp_path / "other.json"),
                "--cache-root",
                str(cache),
            ]
        )
        == 1
    )
    assert "differs from the selected frozen run profile" in capsys.readouterr().out
    assert not cache.exists()


def test_registry_cannot_be_silently_ignored_by_legacy_plan(tmp_path, capsys):
    cache = tmp_path / "must-not-exist"
    assert (
        cli.main(
            [
                "plan",
                "--repository-root",
                str(ROOT),
                "--run-registry",
                str(ROOT / DEFAULT_REGISTRY_RELATIVE),
                "--cache-root",
                str(cache),
            ]
        )
        == 1
    )
    assert "requires --observing-run" in capsys.readouterr().out
    assert not cache.exists()


def test_cli_catalogue_and_blocked_readiness_never_construct_state(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "_orchestrator", lambda args: pytest.fail("catalogue created state")
    )
    assert cli.main(["runs", "--repository-root", str(ROOT)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "RUN_PROFILE_CATALOGUE"
    assert (
        cli.main(
            [
                "run-readiness",
                "--repository-root",
                str(ROOT),
                "--observing-run",
                "O3a",
                "--detectors",
                "V1",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED_RUN_PROFILE"


def test_blocked_plan_creates_no_cache_and_no_o4a_fallback(tmp_path, capsys):
    cache = tmp_path / "must-not-exist"
    assert (
        cli.main(
            [
                "plan",
                "--repository-root",
                str(ROOT),
                "--cache-root",
                str(cache),
                "--observing-run",
                "O3a",
                "--detectors",
                "H1",
                "L1",
            ]
        )
        == 1
    )
    assert "MISSING_WORKFLOW_ADAPTER_CONTRACT" in capsys.readouterr().out
    assert not cache.exists()


def test_detectors_without_observing_run_cannot_modify_legacy_contract(
    tmp_path, capsys
):
    cache = tmp_path / "must-not-exist"
    assert (
        cli.main(
            [
                "plan",
                "--repository-root",
                str(ROOT),
                "--cache-root",
                str(cache),
                "--detectors",
                "V1",
            ]
        )
        == 1
    )
    assert "requires --observing-run" in capsys.readouterr().out
    assert not cache.exists()


def test_explicit_o4a_selection_preserves_existing_plan_and_run_key(tmp_path, capsys):
    args = [
        "plan",
        "--repository-root",
        str(ROOT),
        "--raw-root",
        str(tmp_path / "raw"),
        "--cache-root",
        str(tmp_path / "cache"),
    ]
    assert cli.main(args) == 0
    legacy = json.loads(capsys.readouterr().out)
    assert cli.main([*args, "--observing-run", "O4a", "--detectors", "L1", "H1"]) == 0
    assert json.loads(capsys.readouterr().out) == legacy


def test_checkout_and_installed_module_catalogue_parity():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    wrapper = subprocess.run(
        [sys.executable, "scripts/run_dante_workflow.py", "runs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    module = subprocess.run(
        [
            sys.executable,
            "-m",
            "dante_workflow.cli",
            "runs",
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=environment,
    )
    assert json.loads(wrapper.stdout) == json.loads(module.stdout)


def test_ui_unknown_adapter_is_rejected_before_creating_ledger(monkeypatch, tmp_path):
    from src.dante_workflow.ui import controller

    spec = load_workflow_spec(CONFIG, root=ROOT)
    monkeypatch.setattr(
        controller,
        "load_workflow_spec",
        lambda *args, **kwargs: replace(spec, adapter="unknown_native"),
    )
    cache = tmp_path / "must-not-exist"
    raw = tmp_path / "raw"
    with pytest.raises(AdapterError, match="unsupported workflow adapter"):
        controller.WorkflowUIController(
            selection=controller.UISelection(ROOT, CONFIG, raw, cache, None),
            path_policy=controller.LocalPathPolicy(ROOT, (raw,), (cache,)),
            worker_python=sys.executable,
        )
    assert not cache.exists()
