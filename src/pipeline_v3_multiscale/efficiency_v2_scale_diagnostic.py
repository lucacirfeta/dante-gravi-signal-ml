"""Unconditional paired short-scale diagnostic for efficiency v2.

The production endpoint remains the detector-native 32 s decision.  This
module only summarizes already-computed 0.5/1/2/4 s scores, separately by
detector, morphology, SNR, and scale.  No scale fusion is performed.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import ROOT, _read_jsonl, sha256_file
from src.pipeline_v3_multiscale.efficiency_v2_reference import SCALE_LABELS
from src.pipeline_v3_multiscale.efficiency_v2_runner import (
    load_runner_contract,
    verify_injection_run,
)

SCALE_DIAGNOSTIC_CONTRACT_REL = Path(
    "config/dante_multiscale_efficiency_v2_scale_diagnostic.json"
)
SCHEMA_VERSION = 1
PASS_CI = "PASS_PAIRED_RAW_BLOCK_BOOTSTRAP_CI"
DEGENERATE_EXCEEDANCE = "DEGENERATE_EMPIRICAL_PAIRED_EXCEEDANCE_BOUNDARY"
UNDEFINED_CORRELATIONS = "UNDEFINED_WITHIN_BLOCK_SNR_CORRELATIONS"


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                + "\n"
            )
    temporary.replace(path)


def _assert_file_reference(
    root: Path, reference: Mapping[str, Any], label: str
) -> None:
    path = root / str(reference.get("path", ""))
    if not path.is_file() or sha256_file(path) != str(reference.get("sha256", "")):
        raise ContractError(f"multiscale scale diagnostic {label} mismatch")


def validate_scale_diagnostic_contract(
    payload: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(payload))
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("multiscale scale diagnostic contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported multiscale scale diagnostic schema")
    if value.get("contract_id") != "dante-multiscale-efficiency-v2-scale-diagnostic":
        raise ContractError("multiscale scale diagnostic contract id changed")
    if value.get("status") != "APPROVED_UNCONDITIONAL_PAIRED_SCALE_DIAGNOSTIC_INPUT":
        raise ContractError("multiscale scale diagnostic is not approved")

    root = root.resolve()
    runner = load_runner_contract(root)
    runner_ref = value.get("runner_contract", {})
    if runner_ref.get("contract_digest") != runner["contract_digest"]:
        raise ContractError("multiscale scale diagnostic runner contract changed")
    _assert_file_reference(root, runner_ref, "runner reference")

    frozen = value.get("frozen_input", {})
    compact_path = root / str(frozen.get("compact_summary_path", ""))
    if not compact_path.is_file() or sha256_file(compact_path) != str(
        frozen.get("compact_summary_sha256", "")
    ):
        raise ContractError("multiscale scale diagnostic frozen input mismatch")
    compact = json.loads(compact_path.read_text(encoding="utf-8"))
    if (
        compact.get("run_key") != frozen.get("run_key")
        or compact.get("external_artifact_digest") != frozen.get("artifact_digest")
        or compact.get("trials", {}).get("sha256") != frozen.get("trials_sha256")
        or compact.get("clean_controls", {}).get("sha256")
        != frozen.get("clean_controls_sha256")
    ):
        raise ContractError("multiscale scale diagnostic frozen identity changed")

    population = value.get("population", {})
    if population != {
        "detectors": ["H1", "L1"],
        "roles": {
            "primary_injection": [
                "Blip",
                "NarrowChirp",
                "Whistle",
                "NoiseBlob",
            ],
            "secondary_dsd_control": ["WallOfLines"],
        },
        "target_snr": [8, 12, 16, 24, 32, 48],
        "scales_s": [0.5, 1.0, 2.0, 4.0],
        "uses_all_frozen_blocks": True,
    }:
        raise ContractError("approved multiscale scale diagnostic population changed")

    metrics = value.get("metrics", {})
    if (
        metrics.get("score_delta") != "injected_score_minus_paired_clean_score"
        or metrics.get("injected_margin") != "injected_score_minus_scale_p99"
        or metrics.get("clean_margin") != "paired_clean_score_minus_scale_p99"
        or metrics.get("paired_exceedance_gain")
        != "injected_exceeds_p99_minus_clean_exceeds_p99"
        or metrics.get("cross_scale_raw_score_comparison_allowed") is not False
        or metrics.get("scale_or_fusion_allowed") is not False
    ):
        raise ContractError("approved multiscale scale diagnostic metrics changed")

    uncertainty = value.get("uncertainty", {})
    if uncertainty != {
        "method": "paired_detector_raw_source_block_bootstrap",
        "unit": "raw_source_block",
        "resamples": 2000,
        "confidence": 0.95,
        "seed": 42,
        "quantile_method": "linear",
        "draw_group": "detector_plus_population_role",
        "shared_draws_across_morphology_snr_scale_and_metric": True,
        "iid_bootstrap_allowed": False,
        "detectors_pooled": False,
        "morphologies_pooled": False,
        "scales_pooled": False,
    }:
        raise ContractError("approved multiscale scale diagnostic bootstrap changed")

    boundary = value.get("scientific_boundary", {})
    if (
        boundary.get("primary_endpoint_changed") is not False
        or boundary.get("scale_fusion_performed") is not False
        or boundary.get("automatic_best_scale_selected") is not False
        or boundary.get("multiple_testing_significance_claim_allowed") is not False
        or boundary.get("O3_transfer_validity_established") is not False
    ):
        raise ContractError("multiscale scale diagnostic scientific boundary changed")
    for label, reference in value.get("references", {}).items():
        _assert_file_reference(root, reference, label)
    return value


def load_scale_diagnostic_contract(root: Path = ROOT) -> dict[str, Any]:
    path = root.resolve() / SCALE_DIAGNOSTIC_CONTRACT_REL
    return validate_scale_diagnostic_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root.resolve()
    )


def _percentile_interval(values: np.ndarray, confidence: float) -> list[float]:
    alpha = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(values, [alpha, 1.0 - alpha], method="linear")
    return [float(lower), float(upper)]


def _mean_statistic(
    values: np.ndarray, draws: np.ndarray, *, confidence: float
) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or values.size == 0 or np.any(~np.isfinite(values)):
        raise ContractError("scale diagnostic continuous statistic is invalid")
    bootstrap = values[draws].mean(axis=1)
    return {
        "mean": float(values.mean()),
        "confidence_interval_95": _percentile_interval(bootstrap, confidence),
        "bootstrap_replicates": int(draws.shape[0]),
        "status": PASS_CI,
    }


def _median_statistic(
    values: np.ndarray, draws: np.ndarray, *, confidence: float
) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or values.size == 0 or np.any(~np.isfinite(values)):
        raise ContractError("scale diagnostic median statistic is invalid")
    bootstrap = np.median(values[draws], axis=1)
    return {
        "median": float(np.median(values)),
        "confidence_interval_95": _percentile_interval(bootstrap, confidence),
        "bootstrap_replicates": int(draws.shape[0]),
        "status": PASS_CI,
    }


def _paired_exceedance_statistic(
    injected: np.ndarray,
    clean: np.ndarray,
    draws: np.ndarray,
    *,
    confidence: float,
) -> dict[str, Any]:
    injected = np.asarray(injected, dtype=bool)
    clean = np.asarray(clean, dtype=bool)
    if injected.shape != clean.shape or injected.ndim != 1 or injected.size == 0:
        raise ContractError("scale diagnostic paired exceedance shape is invalid")
    gain = injected.astype(np.int8) - clean.astype(np.int8)
    base = {
        "n_total": int(gain.size),
        "n_injected_exceeds": int(injected.sum()),
        "n_clean_exceeds": int(clean.sum()),
        "net_gain_count": int(gain.sum()),
        "mean_gain": float(gain.mean()),
    }
    if np.all(gain == gain[0]):
        return {
            **base,
            "confidence_interval_95": None,
            "bootstrap_replicates": 0,
            "status": DEGENERATE_EXCEEDANCE,
        }
    bootstrap = gain[draws].mean(axis=1)
    return {
        **base,
        "confidence_interval_95": _percentile_interval(bootstrap, confidence),
        "bootstrap_replicates": int(draws.shape[0]),
        "status": PASS_CI,
    }


def _ordered_cell(
    cell: Sequence[Mapping[str, Any]],
    blocks: Sequence[str],
) -> list[Mapping[str, Any]]:
    if len(cell) != len(blocks):
        raise ContractError("scale diagnostic cell does not cover every source block")
    block_index = {block: index for index, block in enumerate(blocks)}
    ordered: list[Mapping[str, Any] | None] = [None] * len(blocks)
    for row in cell:
        index = block_index[str(row["raw_source_sha256"])]
        if ordered[index] is not None:
            raise ContractError("scale diagnostic cell repeats a source block")
        ordered[index] = row
    if any(row is None for row in ordered):
        raise ContractError("scale diagnostic cell source block is absent")
    return [row for row in ordered if row is not None]


def _trajectory_statistic(
    values: np.ndarray, draws: np.ndarray, *, confidence: float
) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or values.size == 0:
        raise ContractError("scale diagnostic trajectory statistic is invalid")
    defined = np.isfinite(values)
    defined_count = int(defined.sum())
    undefined_count = int((~defined).sum())
    point = float(np.median(values[defined])) if defined_count else None
    if undefined_count:
        return {
            "median": point,
            "confidence_interval_95": None,
            "bootstrap_replicates": 0,
            "defined_blocks": defined_count,
            "undefined_blocks": undefined_count,
            "status": UNDEFINED_CORRELATIONS,
        }
    result = _median_statistic(values, draws, confidence=confidence)
    return {
        **result,
        "defined_blocks": defined_count,
        "undefined_blocks": 0,
    }


def _spearman(x: Sequence[float], y: Sequence[float]) -> float:
    from scipy.stats import spearmanr

    value = float(spearmanr(x, y).statistic)
    return value


def build_scale_diagnostic_tables(
    rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    population = contract["population"]
    allowed = {
        (role, morphology)
        for role, morphologies in population["roles"].items()
        for morphology in morphologies
    }
    selected = [
        row for row in rows if (str(row["role"]), str(row["morphology"])) in allowed
    ]
    uncertainty = contract["uncertainty"]
    rng = np.random.default_rng(int(uncertainty["seed"]))
    resamples = int(uncertainty["resamples"])
    confidence = float(uncertainty["confidence"])
    cell_rows: list[dict[str, Any]] = []
    trajectory_rows: list[dict[str, Any]] = []

    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in selected:
        grouped[(str(row["detector"]), str(row["role"]))].append(row)
    for (detector, role), group in sorted(grouped.items()):
        blocks = sorted({str(row["raw_source_sha256"]) for row in group})
        draws = rng.integers(0, len(blocks), size=(resamples, len(blocks)))
        cells: dict[tuple[str, float], list[Mapping[str, Any]]] = defaultdict(list)
        for row in group:
            cells[(str(row["morphology"]), float(row["target_snr"]))].append(row)

        ordered_cells: dict[tuple[str, float], list[Mapping[str, Any]]] = {}
        for key, cell in cells.items():
            ordered_cells[key] = _ordered_cell(cell, blocks)

        for (morphology, target_snr), ordered in sorted(ordered_cells.items()):
            for scale in SCALE_LABELS:
                scale_rows = [
                    row["endpoints"]["conditional_multiscale"]["scales"][scale]
                    for row in ordered
                ]
                injected = np.asarray(
                    [float(row["injected_score"]) for row in scale_rows]
                )
                clean = np.asarray([float(row["clean_score"]) for row in scale_rows])
                thresholds = {float(row["threshold"]) for row in scale_rows}
                if len(thresholds) != 1:
                    raise ContractError(
                        "scale diagnostic threshold changes within cell"
                    )
                threshold = thresholds.pop()
                injected_exceeds = np.asarray(
                    [bool(row["diagnostic_exceeds_threshold"]) for row in scale_rows]
                )
                clean_exceeds = np.asarray(
                    [bool(row["clean_exceeds_threshold"]) for row in scale_rows]
                )
                cell_rows.append(
                    {
                        "detector": detector,
                        "role": role,
                        "morphology": morphology,
                        "target_snr": target_snr,
                        "scale_s": float(scale),
                        "raw_source_block_count": len(blocks),
                        "scale_threshold": threshold,
                        "score_delta": _mean_statistic(
                            injected - clean, draws, confidence=confidence
                        ),
                        "injected_margin": _mean_statistic(
                            injected - threshold, draws, confidence=confidence
                        ),
                        "clean_margin": _mean_statistic(
                            clean - threshold, draws, confidence=confidence
                        ),
                        "paired_exceedance_gain": _paired_exceedance_statistic(
                            injected_exceeds,
                            clean_exceeds,
                            draws,
                            confidence=confidence,
                        ),
                    }
                )

        snr_grid = [float(value) for value in population["target_snr"]]
        for morphology in population["roles"][role]:
            for scale in SCALE_LABELS:
                block_correlations = []
                mean_delta_by_snr = []
                for target_snr in snr_grid:
                    ordered = ordered_cells[(morphology, target_snr)]
                    deltas = np.asarray(
                        [
                            float(
                                row["endpoints"]["conditional_multiscale"]["scales"][
                                    scale
                                ]["injected_score"]
                            )
                            - float(
                                row["endpoints"]["conditional_multiscale"]["scales"][
                                    scale
                                ]["clean_score"]
                            )
                            for row in ordered
                        ]
                    )
                    mean_delta_by_snr.append(float(deltas.mean()))
                for block_index in range(len(blocks)):
                    block_deltas = []
                    for target_snr in snr_grid:
                        row = ordered_cells[(morphology, target_snr)][block_index]
                        scale_row = row["endpoints"]["conditional_multiscale"][
                            "scales"
                        ][scale]
                        block_deltas.append(
                            float(scale_row["injected_score"])
                            - float(scale_row["clean_score"])
                        )
                    block_correlations.append(_spearman(snr_grid, block_deltas))
                trajectory_rows.append(
                    {
                        "detector": detector,
                        "role": role,
                        "morphology": morphology,
                        "scale_s": float(scale),
                        "raw_source_block_count": len(blocks),
                        "target_snr": snr_grid,
                        "mean_score_delta_by_snr": mean_delta_by_snr,
                        "within_block_spearman": _trajectory_statistic(
                            np.asarray(block_correlations),
                            draws,
                            confidence=confidence,
                        ),
                    }
                )

    expected_cells = int(contract["expected_cardinality"]["scale_cells"])
    expected_trajectories = int(contract["expected_cardinality"]["trajectories"])
    expected_trials = int(contract["expected_cardinality"]["selected_trials"])
    if (
        len(cell_rows) != expected_cells
        or len(trajectory_rows) != expected_trajectories
        or len(selected) != expected_trials
    ):
        raise ContractError("multiscale scale diagnostic cardinality changed")
    overview = {
        "selected_trial_rows": len(selected),
        "scale_cells": len(cell_rows),
        "trajectories": len(trajectory_rows),
        "paired_exceedance_boundary_cells": sum(
            row["paired_exceedance_gain"]["status"] == DEGENERATE_EXCEEDANCE
            for row in cell_rows
        ),
        "scientific_boundary": {
            "primary_endpoint_changed": False,
            "scale_or_fusion_applied": False,
            "automatic_best_scale_selected": False,
            "cross_scale_raw_score_comparison_performed": False,
            "multiple_testing_significance_claimed": False,
            "O3_transfer_validity_established": False,
        },
    }
    return cell_rows, trajectory_rows, overview


def _fmt(value: float) -> str:
    return f"{value:.6g}"


def render_scale_diagnostic_report(payload: Mapping[str, Any]) -> str:
    cells = payload["cells"]
    trajectories = payload["trajectories"]
    lines = [
        "# Multiscale efficiency v2: unconditional paired scale diagnostic",
        "",
        f"Run key: `{payload['run_key']}`",
        "",
        "The 0.5/1/2/4 s scores are non-gating diagnostics. No scale is OR-fused "
        "with the primary 32 s endpoint, no best scale is selected, and raw scores "
        "are not compared across independently calibrated scales.",
        "",
        "## SNR 48 paired response",
        "",
        "Each row reports the paired injected-minus-clean mean score change with "
        "its 95% raw-source-block bootstrap interval, plus injected and clean "
        "threshold exceedance counts under that scale's own frozen p99.",
        "",
        "| Detector | Morphology | Scale (s) | Mean delta [95% CI] | Injected/clean p99 exceeds | Net gain |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in cells:
        if float(row["target_snr"]) != 48.0:
            continue
        delta = row["score_delta"]
        lower, upper = delta["confidence_interval_95"]
        gain = row["paired_exceedance_gain"]
        lines.append(
            "| "
            f"{row['detector']} | {row['morphology']} | {_fmt(row['scale_s'])} | "
            f"{_fmt(delta['mean'])} [{_fmt(lower)}, {_fmt(upper)}] | "
            f"{gain['n_injected_exceeds']}/{gain['n_clean_exceeds']} | "
            f"{gain['net_gain_count']} |"
        )
    lines.extend(
        [
            "",
            "## Within-block SNR response",
            "",
            "The statistic is the median, across frozen raw-source blocks, of the "
            "Spearman correlation between target SNR and paired score delta. "
            "It is evaluated within each scale and is not a cross-scale score comparison.",
            "",
            "| Detector | Morphology | Scale (s) | Median Spearman [95% CI] |",
            "|---|---|---:|---:|",
        ]
    )
    for row in trajectories:
        statistic = row["within_block_spearman"]
        interval = statistic["confidence_interval_95"]
        interval_text = (
            "null"
            if interval is None
            else f"[{_fmt(interval[0])}, {_fmt(interval[1])}]"
        )
        median_text = (
            "null" if statistic["median"] is None else _fmt(statistic["median"])
        )
        lines.append(
            "| "
            f"{row['detector']} | {row['morphology']} | {_fmt(row['scale_s'])} | "
            f"{median_text} {interval_text} |"
        )
    lines.extend(
        [
            "",
            "These are simulation-specific, descriptive diagnostics of the frozen O4a "
            "injections. They do not alter the primary endpoint, correct for selecting "
            "among scales, establish a globally significant detection rule, or validate "
            "transfer to O3.",
            "",
        ]
    )
    return "\n".join(lines)


def _run_key(contract_digest: str, injection_artifact_digest: str) -> str:
    return canonical_json_sha256(
        {
            "stage": "multiscale_efficiency_v2_unconditional_scale_diagnostic",
            "contract_digest": contract_digest,
            "injection_artifact_digest": injection_artifact_digest,
        }
    )


def run_scale_diagnostic(
    *, injection_run_dir: Path, output_root: Path, root: Path = ROOT
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_scale_diagnostic_contract(root)
    injection_summary = verify_injection_run(
        run_dir=injection_run_dir.resolve(), root=root
    )
    if (
        injection_summary["artifact_digest"]
        != contract["frozen_input"]["artifact_digest"]
    ):
        raise ContractError("scale diagnostic injection artifact changed")
    run_key = _run_key(
        contract["contract_digest"], injection_summary["artifact_digest"]
    )
    run_dir = output_root.resolve() / f"scale_diagnostic_{run_key}"
    summary_path = run_dir / "scale_diagnostic_summary.json"
    if summary_path.is_file():
        return verify_scale_diagnostic(
            run_dir=run_dir, injection_run_dir=injection_run_dir, root=root
        ), run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    trials_path = injection_run_dir / injection_summary["trials"]["filename"]
    cells, trajectories, overview = build_scale_diagnostic_tables(
        _read_jsonl(trials_path), contract
    )
    cells_path = run_dir / "scale_cells.jsonl"
    trajectories_path = run_dir / "scale_trajectories.jsonl"
    report_path = run_dir / "scale_diagnostic_report.md"
    _atomic_jsonl(cells_path, cells)
    _atomic_jsonl(trajectories_path, trajectories)
    report_path.write_text(
        render_scale_diagnostic_report(
            {"run_key": run_key, "cells": cells, "trajectories": trajectories}
        ),
        encoding="utf-8",
        newline="\n",
    )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_MULTISCALE_EFFICIENCY_V2_SCALE_DIAGNOSTIC",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "injection_run_key": injection_summary["run_key"],
        "injection_artifact_digest": injection_summary["artifact_digest"],
        "cells": {
            "filename": cells_path.name,
            "row_total": len(cells),
            "sha256": sha256_file(cells_path),
        },
        "trajectories": {
            "filename": trajectories_path.name,
            "row_total": len(trajectories),
            "sha256": sha256_file(trajectories_path),
        },
        "report": {"filename": report_path.name, "sha256": sha256_file(report_path)},
        "overview": overview,
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(summary_path, summary)
    return verify_scale_diagnostic(
        run_dir=run_dir, injection_run_dir=injection_run_dir, root=root
    ), run_dir


def verify_scale_diagnostic(
    *, run_dir: Path, injection_run_dir: Path, root: Path = ROOT
) -> dict[str, Any]:
    root = root.resolve()
    contract = load_scale_diagnostic_contract(root)
    injection_summary = verify_injection_run(
        run_dir=injection_run_dir.resolve(), root=root
    )
    summary_path = run_dir / "scale_diagnostic_summary.json"
    if not summary_path.is_file():
        raise ContractError("multiscale scale diagnostic summary is absent")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("multiscale scale diagnostic artifact digest mismatch")
    expected_run_key = _run_key(
        contract["contract_digest"], injection_summary["artifact_digest"]
    )
    if (
        summary.get("status") != "PASS_MULTISCALE_EFFICIENCY_V2_SCALE_DIAGNOSTIC"
        or summary.get("run_key") != expected_run_key
        or run_dir.name != f"scale_diagnostic_{expected_run_key}"
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("injection_artifact_digest")
        != injection_summary["artifact_digest"]
    ):
        raise ContractError("multiscale scale diagnostic identity changed")
    trials_path = injection_run_dir / injection_summary["trials"]["filename"]
    expected_cells, expected_trajectories, expected_overview = (
        build_scale_diagnostic_tables(_read_jsonl(trials_path), contract)
    )
    cells_path = run_dir / summary["cells"]["filename"]
    trajectories_path = run_dir / summary["trajectories"]["filename"]
    report_path = run_dir / summary["report"]["filename"]
    for path, entry in (
        (cells_path, summary["cells"]),
        (trajectories_path, summary["trajectories"]),
        (report_path, summary["report"]),
    ):
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ContractError(
                f"multiscale scale diagnostic output mismatch: {path.name}"
            )
    if _read_jsonl(cells_path) != expected_cells:
        raise ContractError("multiscale scale diagnostic cell replay mismatch")
    if _read_jsonl(trajectories_path) != expected_trajectories:
        raise ContractError("multiscale scale diagnostic trajectory replay mismatch")
    if summary["overview"] != expected_overview:
        raise ContractError("multiscale scale diagnostic overview replay mismatch")
    expected_report = render_scale_diagnostic_report(
        {
            "run_key": expected_run_key,
            "cells": expected_cells,
            "trajectories": expected_trajectories,
        }
    )
    if report_path.read_text(encoding="utf-8") != expected_report:
        raise ContractError("multiscale scale diagnostic report replay mismatch")
    return summary


__all__ = [
    "DEGENERATE_EXCEEDANCE",
    "PASS_CI",
    "SCALE_DIAGNOSTIC_CONTRACT_REL",
    "build_scale_diagnostic_tables",
    "load_scale_diagnostic_contract",
    "render_scale_diagnostic_report",
    "run_scale_diagnostic",
    "validate_scale_diagnostic_contract",
    "verify_scale_diagnostic",
]
