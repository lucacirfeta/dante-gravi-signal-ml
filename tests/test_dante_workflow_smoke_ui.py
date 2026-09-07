from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from src.dante_workflow.ui.smoke import (
    PublicSmokeUIController,
    PublicSmokeUISettings,
)
from src.dante_workflow.ui.smoke_app import create_public_smoke_app


FAKE_RUNNER = """
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "a" * 64
parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=("plan", "local", "verify"), required=True)
parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
args = parser.parse_args()
run_dir = ROOT / "artifacts/dante_workflow/public_smoke_v1" / KEY
receipt = run_dir / "technical_receipt.json"
report = run_dir / "report.md"
progress = run_dir / "progress.json"
if args.mode == "plan":
    value = {"status": "SMOKE_PLAN", "scope": "technical_public_replay_not_corrected_o4a_release", "run_key": KEY}
elif args.mode == "verify" and not receipt.is_file():
    print(json.dumps({"status": "TECHNICAL_SMOKE_ERROR", "error": "technical smoke receipt is absent"}))
    raise SystemExit(1)
else:
    existed = receipt.is_file()
    run_dir.mkdir(parents=True, exist_ok=True)
    if not existed:
        receipt.write_text(json.dumps({"status": "PASS_TECHNICAL_SMOKE", "run_key": KEY}) + "\\n", encoding="utf-8")
        report.write_text("# Readable smoke report\\n", encoding="utf-8")
        progress.write_text(json.dumps({"schema_version": 1, "status": "COMPLETE", "phase": "complete", "label": "Technical smoke verified", "detail": "Ready", "completed_steps": 4, "total_steps": 4}) + "\\n", encoding="utf-8")
    value = {"status": "SKIPPED_VERIFIED_TECHNICAL_SMOKE" if existed else "PASS_TECHNICAL_SMOKE", "run_key": KEY, "receipt": str(receipt)}
print(json.dumps(value))
"""


def _controller(tmp_path: Path) -> PublicSmokeUIController:
    runner = tmp_path / "scripts/run_dante_workflow_clean_clone.py"
    runner.parent.mkdir(parents=True)
    runner.write_text(FAKE_RUNNER, encoding="utf-8")
    controller = PublicSmokeUIController(
        PublicSmokeUISettings(
            repository_root=tmp_path,
            worker_python=sys.executable,
            secret_key="test-secret",
        )
    )
    controller._hardware_cache = {
        "cuda_available": False,
        "gpu_name": None,
        "recommended_device": "cpu",
        "reason": "CPU is the compatible default; no CUDA GPU was detected.",
    }
    return controller


