"""Block-bootstrap analysis for the frozen multiscale-efficiency-v2 run.

The primary endpoint is the detector-native 32 s recovery decision.  Short
scale responses remain conditional diagnostics: they are never OR-fused with
the primary endpoint.  All uncertainty resamples complete raw-source blocks
and reuses the same draws across morphology, SNR, and scale within each
detector and population role.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
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

ANALYSIS_CONTRACT_REL = Path("config/dante_multiscale_efficiency_v2_analysis.json")
SCHEMA_VERSION = 1

NO_PRIMARY = "NO_OBSERVED_PRIMARY_RECOVERY_BOOTSTRAP_BOUNDARY"
ALL_PRIMARY = "ALL_OBSERVED_PRIMARY_RECOVERIES_BOOTSTRAP_BOUNDARY"
NO_ELIGIBLE = "NO_PRIMARY_RECOVERY_CONDITIONAL_UNDEFINED"
NO_CONDITIONAL = "NO_OBSERVED_CONDITIONAL_RESPONSE_BOOTSTRAP_BOUNDARY"
ALL_CONDITIONAL = "ALL_OBSERVED_CONDITIONAL_RESPONSES_BOOTSTRAP_BOUNDARY"
UNDEFINED_REPLICATES = "UNDEFINED_CONDITIONAL_BOOTSTRAP_REPLICATES"
PASS_CI = "PASS_RAW_BLOCK_BOOTSTRAP_CI"


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
        raise ContractError(f"multiscale analysis {label} reference mismatch")


def validate_analysis_contract(
    payload: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(payload))
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("multiscale analysis contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported multiscale analysis schema")
    if value.get("contract_id") != "dante-multiscale-efficiency-v2-analysis":
        raise ContractError("multiscale analysis contract id changed")
    if value.get("status") != "APPROVED_BLOCK_BOOTSTRAP_ANALYSIS_INPUT":
        raise ContractError("multiscale analysis is not approved")

    root = root.resolve()
    runner = load_runner_contract(root)
    runner_ref = value.get("runner_contract", {})
    if runner_ref.get("contract_digest") != runner["contract_digest"]:
        raise ContractError("multiscale analysis runner contract changed")
    _assert_file_reference(root, runner_ref, "runner contract")

    frozen = value.get("frozen_input", {})
    compact_path = root / str(frozen.get("compact_summary_path", ""))
    if not compact_path.is_file() or sha256_file(compact_path) != str(
        frozen.get("compact_summary_sha256", "")
    ):
        raise ContractError("multiscale analysis frozen input mismatch")
    compact = json.loads(compact_path.read_text(encoding="utf-8"))
    if (
        compact.get("run_key") != frozen.get("run_key")
        or compact.get("external_artifact_digest") != frozen.get("artifact_digest")
        or compact.get("trials", {}).get("sha256") != frozen.get("trials_sha256")
    ):
        raise ContractError("multiscale analysis frozen input identity mismatch")

    uncertainty = value.get("uncertainty", {})
    expected_uncertainty = {
        "method": "detector_raw_source_block_bootstrap",
        "unit": "raw_source_block",
        "resamples": 2000,
        "confidence": 0.95,
        "seed": 42,
        "quantile_method": "linear",
        "draw_group": "detector_plus_population_role",
        "shared_draws_across_morphology_snr_scale": True,
        "iid_bootstrap_allowed": False,
        "detectors_pooled": False,
        "morphology_tiers_pooled": False,
    }
    if uncertainty != expected_uncertainty:
        raise ContractError("approved block-bootstrap construction changed")

    boundary = value.get("boundary_policy", {})
    expected_boundary = {
        "zero_primary_successes": {
            "point": "observed_zero",
            "confidence_interval": None,
            "status": NO_PRIMARY,
        },
        "all_primary_successes": {
            "point": "observed_one",
            "confidence_interval": None,
            "status": ALL_PRIMARY,
        },
        "zero_conditional_denominator": {
            "point": None,
            "confidence_interval": None,
            "status": NO_ELIGIBLE,
        },
        "zero_conditional_responses": {
            "point": "observed_zero",
            "confidence_interval": None,
            "status": NO_CONDITIONAL,
        },
        "all_conditional_responses": {
            "point": "observed_one",
            "confidence_interval": None,
            "status": ALL_CONDITIONAL,
        },
        "conditional_replicate_zero_denominator": {
            "confidence_interval": None,
            "status": UNDEFINED_REPLICATES,
            "ci_requires_all_replicates_defined": True,
        },
        "endpoint_values_are_not_true_probability_claims": True,
    }
    if boundary != expected_boundary:
        raise ContractError("approved fail-closed boundary policy changed")

    interpretation = value.get("required_interpretation", {})
    if (
        interpretation.get("report_conditional_endpoint_prevalence") is not True
        or interpretation.get("report_primary_morphology_response") is not True
        or interpretation.get("wall_of_lines_full_snr_range_limitation")
        != "characterized_empirical_limitation"
        or interpretation.get("representation_cause_status")
        != "plausible_hypothesis_not_demonstrated"
        or interpretation.get("scale_fusion_allowed") is not False
        or interpretation.get("rate_upper_limit_allowed") is not False
    ):
        raise ContractError("multiscale analysis interpretation boundary changed")

    for label, reference in value.get("references", {}).items():
        _assert_file_reference(root, reference, label)
    _validate_technical_replay(value, root=root)
    return value


def load_analysis_contract(root: Path = ROOT) -> dict[str, Any]:
    path = root.resolve() / ANALYSIS_CONTRACT_REL
    return validate_analysis_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root.resolve()
    )


def _analysis_run_key(contract_digest: str, injection_artifact_digest: str) -> str:
    return canonical_json_sha256(
        {
            "analysis_contract_digest": contract_digest,
            "injection_artifact_digest": injection_artifact_digest,
        }
    )


def _percentile_interval(values: np.ndarray, confidence: float) -> list[float]:
    alpha = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(values, [alpha, 1.0 - alpha], method="linear")
    return [float(lower), float(upper)]


def _primary_statistic(
    recovered: np.ndarray,
    draws: np.ndarray,
    *,
    confidence: float,
) -> dict[str, Any]:
    recovered = np.asarray(recovered, dtype=bool)
    n = int(recovered.size)
    k = int(recovered.sum())
    if n == 0:
        raise ContractError("primary efficiency cell is empty")
    point = float(k / n)
    if k == 0:
        return {
            "n_total": n,
            "n_recovered": k,
            "point": point,
            "confidence_interval_95": None,
            "bootstrap_defined_replicates": 0,
            "bootstrap_undefined_replicates": 0,
            "status": NO_PRIMARY,
        }
    if k == n:
        return {
            "n_total": n,
            "n_recovered": k,
            "point": point,
            "confidence_interval_95": None,
            "bootstrap_defined_replicates": 0,
            "bootstrap_undefined_replicates": 0,
            "status": ALL_PRIMARY,
        }
    bootstrap = recovered[draws].mean(axis=1)
    return {
        "n_total": n,
        "n_recovered": k,
        "point": point,
        "confidence_interval_95": _percentile_interval(bootstrap, confidence),
        "bootstrap_defined_replicates": int(draws.shape[0]),
        "bootstrap_undefined_replicates": 0,
        "status": PASS_CI,
    }


def _conditional_statistic(
    eligible: np.ndarray,
    response: np.ndarray,
    draws: np.ndarray,
    *,
    confidence: float,
) -> dict[str, Any]:
    eligible = np.asarray(eligible, dtype=bool)
    response = np.asarray(response, dtype=bool)
    if eligible.shape != response.shape or eligible.size == 0:
        raise ContractError("conditional response cell shape is invalid")
    if np.any(response & ~eligible):
        raise ContractError("conditional response exists outside primary eligibility")
    denominator = int(eligible.sum())
    numerator = int(response.sum())
    base = {
        "n_total": int(eligible.size),
        "n_primary_recovered": denominator,
        "n_scale_responses": numerator,
    }
    if denominator == 0:
        return {
            **base,
            "point": None,
            "confidence_interval_95": None,
            "bootstrap_defined_replicates": 0,
            "bootstrap_undefined_replicates": 0,
            "status": NO_ELIGIBLE,
        }
    point = float(numerator / denominator)
    if numerator == 0:
        return {
            **base,
            "point": point,
            "confidence_interval_95": None,
            "bootstrap_defined_replicates": 0,
            "bootstrap_undefined_replicates": 0,
            "status": NO_CONDITIONAL,
        }
    if numerator == denominator:
        return {
            **base,
            "point": point,
            "confidence_interval_95": None,
            "bootstrap_defined_replicates": 0,
            "bootstrap_undefined_replicates": 0,
            "status": ALL_CONDITIONAL,
        }

    bootstrap_denominator = eligible[draws].sum(axis=1)
    bootstrap_numerator = response[draws].sum(axis=1)
    defined = bootstrap_denominator > 0
    defined_count = int(defined.sum())
    undefined_count = int((~defined).sum())
    if undefined_count:
        return {
            **base,
            "point": point,
            "confidence_interval_95": None,
            "bootstrap_defined_replicates": defined_count,
            "bootstrap_undefined_replicates": undefined_count,
            "status": UNDEFINED_REPLICATES,
        }
    bootstrap = bootstrap_numerator / bootstrap_denominator
    return {
        **base,
        "point": point,
        "confidence_interval_95": _percentile_interval(bootstrap, confidence),
        "bootstrap_defined_replicates": defined_count,
        "bootstrap_undefined_replicates": 0,
        "status": PASS_CI,
    }


def _group_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["detector"]), str(row["role"]))].append(row)
    return dict(grouped)


def _validate_technical_replay(
    contract: Mapping[str, Any], *, root: Path
) -> None:
    reference = contract.get("technical_replay", {})
    _assert_file_reference(root, reference, "flat-response SNR replay")
    path = root / str(reference.get("path", ""))
    evidence = json.loads(path.read_text(encoding="utf-8"))
    body = dict(evidence)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("flat-response SNR replay artifact digest mismatch")
    if (
        evidence.get("status") != "PASS_FLAT_RESPONSE_SNR_SCALING_REPLAY"
        or declared != reference.get("artifact_digest")
        or evidence.get("summary") != reference.get("summary")
        or evidence.get("target_snr") != [8, 12, 16, 24, 32, 48]
        or len(evidence.get("rows", [])) != 8
    ):
        raise ContractError("flat-response SNR replay identity changed")
    targets = [8, 12, 16, 24, 32, 48]
    expected_paths = {
        (detector, morphology)
        for detector in ("H1", "L1")
        for morphology in ("Blip", "NoiseBlob", "WallOfLines", "Whistle")
    }
    observed_paths = {
        (str(row.get("detector")), str(row.get("morphology")))
        for row in evidence["rows"]
    }
    if observed_paths != expected_paths:
        raise ContractError("flat-response SNR replay coverage changed")
    for row in evidence["rows"]:
        expected_role = (
            "secondary_dsd_control"
            if row.get("morphology") == "WallOfLines"
            else "primary_injection"
        )
        if (
            row.get("role_index") != 0
            or row.get("role") != expected_role
            or len(row.get("achieved_snr", [])) != len(targets)
            or float(row.get("unit_snr_relative_error", 1.0)) != 0.0
            or float(row.get("maximum_absolute_snr_error", 1.0)) > 1e-12
            or row.get("all_scaled_waveform_hashes_match") is not True
        ):
            raise ContractError("flat-response SNR replay failed closed")
        if any(
            abs(float(achieved) - target) > 1e-12
            for achieved, target in zip(row["achieved_snr"], targets, strict=True)
        ):
            raise ContractError("flat-response SNR target was not reproduced")


def _primary_response_diagnostics(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target_grid = [8.0, 12.0, 16.0, 24.0, 32.0, 48.0]
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    block_groups: dict[
        tuple[str, str, str, str], list[Mapping[str, Any]]
    ] = defaultdict(list)
    maximum_scale_identity_error = 0.0
    for row in rows:
        key = (str(row["detector"]), str(row["role"]), str(row["morphology"]))
        groups[key].append(row)
        block_groups[(*key, str(row["raw_source_sha256"]))].append(row)
        maximum_scale_identity_error = max(
            maximum_scale_identity_error,
            abs(
                float(row["amplitude_scale"]) * float(row["unit_snr"])
                - float(row["target_snr"])
            ),
        )

    all_complete = True
    all_waveforms_unique = True
    all_injected_raw_unique = True
    for block_rows in block_groups.values():
        targets = sorted(float(row["target_snr"]) for row in block_rows)
        all_complete &= targets == target_grid
        all_waveforms_unique &= (
            len({str(row["scaled_waveform_sha256"]) for row in block_rows})
            == len(target_grid)
        )
        all_injected_raw_unique &= (
            len({str(row["injected_raw_context_sha256"]) for row in block_rows})
            == len(target_grid)
        )

    diagnostics: list[dict[str, Any]] = []
    for (detector, role, morphology), group in sorted(groups.items()):
        by_snr: dict[float, list[Mapping[str, Any]]] = defaultdict(list)
        by_block: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in group:
            by_snr[float(row["target_snr"])].append(row)
            by_block[str(row["raw_source_sha256"])].append(row)
        if sorted(by_snr) != target_grid:
            raise ContractError("primary response SNR grid changed")

        correlations: list[float] = []
        for block_rows in by_block.values():
            ordered = sorted(block_rows, key=lambda item: float(item["target_snr"]))
            scores = np.asarray(
                [
                    float(row["endpoints"]["primary"]["injected_score"])
                    for row in ordered
                ],
                dtype=float,
            )
            if float(np.std(scores)) > 0.0:
                correlations.append(
                    float(np.corrcoef(np.asarray(target_grid), scores)[0, 1])
                )

        cells = []
        for target_snr in target_grid:
            cell = by_snr[target_snr]
            thresholds = {
                float(row["endpoints"]["primary"]["threshold"]) for row in cell
            }
            if len(thresholds) != 1:
                raise ContractError("primary threshold changed within diagnostic cell")
            recovered = {
                str(row["identity_digest"])
                for row in cell
                if bool(row["endpoints"]["primary"]["end_to_end_recovered"])
            }
            clean_above = {
                str(row["identity_digest"])
                for row in cell
                if bool(row["endpoints"]["primary"]["clean_exceeds_threshold"])
            }
            injected_scores = np.asarray(
                [float(row["endpoints"]["primary"]["injected_score"]) for row in cell]
            )
            clean_scores = np.asarray(
                [float(row["endpoints"]["primary"]["clean_score"]) for row in cell]
            )
            cells.append(
                {
                    "target_snr": target_snr,
                    "n_total": len(cell),
                    "n_recovered": len(recovered),
                    "n_clean_above_threshold": len(clean_above),
                    "recovered_identities_equal_clean_above_threshold": recovered
                    == clean_above,
                    "threshold": thresholds.pop(),
                    "mean_clean_score": float(clean_scores.mean()),
                    "mean_injected_score": float(injected_scores.mean()),
                    "mean_injected_minus_clean_score": float(
                        (injected_scores - clean_scores).mean()
                    ),
                    "maximum_injected_score": float(injected_scores.max()),
                }
            )
        diagnostics.append(
            {
                "detector": detector,
                "role": role,
                "morphology": morphology,
                "median_within_block_score_snr_correlation": (
                    float(np.median(correlations)) if correlations else None
                ),
                "cells": cells,
            }
        )

    integrity = {
        "maximum_amplitude_scale_times_unit_snr_error": float(
            maximum_scale_identity_error
        ),
        "all_blocks_have_complete_snr_grid": bool(all_complete),
        "all_blocks_have_six_unique_scaled_waveform_hashes": bool(
            all_waveforms_unique
        ),
        "all_blocks_have_six_unique_injected_raw_hashes": bool(
            all_injected_raw_unique
        ),
    }
    if not all(integrity[key] for key in integrity if key.startswith("all_")):
        raise ContractError("primary response injection identity audit failed")
    return diagnostics, integrity


def build_analysis_tables(
    rows: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    uncertainty = contract["uncertainty"]
    resamples = int(uncertainty["resamples"])
    confidence = float(uncertainty["confidence"])
    rng = np.random.default_rng(int(uncertainty["seed"]))
    primary_rows: list[dict[str, Any]] = []
    conditional_rows: list[dict[str, Any]] = []
    wall_rows: list[dict[str, Any]] = []

    for (detector, role), group in sorted(_group_rows(rows).items()):
        blocks = sorted({str(row["raw_source_sha256"]) for row in group})
        block_index = {block: index for index, block in enumerate(blocks)}
        draws = rng.integers(0, len(blocks), size=(resamples, len(blocks)))
        cells: dict[tuple[str, float], list[Mapping[str, Any]]] = defaultdict(list)
        for row in group:
            cells[(str(row["morphology"]), float(row["target_snr"]))].append(row)

        for (morphology, target_snr), cell in sorted(cells.items()):
            if len(cell) != len(blocks):
                raise ContractError(
                    "analysis cell does not cover every raw source block"
                )
            ordered: list[Mapping[str, Any] | None] = [None] * len(blocks)
            for row in cell:
                index = block_index[str(row["raw_source_sha256"])]
                if ordered[index] is not None:
                    raise ContractError("analysis cell repeats a raw source block")
                ordered[index] = row
            if any(row is None for row in ordered):
                raise ContractError("analysis cell raw source block is absent")
            ordered_rows = [row for row in ordered if row is not None]
            recovered = np.asarray(
                [
                    bool(row["endpoints"]["primary"]["end_to_end_recovered"])
                    for row in ordered_rows
                ],
                dtype=bool,
            )
            primary = {
                "detector": detector,
                "role": role,
                "morphology": morphology,
                "target_snr": target_snr,
                **_primary_statistic(recovered, draws, confidence=confidence),
            }
            primary_rows.append(primary)

            for scale in SCALE_LABELS:
                response = np.asarray(
                    [
                        bool(
                            row["endpoints"]["conditional_multiscale"]["scales"][scale][
                                "conditional_scale_response"
                            ]
                        )
                        if recovered[index]
                        else False
                        for index, row in enumerate(ordered_rows)
                    ],
                    dtype=bool,
                )
                conditional_rows.append(
                    {
                        "detector": detector,
                        "role": role,
                        "morphology": morphology,
                        "target_snr": target_snr,
                        "scale_s": float(scale),
                        **_conditional_statistic(
                            recovered, response, draws, confidence=confidence
                        ),
                    }
                )

            if morphology == "WallOfLines":
                primary_scores = [
                    float(row["endpoints"]["primary"]["injected_score"])
                    for row in ordered_rows
                ]
                primary_thresholds = {
                    float(row["endpoints"]["primary"]["threshold"])
                    for row in ordered_rows
                }
                if len(primary_thresholds) != 1:
                    raise ContractError(
                        "WallOfLines primary threshold changed within cell"
                    )
                threshold = primary_thresholds.pop()
                diagnostics = {}
                for scale in SCALE_LABELS:
                    diagnostics[scale] = {
                        "n_exceeds_threshold": sum(
                            bool(
                                row["endpoints"]["conditional_multiscale"]["scales"][
                                    scale
                                ]["diagnostic_exceeds_threshold"]
                            )
                            for row in ordered_rows
                        ),
                        "n_total": len(ordered_rows),
                        "interpretation": "non_gating_unconditional_diagnostic",
                    }
                wall_rows.append(
                    {
                        "detector": detector,
                        "role": role,
                        "morphology": morphology,
                        "target_snr": target_snr,
                        "n_total": len(ordered_rows),
                        "n_primary_recovered": int(recovered.sum()),
                        "max_primary_score": float(max(primary_scores)),
                        "primary_threshold": threshold,
                        "max_score_to_threshold_ratio": float(
                            max(primary_scores) / threshold
                        ),
                        "short_scale_diagnostics": diagnostics,
                    }
                )

    expected_primary = 96
    expected_conditional = expected_primary * len(SCALE_LABELS)
    if (
        len(primary_rows) != expected_primary
        or len(conditional_rows) != expected_conditional
    ):
        raise ContractError("multiscale analysis cell cardinality changed")

    conditional_status = Counter(row["status"] for row in conditional_rows)
    defined = len(conditional_rows) - conditional_status[NO_ELIGIBLE]
    endpoints = conditional_status[NO_CONDITIONAL] + conditional_status[ALL_CONDITIONAL]
    primary_by_role: dict[str, Counter[str]] = defaultdict(Counter)
    for row in primary_rows:
        primary_by_role[str(row["role"])][str(row["status"])] += 1
    conditional_by_scale: dict[str, Counter[str]] = defaultdict(Counter)
    for row in conditional_rows:
        conditional_by_scale[str(row["scale_s"])][str(row["status"])] += 1
    primary_grid = []
    primary_groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(
        list
    )
    for row in primary_rows:
        primary_groups[
            (str(row["detector"]), str(row["role"]), str(row["morphology"]))
        ].append(row)
    for (detector, role, morphology), entries in sorted(primary_groups.items()):
        primary_grid.append(
            {
                "detector": detector,
                "role": role,
                "morphology": morphology,
                "cells": [
                    {
                        "target_snr": float(entry["target_snr"]),
                        "n_recovered": int(entry["n_recovered"]),
                        "n_total": int(entry["n_total"]),
                        "point": float(entry["point"]),
                        "status": str(entry["status"]),
                    }
                    for entry in sorted(entries, key=lambda item: item["target_snr"])
                ],
            }
        )
    response_diagnostics, injection_identity_audit = _primary_response_diagnostics(
        rows
    )
    overview = {
        "primary_cells": len(primary_rows),
        "primary_status_counts": dict(
            sorted(Counter(row["status"] for row in primary_rows).items())
        ),
        "primary_status_counts_by_role": {
            role: dict(sorted(counts.items()))
            for role, counts in sorted(primary_by_role.items())
        },
        "primary_recovery_grid": primary_grid,
        "primary_morphology_response": response_diagnostics,
        "injection_identity_audit": injection_identity_audit,
        "flat_response_snr_replay": dict(contract["technical_replay"]["summary"]),
        "conditional_cells": len(conditional_rows),
        "conditional_status_counts": dict(sorted(conditional_status.items())),
        "conditional_status_counts_by_scale": {
            scale: dict(sorted(counts.items()))
            for scale, counts in sorted(
                conditional_by_scale.items(), key=lambda item: float(item[0])
            )
        },
        "conditional_defined_cells": defined,
        "conditional_observed_zero_cells": conditional_status[NO_CONDITIONAL],
        "conditional_observed_one_cells": conditional_status[ALL_CONDITIONAL],
        "conditional_interior_cells": defined - endpoints,
        "conditional_endpoint_cells": endpoints,
        "conditional_endpoint_fraction_of_defined": float(endpoints / defined),
        "wall_of_lines_full_snr_range": sorted(
            wall_rows, key=lambda row: (row["target_snr"], row["detector"])
        ),
    }
    return primary_rows, conditional_rows, overview


def render_report(summary: Mapping[str, Any]) -> str:
    overview = summary["overview"]
    endpoints = int(overview["conditional_endpoint_cells"])
    defined = int(overview["conditional_defined_cells"])
    percent = 100.0 * float(overview["conditional_endpoint_fraction_of_defined"])
    response_lookup = {
        (row["detector"], row["role"], row["morphology"]): row
        for row in overview["primary_morphology_response"]
    }

    def _counts(detector: str, role: str, morphology: str) -> str:
        row = response_lookup[(detector, role, morphology)]
        return ", ".join(
            f"{cell['n_recovered']}/{cell['n_total']}" for cell in row["cells"]
        )

    def _snr48(detector: str, role: str, morphology: str) -> Mapping[str, Any]:
        row = response_lookup[(detector, role, morphology)]
        return next(cell for cell in row["cells"] if cell["target_snr"] == 48.0)
    lines = [
        "# Multiscale efficiency v2: verified analysis report",
        "",
        f"Run key: `{summary['run_key']}`",
        "",
        "## Scope",
        "",
        "This report measures simulation-specific recovery in the frozen paired O4a injection study. "
        "The primary endpoint is the detector-native 32 s decision. Short-scale responses are "
        "conditional diagnostics only; no scale OR fusion, astrophysical population efficiency, "
        "rate upper limit, global significance, or O3 transfer claim is made.",
        "",
        "## Conditional response pattern",
        "",
        f"Of {defined} conditional cells with at least one primary recovery, {endpoints} "
        f"({percent:.1f}%) lie at an observed endpoint: "
        f"{overview['conditional_observed_zero_cells']} have no observed short-scale response and "
        f"{overview['conditional_observed_one_cells']} respond for every eligible trial. Only "
        f"{overview['conditional_interior_cells']} cells are intermediate. In this finite, paired "
        "simulation grid, the conditional multiscale response is therefore predominantly "
        "endpoint-like (always present or never present) rather than gradual. This is an empirical "
        "description, not evidence that the underlying response probability is exactly zero or one, "
        "and not proof of a particular mechanism.",
        "",
        "Endpoint cells retain their observed point value but have a null confidence interval. "
        "Interior conditional cells receive a 95% raw-source-block bootstrap interval only when all "
        "2,000 shared bootstrap replicates retain a non-zero eligible denominator.",
        "",
        "Status counts by short scale:",
        "",
        "| Scale (s) | Undefined (no primary) | Observed 0 | Observed 1 | Interior CI | Interior CI null |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for scale, counts in overview["conditional_status_counts_by_scale"].items():
        lines.append(
            f"| {float(scale):g} | {counts.get(NO_ELIGIBLE, 0)} | "
            f"{counts.get(NO_CONDITIONAL, 0)} | {counts.get(ALL_CONDITIONAL, 0)} | "
            f"{counts.get(PASS_CI, 0)} | {counts.get(UNDEFINED_REPLICATES, 0)} |"
        )
    lines.extend(
        [
            "",
            "## Primary end-to-end recovery",
            "",
            "Each entry is recovered/total for SNR 8, 12, 16, 24, 32, and 48. Full point estimates, "
            "confidence intervals, and boundary states are in `primary_efficiency.jsonl`.",
            "",
            "| Detector | Population role | Morphology | 8 | 12 | 16 | 24 | 32 | 48 |",
            "|:--|:--|:--|--:|--:|--:|--:|--:|--:|",
        ]
    )
    for grid_row in overview["primary_recovery_grid"]:
        cells = " | ".join(
            f"{cell['n_recovered']}/{cell['n_total']}" for cell in grid_row["cells"]
        )
        lines.append(
            f"| {grid_row['detector']} | {grid_row['role']} | "
            f"{grid_row['morphology']} | {cells} |"
        )
    lines.extend(
        [
            "",
            "## Morphology-dependent primary sensitivity",
            "",
            "The primary curves are not uniformly SNR-responsive. `NoiseBlob` is flat in both "
            f"detectors ({_counts('H1', 'primary_injection', 'NoiseBlob')} in H1 and "
            f"{_counts('L1', 'primary_injection', 'NoiseBlob')} in L1). At every SNR, the "
            "recovered identities are exactly the clean-control identities that were already "
            "above threshold. At SNR 48, the mean injected-minus-clean score is "
            f"{_snr48('H1', 'primary_injection', 'NoiseBlob')['mean_injected_minus_clean_score']:+.6f} "
            "in H1 and "
            f"{_snr48('L1', 'primary_injection', 'NoiseBlob')['mean_injected_minus_clean_score']:+.6f} "
            "in L1. Within this experiment, `NoiseBlob` therefore produces essentially no "
            "primary-score response across the tested dynamic range.",
            "",
            "`Whistle` has a mostly flat recovery count but not a flat representation score: "
            f"the SNR-48 mean score increment is {_snr48('H1', 'primary_injection', 'Whistle')['mean_injected_minus_clean_score']:+.6f} "
            f"in H1 and {_snr48('L1', 'primary_injection', 'Whistle')['mean_injected_minus_clean_score']:+.6f} "
            "in L1, while the median within-block score/SNR correlations are "
            f"{response_lookup[('H1', 'primary_injection', 'Whistle')]['median_within_block_score_snr_correlation']:.3f} "
            f"and {response_lookup[('L1', 'primary_injection', 'Whistle')]['median_within_block_score_snr_correlation']:.3f}. "
            "The injected morphology is encoded increasingly strongly, but usually remains "
            "below the frozen p99 primary threshold. This is distinct from the `NoiseBlob` "
            "failure mode.",
            "",
            "`Blip` shows weak, late sensitivity rather than complete blindness: recovery stays "
            "near the clean-control baseline through SNR 24 and rises to "
            f"{_snr48('H1', 'primary_injection', 'Blip')['n_recovered']}/100 in H1 and "
            f"{_snr48('L1', 'primary_injection', 'Blip')['n_recovered']}/100 in L1 only at SNR 48. "
            "By contrast, `NarrowChirp` rises to "
            f"{_snr48('H1', 'primary_injection', 'NarrowChirp')['n_recovered']}/100 (H1) and "
            f"{_snr48('L1', 'primary_injection', 'NarrowChirp')['n_recovered']}/100 (L1), and "
            "`ScatteredLight` rises to "
            f"{_snr48('H1', 'primary_injection', 'ScatteredLight')['n_recovered']}/100 and "
            f"{_snr48('L1', 'primary_injection', 'ScatteredLight')['n_recovered']}/100. "
            "These positive controls show that "
            "the same frozen pipeline can produce rising efficiency curves; the flatness is "
            "morphology-dependent rather than a universal property of the injection study.",
            "",
            "## WallOfLines full-range limitation",
            "",
        ]
    )
    for row in overview["wall_of_lines_full_snr_range"]:
        if row["target_snr"] != 48.0:
            continue
        diagnostics = ", ".join(
            f"{scale}s={entry['n_exceeds_threshold']}/{entry['n_total']}"
            for scale, entry in row["short_scale_diagnostics"].items()
        )
        lines.append(
            f"- {row['detector']} at SNR {row['target_snr']:g}: primary recovery "
            f"{row['n_primary_recovered']}/{row['n_total']}; maximum primary score "
            f"{row['max_primary_score']:.6f} versus threshold {row['primary_threshold']:.6f}; "
            f"non-gating short-scale threshold exceedances {diagnostics}."
        )
    lines.extend(
        [
            "",
            "`WallOfLines` is thus characterized as systematically unrecovered by the primary "
            "endpoint in both detectors at every tested SNR from 8 through 48 (0/40 in all "
            "12 detector/SNR cells), not only at high SNR. It is substantially blind to this "
            "morphology over the tested dynamic range. A plausible hypothesis is that the "
            "Q-transform/DINO/VQ representation, designed around localized transient structure, "
            "can treat persistent or quasi-stationary spectral lines as background-like. The "
            "experiment does not establish that mechanism as the cause.",
            "",
            "## Injection-scaling audit",
            "",
            "The frozen ledger satisfies `amplitude_scale * unit_snr = target_snr` with a maximum "
            f"absolute error of {overview['injection_identity_audit']['maximum_amplitude_scale_times_unit_snr_error']:.3e}. "
            "Every detector/role/morphology/raw-block group contains the complete six-point SNR "
            "grid, six distinct scaled-waveform hashes, and six distinct injected-raw hashes. "
            "A direct replay from the frozen clean raw window independently recomputed unit and "
            "scaled matched-filter SNR for one block per detector for `NoiseBlob`, `Whistle`, "
            "`Blip`, and `WallOfLines`: all eight paths reproduced all six targets with maximum "
            f"absolute error {overview['flat_response_snr_replay']['maximum_absolute_snr_error']:.3e}, "
            "zero unit-SNR relative error, and matching scaled-waveform hashes.",
            "",
            "These checks find no evidence that the flat curves arise from unchanged injections, "
            "incorrect amplitude scaling, or mislabeled target SNR. The remaining limitation lies "
            "after injection, in the interaction among preprocessing, representation, index, and "
            "the frozen detector-native threshold. This audit does not isolate a unique causal "
            "component.",
            "",
            "## Uncertainty and audit boundary",
            "",
            "All intervals use complete raw-source-block resampling, separately by detector and "
            "population role, with shared draws across morphology, SNR, and scale. Detectors and "
            "morphology tiers are never pooled. A missing interval is an explicit fail-closed "
            "boundary state, not a numerical zero-width confidence claim.",
            "",
        ]
    )
    return "\n".join(lines)


def _summary_body(
    *,
    contract: Mapping[str, Any],
    run_key: str,
    injection_summary: Mapping[str, Any],
    primary_path: Path,
    conditional_path: Path,
    report_path: Path,
    overview: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_MULTISCALE_EFFICIENCY_V2_ANALYSIS",
        "run_key": run_key,
        "analysis_contract_digest": contract["contract_digest"],
        "injection_run_key": injection_summary["run_key"],
        "injection_artifact_digest": injection_summary["artifact_digest"],
        "primary_efficiency": {
            "filename": primary_path.name,
            "row_total": int(overview["primary_cells"]),
            "sha256": sha256_file(primary_path),
        },
        "conditional_response": {
            "filename": conditional_path.name,
            "row_total": int(overview["conditional_cells"]),
            "sha256": sha256_file(conditional_path),
        },
        "report": {"filename": report_path.name, "sha256": sha256_file(report_path)},
        "overview": overview,
        "scientific_boundary": {
            "bootstrap_unit": "raw_source_block",
            "bootstrap_resamples": 2000,
            "detectors_pooled": False,
            "morphology_tiers_pooled": False,
            "scale_or_fusion_applied": False,
            "rate_upper_limit_computed": False,
            "endpoint_values_are_true_probability_claims": False,
            "wall_of_lines_mechanism_proven": False,
            "flat_response_snr_scaling_replay": "PASS",
            "flat_response_unique_injected_raw_hashes": True,
            "post_injection_failure_component_isolated": False,
        },
    }


def run_analysis(
    *, injection_run_dir: Path, output_root: Path, root: Path = ROOT
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_analysis_contract(root)
    injection_summary = verify_injection_run(
        run_dir=injection_run_dir.resolve(), root=root
    )
    if (
        injection_summary["artifact_digest"]
        != contract["frozen_input"]["artifact_digest"]
    ):
        raise ContractError("analysis input injection artifact changed")
    run_key = _analysis_run_key(
        contract["contract_digest"], injection_summary["artifact_digest"]
    )
    run_dir = output_root.resolve() / f"analysis_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "analysis_summary.json"
    if summary_path.is_file():
        return verify_analysis_run(
            run_dir=run_dir, injection_run_dir=injection_run_dir, root=root
        ), run_dir

    trials_path = injection_run_dir / injection_summary["trials"]["filename"]
    rows = _read_jsonl(trials_path)
    primary, conditional, overview = build_analysis_tables(rows, contract)
    primary_path = run_dir / "primary_efficiency.jsonl"
    conditional_path = run_dir / "conditional_response.jsonl"
    report_path = run_dir / "analysis_report.md"
    _atomic_jsonl(primary_path, primary)
    _atomic_jsonl(conditional_path, conditional)
    placeholder = {
        "run_key": run_key,
        "overview": overview,
    }
    report_path.write_text(render_report(placeholder), encoding="utf-8", newline="\n")
    body = _summary_body(
        contract=contract,
        run_key=run_key,
        injection_summary=injection_summary,
        primary_path=primary_path,
        conditional_path=conditional_path,
        report_path=report_path,
        overview=overview,
    )
    _atomic_json(summary_path, {**body, "artifact_digest": canonical_json_sha256(body)})
    return verify_analysis_run(
        run_dir=run_dir, injection_run_dir=injection_run_dir, root=root
    ), run_dir


def verify_analysis_run(
    *, run_dir: Path, injection_run_dir: Path, root: Path = ROOT
) -> dict[str, Any]:
    root = root.resolve()
    contract = load_analysis_contract(root)
    injection_summary = verify_injection_run(
        run_dir=injection_run_dir.resolve(), root=root
    )
    summary_path = run_dir / "analysis_summary.json"
    if not summary_path.is_file():
        raise ContractError("multiscale analysis summary is absent")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("multiscale analysis artifact digest mismatch")
    expected_run_key = _analysis_run_key(
        contract["contract_digest"], injection_summary["artifact_digest"]
    )
    if (
        summary.get("status") != "PASS_MULTISCALE_EFFICIENCY_V2_ANALYSIS"
        or summary.get("run_key") != expected_run_key
        or run_dir.name != f"analysis_{expected_run_key}"
        or summary.get("analysis_contract_digest") != contract["contract_digest"]
        or summary.get("injection_artifact_digest")
        != injection_summary["artifact_digest"]
    ):
        raise ContractError("multiscale analysis identity changed")

    trials_path = injection_run_dir / injection_summary["trials"]["filename"]
    expected_primary, expected_conditional, expected_overview = build_analysis_tables(
        _read_jsonl(trials_path), contract
    )
    primary_path = run_dir / summary["primary_efficiency"]["filename"]
    conditional_path = run_dir / summary["conditional_response"]["filename"]
    report_path = run_dir / summary["report"]["filename"]
    for path, entry in (
        (primary_path, summary["primary_efficiency"]),
        (conditional_path, summary["conditional_response"]),
        (report_path, summary["report"]),
    ):
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ContractError(f"multiscale analysis output mismatch: {path.name}")
    if _read_jsonl(primary_path) != expected_primary:
        raise ContractError("multiscale primary efficiency replay mismatch")
    if _read_jsonl(conditional_path) != expected_conditional:
        raise ContractError("multiscale conditional response replay mismatch")
    if summary["overview"] != expected_overview:
        raise ContractError("multiscale analysis overview replay mismatch")
    expected_report = render_report(
        {"run_key": expected_run_key, "overview": expected_overview}
    )
    if report_path.read_text(encoding="utf-8") != expected_report:
        raise ContractError("multiscale analysis report replay mismatch")
    if summary["scientific_boundary"] != {
        "bootstrap_unit": "raw_source_block",
        "bootstrap_resamples": 2000,
        "detectors_pooled": False,
        "morphology_tiers_pooled": False,
        "scale_or_fusion_applied": False,
        "rate_upper_limit_computed": False,
        "endpoint_values_are_true_probability_claims": False,
        "wall_of_lines_mechanism_proven": False,
        "flat_response_snr_scaling_replay": "PASS",
        "flat_response_unique_injected_raw_hashes": True,
        "post_injection_failure_component_isolated": False,
    }:
        raise ContractError("multiscale analysis scientific boundary changed")
    return summary


__all__ = [
    "ALL_CONDITIONAL",
    "ALL_PRIMARY",
    "ANALYSIS_CONTRACT_REL",
    "NO_CONDITIONAL",
    "NO_ELIGIBLE",
    "NO_PRIMARY",
    "PASS_CI",
    "UNDEFINED_REPLICATES",
    "_conditional_statistic",
    "_primary_statistic",
    "build_analysis_tables",
    "load_analysis_contract",
    "render_report",
    "run_analysis",
    "validate_analysis_contract",
    "verify_analysis_run",
]
