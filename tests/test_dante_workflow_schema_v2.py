"""Synthetic administrative graphs, not scientific replay or run approval."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from src.dante_workflow.adapters import AdapterError, WorkflowPaths, build_adapter
from src.dante_workflow.orchestrator import WorkflowOrchestrator
from src.dante_workflow.schema import (
    REQUIRED_STAGE_NAMES,
    WorkflowSchemaError,
    canonical_json_sha256,
    load_workflow_spec,
    validate_workflow_spec,
)

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "config/dante_workflow_productization_v1.json"


def _seal(value):
    body = deepcopy(value)
    body.pop("contract_digest", None)
    value["contract_digest"] = canonical_json_sha256(body)
    return value


def _write_profile(root, workflow, profile):
    path = root / "config/graphs/synthetic_v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_seal(profile), sort_keys=True), encoding="utf-8")
    workflow["graph_profile"] = {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    _seal(workflow)
    return path


def _fixture(root, *, minimal=False):
    workflow = json.loads(LEGACY.read_text(encoding="utf-8"))
    for reference in workflow["scientific_configs"].values():
        dest = root / reference["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / reference["path"], dest)
    for stage in workflow["stages"]:
        for token in stage["verifier_command"]:
            if token.startswith("scripts/") and token.endswith(".py"):
                dest = root / token
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / token, dest)
    workflow["schema_version"] = 2
    workflow["workflow_id"] = "synthetic-profile-workflow-v2"
    if minimal:
        workflow["adapter"] = "synthetic_unimplemented"
        stage = deepcopy(workflow["stages"][0])
        stage["config_refs"] = list(workflow["scientific_configs"])
        workflow["stages"] = [stage]
    profile = {
        "schema_version": 1,
        "profile_id": "synthetic-o3a" if minimal else "synthetic-o4a",
        "observing_run": "O3a" if minimal else "O4a",
        "detectors": ["H1", "L1"],
        "adapter": workflow["adapter"],
        "stages": deepcopy(workflow["stages"]),
    }
    path = _write_profile(root, workflow, profile)
    return workflow, profile, path


def test_v1_remains_v1_without_a_profile():
    spec = load_workflow_spec(LEGACY, root=ROOT)
    assert spec.schema_version == 1
    assert spec.graph_profile is None
    assert spec.topological_stage_names() == REQUIRED_STAGE_NAMES
    assert spec.contract_digest == json.loads(LEGACY.read_text())["contract_digest"]


def test_v2_loader_binds_profile_and_full_graph(tmp_path):
    workflow, profile, path = _fixture(tmp_path)
    config = tmp_path / "config/workflow_v2.json"
    config.write_text(json.dumps(workflow), encoding="utf-8")
    spec = load_workflow_spec(config, root=tmp_path)
    assert spec.schema_version == 2
    assert spec.graph_profile.profile_id == profile["profile_id"]
    assert spec.graph_profile.observing_run == "O4a"
    assert spec.graph_profile.detectors == ("H1", "L1")
    assert (
        spec.graph_profile.reference.sha256
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert spec.graph_profile.contract_digest == profile["contract_digest"]
    assert spec.topological_stage_names() == REQUIRED_STAGE_NAMES
    with pytest.raises((AttributeError, TypeError)):
        spec.graph_profile.detectors = ("V1",)


def test_different_explicit_profile_graph_is_not_forced_into_o4a(tmp_path):
    workflow, _, _ = _fixture(tmp_path, minimal=True)
    spec = validate_workflow_spec(workflow, root=tmp_path)
    assert spec.topological_stage_names() == ("PREFLIGHT",)
    paths = WorkflowPaths(tmp_path, tmp_path / "raw", tmp_path / "cache")
    with pytest.raises(AdapterError, match="unsupported workflow adapter"):
        WorkflowOrchestrator.from_spec(spec=spec, paths=paths)
    assert not paths.cache_root.exists()


@pytest.mark.parametrize(
    "operation",
    [
        "remove",
        "reorder",
        "verifier",
        "dependency",
        "output",
        "visibility",
        "resumability",
    ],
)
def test_resigned_workflow_cannot_change_sealed_profile_graph(tmp_path, operation):
    workflow, _, _ = _fixture(tmp_path)
    if operation == "remove":
        workflow["stages"].pop()
    elif operation == "reorder":
        workflow["stages"].reverse()
    elif operation == "verifier":
        workflow["stages"][0]["verifier_command"] = ["python", "-c", "pass"]
    elif operation == "dependency":
        workflow["stages"][1]["dependencies"] = []
    elif operation == "output":
        workflow["stages"][0]["expected_outputs"] = ["fake_receipt"]
    elif operation == "visibility":
        workflow["stages"][0]["outcome_visibility"] = "AFTER_VERIFICATION"
    else:
        workflow["stages"][0]["resumability"] = "RESUME_IN_PLACE"
    _seal(workflow)
    with pytest.raises(WorkflowSchemaError, match="profile graph"):
        validate_workflow_spec(workflow, root=tmp_path)


def test_profile_file_change_fails_even_with_valid_profile_seal(tmp_path):
    workflow, profile, path = _fixture(tmp_path)
    profile["profile_id"] = "changed"
    path.write_text(json.dumps(_seal(profile)), encoding="utf-8")
    with pytest.raises(WorkflowSchemaError, match="digest mismatch"):
        validate_workflow_spec(workflow, root=tmp_path)


def test_profile_internal_seal_is_not_replaced_by_file_sha(tmp_path):
    workflow, profile, path = _fixture(tmp_path)
    profile["contract_digest"] = "0" * 64
    path.write_text(json.dumps(profile), encoding="utf-8")
    workflow["graph_profile"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    _seal(workflow)
    with pytest.raises(WorkflowSchemaError, match="profile seal"):
        validate_workflow_spec(workflow, root=tmp_path)


@pytest.mark.parametrize("version", [True, 2.0, "2", 3])
def test_v2_does_not_accept_ambiguous_schema_versions(tmp_path, version):
    workflow, _, _ = _fixture(tmp_path)
    workflow["schema_version"] = version
    _seal(workflow)
    with pytest.raises(WorkflowSchemaError):
        validate_workflow_spec(workflow, root=tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("detectors", []),
        ("detectors", ["H1", "H1"]),
        ("detectors", ["VIRGO"]),
        ("observing_run", ""),
        ("adapter", "other"),
        ("scientific_override", {"top_k": 1}),
    ],
)
def test_profile_fields_are_strict(tmp_path, field, value):
    workflow, profile, _ = _fixture(tmp_path)
    profile[field] = value
    _write_profile(tmp_path, workflow, profile)
    with pytest.raises(WorkflowSchemaError):
        validate_workflow_spec(workflow, root=tmp_path)


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.json",
        "/absolute.json",
        "config/../other.json",
        "config\\graph.json",
        "C:/graph.json",
        "scripts/graph.json",
        ".",
        "",
    ],
)
def test_profile_path_is_confined_to_checkout_config(tmp_path, relative):
    workflow, _, _ = _fixture(tmp_path)
    workflow["graph_profile"]["path"] = relative
    _seal(workflow)
    with pytest.raises(WorkflowSchemaError, match="profile.*path|profile.*config"):
        validate_workflow_spec(workflow, root=tmp_path)


def test_empty_profile_graph_is_not_a_successful_workflow(tmp_path):
    workflow, profile, _ = _fixture(tmp_path)
    workflow["stages"] = profile["stages"] = []
    _write_profile(tmp_path, workflow, profile)
    with pytest.raises(WorkflowSchemaError, match="must not be empty"):
        validate_workflow_spec(workflow, root=tmp_path)


@pytest.mark.parametrize("gate", ["index_manifest", "cohort", "rescore"])
def test_native_parent_gates_survive_even_if_both_graphs_are_resigned(tmp_path, gate):
    workflow, profile, _ = _fixture(tmp_path)
    name = "RESCORE" if gate == "rescore" else "NATIVE_CALIBRATION"
    stage = next(item for item in workflow["stages"] if item["name"] == name)
    parent = "COHORT" if gate == "cohort" else "INDEX"
    stage["dependencies"] = [
        item for item in stage["dependencies"] if item["stage"] != parent
    ]
    if gate == "index_manifest":
        stage["required_inputs"].remove("index_window_manifest")
    profile["stages"] = deepcopy(workflow["stages"])
    _write_profile(tmp_path, workflow, profile)
    with pytest.raises(WorkflowSchemaError, match="requires"):
        validate_workflow_spec(workflow, root=tmp_path)


@pytest.mark.parametrize("change", ["run", "detectors", "short_graph"])
def test_o4a_adapter_rejects_profile_scope_or_graph_mismatch(tmp_path, change):
    workflow, profile, _ = _fixture(tmp_path)
    if change == "run":
        profile["observing_run"] = "O3a"
    elif change == "detectors":
        profile["detectors"] = ["H1", "L1", "V1"]
    else:
        workflow, profile, _ = _fixture(tmp_path, minimal=True)
        workflow["adapter"] = profile["adapter"] = "o4a_corrected"
        profile["observing_run"] = "O4a"
    _write_profile(tmp_path, workflow, profile)
    spec = validate_workflow_spec(workflow, root=tmp_path)
    with pytest.raises(AdapterError, match="profile|graph"):
        build_adapter(spec)


def test_v1_cannot_opt_into_a_short_graph_by_attaching_profile(tmp_path):
    workflow, _, _ = _fixture(tmp_path)
    workflow["schema_version"] = 1
    _seal(workflow)
    with pytest.raises(WorkflowSchemaError, match="unknown=.*graph_profile"):
        validate_workflow_spec(workflow, root=tmp_path)


def test_v2_missing_profile_fails_closed(tmp_path):
    workflow, _, _ = _fixture(tmp_path)
    workflow.pop("graph_profile")
    _seal(workflow)
    with pytest.raises(WorkflowSchemaError, match="missing=.*graph_profile"):
        validate_workflow_spec(workflow, root=tmp_path)


def test_same_o4a_commands_are_preserved_but_v2_has_a_new_identity(tmp_path):
    workflow, _, _ = _fixture(tmp_path)
    v2 = validate_workflow_spec(workflow, root=tmp_path)
    v1 = load_workflow_spec(LEGACY, root=ROOT)
    paths = WorkflowPaths(ROOT, tmp_path / "raw", tmp_path / "cache")
    source = {"git_head": "a" * 40, "tracked_worktree_diff_sha256": "b" * 64}
    old = WorkflowOrchestrator.from_spec(spec=v1, paths=paths, source_identity=source)
    new = WorkflowOrchestrator.from_spec(spec=v2, paths=paths, source_identity=source)
    for name in REQUIRED_STAGE_NAMES:
        for action in ("run", "verify"):
            assert old.commands[name][action].argv == new.commands[name][action].argv
    assert old.run_key != new.run_key


@pytest.mark.parametrize(
    "change",
    [
        "cycle",
        "self",
        "unknown_parent",
        "duplicate_stage",
        "duplicate_producer",
        "unproduced_input",
        "artifact_gate",
        "disabled_policy",
        "unused_config",
        "missing_verifier",
        "visibility_type",
        "gate_type",
    ],
)
def test_graph_integrity_and_policy_are_not_replaced_by_profile_seal(tmp_path, change):
    workflow, profile, _ = _fixture(tmp_path)
    stages = workflow["stages"]
    if change == "cycle":
        stages[0]["dependencies"] = [
            {"stage": stages[-1]["name"], "gate": "VERIFIED_STAGE"}
        ]
    elif change == "self":
        stages[0]["dependencies"] = [
            {"stage": stages[0]["name"], "gate": "VERIFIED_STAGE"}
        ]
    elif change == "unknown_parent":
        stages[0]["dependencies"] = [{"stage": "UNKNOWN", "gate": "VERIFIED_STAGE"}]
    elif change == "duplicate_stage":
        stages.append(deepcopy(stages[0]))
    elif change == "duplicate_producer":
        stages[1]["expected_outputs"].append(stages[0]["expected_outputs"][0])
    elif change == "unproduced_input":
        stages[-1]["required_inputs"].append("unpublished")
    elif change == "artifact_gate":
        native = next(item for item in stages if item["name"] == "NATIVE_CALIBRATION")
        gate = next(item for item in native["dependencies"] if item["stage"] == "INDEX")
        gate["artifact"] = "unpublished"
    elif change == "disabled_policy":
        workflow["policies"]["hide_outcomes_until_verified"] = False
    elif change == "unused_config":
        for stage in stages:
            stage["config_refs"] = [
                ref for ref in stage["config_refs"] if ref != "runtime"
            ]
    elif change == "missing_verifier":
        stages[0]["verifier_command"] = ["python", "scripts/missing.py"]
    elif change == "visibility_type":
        stages[0]["outcome_visibility"] = []
    else:
        stages[1]["dependencies"][0]["gate"] = []
    profile["stages"] = deepcopy(stages)
    _write_profile(tmp_path, workflow, profile)
    with pytest.raises(WorkflowSchemaError):
        validate_workflow_spec(workflow, root=tmp_path)


def test_duplicate_profile_json_fields_are_rejected(tmp_path):
    workflow, _, path = _fixture(tmp_path)
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw[:-1] + ', "profile_id":"another"}', encoding="utf-8")
    workflow["graph_profile"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    _seal(workflow)
    with pytest.raises(WorkflowSchemaError, match="duplicate JSON field"):
        validate_workflow_spec(workflow, root=tmp_path)


def test_duplicate_workflow_json_fields_are_rejected(tmp_path):
    workflow, _, _ = _fixture(tmp_path)
    path = tmp_path / "config/workflow.json"
    path.write_text(
        json.dumps(workflow)[:-1] + ', "adapter":"other"}', encoding="utf-8"
    )
    with pytest.raises(WorkflowSchemaError, match="duplicate JSON field"):
        load_workflow_spec(path, root=tmp_path)


def test_graph_profile_symlink_cannot_escape_checkout(tmp_path):
    root = tmp_path / "repo"
    workflow, _, path = _fixture(root)
    outside = tmp_path / "outside.json"
    outside.write_bytes(path.read_bytes())
    link = path.with_name("escape.json")
    link.symlink_to(outside)
    workflow["graph_profile"]["path"] = link.relative_to(root).as_posix()
    _seal(workflow)
    with pytest.raises(WorkflowSchemaError, match="profile path escapes"):
        validate_workflow_spec(workflow, root=root)
