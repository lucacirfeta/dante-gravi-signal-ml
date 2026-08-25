#!/usr/bin/env python3
"""Fail-closed verification for the DANTE-Light v6 pre-Phase-B audit."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_pre_phase_b import (
    audit_remaining_capacity,
    file_sha256,
    load_audit_contract,
    load_jsonl,
    v5_training_spacing,
)


DEFAULT_CONFIG = ROOT / "config/dante_light_prefilter_v6_pre_phase_b_audit.json"
DEFAULT_ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v6_design"
    / "pre_phase_b_audit_v6.json"
)


def _quantiles(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        name: float(value)
        for name, value in zip(
            ("minimum", "p25", "median", "p75", "maximum"),
            np.quantile(array, (0.0, 0.25, 0.5, 0.75, 1.0)),
            strict=True,
        )
    }


def _same_numbers(first: object, second: object, *, path: str = "root") -> None:
    if isinstance(first, dict) and isinstance(second, dict):
        if set(first) != set(second):
            raise ContractError(f"audit key mismatch at {path}")
        for key in first:
            _same_numbers(first[key], second[key], path=f"{path}.{key}")
        return
    if isinstance(first, list) and isinstance(second, list):
        if len(first) != len(second):
            raise ContractError(f"audit length mismatch at {path}")
        for index, (left, right) in enumerate(zip(first, second, strict=True)):
            _same_numbers(left, right, path=f"{path}[{index}]")
        return
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        if not math.isclose(float(first), float(second), rel_tol=0.0, abs_tol=1e-12):
            raise ContractError(f"audit numeric mismatch at {path}")
        return
    if first != second:
        raise ContractError(f"audit value mismatch at {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--deep", action="store_true")
    parser.add_argument(
        "--training-cache-root",
        type=Path,
        default=Path(r"E:\dante_cache\dante_light\prefilter_l4_v5_training"),
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    artifact_path = args.artifact.resolve()
    contract = load_audit_contract(config_path, root=ROOT)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 pre-Phase-B artifact digest mismatch")
    if payload.get("status") != "PRE_PHASE_B_DIAGNOSTIC_COMPLETE_AWAITING_DECISION":
        raise ContractError("v6 pre-Phase-B audit is incomplete")
    if payload.get("contract_digest") != contract["contract_digest"]:
        raise ContractError("v6 pre-Phase-B artifact uses the wrong contract")
    if payload.get("scientific_boundary") != contract["scientific_boundary"]:
        raise ContractError("v6 pre-Phase-B boundary mismatch")
    if any(payload["outcome_access"].get(key) != [] for key in (
        "teacher_targets", "morphology_labels", "development", "confirmation", "o4b"
    )):
        raise ContractError("v6 pre-Phase-B artifact records forbidden outcome access")
    if any(payload["decision"].get(key) is not False for key in (
        "phase_b_frozen", "lambda_frozen", "partial_blocks_admitted",
        "population_changed", "training_authorized"
    )):
        raise ContractError("v6 pre-Phase-B artifact makes a forbidden decision")

    references = contract["source_references"]
    raw_rows = load_jsonl(ROOT / references["raw_manifest"]["path"])
    identity = json.loads(
        (ROOT / references["v5_identity_audit"]["path"]).read_text(encoding="utf-8")
    )
    split_rows = load_jsonl(ROOT / references["v5_split_entries"]["path"])
    flags = json.loads(
        (ROOT / references["gwosc_segment_snapshot"]["path"]).read_text(encoding="utf-8")
    )
    expected_capacity = audit_remaining_capacity(
        raw_rows=raw_rows,
        identity_audit=identity,
        v5_split_rows=split_rows,
        flags=flags["flags"],
        specification=contract["capacity_audit"],
        contract_digest=contract["contract_digest"],
    )
    _same_numbers(payload["capacity"], expected_capacity, path="capacity")
    _same_numbers(
        payload["v5_training_spacing_reference"],
        v5_training_spacing(split_rows),
        path="v5_spacing",
    )

    gradient = payload["gradient_scale"]
    if gradient["input"].get("teacher_targets_read") is not False:
        raise ContractError("gradient diagnostic read teacher targets")
    if gradient["loss_contract"].get("lambda_selected") is not False:
        raise ContractError("gradient diagnostic selected lambda")
    if gradient["interpretation_boundary"].get("lambda_one_automatically_approved") is not False:
        raise ContractError("gradient diagnostic automatically approved lambda=1")
    replicates = gradient["replicates"]
    if len(replicates) != int(contract["gradient_diagnostic"]["replicates"]):
        raise ContractError("gradient replicate count mismatch")
    if len(gradient["input"]["selected_blocks"]) != 2 * int(
        contract["gradient_diagnostic"]["blocks_per_detector"]
    ):
        raise ContractError("gradient input block count mismatch")
    for replicate in replicates:
        for space in ("prediction_gradient_l2", "parameter_gradient_l2"):
            values = replicate[space]
            for key in ("value", "rank", "value_to_rank_ratio"):
                if not math.isfinite(float(values[key])) or float(values[key]) <= 0:
                    raise ContractError("invalid gradient diagnostic norm")
            if not math.isclose(
                float(values["value_to_rank_ratio"]),
                float(values["value"]) / float(values["rank"]),
                rel_tol=1e-12,
                abs_tol=0.0,
            ):
                raise ContractError("gradient ratio arithmetic mismatch")
    expected_prediction = _quantiles(
        [row["prediction_gradient_l2"]["value_to_rank_ratio"] for row in replicates]
    )
    expected_parameter = _quantiles(
        [row["parameter_gradient_l2"]["value_to_rank_ratio"] for row in replicates]
    )
    _same_numbers(
        gradient["summary"]["prediction_value_to_rank_gradient_ratio"],
        expected_prediction,
        path="prediction_gradient_summary",
    )
    _same_numbers(
        gradient["summary"]["parameter_value_to_rank_gradient_ratio"],
        expected_parameter,
        path="parameter_gradient_summary",
    )

    for name, reference in payload["source_references"].items():
        relative = Path(reference["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError(f"non-portable audit source reference: {name}")
        source = ROOT / relative
        if not source.is_file() or file_sha256(source) != reference["sha256"]:
            raise ContractError(f"v6 pre-Phase-B artifact source mismatch: {name}")

    if args.deep:
        with tempfile.TemporaryDirectory(prefix="dante-v6-pre-b-") as directory:
            regenerated_path = Path(directory) / "audit.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_dante_light_prefilter_v6_pre_phase_b_audit.py"),
                    "--config",
                    str(config_path),
                    "--output",
                    str(regenerated_path),
                    "--training-cache-root",
                    str(args.training_cache_root.resolve()),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                raise ContractError(f"deep audit recomputation failed: {completed.stderr}")
            regenerated = json.loads(regenerated_path.read_text(encoding="utf-8"))
            _same_numbers(payload["capacity"], regenerated["capacity"], path="deep.capacity")
            _same_numbers(
                payload["v5_training_spacing_reference"],
                regenerated["v5_training_spacing_reference"],
                path="deep.v5_spacing",
            )
            _same_numbers(
                payload["gradient_scale"],
                regenerated["gradient_scale"],
                path="deep.gradient_scale",
            )

    print(
        json.dumps(
            {
                "status": "PASS",
                "artifact": artifact_path.relative_to(ROOT).as_posix(),
                "artifact_digest": declared,
                "deep": bool(args.deep),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
