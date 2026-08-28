#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.review_telemetry_v8_1 import (
    DEFAULT_CONTRACT,
    ReviewTelemetryLedger,
    initialize_telemetry,
    load_contract,
    sufficiency_scenarios,
    verify_contract_provenance,
)


DEFAULT_SOURCE = ROOT / "runs/dante_light/o4b_v2/shared"
DEFAULT_TELEMETRY_ROOT = Path("E:/dante_cache/dante_light/v8_1_review_telemetry")
DEFAULT_EXPORT_ROOT = Path("E:/dante_cache/dante_light/v8_1_review_export")


def _ledger(args: argparse.Namespace) -> ReviewTelemetryLedger:
    return ReviewTelemetryLedger(
        args.telemetry_dir,
        contract=load_contract(args.contract),
    )


def _record_id_or_next(
    ledger: ReviewTelemetryLedger, requested: str | None
) -> str:
    if requested:
        return requested
    pending = ledger.pending()
    if not pending:
        raise SystemExit("no FIFO review item is currently pending")
    return pending[0]["source_record_id"]


def _open_packet(packet: dict[str, object]) -> None:
    uri = Path(str(packet["packet_html"])).resolve().as_uri()
    if not webbrowser.open(uri):
        raise SystemExit(f"could not open review packet; open manually: {uri}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage outcome-blind DANTE-Light v8.1 review telemetry."
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--telemetry-dir", type=Path, default=DEFAULT_TELEMETRY_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create a ledger and enroll exact escalations")
    init.add_argument("--operator-id", required=True, help="private identifier; only SHA256 is stored")
    init.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    init.add_argument(
        "--source-semantics",
        choices=("historical_backlog_enrollment", "poll_observed_enrollment"),
        default="historical_backlog_enrollment",
    )
    init.add_argument("--require-historical-anchor", action="store_true")

    sync = subparsers.add_parser("sync", help="idempotently enroll new exact escalations")
    sync.add_argument("--source-dir", type=Path, required=True)
    sync.add_argument(
        "--source-semantics",
        choices=("historical_backlog_enrollment", "poll_observed_enrollment"),
        required=True,
    )

    next_parser = subparsers.add_parser("next", help="show the next FIFO item without outcomes or scores")
    next_parser.add_argument("--limit", type=int, default=1)

    show = subparsers.add_parser("show", help="build the standardized packet for a review item")
    show.add_argument("--record-id", help="defaults to the next FIFO item")
    show.add_argument("--open", action="store_true", help="open the packet in the default browser")

    start = subparsers.add_parser("start", help="prepare the packet and start measured review")
    start.add_argument("--record-id", help="defaults to the next FIFO item")
    start.add_argument("--open", action="store_true", help="open the packet after the durable STARTED event")

    complete = subparsers.add_parser("complete", help="complete a review after the frozen checklist")
    complete.add_argument("--record-id", required=True)
    complete.add_argument(
        "--confirm-checklist",
        action="store_true",
        help="confirm all six frozen checklist items were inspected",
    )

    export_all = subparsers.add_parser(
        "export-all", help="write one static folder containing every review output"
    )
    export_all.add_argument("--output-dir", type=Path, default=DEFAULT_EXPORT_ROOT)

    subparsers.add_parser("status", help="report descriptive timing only")
    subparsers.add_parser("verify", help="verify contract, manifest, chain and transitions")
    subparsers.add_parser("sufficiency-scenarios", help="show non-gating iid mathematical floors")
    args = parser.parse_args()

    if args.command == "init":
        ledger, enrolled = initialize_telemetry(
            args.telemetry_dir,
            operator_id=args.operator_id,
            source_dir=args.source_dir,
            source_semantics=args.source_semantics,
            contract_path=args.contract,
            require_historical_anchor=args.require_historical_anchor,
        )
        output = {"enrolled": enrolled, "status": ledger.status()}
    elif args.command == "sufficiency-scenarios":
        output = sufficiency_scenarios(load_contract(args.contract))
    else:
        ledger = _ledger(args)
        if args.command == "sync":
            output = {
                "enrolled": ledger.sync_source(
                    args.source_dir, source_semantics=args.source_semantics
                ),
                "status": ledger.status(),
            }
        elif args.command == "next":
            if args.limit < 1:
                parser.error("--limit must be positive")
            output = {"pending": ledger.pending()[: args.limit]}
        elif args.command == "show":
            record_id = _record_id_or_next(ledger, args.record_id)
            output = ledger.build_review_packet(record_id)
            if args.open:
                _open_packet(output)
        elif args.command == "start":
            record_id = _record_id_or_next(ledger, args.record_id)
            packet = ledger.build_review_packet(record_id)
            event = ledger.transition(record_id, "STARTED")
            output = {"event": event, "review_packet": packet}
            if args.open:
                _open_packet(packet)
        elif args.command == "complete":
            if not args.confirm_checklist:
                parser.error("complete requires --confirm-checklist")
            packet = ledger.build_review_packet(args.record_id)
            event = ledger.transition(args.record_id, "COMPLETED")
            output = {"event": event, "review_packet_digest": packet["packet"]["packet_digest"]}
        elif args.command == "export-all":
            output = ledger.export_review_batch(args.output_dir)
        elif args.command == "status":
            output = ledger.status()
        elif args.command == "verify":
            output = {
                "contract_provenance": verify_contract_provenance(
                    load_contract(args.contract), root=ROOT
                ),
                "ledger": ledger.status(),
                "status": "PASS_OUTCOME_BLIND_TELEMETRY_INTEGRITY",
            }
        else:  # pragma: no cover
            raise AssertionError(args.command)
    print(json.dumps(output, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
