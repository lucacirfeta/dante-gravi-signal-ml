"""HTTP routes for the local workflow controller."""

from __future__ import annotations

import hmac
from typing import Any

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .controller import UIControlError, WorkflowUIController


def _controller() -> WorkflowUIController:
    return current_app.extensions["dante_workflow_controller"]


def _csrf() -> None:
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    expected = current_app.config["DANTE_CSRF_TOKEN"]
    if not hmac.compare_digest(supplied, expected):
        abort(403)


def _artifact_rows(status: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for stage in status["stages"]:
        if stage["status"] != "VERIFIED":
            continue
        rows.extend(
            {
                "stage": stage["name"],
                "name": artifact["name"],
                "sha256": artifact["sha256"],
            }
            for artifact in stage.get("artifacts", [])
        )
    return rows


def register_routes(app) -> None:
    @app.get("/")
    def dashboard():
        controller = _controller()
        status = controller.public_status()
        selection = controller.selection
        report_ready = False
        try:
            controller.report_path()
        except UIControlError:
            pass
        else:
            report_ready = True
        return render_template(
            "dashboard.html",
            csrf_token=current_app.config["DANTE_CSRF_TOKEN"],
            status=status,
            plan=controller.plan(),
            preflight=controller.local_preflight(),
            configs=controller.scientific_configs(),
            logs=controller.administrative_logs(),
            artifacts=_artifact_rows(status),
            selection=selection,
            report_ready=report_ready,
        )

    @app.get("/api/status")
    def api_status():
        return jsonify(_controller().public_status())

    @app.get("/api/logs")
    def api_logs():
        return jsonify(
            {
                "status": "ADMINISTRATIVE_LOGS",
                "events": _controller().administrative_logs(),
            }
        )

    @app.post("/selection")
    def select_paths():
        _csrf()
        try:
            controller = _controller()
            with controller.control(request.form.get("run_key", "")):
                controller.select(
                    repository_root=request.form.get("repository_root", ""),
                    raw_root=request.form.get("raw_root", ""),
                    cache_root=request.form.get("cache_root", ""),
                    workflow_root=request.form.get("workflow_root", ""),
                )
        except (UIControlError, OSError, ValueError) as exc:
            flash(str(exc), "error")
        else:
            flash("Local paths selected; scientific configuration is unchanged.", "success")
        return redirect(url_for("dashboard"))

    @app.post("/actions/<action>")
    def action(action: str):
        _csrf()
        try:
            controller = _controller()
            with controller.control(request.form.get("run_key", "")):
                if action == "stop":
                    controller.request_stop()
                    message = "Stop requested after the current atomic stage."
                elif action in {"start", "resume", "adopt", "preflight", "verify"}:
                    result = controller.launch(action)
                    message = f"Independent worker launched (PID {result['pid']})."
                else:
                    abort(404)
        except (UIControlError, OSError) as exc:
            flash(str(exc), "error")
        else:
            flash(message, "success")
        return redirect(url_for("dashboard"))

    @app.get("/artifacts/<stage>/<name>")
    def artifact(stage: str, name: str):
        try:
            path = _controller().verified_artifact(stage, name)
        except UIControlError:
            abort(404)
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.get("/logs/<stage>/<name>")
    def verified_log(stage: str, name: str):
        try:
            content = _controller().verified_log(stage, name)
        except UIControlError:
            abort(404)
        return current_app.response_class(content, mimetype="text/plain")

    @app.get("/report")
    def report():
        try:
            path = _controller().report_path()
        except UIControlError:
            abort(404)
        return send_file(path, as_attachment=False, download_name=path.name)
