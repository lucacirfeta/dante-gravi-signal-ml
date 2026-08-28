from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.review_telemetry_v8_1 import (
    ReviewTelemetryLedger,
    _load_source,
    _verify_anchor,
    iid_order_statistic_floor,
    load_contract,
    sufficiency_scenarios,
    verify_contract_provenance,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runs/dante_light/o4b_v2/shared"


def _time(second: int) -> tuple[str, int]:
    return f"2026-08-28T12:00:{second:02d}.000000Z", 1_787_918_400_000_000_000 + second * 1_000_000_000


def _ledger(tmp_path: Path) -> ReviewTelemetryLedger:
    return ReviewTelemetryLedger(
        tmp_path / "telemetry",
        contract=load_contract(),
        operator_id="test-operator",
        create=True,
        now=_time(0),
    )


def test_contract_has_no_operational_gate_and_anchor_is_current() -> None:
    contract = load_contract()
    assert contract["operational_parameters"] == {
        "age_override": None,
        "deadline": None,
        "top_x_budget": None,
    }
    source = _load_source(SOURCE)
    _verify_anchor(contract, source)
    assert len(source["escalations"]) == 18
    assert {row["detector"] for row in source["escalations"]} == {"H1", "L1"}
    assert verify_contract_provenance(contract)["historical_escalations"] == 18


def test_illustrative_floors_are_exact_and_never_a_gate() -> None:
    assert iid_order_statistic_floor(0.90, 0.90) == 22
    assert iid_order_statistic_floor(0.90, 0.95) == 29
    assert iid_order_statistic_floor(0.95, 0.90) == 45
    assert iid_order_statistic_floor(0.95, 0.95) == 59
    assert iid_order_statistic_floor(0.99, 0.95) == 299
    result = sufficiency_scenarios(load_contract())
    assert result["iid_assumption_accepted_for_inference"] is False
    assert result["status"] == "ILLUSTRATIVE_ONLY_NOT_A_TELEMETRY_READINESS_GATE"


def test_historical_sync_is_idempotent_and_outcome_blind(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    assert ledger.sync_source(
        SOURCE,
        source_semantics="historical_backlog_enrollment",
        require_historical_anchor=True,
        now=_time(1),
    ) == 18
    assert ledger.sync_source(
        SOURCE,
        source_semantics="historical_backlog_enrollment",
        require_historical_anchor=True,
        now=_time(2),
    ) == 0
    events = [json.loads(line) for line in ledger.events_path.read_text().splitlines()]
    serialized = json.dumps(events).lower()
    for forbidden in ("review_outcome", "class_label", "morphology", "teacher_score", "priority_score"):
        assert forbidden not in serialized
    status = ledger.status()
    assert status["enrolled"] == 18
    assert status["queued"] == 18
    assert status["completed"] == 0
    assert status["operational_budget_freeze_allowed"] is False


def test_state_machine_and_descriptive_timings(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.sync_source(
        SOURCE,
        source_semantics="historical_backlog_enrollment",
        require_historical_anchor=True,
        now=_time(1),
    )
    record_id = ledger.pending()[0]["source_record_id"]
    ledger.transition(record_id, "STARTED", now=_time(5))
    ledger.transition(record_id, "COMPLETED", now=_time(11))
    status = ledger.status()
    assert status["queued"] == 17
    assert status["completed"] == 1
    assert status["observed_wait_from_enrollment"]["median_s"] == 4.0
    assert status["operator_service_time"]["median_s"] == 6.0
    assert status["observed_cycle_from_enrollment"]["median_s"] == 10.0
    assert status["inference_status"] == "DESCRIPTIVE_ONLY_SUFFICIENCY_THRESHOLD_UNFROZEN"


def test_review_packet_is_provenance_bound_and_standardized(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.sync_source(
        SOURCE,
        source_semantics="historical_backlog_enrollment",
        require_historical_anchor=True,
        now=_time(1),
    )
    record_id = ledger.pending()[0]["source_record_id"]
    result = ledger.build_review_packet(record_id)
    packet = result["packet"]
    assert packet["procedure_revision"] == 2
    assert packet["source_record_id"] == "dlr1-54bcc67eb4c3e2f1e6c70267"
    assert packet["gallery_position"] == {
        "one_based_index": 1,
        "row": 1,
        "column": 1,
    }
    assert packet["exact_decision"]["score"] == pytest.approx(0.38023295998573303)
    assert packet["cross_detector"]["measurement_status"] == "MEASURED"
    assert packet["catalog_crossmatch"]["match_count"] == 0
    assert len(packet["checklist"]) == 6
    assert "review_outcome" not in json.dumps(packet).lower()
    assert Path(result["candidate_image"]).is_file()
    assert Path(result["packet_html"]).is_file()
    assert Path(result["packet_json"]).is_file()
    from PIL import Image

    with Image.open(result["candidate_image"]) as image:
        assert image.size == (530, 515)


def test_review_packet_rejects_non_cohort_identity(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.sync_source(
        SOURCE,
        source_semantics="historical_backlog_enrollment",
        require_historical_anchor=True,
        now=_time(1),
    )
    state = ledger._state()
    record_id = next(iter(state))
    state[record_id]["identity"]["window_id"] = "dlw1-not-in-frozen-manifest"
    original = ledger._state
    ledger._state = lambda: state  # type: ignore[method-assign]
    try:
        with pytest.raises(ContractError, match="not unique"):
            ledger.build_review_packet(record_id)
    finally:
        ledger._state = original  # type: ignore[method-assign]


def test_invalid_transitions_fail_closed(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.sync_source(
        SOURCE,
        source_semantics="historical_backlog_enrollment",
        require_historical_anchor=True,
        now=_time(1),
    )
    record_id = ledger.pending()[0]["source_record_id"]
    with pytest.raises(ContractError, match="cannot mark"):
        ledger.transition(record_id, "COMPLETED", now=_time(2))
    ledger.transition(record_id, "STARTED", now=_time(3))
    with pytest.raises(ContractError, match="cannot mark"):
        ledger.transition(record_id, "STARTED", now=_time(4))


def test_hash_chain_tampering_fails_closed(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.sync_source(
        SOURCE,
        source_semantics="historical_backlog_enrollment",
        require_historical_anchor=True,
        now=_time(1),
    )
    lines = ledger.events_path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["detector"] = "V1"
    lines[0] = json.dumps(event)
    ledger.events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ContractError, match="digest mismatch"):
        ReviewTelemetryLedger(tmp_path / "telemetry", contract=load_contract())


def test_manifest_refuses_outcome_fields(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    manifest = json.loads(ledger.manifest_path.read_text())
    body = dict(manifest)
    body.pop("manifest_digest")
    body["outcome_fields_permitted"] = ["review_outcome"]
    body["manifest_digest"] = canonical_json_sha256(body)
    ledger.manifest_path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ContractError, match="outcome fields"):
        ReviewTelemetryLedger(tmp_path / "telemetry", contract=load_contract())


def test_contract_digest_tampering_fails_closed(tmp_path: Path) -> None:
    contract = load_contract()
    changed = copy.deepcopy(contract)
    changed["operational_parameters"]["top_x_budget"] = 10
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ContractError, match="digest mismatch"):
        load_contract(path)


def test_cli_review_flow_requires_checklist_confirmation(tmp_path: Path) -> None:
    script = ROOT / "scripts/manage_dante_light_v8_1_review_telemetry.py"
    telemetry = tmp_path / "cli-telemetry"
    base = [sys.executable, str(script), "--telemetry-dir", str(telemetry)]
    subprocess.run(
        base
        + [
            "init",
            "--operator-id",
            "cli-test",
            "--require-historical-anchor",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    start = subprocess.run(
        base + ["start"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    started = json.loads(start.stdout)
    record_id = started["event"]["source_record_id"]
    refused = subprocess.run(
        base + ["complete", "--record-id", record_id],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode != 0
    subprocess.run(
        base
        + [
            "complete",
            "--record-id",
            record_id,
            "--confirm-checklist",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    status = subprocess.run(
        base + ["status"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    assert json.loads(status.stdout)["completed"] == 1
