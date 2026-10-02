"""Synthetic common-engine checks, never a real science/run qualification."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from src.dante_workflow import cli
from src.dante_workflow.adapters import StageAdapter, StageCommand, WorkflowPaths
from src.dante_workflow.orchestrator import (
    CommandResult,
    OrchestrationError,
    WorkflowOrchestrator,
)
from src.dante_workflow.operation_policy import RETAINED_PASS
from src.dante_workflow.reporting import (
    build_workflow_report,
    verify_report_file,
    write_workflow_report,
)
from src.dante_workflow.schema import (
    WorkflowSchemaError,
    canonical_json_sha256,
    validate_workflow_spec,
)
from src.dante_workflow.verification import (
    WorkflowVerificationError,
    verify_release_receipt,
    verify_workflow,
)

ROOT = Path(__file__).resolve().parents[1]


def seal(value, field="contract_digest"):
    body = deepcopy(value)
    body.pop(field, None)
    value[field] = canonical_json_sha256(body)
    return value


def write_profile(root, workflow, profile):
    path = root / "config/synthetic_operation_profile.json"
    path.write_text(json.dumps(seal(profile)), encoding="utf-8")
    workflow["graph_profile"] = {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    seal(workflow)


def fixture(root, observing_run="O3a"):
    workflow = json.loads(
        (ROOT / "config/dante_workflow_productization_v1.json").read_text()
    )
    for ref in workflow["scientific_configs"].values():
        dest = root / ref["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / ref["path"], dest)
    for stage in workflow["stages"]:
        for token in stage["verifier_command"]:
            if token.startswith("scripts/") and token.endswith(".py"):
                dest = root / token
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / token, dest)
    workflow.update(
        schema_version=2, workflow_id="synthetic-common-retained", adapter="synthetic"
    )
    profile = {
        "schema_version": 2,
        "profile_id": "synthetic-common",
        "observing_run": observing_run,
        "detectors": ["H1", "L1"],
        "adapter": "synthetic",
        "stages": deepcopy(workflow["stages"]),
        "operation_policy": {
            "mode": "VERIFY_RETAINED_ONLY",
            "stage_receipts": {
                stage["name"]: {
                    "status": f"PASS_SYNTHETIC_{stage['name']}_RETAINED_ONLY",
                    "verification_level": "SYNTHETIC_TEST_ONLY",
                    "seal_field": "receipt_digest",
                }
                for stage in workflow["stages"]
            },
        },
    }
    write_profile(root, workflow, profile)
    return workflow, profile


class SyntheticReadOnlyAdapter(StageAdapter):
    supports_retained_verification = True

    def build_command(self, stage, action, paths):
        assert action == "verify", "retained-only must not construct a run command"
        return StageCommand(
            stage,
            action,
            self.spec.stage(stage).verifier_command,
            paths.repository_root,
            self.scientific_digests_for_stage(stage),
        )

    def cohort_manifest_receipt_from_verifier(self, payload):
        return self.artifact_receipt(
            "native_cohort_manifest", Path(payload["ledger_path"])
        )

    def index_window_manifest_receipt(self, path):
        return self.artifact_receipt("index_window_manifest", path)


class RetainedRunner:
    def __init__(self, root):
        self.path = root / "retained.jsonl"
        self.path.write_bytes(b'{"detector":"H1","gps_start":1}\n')
        self.calls = []
        self.mutation = None

    def __call__(self, command):
        assert command.action == "verify"
        self.calls.append(command.stage)
        body = {
            "status": f"PASS_SYNTHETIC_{command.stage}_RETAINED_ONLY",
            "verification_level": "SYNTHETIC_TEST_ONLY",
            "full_workflow_verified": False,
            "ledger_path": str(self.path),
            "stage": command.stage,
            "secret_outcome": "never transcribe into aggregate receipt",
        }
        if self.mutation:
            self.mutation(body)
        return CommandResult(0, json.dumps(seal(body, "receipt_digest")), "")


def controller(root, *, observing_run="O3a"):
    workflow, profile = fixture(root, observing_run)
    spec = validate_workflow_spec(workflow, root=root)
    runner = RetainedRunner(root)
    paths = WorkflowPaths(root, root / "raw", root / "cache")
    orchestrator = WorkflowOrchestrator(
        spec=spec,
        adapter=SyntheticReadOnlyAdapter(spec),
        paths=paths,
        runner=runner,
        source_identity={"synthetic_test": "only"},
    )
    return orchestrator, runner, workflow, profile


@pytest.mark.parametrize("run", ["O3a", "O4a"])
def test_common_retained_adoption_and_scoped_release(tmp_path, run):
    orchestrator, runner, _, _ = controller(tmp_path, observing_run=run)
    original = runner.path.read_bytes()
    assert all(set(actions) == {"verify"} for actions in orchestrator.commands.values())
    assert all(
        stage["run_command_digest"] is None for stage in orchestrator.plan()["stages"]
    )
    assert orchestrator.plan()["operation_policy"]["new_execution_allowed"] is False
    orchestrator.adopt_verified_existing()
    receipt = verify_workflow(orchestrator)
    assert receipt["status"] == RETAINED_PASS
    assert receipt["scientific_boundary"]["full_workflow_verified"] is False
    assert receipt["scientific_boundary"]["new_scientific_run_executed"] is False
    assert "secret_outcome" not in json.dumps(receipt)
    assert len(runner.calls) == 2 * len(orchestrator.spec.stages)
    assert verify_workflow(orchestrator) == receipt
    assert (
        verify_release_receipt(Path(receipt["receipt_path"]))["status"] == RETAINED_PASS
    )
    report = build_workflow_report(orchestrator)
    assert RETAINED_PASS in report and "full_workflow_verified=false" in report
    assert "- Status: `PASS_VERIFIED_WORKFLOW`" not in report
    write_workflow_report(orchestrator)
    assert verify_report_file(orchestrator).is_file()
    assert runner.path.read_bytes() == original


@pytest.mark.parametrize(
    "kwargs", [{}, {"through_stage": "PREFLIGHT"}, {"repair_stage": "SCAN"}]
)
def test_new_execution_blocked_before_lease_or_process(tmp_path, kwargs):
    orchestrator, runner, _, _ = controller(tmp_path)
    events = orchestrator.ledger.read_events()
    with pytest.raises(OrchestrationError, match="forbids"):
        orchestrator.execute(**kwargs)
    assert not orchestrator.ledger.lease_path.exists()
    assert orchestrator.ledger.read_events() == events
    assert runner.calls == []


@pytest.mark.parametrize("command", ["run", "resume", "preflight"])
def test_cli_cannot_bypass_retained_policy(tmp_path, monkeypatch, command):
    orchestrator, runner, _, _ = controller(tmp_path)
    monkeypatch.setattr(cli, "_orchestrator", lambda _: orchestrator)
    assert cli.main([command]) == 1
    assert not runner.calls and not orchestrator.ledger.lease_path.exists()


def test_cli_report_does_not_execute_a_scientific_stage(tmp_path, monkeypatch):
    orchestrator, runner, _, _ = controller(tmp_path)
    orchestrator.adopt_verified_existing()
    calls_before = len(runner.calls)
    monkeypatch.setattr(cli, "_orchestrator", lambda _: orchestrator)
    assert cli.main(["report"]) == 0
    assert len(runner.calls) - calls_before == len(orchestrator.spec.stages)
    assert all(set(actions) == {"verify"} for actions in orchestrator.commands.values())


@pytest.mark.parametrize("action", ["start", "resume", "preflight"])
def test_ui_rejects_new_execution_before_launcher(tmp_path, action):
    from src.dante_workflow.ui.controller import WorkflowUIController, UIControlError

    orchestrator, _, _, _ = controller(tmp_path)
    # Exercise the actual guard without initializing a real launcher.
    fake = SimpleNamespace(orchestrator=orchestrator)
    with pytest.raises(UIControlError, match="forbids"):
        WorkflowUIController.launch(fake, action)


def test_policy_alone_does_not_certify_a_legacy_adapter(tmp_path):
    workflow, _ = fixture(tmp_path)
    spec = validate_workflow_spec(workflow, root=tmp_path)

    class LegacyAdapter(SyntheticReadOnlyAdapter):
        supports_retained_verification = False

    with pytest.raises(OrchestrationError, match="does not support"):
        WorkflowOrchestrator(
            spec=spec,
            adapter=LegacyAdapter(spec),
            paths=WorkflowPaths(tmp_path, tmp_path / "raw", tmp_path / "cache"),
            source_identity={"test": "only"},
        )
    assert not (tmp_path / "cache").exists()


def test_retained_command_must_match_frozen_verifier_before_opening_ledger(tmp_path):
    workflow, _ = fixture(tmp_path)
    spec = validate_workflow_spec(workflow, root=tmp_path)

    class WrongAdapter(SyntheticReadOnlyAdapter):
        def build_command(self, stage, action, paths):
            return replace(
                super().build_command(stage, action, paths),
                argv=("python", "-c", "print('PASS')"),
            )

    from src.dante_workflow.adapters import AdapterError

    with pytest.raises(AdapterError, match="diverges"):
        WorkflowOrchestrator(
            spec=spec,
            adapter=WrongAdapter(spec),
            paths=WorkflowPaths(tmp_path, tmp_path / "raw", tmp_path / "cache"),
            source_identity={"test": "only"},
        )
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize(
    "corruption", ["non-json", "duplicate", "unsealed", "wrong-seal", "missing-scope"]
)
def test_zero_exit_alone_cannot_admit_retained_stage(tmp_path, corruption):
    orchestrator, runner, _, _ = controller(tmp_path)

    def malformed(command):
        result = runner(command)
        body = json.loads(result.stdout)
        if corruption == "non-json":
            text = "PASS"
        elif corruption == "duplicate":
            text = result.stdout[:-1] + ', "status": "PASS"}'
        elif corruption == "unsealed":
            body.pop("receipt_digest")
            text = json.dumps(body)
        elif corruption == "missing-scope":
            body.pop("full_workflow_verified")
            text = json.dumps(seal(body, "receipt_digest"))
        else:
            body["receipt_digest"] = "0" * 64
            text = json.dumps(body)
        return CommandResult(0, text, "")

    orchestrator.runner = malformed
    with pytest.raises(OrchestrationError, match="adoption failed"):
        orchestrator.adopt_verified_existing()
    assert orchestrator.ledger.stage_status("PREFLIGHT") == "FAILED"
    assert not (orchestrator.run_dir / "workflow_release_receipt.json").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("full_workflow_verified", True),
        ("full_workflow_verified", 0),
        ("status", "PASS_VERIFIED_WORKFLOW"),
        ("verification_level", "OTHER"),
    ],
)
def test_sealed_but_wrong_stage_scope_is_not_admitted(tmp_path, field, value):
    orchestrator, runner, _, _ = controller(tmp_path)
    runner.mutation = lambda body: body.update({field: value})
    with pytest.raises(OrchestrationError, match="adoption failed"):
        orchestrator.adopt_verified_existing()
    assert orchestrator.ledger.stage_status("PREFLIGHT") == "FAILED"
    assert len(runner.calls) == 1
    assert not (orchestrator.run_dir / "workflow_release_receipt.json").exists()


def test_replay_cannot_silently_replace_adopted_evidence(tmp_path):
    orchestrator, runner, _, _ = controller(tmp_path)
    orchestrator.adopt_verified_existing()
    runner.mutation = lambda body: body.update(new_parent="changed")
    with pytest.raises(WorkflowVerificationError, match="replay differs"):
        verify_workflow(orchestrator)


def test_retained_release_cannot_be_relabelled_as_full_pass(tmp_path):
    orchestrator, _, _, _ = controller(tmp_path)
    orchestrator.adopt_verified_existing()
    value = verify_workflow(orchestrator)
    path = Path(value.pop("receipt_path"))
    value.pop("receipt_sha256")
    value["status"] = "PASS_VERIFIED_WORKFLOW"
    path.write_text(json.dumps(seal(value, "receipt_digest")))
    with pytest.raises(WorkflowVerificationError, match="cannot claim"):
        verify_release_receipt(path)


@pytest.mark.parametrize("boundary", [None, [], {"full_workflow_verified": True}])
def test_retained_release_rejects_resigned_invalid_boundary(tmp_path, boundary):
    orchestrator, _, _, _ = controller(tmp_path)
    orchestrator.adopt_verified_existing()
    value = verify_workflow(orchestrator)
    path = Path(value.pop("receipt_path"))
    value.pop("receipt_sha256")
    value["scientific_boundary"] = boundary
    path.write_text(json.dumps(seal(value, "receipt_digest")))
    with pytest.raises(WorkflowVerificationError, match="boundary|scope"):
        verify_release_receipt(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda policy: policy.update(mode="RUN_ANYTHING"),
        lambda policy: policy["stage_receipts"].pop("SCAN"),
        lambda policy: policy["stage_receipts"].update(FOREIGN={}),
        lambda policy: policy["stage_receipts"]["SCAN"].update(seal_field="none"),
        lambda policy: policy["stage_receipts"]["SCAN"].update(seal_field=[]),
        lambda policy: policy["stage_receipts"].update(SCAN=None),
        lambda policy: policy["stage_receipts"]["SCAN"].update(
            status="PASS_VERIFIED_WORKFLOW"
        ),
        lambda policy: policy.update(extra=True),
        lambda policy: policy.update(mode="EXECUTE_AND_VERIFY"),
    ],
)
def test_profile_policy_fails_closed_even_when_resigned(tmp_path, mutation):
    workflow, profile = fixture(tmp_path)
    mutation(profile["operation_policy"])
    write_profile(tmp_path, workflow, profile)
    with pytest.raises(WorkflowSchemaError):
        validate_workflow_spec(workflow, root=tmp_path)


def test_new_execute_policy_preserves_legacy_operation_semantics(tmp_path):
    workflow, profile = fixture(tmp_path)
    profile["operation_policy"] = {"mode": "EXECUTE_AND_VERIFY", "stage_receipts": {}}
    write_profile(tmp_path, workflow, profile)
    spec = validate_workflow_spec(workflow, root=tmp_path)
    assert not spec.retained_only
    assert spec.graph_profile.operation_policy.mode == "EXECUTE_AND_VERIFY"


def test_profile_policy_is_hash_bound_and_immutable(tmp_path):
    workflow, profile = fixture(tmp_path)
    spec = validate_workflow_spec(workflow, root=tmp_path)
    with pytest.raises(TypeError):
        spec.graph_profile.operation_policy.stage_receipts["SCAN"]["status"] = "other"
    profile["operation_policy"]["stage_receipts"]["SCAN"]["verification_level"] = (
        "OTHER"
    )
    path = tmp_path / workflow["graph_profile"]["path"]
    path.write_text(json.dumps(seal(profile)))
    with pytest.raises(WorkflowSchemaError, match="file digest"):
        validate_workflow_spec(workflow, root=tmp_path)
