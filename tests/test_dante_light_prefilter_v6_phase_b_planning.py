from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_phase_b_planning import load_planning_contract


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dante_light_prefilter_v6_phase_b_planning_audit.json"
ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v6_design"
    / "phase_b_planning_audit_v6.json"
)
REPORT = ROOT / "docs/DANTE_LIGHT_L4_PREFILTER_V6_PHASE_B_FREEZE_PROPOSAL_2026-08-25.md"


def test_planning_contract_cannot_select_or_access_outcomes() -> None:
    payload = load_planning_contract(CONFIG, root=ROOT)
    assert payload["allocation_selection_allowed"] is False
    assert all(value is False for value in payload["scientific_boundary"].values())


def test_planning_contract_rejects_retroactive_selection(tmp_path: Path) -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["allocation_selection_allowed"] = True
    body = dict(payload)
    body.pop("contract_digest")
    payload["contract_digest"] = canonical_json_sha256(body)
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="cannot select"):
        load_planning_contract(path, root=ROOT)


def test_committed_planning_audit_is_bounded_and_recomputes() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_dante_light_prefilter_v6_phase_b_planning_audit.py"),
            "--deep",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert all(value == [] for value in payload["outcome_access"].values())
    assert all(value is False for value in payload["decision"].values())
    assert payload["capacity"]["interpretation_boundary"][
        "whole_block_resampling_required"
    ] is True
    assert all(
        scenario["selected"] is False
        for scenario in payload["capacity"]["allocation_scenarios"]
    )


def test_planning_report_matches_committed_identity_capacity() -> None:
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    report = REPORT.read_text(encoding="utf-8")
    assert payload["artifact_digest"] in report
    for detector in ("H1", "L1"):
        capacity = payload["capacity"][detector]
        expected = (
            f"| {detector} | {capacity['official_eligible_block_count']} | "
            f"{capacity['currently_local_eligible_block_count']} | "
            f"{capacity['additional_not_currently_local_count']} |"
        )
        assert expected in report


def test_verifier_rejects_tampered_capacity(tmp_path: Path) -> None:
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    payload["capacity"]["H1"]["official_eligible_block_count"] += 1
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_dante_light_prefilter_v6_phase_b_planning_audit.py"),
            "--artifact",
            str(path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "artifact digest mismatch" in completed.stderr
