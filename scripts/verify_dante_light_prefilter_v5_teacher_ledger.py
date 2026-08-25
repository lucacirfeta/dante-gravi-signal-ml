#!/usr/bin/env python3
"""Fail-closed verifier for the DANTE-Light v5 teacher ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_teacher import (  # noqa: E402
    ExactNativeTeacher,
    load_training_rows,
    prepare_teacher_input,
    default_cache_root,
    load_teacher_contract,
    verify_teacher_ledger_summary,
)
from src.dante_light.contracts import RepresentationContract, WindowIdentity  # noqa: E402


DEFAULT_ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_training/teacher_ledger_summary_v5.json"
)


def verify(
    *,
    artifact: Path = DEFAULT_ARTIFACT,
    cache_root: Path | None = None,
    require_complete: bool = True,
    replay_samples: bool = False,
    device: str | None = None,
) -> dict:
    summary = json.loads(artifact.read_text(encoding="utf-8"))
    selected_cache_root = cache_root or default_cache_root()
    contract = load_teacher_contract(root=ROOT)
    result = verify_teacher_ledger_summary(
        summary,
        root=ROOT,
        contract=contract,
        cache_root=selected_cache_root,
        require_complete=require_complete,
    )
    if replay_samples:
        run_dir = selected_cache_root / summary["cache_location"]["run_subdirectory"]
        recorded = {}
        for reference in summary["block_references"]:
            block = json.loads((run_dir / reference["path"]).read_text(encoding="utf-8"))
            for row in block["rows"]:
                window_id = row["window"]["window_id"]
                if window_id in contract["replay_sample_window_ids"]:
                    recorded[window_id] = row
        if set(recorded) != set(contract["replay_sample_window_ids"]):
            raise RuntimeError("v5 teacher replay samples are absent from the ledger")
        _header, rows = load_training_rows(root=ROOT)
        by_id = {row["window"]["window_id"]: row for row in rows}
        representation = RepresentationContract(**{
            key: value for key, value in contract["representation"].items()
            if key != "contract_sha256"
        })
        prepared = [
            prepare_teacher_input(
                WindowIdentity.from_dict(by_id[window_id]["window"]),
                representation=representation,
                local_only=True,
            )
            for window_id in contract["replay_sample_window_ids"]
        ]
        teacher = ExactNativeTeacher(
            root=ROOT, representation=representation, device=device
        )
        scores, _timings = teacher.score([item.image for item in prepared])
        replay = []
        for window_id, item, score in zip(
            contract["replay_sample_window_ids"], prepared, scores, strict=True
        ):
            expected = recorded[window_id]
            observed_hex = np.float32(score).tobytes().hex()
            if (
                item.raw_strain_sha256 != expected["raw_strain_sha256"]
                or item.clean_strain_sha256 != expected["clean_strain_sha256"]
                or item.image_sha256 != expected["image_sha256"]
                or observed_hex != expected["teacher_target"]["float32_hex"]
            ):
                raise RuntimeError(f"v5 teacher replay mismatch: {window_id}")
            replay.append(
                {
                    "window_id": window_id,
                    "detector": expected["window"]["detector"],
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
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--allow-smoke", action="store_true")
    parser.add_argument("--replay-samples", action="store_true")
    parser.add_argument("--device", default=None)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(
                artifact=args.artifact,
                cache_root=args.cache_root,
                require_complete=not args.allow_smoke,
                replay_samples=args.replay_samples,
                device=args.device,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
