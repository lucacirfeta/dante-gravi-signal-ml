"""Synthetic O3a interface checks; never execute numerical/scientific CLIs."""

from copy import deepcopy
from dataclasses import replace
import ast
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from src.dante_workflow.adapters import AdapterError, WorkflowPaths, build_adapter
from src.dante_workflow.adapters.o3a_native import NATIVE_COMMANDS, O3aNativeAdapter
from src.dante_workflow.orchestrator import CommandResult, WorkflowOrchestrator
from src.dante_workflow.schema import canonical_json_sha256, validate_workflow_spec
from src.dante_workflow.verification import verify_workflow

ROOT = Path(__file__).resolve().parents[1]


def seal(value, field="contract_digest"):
    body = deepcopy(value)
    body.pop(field, None)
    value[field] = canonical_json_sha256(body)
    return value


@pytest.fixture
def interface(tmp_path):
    legacy = json.loads(
        (ROOT / "config/dante_workflow_productization_v1.json").read_text()
    )
    stages = [stage for stage in legacy["stages"] if stage["name"] in NATIVE_COMMANDS]
    produced = {name for stage in stages for name in stage["expected_outputs"]}
    configs = {}
    for stage in stages:
        definition = NATIVE_COMMANDS[stage["name"]]
        config = tmp_path / definition.config_path
        config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / definition.config_path, config)
        configs[stage["name"]] = {
            "path": definition.config_path,
            "sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        }
        stage["config_refs"] = [stage["name"]]
        stage["verifier_command"] = [
            "python",
            definition.script,
            *definition.verify_selector,
        ]
        source = tmp_path / definition.script
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / definition.script, source)
        if stage["name"] == "COHORT":
            stage["dependencies"] = []
            stage["required_inputs"] = ["external:already_verified_primary_scan"]
        else:
            # Fixture-only external parents; not a production adoption policy.
            stage["required_inputs"] = [
                name
                if name in produced or name.startswith("external:")
                else f"external:{name}"
                for name in stage["required_inputs"]
            ]
    profile = seal(
        {
            "schema_version": 1,
            "profile_id": "synthetic-o3a-native-interface",
            "observing_run": "O3a",
            "detectors": ["H1", "L1"],
            "adapter": "o3a_native_diagnostic",
            "stages": stages,
        }
    )
    profile_path = tmp_path / "config/synthetic_profile.json"
    profile_path.write_text(json.dumps(profile))
    workflow = seal(
        {
            "schema_version": 2,
            "workflow_id": "synthetic-o3a-native-workflow",
            "adapter": "o3a_native_diagnostic",
            "scientific_configs": configs,
            "stages": stages,
            "policies": legacy["policies"],
            "graph_profile": {
                "path": "config/synthetic_profile.json",
                "sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
            },
        }
    )
    spec = validate_workflow_spec(workflow, root=tmp_path)
    paths = WorkflowPaths(tmp_path, tmp_path / "raw", tmp_path / "cache")
    return O3aNativeAdapter(spec, python_executable="explicit-python"), paths


@pytest.mark.parametrize(
    "stage",
    [
        "COHORT",
        "INDEX",
        "NATIVE_CALIBRATION",
        "RESCORE",
        "THRESHOLDS",
        "CLASSIFY",
        "TAXONOMY",
        "COINCIDENCE",
        "PEM",
    ],
)
@pytest.mark.parametrize("action", ["run", "verify"])
def test_real_cli_selectors_and_only_path_arguments(interface, stage, action):
    adapter, paths = interface
    definition = NATIVE_COMMANDS[stage]
    command = adapter.build_command(stage, action, paths)
    selector = (
        definition.run_selector if action == "run" else definition.verify_selector
    )
    assert command.argv[: 2 + len(selector)] == (
        "explicit-python",
        definition.script,
        *selector,
    )
    tail = command.argv[2 + len(selector) :]
    assert tail[:2] == ("--external-root", str(paths.cache_root / "o3a_native_v1"))
    if stage == "COHORT":
        assert tail[2:] == (
            "--primary-external-root",
            str(paths.cache_root / "o3a_native_v1"),
            "--raw-root",
            str(paths.raw_root),
        )
    else:
        assert len(tail) == 2
    assert command.scientific_config_digests == {
        stage: adapter.spec.scientific_configs[stage].sha256
    }
    if action == "verify":
        adapter.assert_verify_command_matches_contract(command)


