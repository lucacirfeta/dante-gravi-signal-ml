from __future__ import annotations

from collections import Counter
import hashlib
import json
import subprocess

import pytest

from src.dante_light.prefilter_v5_power import gate_pass_probability
from src.dante_light.prefilter_v7_freeze import ROOT, repository_reference, verify_freeze


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_v7_freeze_verifies_and_is_outcome_blind() -> None:
    result = verify_freeze(ROOT)
    assert result["status"] == "PASS"
    assert result["outcome_access_at_freeze"] == {
        "v7_student_outputs": [],
        "threshold_search_student_outputs": [],
        "risk_calibration_student_outputs": [],
        "confirmation_student_outputs": [],
        "o4b": [],
    }


def test_v7_uses_correct_teacher_positive_endpoint_and_independent_holdout() -> None:
    contract = json.loads((ROOT / "config/dante_light_prefilter_v7_outcome_blind_contract.json").read_text(encoding="utf-8"))
    assert contract["gates"]["primary_teacher_positive"]["endpoint"] == "P(Light_defers|exact_DANTE_retains, frozen_O4a_candidate_catalog)"
    assert contract["threshold_selection"]["selection_partition"] == "threshold_search"
    assert contract["task"]["routing_rule"] == "defer_if_score_greater_than_or_equal_to_detector_threshold_else_discard"
    assert contract["threshold_selection"]["freeze_before_risk_calibration"] is True
    assert contract["threshold_selection"]["calibration_failure_action"] == "STOP_NO_RETUNE_NO_FALLBACK"
    assert contract["gates"]["protected_morphology"]["aggregation_across_morphologies_allowed"] is False


def test_v7_primary_positive_blocks_are_disjoint() -> None:
    rows = _jsonl(ROOT / "config/dante_light_prefilter_v7_identities.jsonl")
    positives = [row for row in rows if row["role"] == "teacher_positive"]
    keys = [row["block_key"] for row in positives]
    assert len(keys) == len(set(keys))
    background = {row["block_key"] for row in rows if row["role"] == "background"}
    assert not (set(keys) & background)


def test_v7_counts_match_frozen_contract() -> None:
    contract = json.loads((ROOT / "config/dante_light_prefilter_v7_outcome_blind_contract.json").read_text(encoding="utf-8"))
    rows = _jsonl(ROOT / "config/dante_light_prefilter_v7_identities.jsonl")
    counts = Counter((row["detector"], row["partition"], row["role"]) for row in rows)
    for detector in ("H1", "L1"):
        for partition, expected in contract["identity_counts"]["background_per_detector"].items():
            assert counts[(detector, partition, "background")] == expected
        for partition, expected in contract["identity_counts"]["teacher_positive_per_detector"].items():
            assert counts[(detector, partition, "teacher_positive")] == expected


def test_v7_n60_power_matches_exact_binomial_contract() -> None:
    probability = gate_pass_probability(
        60,
        true_retention=0.95,
        minimum_retention=0.90,
        minimum_wilson_lower=0.80,
        confidence=0.95,
    )
    assert probability == pytest.approx(0.9212807354)
    assert probability >= 0.90


def test_v7_confirmation_seal_covers_primary_protected_and_operational_endpoints() -> None:
    seal = json.loads((ROOT / "config/dante_light_prefilter_v7_confirmation_seal.json").read_text(encoding="utf-8"))
    assert seal["status"] == "SEALED_NOT_OPENED"
    assert seal["access_entries_at_freeze"] == 0
    assert {
        "teacher_positive_retention_by_detector",
        "protected_retention_by_detector_and_morphology",
        "natural_background_discard_fraction_by_detector",
        "paired_block_bootstrap_mean_net_saving",
    } <= set(seal["protected_endpoints"])


def test_v7_family01_limitation_is_explicit() -> None:
    contract = json.loads((ROOT / "config/dante_light_prefilter_v7_outcome_blind_contract.json").read_text(encoding="utf-8"))
    boundary = contract["scientific_boundary"]
    assert boundary["observed_o4a_teacher_positive_population_is_overwhelmingly_Family_01"] is True
    assert boundary["primary_gate_does_not_establish_broad_unseen_morphology_coverage"] is True
    assert boundary["primary_teacher_positive_population_is_catalog_conditioned_not_continuous_traffic"] is True


def test_v7_background_prevalence_is_rare_but_not_empty() -> None:
    audit = json.loads(
        (
            ROOT
            / "artifacts/dante_light/prefilter_l4_v7_design/background_teacher_prevalence_audit_v7.json"
        ).read_text(encoding="utf-8")
    )
    assert audit["counts"]["H1"]["n"] == 1440
    assert audit["counts"]["H1"]["exact_dante_retained"] == 23
    assert audit["counts"]["L1"]["n"] == 1440
    assert audit["counts"]["L1"]["exact_dante_retained"] == 49
    assert audit["decision_rule"] == "native_o4a_novelty_score_strictly_greater_than_historical_detector_threshold"
    assert audit["interpretation"]["zero_of_1440_claim_rejected"] is True


def test_v7_repository_reference_is_portable_across_checkout_line_endings(
    tmp_path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "core.autocrlf", "true"], cwd=tmp_path, check=True)
    path = tmp_path / "sample.py"
    path.write_bytes(b"a=1\nb=2\n")
    subprocess.run(["git", "add", "sample.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=tmp_path, check=True)
    path.write_bytes(b"a=1\r\nb=2\r\n")
    reference = repository_reference(tmp_path, path)
    assert reference["sha256"] == hashlib.sha256(b"a=1\nb=2\n").hexdigest()
