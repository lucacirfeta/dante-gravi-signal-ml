"""Flask application factory for the optional local DANTE UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import secrets
import sys

from .controller import LocalPathPolicy, UISelection, WorkflowUIController


@dataclass(frozen=True, slots=True)
class UISettings:
    repository_root: Path
    config_path: Path
    raw_root: Path
    cache_root: Path
    workflow_root: Path | None = None
    allowed_raw_roots: tuple[Path, ...] = ()
    allowed_cache_roots: tuple[Path, ...] = ()
    worker_python: str = sys.executable
    secret_key: str | None = None

    def __post_init__(self) -> None:
        for name in ("repository_root", "config_path", "raw_root", "cache_root"):
            object.__setattr__(self, name, getattr(self, name).resolve())
        if self.workflow_root is not None:
            object.__setattr__(self, "workflow_root", self.workflow_root.resolve())


def create_app(
    settings: UISettings,
    *,
    controller: WorkflowUIController | None = None,
):
    """Create a loopback-oriented UI without starting or owning a worker."""

    try:
        from flask import Flask
    except ImportError as exc:  # pragma: no cover - exercised by launcher message
        raise RuntimeError("install requirements-ui.txt to use the local UI") from exc

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=settings.secret_key or secrets.token_hex(32),
        DANTE_CSRF_TOKEN=secrets.token_urlsafe(32),
        MAX_CONTENT_LENGTH=64 * 1024,
        TRUSTED_HOSTS=["127.0.0.1", "localhost", "[::1]"],
    )
    if controller is None:
        controller = WorkflowUIController(
            selection=UISelection(
                repository_root=settings.repository_root,
                config_path=settings.config_path,
                raw_root=settings.raw_root,
                cache_root=settings.cache_root,
                workflow_root=settings.workflow_root,
            ),
            path_policy=LocalPathPolicy(
                repository_root=settings.repository_root,
                raw_roots=settings.allowed_raw_roots or (settings.raw_root,),
                cache_roots=settings.allowed_cache_roots or (settings.cache_root,),
            ),
            worker_python=settings.worker_python,
        )
    app.extensions["dante_workflow_controller"] = controller

    from .views import register_routes

    register_routes(app)

    @app.after_request
    def _security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return app
