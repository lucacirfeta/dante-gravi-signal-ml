"""Freeze, preflight, run or verify O3a physical coincidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_coincidence import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    archive_infrastructure_failure,
    freeze_contract,
    load_contract,
    preflight_sources,
    run_native_coincidence,
    verify_native_coincidence,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--freeze", action="store_true")
    action.add_argument("--check", action="store_true")
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--run", action="store_true")
    action.add_argument("--verify", action="store_true")
    action.add_argument("--archive-infrastructure-failure", action="store_true")
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    args = parser.parse_args()
    if args.freeze or args.check:
        value = freeze_contract(root=ROOT) if args.freeze else load_contract(root=ROOT)
        print(
            json.dumps(
                {
                    "status": value["status"],
                    "contract_digest": value["contract_digest"],
                    "measurement": value["measurement"]["algorithm"],
                    "outcomes_opened": False,
                },
                sort_keys=True,
            )
        )
        return
    if args.preflight:
        value, directory = preflight_sources(root=ROOT, external_root=args.external_root)
        print(json.dumps({
            "status": value["status"],
            "preflight_digest": value["preflight_digest"],
            "source_audit": value["source_audit"],
            "run_root": str(directory),
        }, sort_keys=True))
        return
    if args.archive_infrastructure_failure:
        archive = archive_infrastructure_failure(root=ROOT, external_root=args.external_root)
        print(json.dumps({"status": "ARCHIVED_VERIFIED_INFRASTRUCTURE_FAILURE",
                          "archive": str(archive)}, sort_keys=True))
        return
    summary, directory = (
        run_native_coincidence(root=ROOT, external_root=args.external_root)
        if args.run else verify_native_coincidence(root=ROOT, external_root=args.external_root)
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "artifact_digest": summary["artifact_digest"],
                "run_dir": str(directory),
                "replay_verified": args.verify,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
