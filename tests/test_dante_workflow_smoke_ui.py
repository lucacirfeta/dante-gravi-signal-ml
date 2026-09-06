from __future__ import annotations

import hashlib
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
    value = {"status": "SKIPPED_VERIFIED_TECHNICAL_SMOKE" if existed else "PASS_TECHNICAL_SMOKE", "run_key": KEY, "receipt": str(receipt)}
print(json.dumps(value))
"""


def _controller(tmp_path: Path) -> PublicSmokeUIController:
    runner = tmp_path / "scripts/run_dante_workflow_clean_clone.py"
    runner.parent.mkdir(parents=True)
    runner.write_text(FAKE_RUNNER, encoding="utf-8")
    return PublicSmokeUIController(
        PublicSmokeUISettings(
            repository_root=tmp_path,
            worker_python=sys.executable,
            secret_key="test-secret",
        )
    )


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
    assert b"not a corrected O4a release" in page.data
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


def test_public_smoke_ui_rejects_csrf_stale_identity_and_bad_device(tmp_path) -> None:
    controller = _controller(tmp_path)
    app = create_public_smoke_app(controller.settings, controller=controller)
    app.config.update(TESTING=True)
    client = app.test_client()

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
