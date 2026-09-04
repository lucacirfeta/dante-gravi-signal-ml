#!/usr/bin/env python3
"""Verify a complete productized DANTE workflow or an existing receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_workflow.adapters import WorkflowPaths  # noqa: E402
from src.dante_workflow.orchestrator import WorkflowOrchestrator  # noqa: E402
from src.dante_workflow.schema import load_workflow_spec  # noqa: E402
from src.dante_workflow.verification import (  # noqa: E402
    WorkflowVerificationError,
    verify_release_receipt,
    verify_workflow,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config/dante_workflow_productization_v1.json",
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument(
        "--cache-root", type=Path, default=Path("E:/dante_cache/dante_light")
    )
    parser.add_argument("--workflow-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.release is not None:
            result = verify_release_receipt(args.release)
        else:
            repository_root = args.repository_root.resolve()
            spec = load_workflow_spec(args.config.resolve(), root=repository_root)
            orchestrator = WorkflowOrchestrator.corrected_o4a(
                spec=spec,
                paths=WorkflowPaths(
                    repository_root=repository_root,
                    raw_root=args.raw_root,
                    cache_root=args.cache_root,
                ),
                workflow_root=args.workflow_root,
            )
            result = verify_workflow(orchestrator)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, WorkflowVerificationError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "WORKFLOW_VERIFICATION_ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
