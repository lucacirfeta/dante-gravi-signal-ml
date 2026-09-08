#!/usr/bin/env python3
"""Bounded local-web UI spike for the persistent DANTE workflow ledger."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_workflow.adapters import WorkflowPaths  # noqa: E402
from src.dante_workflow.orchestrator import WorkflowOrchestrator  # noqa: E402
from src.dante_workflow.schema import load_workflow_spec  # noqa: E402


DEFAULT_CONFIG = ROOT / "config/dante_workflow_productization_v1.json"


def create_app(
    *,
    config: Path = DEFAULT_CONFIG,
    repository_root: Path = ROOT,
    raw_root: Path = Path("E:/o4a"),
    cache_root: Path = Path("E:/dante_cache/dante_light"),
    workflow_root: Path | None = None,
) -> Any:
    """Create a read-only UI over one content-addressed workflow run."""

    try:
        from flask import Flask, jsonify, render_template_string
    except ImportError as exc:  # pragma: no cover - exercised without UI extras
        raise RuntimeError(
            "UI dependencies are absent; install requirements-ui.txt"
        ) from exc

    repository_root = repository_root.resolve()
    spec = load_workflow_spec(config.resolve(), root=repository_root)
    orchestrator = WorkflowOrchestrator.corrected_o4a(
        spec=spec,
        paths=WorkflowPaths(
            repository_root=repository_root,
            raw_root=raw_root,
            cache_root=cache_root,
        ),
        workflow_root=workflow_root,
    )
    app = Flask(__name__)
    app.config["DANTE_ORCHESTRATOR"] = orchestrator

    @app.get("/health")
    def health() -> Any:
        return jsonify(
            {
                "schema_version": 1,
                "status": "PASS_UI_SPIKE_HEALTH",
                "run_key": orchestrator.run_key,
            }
        )

    @app.get("/api/status")
    def workflow_status() -> Any:
        return jsonify(orchestrator.status())

    @app.get("/")
    def index() -> str:
        status = orchestrator.status()
        return render_template_string(
            """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>DANTE workflow spike</title>
  </head>
  <body>
    <main>
      <h1>DANTE workflow</h1>
      <p><strong>Run key:</strong> <code>{{ status.run_key }}</code></p>
      <p><strong>Next stage:</strong> {{ status.next_incomplete_stage }}</p>
      <table>
        <caption>Infrastructure status only</caption>
        <thead><tr><th>Stage</th><th>Status</th></tr></thead>
        <tbody>
        {% for stage in status.stages %}
          <tr><td>{{ stage.name }}</td><td>{{ stage.status }}</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </main>
  </body>
</html>""",
            status=status,
        )

    return app


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument(
        "--cache-root", type=Path, default=Path("E:/dante_cache/dante_light")
    )
    parser.add_argument("--workflow-root", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("the bounded UI spike only binds to the local host")
    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    try:
        from waitress import serve
    except ImportError as exc:
        raise SystemExit(
            "UI dependencies are absent; install requirements-ui.txt"
        ) from exc
    app = create_app(
        config=args.config,
        repository_root=args.repository_root,
        raw_root=args.raw_root,
        cache_root=args.cache_root,
        workflow_root=args.workflow_root,
    )
    serve(app, host=args.host, port=args.port, threads=4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
