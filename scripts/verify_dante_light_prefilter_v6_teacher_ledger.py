#!/usr/bin/env python3
"""Fail-closed verifier for the frozen v6 Phase-B teacher ledger."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import RepresentationContract, WindowIdentity
from src.dante_light.prefilter_v5_teacher import ExactNativeTeacher, prepare_teacher_input
from src.dante_light.prefilter_v6_teacher import (
    load_teacher_contract,
    phase_b_windows,
    verify_teacher_ledger_summary,
)


DEFAULT_ARTIFACT = ROOT / "artifacts/dante_light/prefilter_l4_v6_training/teacher_ledger_summary_v6.json"
DEFAULT_CACHE = Path(
    os.environ.get(
        "DANTE_V6_TRAINING_CACHE_ROOT",
        r"E:\dante_cache\dante_light\prefilter_l4_v6_training",
    )
)


def verify(
    *,
    artifact: Path,
    cache_root: Path,
    require_complete: bool = True,
    replay_samples: bool = False,
    raw_cache_root: Path | None = None,
    device: str | None = None,
) -> dict:
    summary = json.loads(artifact.read_text(encoding="utf-8"))
    result = verify_teacher_ledger_summary(
        summary,
        root=ROOT,
        cache_root=cache_root,
        require_complete=require_complete,
    )
    if replay_samples:
        contract = load_teacher_contract(root=ROOT)
        identities = phase_b_windows(root=ROOT)
        selected = [
            next(row for row in identities if row["detector"] == detector)
            for detector in ("H1", "L1")
        ]
        selected_ids = {row["window"]["window_id"] for row in selected}
        run_dir = cache_root / summary["cache_location"]["run_subdirectory"]
        recorded = {}
        for reference in summary["block_references"]:
            block = json.loads((run_dir / reference["path"]).read_text(encoding="utf-8"))
            for row in block["rows"]:
                if row["window"]["window_id"] in selected_ids:
                    recorded[row["window"]["window_id"]] = row
        if set(recorded) != selected_ids:
            raise RuntimeError("v6 teacher deterministic replay samples are absent")
        raw_summary = json.loads(
            (ROOT / contract["source_references"]["raw_cache_summary"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        selected_raw_root = raw_cache_root or Path(
            os.environ.get(
                "DANTE_V6_RAW_CACHE_ROOT",
                r"E:\dante_cache\dante_light\prefilter_l4_v6_raw",
            )
        )
        raw_run_dir = selected_raw_root / raw_summary["cache_location"]["run_subdirectory"]
        existing = os.environ.get("DANTE_DATA_DIRS", "")
        os.environ["DANTE_DATA_DIRS"] = str(raw_run_dir) + (
            os.pathsep + existing if existing else ""
        )
        representation = RepresentationContract(
            **{
                key: value
                for key, value in contract["representation"].items()
                if key != "contract_sha256"
            }
        )
        prepared = [
            prepare_teacher_input(
                WindowIdentity.from_dict(row["window"]),
                representation=representation,
                local_only=True,
            )
            for row in selected
        ]
        teacher = ExactNativeTeacher(root=ROOT, representation=representation, device=device)
        scores, _timings = teacher.score([item.image for item in prepared])
        replay = []
        for selected_row, item, score in zip(selected, prepared, scores, strict=True):
            window_id = selected_row["window"]["window_id"]
            expected = recorded[window_id]
            observed_hex = np.float32(score).tobytes().hex()
            if (
                item.raw_strain_sha256 != expected["raw_strain_sha256"]
                or item.clean_strain_sha256 != expected["clean_strain_sha256"]
                or item.image_sha256 != expected["image_sha256"]
                or observed_hex != expected["teacher_target"]["float32_hex"]
            ):
                raise RuntimeError(f"v6 teacher exact replay mismatch: {window_id}")
            replay.append(
                {
                    "window_id": window_id,
                    "detector": selected_row["detector"],
                    "score_float32_hex": observed_hex,
                    "image_sha256": item.image_sha256,
                    "status": "EXACT_MATCH",
                }
            )
        result["exact_replay_samples"] = replay
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--allow-smoke", action="store_true")
    parser.add_argument("--replay-samples", action="store_true")
    parser.add_argument("--raw-cache-root", type=Path, default=None)
    parser.add_argument("--device", default=None)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(
                artifact=args.artifact.resolve(),
                cache_root=args.cache_root.resolve(),
                require_complete=not args.allow_smoke,
                replay_samples=args.replay_samples,
                raw_cache_root=(
                    args.raw_cache_root.resolve() if args.raw_cache_root is not None else None
                ),
                device=args.device,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
