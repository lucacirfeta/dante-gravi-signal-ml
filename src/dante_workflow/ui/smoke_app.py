"""Loopback Flask application for the bounded public technical smoke."""

from __future__ import annotations

import hmac
import secrets

from .controller import UIControlError
from .smoke import PublicSmokeUIController, PublicSmokeUISettings


def create_public_smoke_app(
    settings: PublicSmokeUISettings,
    *,
    controller: PublicSmokeUIController | None = None,
):
    try:
        from flask import (
            Flask,
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
    except ImportError as exc:  # pragma: no cover - launcher message
        raise RuntimeError("install requirements-ui.txt to use the local UI") from exc

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=settings.secret_key or secrets.token_hex(32),
        DANTE_CSRF_TOKEN=secrets.token_urlsafe(32),
        MAX_CONTENT_LENGTH=64 * 1024,
        TRUSTED_HOSTS=["127.0.0.1", "localhost", "[::1]"],
    )
    active = controller or PublicSmokeUIController(settings)
    app.extensions["dante_public_smoke_controller"] = active

    def selected_device() -> str:
        device = request.values.get("device", "cpu")
        if device not in {"cpu", "cuda"}:
            abort(400)
        return device

    def csrf() -> None:
        supplied = request.form.get("csrf_token", "")
        if not hmac.compare_digest(supplied, current_app.config["DANTE_CSRF_TOKEN"]):
            abort(403)

    @app.get("/")
    def dashboard():
        device = selected_device()
        return render_template(
            "public_smoke.html",
            csrf_token=current_app.config["DANTE_CSRF_TOKEN"],
            status=active.public_status(device),
        )

    @app.get("/api/status")
    def api_status():
        return jsonify(active.public_status(selected_device()))

    @app.post("/actions/<action>")
    def action(action: str):
        csrf()
        device = selected_device()
        try:
            result = active.launch(action, device, request.form.get("run_key", ""))
        except (OSError, UIControlError) as exc:
            flash(str(exc), "error")
        else:
            flash(
                f"Independent smoke worker launched (PID {result['pid']}).", "success"
            )
        return redirect(url_for("dashboard", device=device))

    @app.get("/receipt")
    def receipt():
        device = selected_device()
        status = active.public_status(device)
        if status["status"] != "VERIFIED_TECHNICAL_SMOKE":
            abort(404)
        path = (
            settings.repository_root
            / "artifacts/dante_workflow/public_smoke_v1"
            / status["run_key"]
            / "technical_receipt.json"
        )
        return send_file(path, as_attachment=False, download_name=path.name)

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return app
