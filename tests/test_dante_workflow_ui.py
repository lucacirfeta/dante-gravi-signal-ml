from __future__ import annotations

import os
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("flask")

from src.dante_workflow.schema import REQUIRED_STAGE_NAMES
from src.dante_workflow.ui.app import UISettings, create_app
from src.dante_workflow.ui.controller import (
    LocalPathPolicy,
    UIControlError,
    UISelection,
    WorkflowUIController,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dante_workflow_productization_v1.json"


class FakeController:
    def __init__(self, tmp_path: Path) -> None:
        self.selection = SimpleNamespace(
            repository_root=ROOT,
            raw_root=tmp_path / "raw",
            cache_root=tmp_path / "cache",
            workflow_root=tmp_path / "workflow",
        )
        self.calls: list[tuple[str, object]] = []
        self.artifact = tmp_path / "verified.json"
        self.artifact.write_text('{"status":"PASS"}\n', encoding="utf-8")

    def public_status(self):
        return {
            "schema_version": 1,
            "status": "WORKFLOW_STATUS",
            "workflow_id": "dante.o4a.corrected.productization.v1",
            "run_key": "a" * 64,
            "run_dir": str(self.selection.workflow_root),
            "next_incomplete_stage": "PREFLIGHT",
            "worker": {"state": "IDLE", "stop_requested": False},
            "stages": [
                {"name": name, "status": "PENDING"}
                for name in REQUIRED_STAGE_NAMES
            ],
        }

    def plan(self):
        return {
            "stages": [
                {"name": name, "dependencies": []}
                for name in REQUIRED_STAGE_NAMES
            ]
        }

    def local_preflight(self):
        return {
            "status": "READY",
            "note": "Scientific PREFLIGHT remains authoritative.",
            "checks": [
                {"name": "Worker Python", "verdict": "PASS", "detail": "python"}
            ],
        }

    def scientific_configs(self):
        return [
            {"name": "frozen", "path": "config/frozen.json", "sha256": "b" * 64}
        ]

    def administrative_logs(self):
        return []

    def report_path(self):
        raise UIControlError("not ready")

    def select(self, **values):
        self.calls.append(("select", values))
        return self.public_status()

    def launch(self, action: str):
        self.calls.append(("launch", action))
        return {"status": "WORKER_LAUNCHED", "pid": 4321}

    def require_run_key(self, expected: str):
        if expected != "a" * 64:
            raise UIControlError("this page refers to a different run")

    @contextmanager
    def control(self, expected: str):
        self.require_run_key(expected)
        yield

    def request_stop(self):
        self.calls.append(("stop", None))
        return {"status": "STOP_AFTER_CURRENT_STAGE_REQUESTED"}

    def verified_artifact(self, stage: str, name: str):
        if (stage, name) != ("PREFLIGHT", "preflight_receipt"):
            raise UIControlError("unverified")
        return self.artifact

    def verified_log(self, stage: str, name: str):
        if (stage, name) != ("PREFLIGHT", "verify.stdout.txt"):
            raise UIControlError("unverified")
        return "verified log"


def _app(tmp_path: Path):
    controller = FakeController(tmp_path)
    app = create_app(
        UISettings(
            repository_root=ROOT,
            config_path=CONFIG,
            raw_root=tmp_path / "raw",
            cache_root=tmp_path / "cache",
            secret_key="test-secret",
        ),
        controller=controller,
    )
    app.config.update(TESTING=True)
    return app, controller


def test_dashboard_is_semantic_and_contains_no_unverified_outcomes(
    tmp_path: Path,
) -> None:
    app, _ = _app(tmp_path)

    response = app.test_client().get("/")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "DANTE workflow controller" in page
    assert "Execution state for all 15 workflow stages" in page
    assert page.count('data-stage="') == 15
    assert "Scientific contracts" in page
    assert "No verified artifacts yet" in page
    assert "sensitive-outcome-value" not in page
    assert "candidate outcome" in page.lower()
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_post_controls_require_csrf_and_delegate_only_to_controller(
    tmp_path: Path,
) -> None:
    app, controller = _app(tmp_path)
    client = app.test_client()

    assert client.post("/actions/start").status_code == 403

    response = client.post(
        "/actions/start",
        data={"csrf_token": app.config["DANTE_CSRF_TOKEN"], "run_key": "a" * 64},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert controller.calls == [("launch", "start")]
    assert "Independent worker launched" in response.get_data(as_text=True)


def test_stop_and_selection_are_explicit_administrative_actions(
    tmp_path: Path,
) -> None:
    app, controller = _app(tmp_path)
    client = app.test_client()
    token = app.config["DANTE_CSRF_TOKEN"]

    stop = client.post("/actions/stop", data={"csrf_token": token, "run_key": "a" * 64})
    selected = client.post(
        "/selection",
        data={
            "csrf_token": token,
            "run_key": "a" * 64,
            "repository_root": str(ROOT),
            "raw_root": str(tmp_path / "raw"),
            "cache_root": str(tmp_path / "cache"),
            "workflow_root": "",
        },
    )

    assert stop.status_code == selected.status_code == 302
    assert controller.calls[0] == ("stop", None)
    assert controller.calls[1][0] == "select"


def test_artifacts_and_logs_are_fail_closed_until_verified(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    client = app.test_client()

    artifact = client.get("/artifacts/PREFLIGHT/preflight_receipt")
    log = client.get("/logs/PREFLIGHT/verify.stdout.txt")

    assert artifact.status_code == 200
    assert artifact.get_json() == {"status": "PASS"}
    assert log.status_code == 200
    assert log.get_data(as_text=True) == "verified log"
    assert client.get("/artifacts/SCAN/candidate_catalog").status_code == 404
    assert client.get("/logs/SCAN/run.stdout.txt").status_code == 404
    assert client.get("/report").status_code == 404


def test_path_policy_rejects_traversal_outside_explicit_roots(tmp_path: Path) -> None:
    raw = tmp_path / "allowed-raw"
    cache = tmp_path / "allowed-cache"
    policy = LocalPathPolicy(ROOT, (raw,), (cache,))

    policy.validate(UISelection(ROOT, CONFIG, raw / "o4a", cache, cache / "runs"))
    with pytest.raises(UIControlError, match="raw-data selector"):
        policy.validate(UISelection(ROOT, CONFIG, tmp_path / "other", cache, None))
    with pytest.raises(UIControlError, match="workflow selector"):
        policy.validate(UISelection(ROOT, CONFIG, raw, cache, tmp_path / "other"))


@pytest.mark.parametrize(
    ("action", "worker_command"),
    [("start", "report"), ("adopt", "adopt-verified")],
)
def test_real_controller_launches_detached_cli_without_running_a_stage_in_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    worker_command: str,
) -> None:
    raw = tmp_path / "raw"
    cache = tmp_path / "cache"
    raw.mkdir()
    cache.mkdir()
    controller = WorkflowUIController(
        selection=UISelection(ROOT, CONFIG, raw, cache, tmp_path / "workflow"),
        path_policy=LocalPathPolicy(ROOT, (raw,), (cache, tmp_path / "workflow")),
        worker_python=os.fspath(Path(os.sys.executable)),
    )
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = os.getpid()

    def fake_popen(command, **options):
        captured["command"] = command
        captured["options"] = options
        return FakeProcess()

    monkeypatch.setattr("src.dante_workflow.ui.controller.spawn_worker", fake_popen)
    monkeypatch.setattr(
        "src.dante_workflow.ui.controller.platform.platform", lambda: "test-platform"
    )

    result = controller.launch(action)

    assert result["status"] == "WORKER_LAUNCHED"
    assert captured["command"][2] == worker_command
    assert captured["options"]["stdin"] is not None
    assert "stdout" in captured["options"] and "stderr" in captured["options"]
    assert controller.orchestrator.ledger.read_events() == []
    assert controller.worker_state()["state"] == "LAUNCHING"
    assert controller.administrative_logs()[-1]["event"] == "WORKER_LAUNCHED"
    with pytest.raises(UIControlError, match="already present"):
        controller.launch(action)


@pytest.mark.parametrize("action", ["preflight", "adopt", "verify"])
def test_validation_buttons_use_the_independent_worker(tmp_path, action):
    app, controller = _app(tmp_path)
    response = app.test_client().post(
        f"/actions/{action}",
        data={"csrf_token": app.config["DANTE_CSRF_TOKEN"], "run_key": "a" * 64},
    )
    assert response.status_code == 302
    assert controller.calls == [("launch", action)]


def test_stale_page_and_untrusted_host_cannot_control_current_run(tmp_path: Path) -> None:
    app, controller = _app(tmp_path)
    client = app.test_client()
    response = client.post(
        "/actions/start",
        data={"csrf_token": app.config["DANTE_CSRF_TOKEN"], "run_key": "old-run"},
        follow_redirects=True,
    )
    assert "different run" in response.get_data(as_text=True)
    assert controller.calls == []
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400


def test_real_failed_stage_outcomes_are_sealed_in_all_http_views(tmp_path: Path) -> None:
    from src.dante_workflow.orchestrator import CommandResult

    settings = UISettings(
        repository_root=ROOT, config_path=CONFIG,
        raw_root=tmp_path / "raw", cache_root=tmp_path / "cache",
    )
    app = create_app(settings)
    app.config.update(TESTING=True)
    controller = app.extensions["dante_workflow_controller"]
    secret = "sensitive-outcome-value"
    controller.orchestrator.runner = lambda command: CommandResult(1, secret, secret)
    controller.orchestrator.execute(through_stage="PREFLIGHT")
    client = app.test_client()
    for path in ("/", "/api/status", "/api/logs"):
        response = client.get(path)
        assert response.status_code == 200
        assert secret not in response.get_data(as_text=True)
    for path in (
        "/artifacts/PREFLIGHT/preflight_receipt", "/logs/PREFLIGHT/run.stdout.txt",
        "/logs/UNKNOWN/run.stdout.txt", "/report",
    ):
        assert client.get(path).status_code == 404


def test_ambiguous_interrupted_launch_is_not_silently_restarted(tmp_path, monkeypatch):
    app = create_app(UISettings(
        repository_root=ROOT, config_path=CONFIG,
        raw_root=tmp_path / "raw", cache_root=tmp_path / "cache",
    ))
    controller = app.extensions["dante_workflow_controller"]
    controller._launch_path.parent.mkdir(parents=True, exist_ok=True)
    controller._launch_path.write_text(json.dumps({
        "launcher_pid": 99999, "schema_version": 1,
        "run_key": controller.orchestrator.run_key,
    }), encoding="utf-8")
    monkeypatch.setattr(controller, "_process_alive", lambda pid: False)
    assert controller.worker_state()["state"] == "STALE_LAUNCH"
    with pytest.raises(UIControlError, match="already present"):
        controller.launch("start")
    assert controller._launch_path.is_file()


def test_real_detached_child_survives_controller_exit_and_reconnect(tmp_path):
    from src.dante_workflow.processes import process_alive

    helper = ROOT / "tests/fixtures/dante_workflow_ui_lifecycle.py"
    try:
        launcher = subprocess.run(
            [sys.executable, str(helper), "launcher", str(tmp_path)],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=True,
        )
        launched = json.loads(launcher.stdout)
        assert process_alive(launched["pid"])
        app = create_app(UISettings(
            repository_root=ROOT, config_path=CONFIG,
            raw_root=tmp_path / "raw", cache_root=tmp_path / "cache",
        ))
        status = app.test_client().get("/api/status").get_json()
        assert status["run_key"] == launched["run_key"]
        assert status["worker"]["pid"] == launched["pid"]
        assert status["worker"]["state"] == "LAUNCHING"
        assert all(stage["status"] == "PENDING" for stage in status["stages"])
    finally:
        (tmp_path / "release-child").touch()
    deadline = time.monotonic() + 10
    while process_alive(launched["pid"]) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not process_alive(launched["pid"])
