"""Installed and checkout-compatible DANTE workflow controller."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .adapters import WorkflowPaths
from .orchestrator import OrchestrationError, WorkflowOrchestrator
from .reporting import WorkflowReportingError, write_workflow_report
from .schema import load_workflow_spec
from .state import WorkflowStateError
from .verification import WorkflowVerificationError, verify_workflow


DEFAULT_CONFIG_RELATIVE = Path("config/dante_workflow_productization_v1.json")


def _add_common(
    parser: argparse.ArgumentParser,
    *,
    default_repository_root: Path,
) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        help="Workflow contract; defaults to <repository-root>/config/...",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=default_repository_root,
        help="Complete DANTE source checkout containing config/ and scripts/",
    )
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument(
        "--cache-root", type=Path, default=Path("E:/dante_cache/dante_light")
    )
    parser.add_argument("--workflow-root", type=Path)
    parser.add_argument("--expected-run-key", help="Reject a changed UI launch identity")


def _parser(
    *,
    default_repository_root: Path | None = None,
) -> argparse.ArgumentParser:
    repository_root = (default_repository_root or Path.cwd()).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "plan",
        "preflight",
        "run",
        "resume",
        "adopt-verified",
        "status",
        "verify",
        "report",
    ):
        command = commands.add_parser(name)
        _add_common(command, default_repository_root=repository_root)
        if name in {"run", "resume"}:
            selection = command.add_mutually_exclusive_group()
            selection.add_argument("--through-stage")
            selection.add_argument("--repair-stage")
        elif name == "adopt-verified":
            command.add_argument("--through-stage")
    return parser


def _orchestrator(args: argparse.Namespace) -> WorkflowOrchestrator:
    repository_root = args.repository_root.resolve()
    config = (
        args.config.resolve()
        if args.config is not None
        else repository_root / DEFAULT_CONFIG_RELATIVE
    )
    spec = load_workflow_spec(config, root=repository_root)
    return WorkflowOrchestrator.corrected_o4a(
        spec=spec,
        paths=WorkflowPaths(
            repository_root=repository_root,
            raw_root=args.raw_root,
            cache_root=args.cache_root,
        ),
        workflow_root=args.workflow_root,
    )


def main(
    argv: list[str] | None = None,
    *,
    default_repository_root: Path | None = None,
) -> int:
    """Run the administrative controller against an explicit source checkout."""

    args = _parser(default_repository_root=default_repository_root).parse_args(argv)
    try:
        orchestrator = _orchestrator(args)
        if args.expected_run_key and args.expected_run_key != orchestrator.run_key:
            raise OrchestrationError("requested run key differs from current source or paths")
        if args.command == "plan":
            result = orchestrator.plan()
        elif args.command == "status":
            result = orchestrator.status()
        elif args.command == "verify":
            result = verify_workflow(orchestrator)
        elif args.command == "preflight":
            result = orchestrator.execute(through_stage="PREFLIGHT")
        elif args.command == "adopt-verified":
            result = orchestrator.adopt_verified_existing(
                through_stage=args.through_stage
            )
        elif args.command == "report":
            result = orchestrator.execute(through_stage="REPORT")
            if (
                result["status"] != "WORKFLOW_EXECUTION_STOPPED"
                and orchestrator.ledger.next_incomplete_stage() is None
                and not any(
                    item.get("status") == "FAILED" for item in result["results"]
                )
            ):
                result["derived_report_path"] = str(write_workflow_report(orchestrator))
        else:
            result = orchestrator.execute(
                through_stage=args.through_stage,
                repair_stage=args.repair_stage,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        print(f"{result['status']}: {orchestrator.run_key}", file=sys.stderr)
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
