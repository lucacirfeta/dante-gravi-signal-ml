#!/usr/bin/env python3
"""Build DANTE-Light escalation follow-up artifacts for an explicit run directory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dante_light.followup import (
    DEFAULT_PRIMARY_INDEX,
    GWTC5_URL,
    build_followup_manifest,
    build_morphology_gallery,
    fetch_and_crossmatch_gwtc5,
    run_physical_followup,
)
from src.dante_light.contracts import ContractError, canonical_json_sha256


def _outputs(directory: Path) -> dict[str, Path]:
    return {
        "manifest": directory / "manifest_v1.json",
        "physical": directory / "physical_v1.json",
        "catalog": directory / "catalog_v1.json",
        "catalog_raw": directory / "gwtc5_events_raw_v1.json",
        "gallery": directory / "gallery_v1.png",
        "gallery_evidence": directory / "gallery_v1.json",
    }


def _record_run(path: Path) -> str:
    runs: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                runs.add(str(json.loads(line)["window"]["run"]))
    if len(runs) != 1:
        raise ContractError(f"records must contain exactly one run: {path}: {sorted(runs)}")
    return runs.pop()


def _bind_manifest_run(payload: dict, *, run: str, path: Path) -> dict:
    body = dict(payload)
    body.pop("manifest_sha256", None)
    body["run"] = run
    enriched = {**body, "manifest_sha256": canonical_json_sha256(body)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(enriched, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return enriched


def run_stage(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    paths = _outputs(output_dir)
    if args.stage == "manifest":
        if args.canonical_records is None or args.shared_records is None:
            raise ValueError("manifest stage requires --canonical-records and --shared-records")
        canonical_run = _record_run(args.canonical_records)
        if _record_run(args.shared_records) != canonical_run:
            raise ContractError("canonical/shared records belong to different runs")
        payload = build_followup_manifest(
            canonical_records=args.canonical_records,
            shared_records=args.shared_records,
            output_path=paths["manifest"],
        )
        return _bind_manifest_run(payload, run=canonical_run, path=paths["manifest"])
    if not paths["manifest"].is_file():
        raise ValueError(f"follow-up manifest does not exist: {paths['manifest']}")
    if args.stage == "physical":
        return run_physical_followup(
            manifest_path=paths["manifest"],
            output_path=paths["physical"],
            primary_index=args.primary_index,
            device=args.device,
            with_iou=not args.no_iou,
        )
    if args.stage == "catalog":
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        if manifest.get("run") != "O4B":
            raise ValueError(
                "current catalog adapter is validated only for O4B/GWTC-5.0; "
                "a later run requires a new catalog contract"
            )
        return fetch_and_crossmatch_gwtc5(
            manifest_path=paths["manifest"],
            output_path=paths["catalog"],
            raw_output_path=paths["catalog_raw"],
            source_url=args.catalog_url,
        )
    if not paths["physical"].is_file():
        raise ValueError(f"physical follow-up does not exist: {paths['physical']}")
    return build_morphology_gallery(
        manifest_path=paths["manifest"],
        physical_path=paths["physical"],
        output_path=paths["gallery"],
        evidence_path=paths["gallery_evidence"],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("manifest", "physical", "catalog", "gallery")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New run-specific follow-up directory; never reuse another run's directory.",
    )
    parser.add_argument("--canonical-records", type=Path)
    parser.add_argument("--shared-records", type=Path)
    parser.add_argument("--primary-index", type=Path, default=DEFAULT_PRIMARY_INDEX)
    parser.add_argument("--catalog-url", default=GWTC5_URL)
    parser.add_argument("--device", default=None)
    parser.add_argument("--no-iou", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_stage(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            result.get("selection", result.get("summary", {"status": result.get("status")})),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
