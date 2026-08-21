from __future__ import annotations

import hashlib
import json

import pytest

from src.dante_light.contracts import ContractError, WindowIdentity
from src.dante_light.prefilter_evaluation import evaluate_prefilter, wilson_interval


def _write_case(tmp_path, *, reduction_target=0.5, tamper=False):
    tuning_path = tmp_path / "tuning.json"
    tuning_path.write_text('{"status":"frozen"}\n', encoding="utf-8")
    tuning = {
        "path": tuning_path.name,
        "sha256": hashlib.sha256(tuning_path.read_bytes()).hexdigest(),
    }
    representation_sha256 = "b" * 64
    split_hashes = {
        "shadow": "c" * 64,
        "robust_candidate": "d" * 64,
        "known_glitch": "e" * 64,
        "injection": "f" * 64,
    }
    contract = {
        "schema_version": 1,
        "status": "locked_before_evaluation",
        "contract_id": "fixture-v1",
        "feature_source": "canonical_whitened_subwindow_v1",
        "crest_threshold": 5.0,
        "band_fraction_threshold": 0.2,
        "audit_fraction": 0.25,
        "audit_seed": 42,
        "minimum_compute_reduction": reduction_target,
        "minimum_exact_escalates": 18,
        "representation_sha256": representation_sha256,
        "evaluation_start_gps_by_detector": {"H1": 1000.0},
        "required_detectors": ["H1"],
        "required_morphologies_by_role": {
            "known_glitch": ["fixture_glitch"],
            "injection": ["fixture_injection"],
        },
        "cohort_split_sha256_by_role": split_hashes,
        "threshold_tuning_artifact": tuning,
        "required_groups": [
            {
                "name": "robust",
                "filters": {
                    "role": "robust_candidate",
                    "detector": "H1",
                    "retention_target": True,
                },
                "minimum_n": 18,
                "minimum_retention": 1.0,
                "minimum_wilson_lower": 0.8,
            },
            {
                "name": "known",
                "filters": {
                    "role": "known_glitch",
                    "detector": "H1",
                    "morphology": "fixture_glitch",
                    "retention_target": True,
                },
                "minimum_n": 18,
                "minimum_retention": 0.9,
                "minimum_wilson_lower": 0.8,
            },
            {
                "name": "injection",
                "filters": {
                    "role": "injection",
                    "detector": "H1",
                    "morphology": "fixture_injection",
                    "retention_target": True,
                },
                "minimum_n": 18,
                "minimum_retention": 0.9,
                "minimum_wilson_lower": 0.8,
            },
        ],
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    rows = []
    for index in range(240):
        positive = index < 18
        window = WindowIdentity("O4B", "H1", 1000.0 + index * 32)
        roles = ["shadow"]
        if positive:
            roles.append("robust_candidate")
        if 18 <= index < 38:
            roles.append("known_glitch")
        if 38 <= index < 58:
            roles.append("injection")
        selected_control = index < 58
        morphology = None
        if 18 <= index < 38:
            morphology = "fixture_glitch"
        elif 38 <= index < 58:
            morphology = "fixture_injection"
        elif positive:
            morphology = "unknown"
        rows.append(
            {
                "window": window.to_dict(),
                "roles": roles,
                "partition": "evaluation",
                "split_artifact_sha256_by_role": {
                    role: split_hashes[role] for role in roles
                },
                "detector": "H1",
                "morphology": morphology,
                "exact_disposition": "ESCALATE" if positive else "NOT_ESCALATED",
                "retention_target": selected_control,
                "representation_sha256": representation_sha256,
                "strain_sha256": f"{index + 1:064x}",
                "features": {
                    "rms": 1.0,
                    "crest_factor": 8.0 if selected_control else 2.0,
                    "peak_band_fraction": 0.1,
                    "high_quantile_power": 3.0,
                },
            }
        )
    rows_path = tmp_path / "rows.jsonl"
    rows_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    ledger = {
        "schema_version": 1,
        "status": "complete",
        "feature_source": "canonical_whitened_subwindow_v1",
        "outcome_fields_used_for_threshold_selection": [],
        "threshold_tuning_artifact": tuning,
        "representation_sha256": representation_sha256,
        "cohort_split_sha256_by_role": split_hashes,
        "rows_path": rows_path.name,
        "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
        "row_count": len(rows),
    }
    if tamper:
        ledger["rows_sha256"] = "0" * 64
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    return contract_path, ledger_path


def test_prefilter_evaluation_passes_without_enabling_routing(tmp_path):
    contract, ledger = _write_case(tmp_path, reduction_target=0.5)
    result = evaluate_prefilter(contract_path=contract, ledger_path=ledger)
    assert result["status"] == "PASS"
    assert result["routing_enabled"] is False
    assert result["coverage"]["missed_exact_escalates"] == 0
    assert result["coverage"]["effective_compute_reduction"] >= 0.5


def test_prefilter_evaluation_reports_not_ready_on_failed_gate(tmp_path):
    contract, ledger = _write_case(tmp_path, reduction_target=1.0)
    result = evaluate_prefilter(contract_path=contract, ledger_path=ledger)
    assert result["status"] == "NOT_READY"
    assert next(gate for gate in result["gates"] if gate["name"] == "effective_compute_reduction") == {
        "name": "effective_compute_reduction",
        "status": "FAIL",
    }


def test_prefilter_evaluation_rejects_tampered_rows(tmp_path):
    contract, ledger = _write_case(tmp_path, tamper=True)
    with pytest.raises(ContractError, match="SHA256 mismatch"):
        evaluate_prefilter(contract_path=contract, ledger_path=ledger)


def test_wilson_interval_bounds_point_estimate():
    lower, upper = wilson_interval(9, 10)
    assert lower < 0.9 < upper
