"""Installed and checkout-compatible launcher for the local DANTE UI."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


DEFAULT_CONFIG_RELATIVE = Path("config/dante_workflow_productization_v1.json")


def _parser(
    *,
    default_repository_root: Path | None = None,
) -> argparse.ArgumentParser:
    repository_root = (default_repository_root or Path.cwd()).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=repository_root,
        help="Complete DANTE source checkout containing config/ and scripts/",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Workflow contract; defaults to <repository-root>/config/...",
    )
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument(
        "--cache-root", type=Path, default=Path("E:/dante_cache/dante_light")
    )
    parser.add_argument("--workflow-root", type=Path)
    parser.add_argument("--allow-raw-root", action="append", type=Path, default=[])
    parser.add_argument("--allow-cache-root", action="append", type=Path, default=[])
    parser.add_argument("--worker-python", default=sys.executable)
    parser.add_argument(
        "--public-smoke",
        action="store_true",
        help="open the bounded public technical-smoke controller",
    )
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1"))
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    default_repository_root: Path | None = None,
) -> int:
    """Serve the loopback-only UI for a complete source checkout."""

    args = _parser(default_repository_root=default_repository_root).parse_args(argv)
    try:
        from waitress import serve

        from . import (
            PublicSmokeUISettings,
            UISettings,
            create_app,
            create_public_smoke_app,
        )
    except ImportError:
        print(
            "Install dante-workflow[ui] or requirements-ui.txt before launching "
            "the UI.",
            file=sys.stderr,
        )
        return 2

    repository_root = args.repository_root.resolve()
    config = (
        args.config.resolve()
        if args.config is not None
        else repository_root / DEFAULT_CONFIG_RELATIVE
    )
    if args.public_smoke:
        app = create_public_smoke_app(
            PublicSmokeUISettings(
                repository_root=repository_root,
                worker_python=args.worker_python,
            )
        )
        label = "DANTE public technical smoke UI"
    else:
        app = create_app(
            UISettings(
                repository_root=repository_root,
                config_path=config,
                raw_root=args.raw_root,
                cache_root=args.cache_root,
                workflow_root=args.workflow_root,
                allowed_raw_roots=tuple(args.allow_raw_root) or (args.raw_root,),
                allowed_cache_roots=tuple(args.allow_cache_root)
                or (args.cache_root,),
                worker_python=args.worker_python,
            )
        )
        label = "DANTE workflow UI"
    print(f"{label}: http://{args.host}:{args.port}")
    serve(app, host=args.host, port=args.port, threads=4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
