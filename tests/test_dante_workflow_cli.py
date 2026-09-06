"""Administrative worker entry-point regression tests; no scientific jobs."""

from types import SimpleNamespace

import pytest

from scripts import run_dante_workflow as cli


@pytest.mark.parametrize("status,stage,results", [
    ("WORKFLOW_EXECUTION_STOPPED", "ACQUIRE", []),
    ("WORKFLOW_EXECUTION_COMPLETE", "SCAN", [{"status": "FAILED"}]),
])
def test_report_command_does_not_render_incomplete_runs(monkeypatch, status, stage, results):
    worker = SimpleNamespace(
        run_key="test-run",
        ledger=SimpleNamespace(next_incomplete_stage=lambda: stage),
        execute=lambda **kw: {"status": status, "results": results},
    )
    monkeypatch.setattr(cli, "_orchestrator", lambda args: worker)
    monkeypatch.setattr(cli, "write_workflow_report", lambda obj: pytest.fail("incomplete report"))
    assert cli.main(["report"]) == (1 if results else 0)


def test_worker_refuses_run_key_changed_since_ui_display(monkeypatch, capsys):
    worker = SimpleNamespace(
        run_key="new-run",
        execute=lambda **kw: pytest.fail("changed run must not execute"),
    )
    monkeypatch.setattr(cli, "_orchestrator", lambda args: worker)
    assert cli.main(["report", "--expected-run-key", "displayed-run"]) == 1
    assert "requested run key differs" in capsys.readouterr().out


def test_adopt_verified_command_never_routes_to_execute(monkeypatch):
    calls = []
    worker = SimpleNamespace(
        run_key="test-run",
        adopt_verified_existing=lambda **kwargs: calls.append(kwargs)
        or {"status": "WORKFLOW_ADOPTION", "results": []},
        execute=lambda **kwargs: pytest.fail("adoption must not execute science"),
    )
    monkeypatch.setattr(cli, "_orchestrator", lambda args: worker)

    assert cli.main(["adopt-verified", "--through-stage", "SCAN"]) == 0
    assert calls == [{"through_stage": "SCAN"}]