def test_definition_selectors_match_existing_script_source(interface):
    # This is a source-interface check, not a claim that argparse was executed.
    for definition in NATIVE_COMMANDS.values():
        source = (ROOT / definition.script).read_text()
        for selector in (definition.run_selector, definition.verify_selector):
            for token in selector:
                assert token in source or f'"{token.removeprefix("--")}"' in source
        assert '"--external-root"' in source


def test_config_paths_match_real_scientific_module_constants():
    # Read primary source without importing GWPy/CUDA or executing argparse.
    for definition in NATIVE_COMMANDS.values():
        script = ast.parse((ROOT / definition.script).read_text())
        modules = [
            node.module
            for node in ast.walk(script)
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("src.dante_light.")
        ]
        assert len(modules) == 1
        scientific_source = ROOT / (modules[0].replace(".", "/") + ".py")
        assignments = [
            node.value
            for node in ast.walk(ast.parse(scientific_source.read_text()))
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "CONTRACT_REL"
                for target in node.targets
            )
        ]
        assert len(assignments) == 1
        value = assignments[0]
        if isinstance(value, ast.Call):
            assert isinstance(value.func, ast.Name) and value.func.id == "Path"
            value = value.args[0]
        assert ast.literal_eval(value) == definition.config_path


def test_native_calibration_is_not_rescore_or_threshold_fitting(interface):
    adapter, paths = interface
    native = adapter.build_command("NATIVE_CALIBRATION", "run", paths)
    assert native.argv[1] == "scripts/freeze_dante_o3a_native_calibration_cohort.py"
    assert "--run" not in native.argv
    assert adapter.build_command("RESCORE", "run", paths).argv[2] == "--run"
    assert adapter.build_command("PEM", "verify", paths).argv[2:4] == (
        "--stage",
        "verify",
    )


@pytest.mark.parametrize(
    "change", ["schema", "adapter", "run", "detectors", "stage", "config"]
)
def test_scope_or_binding_mismatch_fails_before_state(interface, change):
    adapter, paths = interface
    spec = adapter.spec
    if change == "schema":
        spec = replace(spec, schema_version=1)
    elif change == "adapter":
        spec = replace(spec, adapter="o4a_corrected")
    elif change in {"run", "detectors"}:
        field = (
            {"observing_run": "O4a"}
            if change == "run"
            else {"detectors": ("H1", "L1", "V1")}
        )
        spec = replace(spec, graph_profile=replace(spec.graph_profile, **field))
    elif change == "stage":
        spec = replace(
            spec, stages=(*spec.stages, replace(spec.stages[0], name="COMPARE"))
        )
    else:
        stages = tuple(
            replace(stage, config_refs=("INDEX",)) if stage.name == "COHORT" else stage
            for stage in spec.stages
        )
        spec = replace(spec, stages=stages)
    with pytest.raises(AdapterError):
        O3aNativeAdapter(spec)
    assert not paths.cache_root.exists()


def test_unfinished_interface_not_registered_as_complete_workflow(interface):
    adapter, paths = interface
    with pytest.raises(AdapterError, match="unsupported workflow adapter"):
        build_adapter(adapter.spec)
    with pytest.raises(AdapterError, match="unsupported workflow adapter"):
        WorkflowOrchestrator.from_spec(spec=adapter.spec, paths=paths)
    assert not paths.cache_root.exists()


@pytest.mark.parametrize(
    "stage,action", [("REPORT", "verify"), ("COHORT", "freeze"), ("COMPARE", "run")]
)
def test_unsupported_stage_or_action_does_not_fall_back(interface, stage, action):
    adapter, paths = interface
    with pytest.raises(AdapterError):
        adapter.build_command(stage, action, paths)


def cohort_payload(tmp_path):
    directory = tmp_path / "verified-cohort"
    directory.mkdir()
    ledger = directory / "native_cohort.jsonl"
    ledger.write_bytes(b"synthetic opaque ledger; not scientific evidence\n")
    summary = seal(
        {
            "status": "PASS_FROZEN_O3A_NATIVE_COHORT",
            "ledger": {
                "filename": ledger.name,
                "sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
            },
        },
        "artifact_digest",
    )
    return {"summary": summary, "run_dir": str(directory)}, ledger


