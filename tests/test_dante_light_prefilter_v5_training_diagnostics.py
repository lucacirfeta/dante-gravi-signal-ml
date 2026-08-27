from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_training_diagnostics import (
    DEFAULT_SPEC,
    diagnostic_metrics,
    load_diagnostic_spec,
    verify_diagnostic_result,
)


ROOT = Path(__file__).resolve().parents[1]


def test_diagnostic_metrics_are_exact_for_identical_ordering() -> None:
    targets = np.asarray([-1.0, 0.0, 1.0], dtype=np.float64)
    values = diagnostic_metrics(targets, targets, beta=1.0)
    assert values["count"] == 3
    assert values["spearman"] == pytest.approx(1.0)
    assert values["pearson"] == pytest.approx(1.0)
    assert values["smooth_l1"] == pytest.approx(0.0)
    assert values["prediction_standard_deviation_ddof0"] == pytest.approx(
        values["target_standard_deviation_ddof0"]
    )


def test_diagnostic_metrics_reject_nonfinite_and_constant_predictions() -> None:
    with pytest.raises(ContractError):
        diagnostic_metrics(
            np.asarray([0.0, 1.0]), np.asarray([0.0, np.nan]), beta=1.0
        )
    with pytest.raises(ContractError, match="non-finite"):
        diagnostic_metrics(
            np.asarray([0.0, 1.0]), np.asarray([1.0, 1.0]), beta=1.0
        )


def test_frozen_diagnostic_spec_is_training_only() -> None:
    spec = load_diagnostic_spec(DEFAULT_SPEC, root=ROOT)
    assert spec["scope"]["allowed_partition"] == "training"
    assert spec["scope"]["development_access_allowed"] is False
    assert spec["scope"]["confirmation_access_allowed"] is False
    assert spec["scope"]["o4b_access_allowed"] is False
    assert spec["metrics"]["pass_fail_threshold"] is None


def _synthetic_result() -> dict:
    contract = json.loads(
        (ROOT / "config/dante_light_prefilter_v5_training_contract.json").read_text(
            encoding="utf-8"
        )
    )
    row_counts = contract["internal_split"]["row_counts"]
    cell = {
        "spearman": 0.5,
        "pearson": 0.5,
        "smooth_l1": 0.1,
        "prediction_standard_deviation_ddof0": 0.5,
        "target_standard_deviation_ddof0": 1.0,
    }
    results = {}
    for arm in ("raw_1d_depthwise", "complex_stft_2d"):
        replicates = []
        for replicate in range(5):
            subsets = {}
            for subset in ("fit", "validation"):
                subsets[subset] = {
                    detector: {
                        **cell,
                        "count": row_counts[detector][subset],
                    }
                    for detector in ("H1", "L1")
                }
            replicates.append(
                {"replicate_index": replicate, "subsets": subsets}
            )
        results[arm] = {"replicates": replicates}
    spec_reference = {
        "path": DEFAULT_SPEC.relative_to(ROOT).as_posix(),
        "sha256": __import__("hashlib").sha256(DEFAULT_SPEC.read_bytes()).hexdigest(),
    }
    body = {
        "schema_version": 1,
        "status": "COMPLETE_RETROSPECTIVE_TRAINING_ONLY_DIAGNOSTIC",
        "diagnostic_spec": spec_reference,
        "parent_training_artifact_digest": "0" * 64,
        "training_run_key": "synthetic",
        "code_references": {},
        "environment": {},
        "training_rows_accessed": {
            subset: {
                detector: row_counts[detector][subset]
                for detector in ("H1", "L1")
            }
            for subset in ("fit", "validation")
        },
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
        "morphology_labels_accessed": [],
        "candidate_promotion_allowed": False,
        "routing_enabled": False,
        "pass_fail_gate_evaluated": False,
        "results": results,
        "result_matrix_digest": canonical_json_sha256(results),
        "elapsed_s": 1.0,
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def test_synthetic_complete_result_verifies() -> None:
    verified = verify_diagnostic_result(_synthetic_result(), root=ROOT)
    assert verified["metric_cells"] == 40
    assert verified["candidate_promotion_allowed"] is False


def test_result_tampering_and_protected_access_fail_closed() -> None:
    result = _synthetic_result()
    result["results"]["raw_1d_depthwise"]["replicates"][0]["subsets"]["fit"][
        "H1"
    ]["spearman"] = 2.0
    with pytest.raises(ContractError, match="digest"):
        verify_diagnostic_result(result, root=ROOT)

    protected = _synthetic_result()
    protected["development_rows_accessed"] = ["forbidden"]
    body = copy.deepcopy(protected)
    body.pop("artifact_digest")
    protected["artifact_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="boundary"):
        verify_diagnostic_result(protected, root=ROOT)
