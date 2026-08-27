#!/usr/bin/env python3
"""Run the frozen capacity and gradient-scale diagnostics before v6 Phase B."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import platform
import sys
from typing import Any

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_phase_a import (
    aggregation_contract,
    build_candidate,
    load_phase_a_contract,
)
from src.dante_light.prefilter_v6_pre_phase_b import (
    audit_remaining_capacity,
    file_sha256,
    l2_gradient_norm,
    load_audit_contract,
    load_jsonl,
    ranknet_block_loss,
    smooth_l1_detector_loss,
    v5_training_spacing,
)


DEFAULT_CONFIG = ROOT / "config/dante_light_prefilter_v6_pre_phase_b_audit.json"
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v6_design"
    / "pre_phase_b_audit_v6.json"
)
DEFAULT_TRAINING_CACHE = Path(
    os.environ.get(
        "DANTE_V5_CACHE_ROOT",
        r"E:\dante_cache\dante_light\prefilter_l4_v5_training",
    )
)


def _atomic_json(path: Path, payload: MappingLike) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


MappingLike = dict[str, Any]


def _seed(contract_digest: str, purpose: str, extra: object | None = None) -> int:
    return int(
        canonical_json_sha256(
            {
                "contract_digest": contract_digest,
                "purpose": purpose,
                "extra": extra,
            }
        )[:16],
        16,
    )


def _quantiles(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0 or not np.isfinite(array).all():
        raise ContractError("invalid gradient diagnostic values")
    return {
        name: float(value)
        for name, value in zip(
            ("minimum", "p25", "median", "p75", "maximum"),
            np.quantile(array, (0.0, 0.25, 0.5, 0.75, 1.0)),
            strict=True,
        )
    }


def _select_input_blocks(
    rows: list[dict[str, Any]], *, contract_digest: str, count: int
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for detector in ("H1", "L1"):
        eligible = [row for row in rows if row["detector"] == detector and row["subset"] == "fit"]
        eligible.sort(
            key=lambda row: (
                canonical_json_sha256(
                    {
                        "contract_digest": contract_digest,
                        "purpose": "v6_pre_phase_b_gradient_input",
                        "detector": detector,
                        "block": int(row["block_index"]),
                    }
                ),
                int(row["block_index"]),
            )
        )
        if len(eligible) < count:
            raise ContractError(f"insufficient historical fit blocks for {detector}")
        selected.extend(eligible[:count])
    return selected


def _load_gradient_input(
    *,
    selected: list[dict[str, Any]],
    summary: dict[str, Any],
    v5_split_rows: list[dict[str, Any]],
    training_cache_root: Path,
) -> tuple[torch.Tensor, list[dict[str, Any]]]:
    run_dir = (training_cache_root / summary["cache_location"]["run_subdirectory"]).resolve()
    expected_by_block: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in v5_split_rows:
        if row.get("partition") != "training" or row.get("role") != "background":
            continue
        key = (str(row["detector"]), int(row["stratum"]["block_index"]))
        expected_by_block.setdefault(key, []).append(row)
    for rows in expected_by_block.values():
        rows.sort(key=lambda row: (float(row["window"]["gps_start"]), row["window"]["window_id"]))
    arrays = []
    provenance = []
    for row in selected:
        key = (str(row["detector"]), int(row["block_index"]))
        expected_rows = expected_by_block.get(key, [])
        if len(expected_rows) != 8:
            raise ContractError(f"historical input block identity mismatch: {key}")
        shard_name = f"{key[0]}_{key[1]}_clean_strain.npz"
        shard_path = run_dir / "blocks" / shard_name
        if not shard_path.is_file():
            raise ContractError(f"historical clean-strain shard missing: {shard_name}")
        with np.load(shard_path, allow_pickle=False) as values:
            strain = np.asarray(values["clean_strain"], dtype=np.float32)
            window_ids = tuple(str(value) for value in values["window_ids"].tolist())
        if strain.shape != (8, 131072) or not np.isfinite(strain).all():
            raise ContractError(f"historical clean-strain shape/value mismatch: {shard_name}")
        position = {window_id: index for index, window_id in enumerate(window_ids)}
        expected_ids = tuple(row["window"]["window_id"] for row in expected_rows)
        if set(position) != set(expected_ids):
            raise ContractError(f"historical clean-strain window identity mismatch: {shard_name}")
        arrays.append(np.stack([strain[position[window_id]] for window_id in expected_ids]))
        provenance.append(
            {
                "detector": row["detector"],
                "block_index": int(row["block_index"]),
                "subset": row["subset"],
                "clean_strain_shard": {
                    "path": f"blocks/{shard_name}",
                    "sha256": file_sha256(shard_path),
                    "shape": [8, 131072],
                    "dtype": "float32",
                    "window_ids_digest": canonical_json_sha256(list(expected_ids)),
                },
            }
        )
    stacked = np.stack(arrays).reshape(2, len(arrays) // 2, 8, 131072)
    return torch.from_numpy(stacked[:, :, :, None, :]), provenance


def _gradient_diagnostic(
    *,
    contract: dict[str, Any],
    root: Path,
    training_cache_root: Path,
) -> dict[str, Any]:
    specification = contract["gradient_diagnostic"]
    split_reference = contract["source_references"]["v5_training_internal_split"]
    split_rows = load_jsonl(root / split_reference["path"])
    count = int(specification["blocks_per_detector"])
    selected = _select_input_blocks(
        split_rows, contract_digest=contract["contract_digest"], count=count
    )
    summary_reference = contract["source_references"]["v5_teacher_ledger_summary"]
    summary = json.loads((root / summary_reference["path"]).read_text(encoding="utf-8"))
    v5_split_reference = contract["source_references"]["v5_split_entries"]
    v5_split_rows = load_jsonl(root / v5_split_reference["path"])
    inputs, provenance = _load_gradient_input(
        selected=selected,
        summary=summary,
        v5_split_rows=v5_split_rows,
        training_cache_root=training_cache_root.resolve(),
    )

    phase_a_reference = contract["source_references"]["phase_a_contract"]
    phase_a = load_phase_a_contract(root / phase_a_reference["path"], root=root)
    teacher_reference = phase_a["parent_references"]["teacher_contract"]
    teacher = json.loads((root / teacher_reference["path"]).read_text(encoding="utf-8"))
    aggregation = aggregation_contract(phase_a, teacher)
    candidate = next(
        row
        for row in phase_a["candidate_matrix"]
        if row["id"] == specification["architecture_id"]
    )

    target_generator = torch.Generator(device="cpu")
    target_seed = _seed(contract["contract_digest"], "synthetic_standardized_targets")
    target_generator.manual_seed(target_seed)
    targets = torch.randn(2, count, 8, generator=target_generator, dtype=torch.float32)
    for detector in range(2):
        values = targets[detector]
        targets[detector] = (values - values.mean()) / values.std(unbiased=False)

    flat_inputs = inputs.reshape(2 * count * 8, 1, 131072)
    replicates = []
    for replicate in range(int(specification["replicates"])):
        model_seed = _seed(contract["contract_digest"], "gradient_model_init", replicate)
        torch.manual_seed(model_seed)
        model = build_candidate(candidate, aggregation).to(dtype=torch.float32).eval()
        predictions_flat = model(flat_inputs).squeeze(-1)
        predictions = predictions_flat.reshape(2, count, 8)
        if not torch.isfinite(predictions).all():
            raise ContractError("non-finite initialization prediction")
        value_loss = smooth_l1_detector_loss(
            predictions,
            targets,
            beta=float(specification["value_loss"]["beta"]),
        )
        rank_loss = ranknet_block_loss(predictions, targets)
        prediction_norms = []
        parameter_norms = []
        for loss in (value_loss, rank_loss):
            prediction_gradient = torch.autograd.grad(
                loss, predictions_flat, retain_graph=True
            )[0]
            prediction_norms.append(float(torch.linalg.vector_norm(prediction_gradient).item()))
            model.zero_grad(set_to_none=True)
            loss.backward(retain_graph=True)
            parameter_norms.append(l2_gradient_norm(model.parameters()))
        if min(*prediction_norms, *parameter_norms) <= 0 or not all(
            math.isfinite(value) for value in (*prediction_norms, *parameter_norms)
        ):
            raise ContractError("invalid initialization gradient norm")
        replicates.append(
            {
                "replicate": replicate,
                "model_seed": model_seed,
                "value_loss": float(value_loss.detach().item()),
                "rank_loss": float(rank_loss.detach().item()),
                "initial_prediction_std": float(predictions.detach().std(unbiased=False).item()),
                "prediction_gradient_l2": {
                    "value": prediction_norms[0],
                    "rank": prediction_norms[1],
                    "value_to_rank_ratio": prediction_norms[0] / prediction_norms[1],
                },
                "parameter_gradient_l2": {
                    "value": parameter_norms[0],
                    "rank": parameter_norms[1],
                    "value_to_rank_ratio": parameter_norms[0] / parameter_norms[1],
                },
            }
        )
    return {
        "architecture_id": candidate["id"],
        "input": {
            "source": specification["input_source"],
            "teacher_targets_read": False,
            "synthetic_target_seed": target_seed,
            "selected_blocks": provenance,
            "shape": list(inputs.shape),
        },
        "loss_contract": {
            "value": specification["value_loss"],
            "rank": specification["rank_loss"],
            "lambda_evaluated": specification["lambda_value_evaluated"],
            "lambda_selected": False,
        },
        "replicates": replicates,
        "summary": {
            "prediction_value_to_rank_gradient_ratio": _quantiles(
                [row["prediction_gradient_l2"]["value_to_rank_ratio"] for row in replicates]
            ),
            "parameter_value_to_rank_gradient_ratio": _quantiles(
                [row["parameter_gradient_l2"]["value_to_rank_ratio"] for row in replicates]
            ),
            "initial_prediction_std": _quantiles(
                [row["initial_prediction_std"] for row in replicates]
            ),
        },
        "interpretation_boundary": {
            "lambda_one_automatically_approved": False,
            "lambda_selection_authorized": False,
            "training_fidelity_established": False,
            "uses_realistic_already_open_inputs_but_synthetic_targets": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--training-cache-root", type=Path, default=DEFAULT_TRAINING_CACHE)
    args = parser.parse_args()

    config_path = args.config.resolve()
    contract = load_audit_contract(config_path, root=ROOT)
    references = contract["source_references"]
    raw_rows = load_jsonl(ROOT / references["raw_manifest"]["path"])
    identity_audit = json.loads(
        (ROOT / references["v5_identity_audit"]["path"]).read_text(encoding="utf-8")
    )
    split_rows = load_jsonl(ROOT / references["v5_split_entries"]["path"])
    flags_snapshot = json.loads(
        (ROOT / references["gwosc_segment_snapshot"]["path"]).read_text(encoding="utf-8")
    )
    capacity = audit_remaining_capacity(
        raw_rows=raw_rows,
        identity_audit=identity_audit,
        v5_split_rows=split_rows,
        flags=flags_snapshot["flags"],
        specification=contract["capacity_audit"],
        contract_digest=contract["contract_digest"],
    )
    spacing = v5_training_spacing(split_rows)
    gradient = _gradient_diagnostic(
        contract=contract,
        root=ROOT,
        training_cache_root=args.training_cache_root,
    )
    source_references = {
        "config": {
            "path": config_path.relative_to(ROOT).as_posix(),
            "sha256": file_sha256(config_path),
        },
        "implementation": {
            "path": "src/dante_light/prefilter_v6_pre_phase_b.py",
            "sha256": file_sha256(ROOT / "src/dante_light/prefilter_v6_pre_phase_b.py"),
        },
        "runner": {
            "path": "scripts/run_dante_light_prefilter_v6_pre_phase_b_audit.py",
            "sha256": file_sha256(Path(__file__).resolve()),
        },
        **references,
    }
    body: dict[str, Any] = {
        "schema_version": 1,
        "status": "PRE_PHASE_B_DIAGNOSTIC_COMPLETE_AWAITING_DECISION",
        "audit_id": contract["audit_id"],
        "contract_digest": contract["contract_digest"],
        "scientific_boundary": contract["scientific_boundary"],
        "outcome_access": {
            "teacher_targets": [],
            "morphology_labels": [],
            "development": [],
            "confirmation": [],
            "o4b": [],
        },
        "capacity": capacity,
        "v5_training_spacing_reference": spacing,
        "gradient_scale": gradient,
        "decision": {
            "phase_b_frozen": False,
            "lambda_frozen": False,
            "partial_blocks_admitted": False,
            "population_changed": False,
            "training_authorized": False,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "torch": torch.__version__,
            "torch_num_threads": torch.get_num_threads(),
        },
        "source_references": source_references,
    }
    payload = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(args.output.resolve(), payload)
    print(
        json.dumps(
            {
                "status": "PASS",
                "artifact_digest": payload["artifact_digest"],
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
