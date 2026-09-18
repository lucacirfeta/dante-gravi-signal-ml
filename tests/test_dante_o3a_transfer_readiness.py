from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_transfer_readiness import (
    DEFAULT_GATE,
    O3A_BOUNDS,
    RECOMMENDATIONS,
    audit_local_readiness,
    load_decision_gate,
)


ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_o3a_gate_is_unresolved_and_fail_closed() -> None:
    gate = load_decision_gate()
    assert gate["official_run_bounds_gps"] == O3A_BOUNDS
    assert gate["recommendations"] == RECOMMENDATIONS
    assert gate["execution_allowed"] is False
    assert gate["outcome_data_accessed"] is False
    assert set(gate["author_decisions"]) == set(RECOMMENDATIONS)
    assert all(value is None for value in gate["author_decisions"].values())


def test_unresolved_gate_rejects_silent_decision(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_GATE.read_text(encoding="utf-8"))
    payload["author_decisions"]["dq_semantics"] = "CBC_CAT1"
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="must remain unresolved"):
        load_decision_gate(path)


def test_readiness_audit_is_local_and_does_not_authorize_execution(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "bounded.hdf5").write_bytes(b"raw")
    result = audit_local_readiness(root=ROOT, cache_root=cache)
    assert result["read_only"] is True
    assert result["network_accessed"] is False
    assert result["dq_segments_accessed"] is False
    assert result["strain_or_outcomes_accessed"] is False
    assert result["execution_authorized"] is False
    assert result["storage"]["raw_file_count"] == 1
    assert result["storage"]["raw_bytes"] == 3
    assert result["audit_sha256"]
