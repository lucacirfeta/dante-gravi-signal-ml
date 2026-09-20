"""Fit the frozen detector-specific O3a initial p99 thresholds.

This stage consumes only the accepted initial-calibration primary scores.  It
does not classify, inspect candidates, select an index cohort, or start the
primary scan.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import struct
from typing import Any, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_initial_calibration_acceptance import (
    CONTRACT_REL as ACCEPTANCE_CONTRACT_REL,
    file_sha256,
    load_acceptance_contract,
)
from src.dante_light.o3a_native_contract import (
    ROOT,
    RUNTIME_REL,
    load_runtime_contract,
)
from src.dante_light.o3a_scale_adequacy import (
    STAGE_CONTRACT_REL,
    load_stage_contract,
)
from src.pipeline_v2_production.background_calibration import (
    block_bootstrap_p99_ci,
)


CONTRACT_REL = "config/dante_o3a_initial_thresholds_v1.json"
IMPLEMENTATION_REL = "src/dante_light/o3a_initial_thresholds.py"
FREEZE_ENTRYPOINT_REL = "scripts/freeze_dante_o3a_initial_thresholds.py"
RUN_ENTRYPOINT_REL = "scripts/run_dante_o3a_initial_thresholds.py"
BOOTSTRAP_IMPLEMENTATION_REL = (
    "src/pipeline_v2_production/background_calibration.py"
)
TEST_REL = "tests/test_dante_o3a_initial_thresholds.py"
SCHEMA_VERSION = 1
DEFAULT_EXTERNAL_ROOT = Path("/mnt/e/dante_cache/dante_light/o3a_native_v1")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _binding(root: Path, relative: str, **extra: Any) -> dict[str, Any]:
    return {
        "path": relative,
        "sha256": file_sha256(root / relative),
        **extra,
    }


def _implementation_sources(root: Path) -> dict[str, str]:
    relatives = (
        IMPLEMENTATION_REL,
        FREEZE_ENTRYPOINT_REL,
        RUN_ENTRYPOINT_REL,
        BOOTSTRAP_IMPLEMENTATION_REL,
        TEST_REL,
    )
    return {relative: file_sha256(root / relative) for relative in relatives}


def _summary_body(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if key != "artifact_digest"}


def _validate_acceptance_summary(
    summary: Mapping[str, Any], *, summary_path: Path
) -> Path:
    if (
        summary.get("status")
        != "PASS_VERIFIED_O3A_INITIAL_CALIBRATION_ACCEPTANCE"
        or summary.get("artifact_digest")
        != canonical_json_sha256(_summary_body(summary))
        or summary.get("accepted_point_rows_by_detector")
        != {"H1": 5000, "L1": 5000}
        or summary.get("accepted_bootstrap_rows_by_detector")
        != {"H1": 4998, "L1": 4998}
        or int(summary.get("failed_block_count", -1)) != 0
    ):
        raise ContractError("O3a acceptance summary is not verified complete")
    ledger = Path(str(summary["accepted_ledger"]["path"]))
    if not ledger.is_file():
        raise ContractError("O3a accepted calibration ledger is absent")
    if file_sha256(ledger) != summary["accepted_ledger"]["sha256"]:
        raise ContractError("O3a accepted calibration ledger hash mismatch")
    if not summary_path.is_file():
        raise ContractError("O3a acceptance summary is absent")
    return ledger


def build_threshold_contract(
    *, root: Path = ROOT, acceptance_summary: Path
) -> dict[str, Any]:
    root = root.resolve()
    stage = load_stage_contract(root=root)
    acceptance = load_acceptance_contract(root=root)
    summary = _read_json(acceptance_summary)
    ledger = _validate_acceptance_summary(
        summary, summary_path=acceptance_summary
    )
    if summary["contract_digest"] != acceptance["contract_digest"]:
        raise ContractError("O3a acceptance summary contract changed")

    approved = stage["author_decisions"]["native_threshold_statistics"]
    method = {
        "name": "non_overlapping_block_bootstrap_p99",
        "detector_specific": bool(approved["detector_specific"]),
        "percentile": int(approved["score_percentile"]),
        "point_percentile_uses_all_rows": bool(
            approved["point_percentile_uses_all_rows"]
        ),
        "bootstrap_uses_first_complete_blocks": True,
        "block_length": int(approved["block_length_rows"]),
        "bootstrap_replicates": int(approved["bootstrap_replicates"]),
        "bootstrap_seed": int(approved["bootstrap_seed"]),
        "bootstrap_chunk_size": int(approved["bootstrap_chunk_size"]),
        "confidence_percentiles": list(approved["confidence_percentiles"]),
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_O3A_INITIAL_THRESHOLDS_V1",
        "run": "O3A",
        "parents": {
            "stage_contract": _binding(
                root,
                STAGE_CONTRACT_REL,
                contract_digest=stage["contract_digest"],
            ),
            "acceptance_contract": _binding(
                root,
                ACCEPTANCE_CONTRACT_REL,
                contract_digest=acceptance["contract_digest"],
            ),
            "canonical_runtime": _binding(
                root,
                RUNTIME_REL,
                contract_digest=acceptance["parents"]["canonical_runtime"][
                    "contract_digest"
                ],
                environment_digest=acceptance["parents"]["canonical_runtime"][
                    "environment_digest"
                ],
            ),
            "acceptance_run": {
                "summary_path": str(acceptance_summary),
                "summary_sha256": file_sha256(acceptance_summary),
                "artifact_digest": summary["artifact_digest"],
                "run_key": summary["run_key"],
                "ledger_path": str(ledger),
                "ledger_sha256": summary["accepted_ledger"]["sha256"],
            },
        },
        "method": method,
        "population": {
            "detectors": ["H1", "L1"],
            "point_rows_per_detector": 5000,
            "bootstrap_rows_per_detector": 4998,
            "complete_blocks_per_detector": 294,
            "point_only_tail_rows_per_detector": 2,
        },
        "adequacy_gate": {
            "finite_thresholds_and_endpoints": True,
            "nondegenerate_intervals": True,
            "point_estimate_inside_interval": True,
            "absolute_and_relative_width_reported": True,
            "post_hoc_o3a_specific_width_cutoff_allowed": False,
        },
        "scientific_boundary": {
            "accepted_primary_scores_only": True,
            "detector_pooling_allowed": False,
            "classification_performed": False,
            "candidate_outcomes_reviewed": False,
            "native_index_selection_performed": False,
            "primary_scan_started": False,
        },
        "execution": {
            "environment": "canonical WSL runtime",
            "atomic_outputs_only": True,
            "resume_partial_output": False,
        },
        "output": {
            "root": str(DEFAULT_EXTERNAL_ROOT),
            "summary_filename": "initial_thresholds_summary.json",
            "large_outputs_committed_to_git": False,
        },
        "implementation_sources": _implementation_sources(root),
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_threshold_contract(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("contract_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("O3a initial-threshold contract digest mismatch")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "FROZEN_O3A_INITIAL_THRESHOLDS_V1"
        or value.get("run") != "O3A"
        or value.get("implementation_sources") != _implementation_sources(root)
    ):
        raise ContractError("O3a initial-threshold contract boundary changed")
    for name in ("stage_contract", "acceptance_contract", "canonical_runtime"):
        reference = value["parents"][name]
        path = root / str(reference["path"])
        if not path.is_file() or file_sha256(path) != reference["sha256"]:
            raise ContractError(f"O3a initial-threshold parent changed: {name}")
    stage = load_stage_contract(root=root)
    approved = stage["author_decisions"]["native_threshold_statistics"]
    method = value["method"]
    expected_method = {
        "name": "non_overlapping_block_bootstrap_p99",
        "detector_specific": True,
        "percentile": int(approved["score_percentile"]),
        "point_percentile_uses_all_rows": True,
        "bootstrap_uses_first_complete_blocks": True,
        "block_length": int(approved["block_length_rows"]),
        "bootstrap_replicates": int(approved["bootstrap_replicates"]),
        "bootstrap_seed": int(approved["bootstrap_seed"]),
        "bootstrap_chunk_size": int(approved["bootstrap_chunk_size"]),
        "confidence_percentiles": list(approved["confidence_percentiles"]),
    }
    if method != expected_method:
        raise ContractError("O3a initial-threshold method changed")
    if value.get("population") != {
        "detectors": ["H1", "L1"],
        "point_rows_per_detector": 5000,
        "bootstrap_rows_per_detector": 4998,
        "complete_blocks_per_detector": 294,
        "point_only_tail_rows_per_detector": 2,
    }:
        raise ContractError("O3a initial-threshold population changed")
    if value.get("adequacy_gate") != {
        "finite_thresholds_and_endpoints": True,
        "nondegenerate_intervals": True,
        "point_estimate_inside_interval": True,
        "absolute_and_relative_width_reported": True,
        "post_hoc_o3a_specific_width_cutoff_allowed": False,
    }:
        raise ContractError("O3a initial-threshold adequacy gate changed")
    if value.get("scientific_boundary") != {
        "accepted_primary_scores_only": True,
        "detector_pooling_allowed": False,
        "classification_performed": False,
        "candidate_outcomes_reviewed": False,
        "native_index_selection_performed": False,
        "primary_scan_started": False,
    }:
        raise ContractError("O3a initial-threshold scientific boundary changed")
    return dict(value)


def load_threshold_contract(*, root: Path = ROOT) -> dict[str, Any]:
    return validate_threshold_contract(
        _read_json(root / CONTRACT_REL), root=root
    )


def write_threshold_contract(
    *, root: Path = ROOT, acceptance_summary: Path
) -> dict[str, Any]:
    value = build_threshold_contract(
        root=root, acceptance_summary=acceptance_summary
    )
    _atomic_json(root / CONTRACT_REL, value)
    return value


def _float32_hex(value: float) -> str:
    return struct.pack("<f", np.float32(value)).hex()


def validate_score_rows(
    rows: Sequence[Mapping[str, Any]], *, contract: Mapping[str, Any]
) -> dict[str, np.ndarray]:
    population = contract["population"]
    expected = int(population["point_rows_per_detector"])
    bootstrap_rows = int(population["bootstrap_rows_per_detector"])
    by_detector: dict[str, list[Mapping[str, Any]]] = {"H1": [], "L1": []}
    for row in rows:
        detector = str(row.get("detector"))
        if detector not in by_detector:
            raise ContractError("O3a calibration ledger detector changed")
        by_detector[detector].append(row)
    result: dict[str, np.ndarray] = {}
    for detector in population["detectors"]:
        detector_rows = by_detector[detector]
        if len(detector_rows) != expected:
            raise ContractError("O3a calibration detector count changed")
        identities: set[tuple[str, int]] = set()
        scores: list[float] = []
        for index, row in enumerate(detector_rows):
            gps = int(row.get("analysis_gps_start", -1))
            score = float(row.get("primary_score", np.nan))
            identity = (detector, gps)
            bootstrap_eligible = index < bootstrap_rows
            if (
                identity in identities
                or gps <= 0
                or not np.isfinite(score)
                or row.get("primary_score_float32_hex") != _float32_hex(score)
                or bool(row.get("bootstrap_eligible")) != bootstrap_eligible
                or bool(row.get("point_only_tail")) == bootstrap_eligible
            ):
                raise ContractError("O3a calibration score row changed")
            identities.add(identity)
            scores.append(score)
        result[detector] = np.asarray(scores, dtype=np.float64)
    return result


def compute_detector_threshold(
    scores: np.ndarray, *, method: Mapping[str, Any]
) -> dict[str, float | int]:
    result = block_bootstrap_p99_ci(
        np.asarray(scores, dtype=np.float64),
        B=int(method["bootstrap_replicates"]),
        seed=int(method["bootstrap_seed"]),
        chunk_size=int(method["bootstrap_chunk_size"]),
        block_length=int(method["block_length"]),
    )
    point = float(result["p99"])
    lower = float(result["ci_lower"])
    upper = float(result["ci_upper"])
    width = upper - lower
    values = np.asarray([point, lower, upper, width], dtype=np.float64)
    if (
        not np.isfinite(values).all()
        or not lower <= point <= upper
        or not width > 0.0
        or point == 0.0
    ):
        raise ContractError("O3a initial p99 interval failed adequacy gate")
    return {
        **result,
        "ci_width": float(width),
        "ci_width_fraction_of_p99": float(width / abs(point)),
    }


def _verified_parent(
    *, contract: Mapping[str, Any]
) -> tuple[dict[str, Any], Path]:
    parent = contract["parents"]["acceptance_run"]
    summary_path = Path(str(parent["summary_path"]))
    if (
        not summary_path.is_file()
        or file_sha256(summary_path) != parent["summary_sha256"]
    ):
        raise ContractError("O3a acceptance summary hash changed")
    summary = _read_json(summary_path)
    ledger = _validate_acceptance_summary(summary, summary_path=summary_path)
    if (
        summary["artifact_digest"] != parent["artifact_digest"]
        or summary["run_key"] != parent["run_key"]
        or str(ledger) != parent["ledger_path"]
        or file_sha256(ledger) != parent["ledger_sha256"]
    ):
        raise ContractError("O3a acceptance evidence changed")
    return summary, ledger


def _run_key(
    contract: Mapping[str, Any], *, environment_digest: str
) -> str:
    return canonical_json_sha256(
        {
            "stage": "o3a_initial_thresholds_v1",
            "contract_digest": contract["contract_digest"],
            "acceptance_artifact_digest": contract["parents"][
                "acceptance_run"
            ]["artifact_digest"],
            "runtime_environment_digest": environment_digest,
        }
    )


def run_initial_thresholds(
    *,
    root: Path = ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_threshold_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    _, ledger = _verified_parent(contract=contract)
    environment_digest = runtime["runtime_environment"]["environment_digest"]
    run_key = _run_key(contract, environment_digest=environment_digest)
    run_dir = external_root.resolve() / f"initial_thresholds_{run_key}"
    summary_path = run_dir / str(contract["output"]["summary_filename"])
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError("O3a initial-threshold failure artifact exists")
    if summary_path.is_file():
        return verify_initial_thresholds(root=root, external_root=external_root)
    try:
        rows = _read_jsonl(ledger)
        scores = validate_score_rows(rows, contract=contract)
        thresholds = {
            detector: {
                **compute_detector_threshold(
                    scores[detector], method=contract["method"]
                ),
                "n_point_rows": len(scores[detector]),
                "n_bootstrap_rows": int(
                    contract["population"]["bootstrap_rows_per_detector"]
                ),
            }
            for detector in contract["population"]["detectors"]
        }
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_VERIFIED_O3A_INITIAL_THRESHOLDS",
            "contract_digest": contract["contract_digest"],
            "run_key": run_key,
            "acceptance_artifact_digest": contract["parents"][
                "acceptance_run"
            ]["artifact_digest"],
            "accepted_ledger_sha256": file_sha256(ledger),
            "runtime_environment_digest": environment_digest,
            "method": contract["method"],
            "thresholds": thresholds,
            "adequacy_gate": {
                **contract["adequacy_gate"],
                "passed": True,
            },
            "scientific_boundary": contract["scientific_boundary"],
        }
        summary = {**body, "artifact_digest": canonical_json_sha256(body)}
        _atomic_json(summary_path, summary)
        return summary, run_dir
    except BaseException as exc:
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAILED_O3A_INITIAL_THRESHOLDS",
            "contract_digest": contract["contract_digest"],
            "run_key": run_key,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        raise


def verify_initial_thresholds(
    *,
    root: Path = ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_threshold_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    _, ledger = _verified_parent(contract=contract)
    environment_digest = runtime["runtime_environment"]["environment_digest"]
    run_key = _run_key(contract, environment_digest=environment_digest)
    run_dir = external_root.resolve() / f"initial_thresholds_{run_key}"
    if (run_dir / "failure.json").is_file():
        raise ContractError("O3a initial-threshold failure artifact exists")
    summary_path = run_dir / str(contract["output"]["summary_filename"])
    if not summary_path.is_file():
        raise ContractError("O3a initial-threshold summary is absent")
    summary = _read_json(summary_path)
    body = _summary_body(summary)
    if (
        summary.get("artifact_digest") != canonical_json_sha256(body)
        or summary.get("status")
        != "PASS_VERIFIED_O3A_INITIAL_THRESHOLDS"
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("run_key") != run_key
        or summary.get("accepted_ledger_sha256") != file_sha256(ledger)
        or summary.get("method") != contract["method"]
        or summary.get("scientific_boundary")
        != contract["scientific_boundary"]
    ):
        raise ContractError("O3a initial-threshold summary changed")
    scores = validate_score_rows(_read_jsonl(ledger), contract=contract)
    recomputed = {
        detector: {
            **compute_detector_threshold(
                scores[detector], method=contract["method"]
            ),
            "n_point_rows": len(scores[detector]),
            "n_bootstrap_rows": int(
                contract["population"]["bootstrap_rows_per_detector"]
            ),
        }
        for detector in contract["population"]["detectors"]
    }
    if recomputed != summary.get("thresholds"):
        raise ContractError("O3a initial-threshold replay changed")
    if summary.get("adequacy_gate") != {
        **contract["adequacy_gate"],
        "passed": True,
    }:
        raise ContractError("O3a initial-threshold adequacy gate changed")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "build_threshold_contract",
    "compute_detector_threshold",
    "load_threshold_contract",
    "run_initial_thresholds",
    "validate_score_rows",
    "validate_threshold_contract",
    "verify_initial_thresholds",
    "write_threshold_contract",
]
