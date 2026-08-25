#!/usr/bin/env python3
"""Fail-closed verifier for the v6 Phase-B screening output."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_protocol import sha256_path
from src.dante_light.prefilter_v6_phase_b import load_phase_b_contract, select_phase_b_arm
from src.dante_light.prefilter_v6_training import training_run_key
from src.dante_light.prefilter_v6_training_contract import load_training_freeze


DEFAULT_ARTIFACT = ROOT / "artifacts/dante_light/prefilter_l4_v6_training/phase_b_screening_summary_v6.json"
DEFAULT_CACHE = Path(
    os.environ.get(
        "DANTE_V6_TRAINING_CACHE_ROOT",
        r"E:\dante_cache\dante_light\prefilter_l4_v6_training",
    )
)


def verify(*, artifact: Path, cache_root: Path, require_complete: bool = True) -> dict:
    summary = json.loads(artifact.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 Phase-B summary digest mismatch")
    contract = load_training_freeze(root=ROOT)
    if summary.get("training_contract_digest") != contract["training_contract_digest"]:
        raise ContractError("v6 Phase-B summary training contract mismatch")
    for field in (
        "phase_c_rows_accessed",
        "phase_d_rows_accessed",
        "o4b_rows_accessed",
        "morphology_labels_accessed",
    ):
        if summary.get(field) != []:
            raise ContractError(f"v6 Phase-B summary crossed protected boundary: {field}")
    for name, reference in summary.get("code_references", {}).items():
        source = ROOT / reference["path"]
        if not source.is_file() or sha256_path(source) != reference["sha256"]:
            raise ContractError(f"v6 Phase-B code reference mismatch: {name}")
    expected_run_key = training_run_key(
        contract,
        code_references=summary["code_references"],
        environment=summary["environment"],
        smoke=bool(summary["smoke"]),
        smoke_batches=summary["smoke_batches"],
    )
    if summary["run_key"] != expected_run_key:
        raise ContractError("v6 Phase-B run key mismatch")
    run_dir = cache_root / f"student_{expected_run_key}"
    replicate_summaries = list(summary["replicate_summaries"])
    seen = set()
    for replicate in replicate_summaries:
        replicate_body = dict(replicate)
        replicate_digest = replicate_body.pop("replicate_digest", None)
        if replicate_digest != canonical_json_sha256(replicate_body):
            raise ContractError("v6 Phase-B replicate digest mismatch")
        key = (replicate["arm_id"], int(replicate["replicate_index"]))
        if key in seen:
            raise ContractError("v6 Phase-B replicate is duplicated")
        seen.add(key)
        if replicate["run_key"] != expected_run_key:
            raise ContractError("v6 Phase-B replicate run key mismatch")
        for field in (
            "phase_c_rows_accessed",
            "phase_d_rows_accessed",
            "o4b_rows_accessed",
            "morphology_labels_accessed",
        ):
            if replicate.get(field) != []:
                raise ContractError(f"v6 Phase-B replicate crossed protected boundary: {field}")
        if replicate["status"] == "TRAINING_COMPLETE":
            for reference_name in ("best_model", "metrics"):
                reference = replicate[reference_name]
                path = run_dir / reference["path"]
                if not path.is_file() or sha256_path(path) != reference["sha256"]:
                    raise ContractError(f"v6 Phase-B replicate {reference_name} changed")
    if require_complete:
        expected = {
            (arm["id"], replicate)
            for arm in contract["arms"]
            for replicate in range(len(contract["replicate_seeds"]))
        }
        if seen != expected or summary.get("full_request") is not True:
            raise ContractError("v6 Phase-B full matrix is incomplete")
        if summary.get("status") not in {"PHASE_B_SCREENING_COMPLETE", "FAILED_NUMERICAL"}:
            raise ContractError("v6 Phase-B full status is invalid")
        phase_b = load_phase_b_contract(root=ROOT)
        expected_selection = select_phase_b_arm(summary["arm_results"], contract=phase_b)
        if summary.get("selection") != expected_selection:
            raise ContractError("v6 Phase-B frozen selection does not reproduce")
    return {
        "status": "PASS_COMPLETE" if require_complete else "PASS_SMOKE_ONLY",
        "run_key": expected_run_key,
        "replicate_count": len(replicate_summaries),
        "selection": summary.get("selection"),
        "phase_c_rows_accessed": [],
        "phase_d_rows_accessed": [],
        "o4b_rows_accessed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--allow-smoke", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            verify(
                artifact=args.artifact.resolve(),
                cache_root=args.cache_root.resolve(),
                require_complete=not args.allow_smoke,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
