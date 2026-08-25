#!/usr/bin/env python3
"""Fail-closed verifier for DANTE-Light v5 student training artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256  # noqa: E402
from src.dante_light.prefilter_v5_protocol import sha256_path  # noqa: E402
from src.dante_light.prefilter_v5_training import (  # noqa: E402
    ARMS,
    DEFAULT_OUTPUT,
    training_run_key,
)
from src.dante_light.prefilter_v5_training_contract import (  # noqa: E402
    DEFAULT_CONTRACT,
    load_training_freeze,
)
from src.dante_light.prefilter_v5_teacher import default_cache_root  # noqa: E402


def _reference(value: dict, label: str) -> None:
    text = str(value["path"])
    path = (ROOT / text).resolve()
    if (
        set(value) != {"path", "sha256"}
        or Path(text).is_absolute()
        or "\\" in text
        or not path.is_relative_to(ROOT.resolve())
        or not path.is_file()
    ):
        raise ContractError(f"v5 training code reference is malformed: {label}")
    candidates = {sha256_path(path)}
    try:
        candidates.add(
            hashlib.sha256(
                subprocess.check_output(
                    ["git", "show", f"HEAD:{text}"],
                    cwd=ROOT,
                    stderr=subprocess.DEVNULL,
                )
            ).hexdigest()
        )
    except (OSError, subprocess.SubprocessError):
        pass
    if value["sha256"] not in candidates:
        raise ContractError(f"v5 training code reference hash mismatch: {label}")


def verify(
    *,
    artifact: Path,
    cache_root: Path | None = None,
    allow_smoke: bool = False,
) -> dict:
    summary = json.loads(artifact.read_text(encoding="utf-8"))
    payload = dict(summary)
    declared = payload.pop("artifact_digest", None)
    if declared != canonical_json_sha256(payload):
        raise ContractError("v5 training summary self-digest mismatch")
    payload["artifact_digest"] = declared
    contract = load_training_freeze(DEFAULT_CONTRACT, root=ROOT)
    if payload["training_contract_digest"] != contract["training_contract_digest"]:
        raise ContractError("v5 training summary contract mismatch")
    for label, reference in payload["code_references"].items():
        _reference(reference, label)
    expected_key = training_run_key(
        contract,
        code_references=payload["code_references"],
        environment=payload["environment"],
        smoke=bool(payload["smoke"]),
        smoke_batches=payload["smoke_batches"],
    )
    if payload["run_key"] != expected_key:
        raise ContractError("v5 training run key mismatch")
    if any(
        payload[field]
        for field in (
            "development_rows_accessed",
            "confirmation_rows_accessed",
            "o4b_rows_accessed",
        )
    ):
        raise ContractError("v5 training accessed a protected partition")
    if payload["candidate_promotion_allowed"] or not payload["student_outputs_are_training_only"]:
        raise ContractError("v5 training silently promoted a training-only model")
    if payload["smoke"] and not allow_smoke:
        raise ContractError("v5 training verifier refuses a smoke artifact")
    run_dir = (cache_root or default_cache_root()) / f"student_{expected_key}"
    expected_lr = float(contract["design"]["optimization"]["optimizer"]["learning_rate"])
    expected_epochs = 1 if payload["smoke"] else int(
        contract["design"]["optimization"]["maximum_epochs"]
    )
    seen = set()
    for replicate in payload["replicate_summaries"]:
        body = dict(replicate)
        digest = body.pop("replicate_digest", None)
        if digest != canonical_json_sha256(body):
            raise ContractError("v5 training replicate self-digest mismatch")
        key = (replicate["arm"], int(replicate["replicate_index"]))
        if key in seen or replicate["arm"] not in ARMS:
            raise ContractError("v5 training replicate identity is invalid or duplicated")
        seen.add(key)
        if replicate["status"] == "FAILED_NUMERICAL":
            if replicate["candidate_promotion_allowed"]:
                raise ContractError("v5 failed replicate permits promotion")
            continue
        if int(replicate["completed_epochs"]) != expected_epochs:
            raise ContractError("v5 training replicate epoch count mismatch")
        model_path = run_dir / replicate["best_model"]["path"]
        metrics_path = run_dir / replicate["metrics"]["path"]
        if (
            sha256_path(model_path) != replicate["best_model"]["sha256"]
            or sha256_path(metrics_path) != replicate["metrics"]["sha256"]
        ):
            raise ContractError("v5 training model or metric hash mismatch")
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))["epochs"]
        if len(metrics) != expected_epochs or any(
            not math.isfinite(float(row["validation_smooth_l1_equal_detector_mean"]))
            or float(row["learning_rate"]) != expected_lr
            for row in metrics
        ):
            raise ContractError("v5 training metrics are incomplete or non-finite")
        minimum = min(
            float(row["validation_smooth_l1_equal_detector_mean"]) for row in metrics
        )
        earliest = next(
            int(row["epoch"])
            for row in metrics
            if float(row["validation_smooth_l1_equal_detector_mean"]) == minimum
        )
        if (
            float(replicate["best_validation_loss"]) != minimum
            or int(replicate["best_epoch"]) != earliest
        ):
            raise ContractError("v5 training checkpoint selection changed")
    if not payload["smoke"]:
        expected = {(arm, index) for arm in ARMS for index in range(5)}
        if seen != expected or not payload["full_request"]:
            raise ContractError("v5 full training does not contain all ten replicates")
    return {
        "status": "PASS_SMOKE_ONLY" if payload["smoke"] else "PASS_TRAINING_COMPLETE",
        "run_key": expected_key,
        "replicate_count": len(seen),
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--allow-smoke", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            verify(
                artifact=args.artifact,
                cache_root=args.cache_root,
                allow_smoke=args.allow_smoke,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
