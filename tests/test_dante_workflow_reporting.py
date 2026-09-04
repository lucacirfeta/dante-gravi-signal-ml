from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.dante_workflow.adapters import O4aCorrectedAdapter, StageCommand, WorkflowPaths
from src.dante_workflow.orchestrator import CommandResult, WorkflowOrchestrator
from src.dante_workflow.reporting import (
    WorkflowReportingError,
    build_workflow_report,
    write_workflow_report,
)
from src.dante_workflow.schema import load_workflow_spec


ROOT = Path(__file__).resolve().parents[1]
SPEC = load_workflow_spec(
    ROOT / "config/dante_workflow_productization_v1.json", root=ROOT
)
SOURCE = {"git_head": "a" * 40, "tracked_worktree_diff_sha256": "b" * 64}


class ReportingRunner:
    def __init__(self, root: Path) -> None:
        self.root = root

    def __call__(self, command: StageCommand) -> CommandResult:
        stage_dir = self.root / command.stage.lower()
        stage_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {"run_dir": str(stage_dir)}
        if command.stage == "SCAN":
            payload.update(
                {
                    "excluded_unique_total": 72053,
                    "invalid_or_silent_drop_count": 0,
                }
            )
        if command.stage == "PEM":
            payload["scientific_boundary"] = {
                "missing_calibration_counted_as_negative": False
            }
        if (command.stage, command.action) == ("COHORT", "verify"):
            content = b'{"detector":"H1","gps_start":1}\n'
            ledger = stage_dir / "native_cohort.jsonl"
            ledger.write_bytes(content)
            payload["ledger"] = {
                "filename": ledger.name,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        return CommandResult(0, json.dumps(payload), "")


def _orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        spec=SPEC,
        adapter=O4aCorrectedAdapter(SPEC),
        paths=WorkflowPaths(
            repository_root=ROOT,
            raw_root=tmp_path / "raw",
            cache_root=tmp_path / "cache",
        ),
        runner=ReportingRunner(tmp_path / "scientific-artifacts"),
        source_identity=SOURCE,
        workflow_root=tmp_path / "workflow-runs",
    )


def test_report_is_derived_from_verified_receipts(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.execute()

    report = build_workflow_report(orchestrator)

    assert "PASS_VERIFIED_WORKFLOW" in report
    assert report.count("| PASS |") == 15
    assert "`excluded_unique_total` | `72053`" in report
    assert "`invalid_or_silent_drop_count` | `0`" in report
    assert "`scientific_boundary.missing_calibration_counted_as_negative`" in report
    assert "diagnostic follow-up outputs" in report
    assert "No global-significance or discovery claim" in report
    assert "not a public real-time or operational alerting system" in report


def test_report_cannot_be_pass_when_workflow_is_incomplete(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.execute(through_stage="SCAN")

    with pytest.raises(WorkflowReportingError, match="complete"):
        build_workflow_report(orchestrator)


def test_tampered_hash_bound_log_blocks_report(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.execute()
    receipt = orchestrator.ledger.latest_verified_artifact(
        "SCAN", "primary_scan_summary"
    )
    wrapper = json.loads(Path(receipt.path).read_text(encoding="utf-8"))
    Path(wrapper["logs"]["verify.stdout.txt"]["path"]).write_text(
        '{"excluded_unique_total":1}', encoding="utf-8"
    )

    with pytest.raises(WorkflowReportingError, match="verified"):
        build_workflow_report(orchestrator)


def test_written_report_matches_derived_text(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.execute()
    expected = build_workflow_report(orchestrator)

    path = write_workflow_report(orchestrator)

    assert path.read_text(encoding="utf-8") == expected
