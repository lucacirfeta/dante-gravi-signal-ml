#!/usr/bin/env python3
"""Plan, run, resume, inspect, and verify the frozen DANTE workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_workflow.adapters import WorkflowPaths  # noqa: E402
from src.dante_workflow.orchestrator import (  # noqa: E402
    OrchestrationError,
    WorkflowOrchestrator,
)
from src.dante_workflow.reporting import (  # noqa: E402
    WorkflowReportingError,
    write_workflow_report,
)
from src.dante_workflow.schema import load_workflow_spec  # noqa: E402
from src.dante_workflow.state import WorkflowStateError  # noqa: E402
from src.dante_workflow.verification import (  # noqa: E402
    WorkflowVerificationError,
    verify_workflow,
)


DEFAULT_CONFIG = ROOT / "config/dante_workflow_productization_v1.json"


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument(
        "--cache-root", type=Path, default=Path("E:/dante_cache/dante_light")
    )
    parser.add_argument("--workflow-root", type=Path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "preflight", "run", "resume", "status", "verify", "report"):
        command = commands.add_parser(name)
        _add_common(command)
        if name in {"run", "resume"}:
            selection = command.add_mutually_exclusive_group()
            selection.add_argument("--through-stage")
            selection.add_argument("--repair-stage")
    return parser


def _orchestrator(args: argparse.Namespace) -> WorkflowOrchestrator:
    repository_root = args.repository_root.resolve()
    spec = load_workflow_spec(args.config.resolve(), root=repository_root)
    return WorkflowOrchestrator.corrected_o4a(
        spec=spec,
        paths=WorkflowPaths(
            repository_root=repository_root,
            raw_root=args.raw_root,
            cache_root=args.cache_root,
        ),
        workflow_root=args.workflow_root,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        orchestrator = _orchestrator(args)
        if args.command == "plan":
            result = orchestrator.plan()
        elif args.command == "status":
            result = orchestrator.status()
        elif args.command == "verify":
            result = verify_workflow(orchestrator)
        elif args.command == "preflight":
            result = orchestrator.execute(through_stage="PREFLIGHT")
        elif args.command == "report":
            result = orchestrator.execute(through_stage="REPORT")
            if not any(item.get("status") == "FAILED" for item in result["results"]):
                result["derived_report_path"] = str(
                    write_workflow_report(orchestrator)
                )
        else:
            result = orchestrator.execute(
                through_stage=args.through_stage,
                repair_stage=args.repair_stage,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        print(
            f"{result['status']}: {orchestrator.run_key}",
            file=sys.stderr,
        )
        if any(
            item.get("status") == "FAILED"
            for item in result.get("results", [])
            if isinstance(item, dict)
        ):
            return 1
        if result.get("verdict") == "FAIL":
            return 1
        return 0
    except (
        OrchestrationError,
        WorkflowReportingError,
        WorkflowStateError,
        WorkflowVerificationError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "WORKFLOW_ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        print(f"WORKFLOW_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
