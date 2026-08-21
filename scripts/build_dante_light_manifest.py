#!/usr/bin/env python3
"""Lock a run-generic DANTE-Light plan, DQ snapshot and shadow manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.manifest import (
    build_shadow_manifest,
    check_shadow_manifest,
    fetch_dq_snapshot,
    load_locked_plan,
    lock_selection_plan,
    write_locked_json,
    write_shadow_manifest,
)


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ContractError(f"JSON object required: {path}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="stage", required=True)
    lock = subparsers.add_parser("lock-plan")
    lock.add_argument("--draft", type=Path, required=True)
    lock.add_argument("--output", type=Path, required=True)
    snapshot = subparsers.add_parser("snapshot-dq")
    snapshot.add_argument("--plan", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    for name in ("build", "check"):
        command = subparsers.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--snapshot", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument(
            "--reference-manifest",
            type=Path,
            default=PROJECT_ROOT / "config" / "reference_artifacts.json",
        )
        command.add_argument("--root", type=Path, default=PROJECT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.stage == "lock-plan":
        payload = lock_selection_plan(_read(args.draft))
        write_locked_json(args.output, payload)
        print(payload["plan_sha256"])
        return 0
    if args.stage == "snapshot-dq":
        payload = fetch_dq_snapshot(load_locked_plan(args.plan))
        write_locked_json(args.output, payload)
        print(payload["snapshot_sha256"])
        return 0
    manifest, entries = build_shadow_manifest(
        plan_path=args.plan,
        snapshot_path=args.snapshot,
        output_path=args.output,
        reference_manifest_path=args.reference_manifest,
        root=args.root,
    )
    if args.stage == "check":
        check_shadow_manifest(args.output, manifest, entries)
        print(f"PASS {manifest['manifest_sha256']}")
    else:
        write_shadow_manifest(args.output, manifest, entries)
        print(json.dumps(manifest["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