def _wait_for_exit(controller: PublicSmokeUIController, run_key: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if controller.worker_state(run_key)["state"] == "EXITED":
            return
        time.sleep(0.02)
    raise AssertionError("public smoke worker did not exit")


def test_public_smoke_ui_launches_same_cli_without_changing_receipt(tmp_path) -> None:
    controller = _controller(tmp_path)
    settings = controller.settings
    command = [
        sys.executable,
        str(controller.runner),
        "--mode",
        "local",
        "--device",
        "cpu",
    ]
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    status_before = controller.public_status("cpu")
    receipt = (
        tmp_path
        / "artifacts/dante_workflow/public_smoke_v1"
        / status_before["run_key"]
        / "technical_receipt.json"
    )
    bytes_before = receipt.read_bytes()

    app = create_public_smoke_app(settings, controller=controller)
    app.config.update(TESTING=True)
    client = app.test_client()
    page = client.get("/?device=cpu")
    assert page.status_code == 200
    assert b"Recheck completed test" in page.data
    assert b"Choose the compute device" in page.data
    assert b"Live and detailed logs" in page.data
    response = client.post(
        "/actions/run",
        data={
            "csrf_token": app.config["DANTE_CSRF_TOKEN"],
            "device": "cpu",
            "run_key": status_before["run_key"],
        },
    )
    assert response.status_code == 302
    _wait_for_exit(controller, status_before["run_key"])

    status_after = controller.public_status("cpu")
    assert status_after["status"] == "VERIFIED_TECHNICAL_SMOKE"
    assert status_after["run_key"] == status_before["run_key"]
    assert receipt.read_bytes() == bytes_before
    assert status_after["receipt_sha256"] == hashlib.sha256(bytes_before).hexdigest()
    assert client.get("/receipt?device=cpu").data == bytes_before
    assert b"Readable smoke report" in client.get("/report?device=cpu").data
    completed_page = client.get("/?device=cpu")
    assert b"Open readable report" in completed_page.data
    assert b"Open technical receipt" in completed_page.data
    assert b"Verified (PASS)" in completed_page.data
    assert b'id="progress-eta">\n      Complete' in completed_page.data


def test_public_smoke_ui_rejects_csrf_stale_identity_and_bad_device(tmp_path) -> None:
    controller = _controller(tmp_path)
    app = create_public_smoke_app(controller.settings, controller=controller)
    app.config.update(TESTING=True)
    client = app.test_client()

    assert b"Start test" in client.get("/?device=cpu").data
    assert client.post("/actions/run", data={"device": "cpu"}).status_code == 403
    response = client.post(
        "/actions/run",
        data={
            "csrf_token": app.config["DANTE_CSRF_TOKEN"],
            "device": "cpu",
            "run_key": "old-run",
        },
        follow_redirects=True,
    )
    assert b"different smoke run" in response.data
    assert client.get("/?device=tpu").status_code == 400


def test_public_smoke_ui_uses_security_headers(tmp_path) -> None:
    controller = _controller(tmp_path)
    app = create_public_smoke_app(controller.settings, controller=controller)
    app.config.update(TESTING=True)
    response = app.test_client().get("/")

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_public_smoke_ui_recommends_detected_cuda(tmp_path) -> None:
    controller = _controller(tmp_path)
    controller._hardware_cache = {
        "cuda_available": True,
        "gpu_name": "Test GPU",
        "recommended_device": "cuda",
        "reason": "CUDA is recommended because a compatible GPU is available.",
    }
    app = create_public_smoke_app(controller.settings, controller=controller)
    app.config.update(TESTING=True)

    page = app.test_client().get("/")

    assert page.status_code == 200
    assert b'id="selected-device">CUDA' in page.data
    assert b"Detected: Test GPU" in page.data
    assert b"CUDA is recommended" in page.data


def test_public_smoke_ui_exposes_progress_and_bounded_logs(tmp_path) -> None:
    controller = _controller(tmp_path)
    run_key = controller.plan("cpu")["run_key"]
    run_dir = tmp_path / "artifacts/dante_workflow/public_smoke_v1" / run_key
    log = run_dir / "canonical/attempt/stdout.log"
    log.parent.mkdir(parents=True)
    log.write_text("download complete\\nprocessing window 2 of 2\\n", encoding="utf-8")
    (run_dir / "progress.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "RUNNING",
                "phase": "canonical",
                "label": "Running canonical replay",
                "detail": "Processing public windows.",
                "completed_steps": 2,
                "total_steps": 4,
                "started_at_unix": time.time() - 10,
                "updated_at_unix": time.time(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    app = create_public_smoke_app(controller.settings, controller=controller)
    app.config.update(TESTING=True)
    client = app.test_client()

    status = client.get("/api/status?device=cpu").get_json()

    assert status["progress"]["percent"] == 50
    assert status["progress"]["eta_seconds"] is not None
    assert status["logs"]["active_name"] == "canonical/attempt/stdout.log"
    assert "processing window 2 of 2" in status["logs"]["active_tail"]
    assert (
        client.get("/logs/canonical/attempt/stdout.log?device=cpu").data
        == log.read_bytes()
    )
    assert client.get("/logs/../../outside.txt?device=cpu").status_code == 404


def test_public_smoke_ui_renders_setup_error_instead_of_http_500(
    tmp_path, monkeypatch
) -> None:
    controller = _controller(tmp_path)

    def fail_status(_device):
        from src.dante_workflow.ui.controller import UIControlError

        raise UIControlError(
            "This technical smoke requires a tracked-clean checkout."
        )

    monkeypatch.setattr(controller, "public_status", fail_status)
    app = create_public_smoke_app(controller.settings, controller=controller)
    app.config.update(TESTING=True)

    page = app.test_client().get("/")

    assert page.status_code == 409
    assert b"The test cannot start from this checkout" in page.data
    assert b"clone" in page.data.lower()
    assert b"No scientific data" in page.data
    assert app.test_client().get("/api/status").status_code == 409