def test_nested_real_cohort_payload_binds_exact_bytes_without_parsing_rows(
    interface, tmp_path
):
    adapter, _ = interface
    payload, ledger = cohort_payload(tmp_path)
    cohort = adapter.cohort_manifest_receipt_from_verifier(payload)
    consumed = adapter.index_window_manifest_receipt(ledger)
    assert cohort.name == "native_cohort_manifest"
    assert consumed.name == "index_window_manifest"
    assert cohort.path == consumed.path == str(ledger.resolve())
    assert cohort.sha256 == consumed.sha256 == payload["summary"]["ledger"]["sha256"]


@pytest.mark.parametrize(
    "change",
    [
        "flattened",
        "missing_summary",
        "status",
        "seal",
        "filename",
        "backslash",
        "drive",
        "sha",
        "bytes",
        "missing_run",
        "symlink",
    ],
)
def test_corrupt_nested_cohort_evidence_is_rejected(interface, tmp_path, change):
    adapter, _ = interface
    payload, ledger = cohort_payload(tmp_path)
    if change == "flattened":
        payload = {"run_dir": payload["run_dir"], **payload["summary"]}
    elif change == "missing_summary":
        payload["summary"] = None
    elif change == "status":
        payload["summary"]["status"] = "FAILED"
        seal(payload["summary"], "artifact_digest")
    elif change == "seal":
        payload["summary"]["artifact_digest"] = "0" * 64
    elif change in {"filename", "backslash", "drive", "sha"}:
        key = "sha256" if change == "sha" else "filename"
        payload["summary"]["ledger"][key] = {
            "filename": "../native_cohort.jsonl",
            "backslash": "..\\outside.jsonl",
            "drive": "C:outside.jsonl",
            "sha": "0" * 64,
        }[change]
        seal(payload["summary"], "artifact_digest")
    elif change == "bytes":
        ledger.write_bytes(b"altered")
    elif change == "missing_run":
        payload["run_dir"] = ""
    else:
        outside = tmp_path / "outside"
        outside.write_bytes(ledger.read_bytes())
        ledger.unlink()
        try:
            ledger.symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation unavailable")
    with pytest.raises(AdapterError):
        adapter.cohort_manifest_receipt_from_verifier(payload)


def test_missing_cli_or_changed_verify_prefix_is_rejected(interface):
    adapter, paths = interface
    script = paths.repository_root / NATIVE_COMMANDS["INDEX"].script
    script.unlink()
    with pytest.raises(AdapterError, match="absent"):
        adapter.build_command("INDEX", "verify", paths)
    stages = tuple(
        replace(stage, verifier_command=("python", "wrong.py", "--verify"))
        if stage.name == "COHORT"
        else stage
        for stage in adapter.spec.stages
    )
    with pytest.raises(AdapterError, match="verifier"):
        changed = O3aNativeAdapter(replace(adapter.spec, stages=stages))
        changed.build_command("COHORT", "verify", paths)


def test_direct_shared_controller_adopts_and_reverifies_synthetic_interface(
    interface, tmp_path
):
    adapter, paths = interface
    payload, _ = cohort_payload(tmp_path)
    observed = []

    def synthetic_runner(command):
        observed.append((command.stage, command.action))
        assert command.action == "verify"
        output = payload if command.stage == "COHORT" else {"synthetic": True}
        return CommandResult(0, json.dumps(output), "")

    controller = WorkflowOrchestrator(
        spec=adapter.spec,
        adapter=adapter,
        paths=paths,
        runner=synthetic_runner,
        source_identity={"test": "synthetic-interface-only"},
    )
    result = controller.adopt_verified_existing()
    assert all(
        row["status"] == "ADOPTED_VERIFIED_EXISTING" for row in result["results"]
    )
    receipt = verify_workflow(controller)
    assert receipt["status"] == "PASS_VERIFIED_WORKFLOW"
    assert receipt["scientific_boundary"]["stage_execution_modes"] == [
        "ADOPTED_VERIFIED_EXISTING"
    ]
    assert len(observed) == 2 * len(adapter.spec.stages)
    assert not any(action == "run" for _, action in observed)
