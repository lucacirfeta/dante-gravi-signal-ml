#!/usr/bin/env python3
"""Launch the optional loopback-only DANTE workflow UI."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_workflow.ui import UISettings, create_app  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config/dante_workflow_productization_v1.json",
    )
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument(
        "--cache-root", type=Path, default=Path("E:/dante_cache/dante_light")
    )
    parser.add_argument("--workflow-root", type=Path)
    parser.add_argument("--allow-raw-root", action="append", type=Path, default=[])
    parser.add_argument("--allow-cache-root", action="append", type=Path, default=[])
    parser.add_argument("--worker-python", default=sys.executable)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1"))
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        from waitress import serve
    except ImportError:
        print("Install requirements-ui.txt before launching the UI.", file=sys.stderr)
        return 2
    app = create_app(
        UISettings(
            repository_root=args.repository_root,
            config_path=args.config,
            raw_root=args.raw_root,
            cache_root=args.cache_root,
            workflow_root=args.workflow_root,
            allowed_raw_roots=tuple(args.allow_raw_root) or (args.raw_root,),
            allowed_cache_roots=tuple(args.allow_cache_root) or (args.cache_root,),
            worker_python=args.worker_python,
        )
    )
    print(f"DANTE workflow UI: http://{args.host}:{args.port}")
    serve(app, host=args.host, port=args.port, threads=4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
