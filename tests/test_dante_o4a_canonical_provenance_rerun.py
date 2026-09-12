from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light import o4a_canonical_provenance_rerun as remediation


ROOT = Path(__file__).resolve().parents[1]


def _protocol() -> dict:
    return json.loads((ROOT / remediation.PROTOCOL_REL).read_text(encoding="utf-8"))


def _resign_protocol(payload: dict, monkeypatch: pytest.MonkeyPatch) -> dict:
    value = copy.deepcopy(payload)
    value.pop("protocol_digest", None)
    digest = canonical_json_sha256(value)
    value["protocol_digest"] = digest
    monkeypatch.setattr(remediation, "EXPECTED_PROTOCOL_DIGEST", digest)
    return value


def _candidate_contract(stage_name: str) -> tuple[dict, dict, list[str]]:
    protocol = remediation.load_protocol(root=ROOT, verify_git=False)
    stage = next(item for item in protocol["stages"] if item["name"] == stage_name)
    baseline = json.loads(
        (ROOT / stage["baseline_contract"]["path"]).read_text(encoding="utf-8")
    )
    candidate = copy.deepcopy(baseline)
    candidate["contract_id"] = f"{baseline['contract_id']}-canonical-rerun"
    candidate["remediation"] = {"protocol_digest": protocol["protocol_digest"]}
    candidate["contract_digest"] = remediation.contract_digest(candidate)
    return baseline, candidate, stage["allowed_changes"]


def test_frozen_protocol_validates_all_bound_baselines() -> None:
    protocol = remediation.load_protocol(root=ROOT, verify_git=True)
    assert protocol["ordered_stages"] == list(remediation.EXPECTED_STAGES)
    assert protocol["mandatory_transparency_note"] is True
    assert len(protocol["stages"]) == 10


def test_contract_gate_accepts_only_declared_metadata_transition() -> None:
    baseline, candidate, allowed = _candidate_contract("COHORT")
    differences = remediation.assert_allowed_contract_transition(
        baseline, candidate, allowed_changes=allowed
    )
    assert differences == {"/contract_digest", "/contract_id", "/remediation"}


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("cohort", "minimum_same_detector_separation_s"), 64.0),
        (("preprocessing", "whitening_pad_s"), 8.0),
        (("clustering", "algorithm"), "different.algorithm"),
        (("gates", "fail_closed"), False),
    ],
)
def test_contract_gate_rejects_scientific_changes(
    path: tuple[str, str], replacement: object
) -> None:
    baseline, candidate, allowed = _candidate_contract("COHORT")
    candidate[path[0]][path[1]] = replacement
    candidate["contract_digest"] = remediation.contract_digest(candidate)
    with pytest.raises(ContractError, match="scientific contract transition"):
        remediation.assert_allowed_contract_transition(
            baseline, candidate, allowed_changes=allowed
        )


def test_contract_gate_rejects_self_digest_mismatch() -> None:
    baseline, candidate, allowed = _candidate_contract("COHORT")
    candidate["contract_digest"] = "0" * 64
    with pytest.raises(ContractError, match="self-digest mismatch"):
        remediation.assert_allowed_contract_transition(
            baseline, candidate, allowed_changes=allowed
        )


def test_protocol_rejects_historical_output_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _protocol()
    payload["paths"]["remediation_external_roots"][0] = payload["paths"][
        "historical_external_roots"
    ][0]
    payload = _resign_protocol(payload, monkeypatch)
    with pytest.raises(ContractError, match="aliases historical evidence"):
        remediation.validate_protocol(payload, root=ROOT, verify_git=False)


def test_protocol_rejects_disabled_transparency_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _protocol()
    payload["mandatory_transparency_note"] = False
    payload = _resign_protocol(payload, monkeypatch)
    with pytest.raises(ContractError, match="transparency note was disabled"):
        remediation.validate_protocol(payload, root=ROOT, verify_git=False)


def test_protocol_rejects_changed_scientific_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _protocol()
    payload["scientific_boundary"]["scoring_changed"] = True
    payload = _resign_protocol(payload, monkeypatch)
    with pytest.raises(ContractError, match="scientific boundary changed"):
        remediation.validate_protocol(payload, root=ROOT, verify_git=False)


def test_canonical_source_hash_is_git_recoverable() -> None:
    payload = remediation.load_protocol(root=ROOT, verify_git=True)
    source = payload["canonical_source"]
    assert remediation.canonical_source_sha256(ROOT / source["path"]) == source[
        "canonical_sha256"
    ]
