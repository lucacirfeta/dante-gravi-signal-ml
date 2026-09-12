from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


def test_runtime_amendment_is_driver_only_and_index_scoped() -> None:
    amendment = remediation.load_runtime_amendment(
        root=ROOT, require_current=False
    )
    assert amendment["scope"] == {
        "stage": "INDEX",
        "allowed_contract_changes": [
            "/references/canonical_runtime/**",
            "/runtime/canonical_runtime_contract_digest",
        ],
    }
    assert amendment["required_environment_differences"] == [
        "/cuda_device/driver_version",
        "/environment_digest",
    ]
    assert amendment["scientific_boundary"]["tolerances_changed"] is False


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


def test_built_cohort_contract_preserves_scientific_sections() -> None:
    protocol = remediation.load_protocol(root=ROOT, verify_git=True)
    stage = remediation.stage_spec(protocol, "COHORT")
    baseline = json.loads(
        (ROOT / stage["baseline_contract"]["path"]).read_text(encoding="utf-8")
    )
    candidate = remediation.build_cohort_contract(root=ROOT)
    remediation.assert_allowed_contract_transition(
        baseline, candidate, allowed_changes=stage["allowed_changes"]
    )
    for key in (
        "historical_parity",
        "cohort",
        "preprocessing",
        "clustering",
        "gates",
    ):
        assert candidate[key] == baseline[key]


def test_frozen_cohort_contract_matches_deterministic_builder() -> None:
    protocol = remediation.load_protocol(root=ROOT, verify_git=True)
    stage = remediation.stage_spec(protocol, "COHORT")
    frozen = json.loads(
        (ROOT / stage["remediation_contract"]).read_text(encoding="utf-8")
    )
    assert frozen == remediation.build_cohort_contract(root=ROOT)


def test_built_index_contract_preserves_scientific_sections() -> None:
    protocol = remediation.load_protocol(root=ROOT, verify_git=True)
    stage = remediation.stage_spec(protocol, "INDEX")
    baseline = json.loads(
        (ROOT / stage["baseline_contract"]["path"]).read_text(encoding="utf-8")
    )
    candidate = remediation.build_index_contract(root=ROOT)
    remediation.assert_allowed_contract_transition(
        baseline,
        candidate,
        allowed_changes=remediation.stage_allowed_changes(
            protocol, "INDEX", root=ROOT
        ),
    )
    for key in (
        "scientific_boundary",
        "preprocessing",
        "representation",
        "clustering",
        "token_order",
        "output",
        "gates",
    ):
        assert candidate[key] == baseline[key]
    assert candidate["runtime"] == {
        **baseline["runtime"],
        "canonical_runtime_contract_digest": (
            "0e09de34355d8530e630740d7d640698df68acee2bf5167eabc337d6389d1db2"
        ),
    }
    assert candidate["parent_native_contract_digest"] == (
        "ddca4c6e8e791f1242c2b289d51781ea874f0b5031a187c887fe029472acbe80"
    )
    assert candidate["remediation"]["index_consumption_manifest_required"] is True
    assert candidate["remediation"]["runtime_amendment"]["digest"] == (
        remediation.EXPECTED_RUNTIME_AMENDMENT_DIGEST
    )


def test_frozen_index_contract_matches_deterministic_builder() -> None:
    protocol = remediation.load_protocol(root=ROOT, verify_git=True)
    stage = remediation.stage_spec(protocol, "INDEX")
    frozen = json.loads(
        (ROOT / stage["remediation_contract"]).read_text(encoding="utf-8")
    )
    assert frozen == remediation.build_index_contract(root=ROOT)


def test_index_consumption_manifest_is_exact_and_outcome_blind() -> None:
    summary = {
        "run_key": "a" * 64,
        "contract_digest": "b" * 64,
        "cohort_artifact_digest": "c" * 64,
        "cohort_row_total": 2,
        "counts_by_detector": {"H1": 1, "L1": 1},
        "replay_ledger": {
            "filename": "native_index_replay.jsonl",
            "sha256": "d" * 64,
            "row_digest": "e" * 64,
            "row_total": 2,
        },
    }
    rows = [
        {
            "cohort_index": index,
            "detector": detector,
            "gps_start": 1000.0 + index,
            "identity_digest": f"{index + 1:064x}",
            "clean_window_sha256": f"{index + 2:064x}",
            "context_sources_digest": f"{index + 3:064x}",
            "raw_context_sha256": f"{index + 4:064x}",
            "image_sha256": f"{index + 5:064x}",
            "patch_tokens_sha256": f"{index + 6:064x}",
            "unused_diagnostic": "not copied",
        }
        for index, detector in enumerate(("H1", "L1"))
    ]
    manifest = remediation.build_index_consumption_manifest(summary, rows)
    assert manifest["status"] == "PASS_INDEX_CONSUMPTION_MANIFEST"
    assert manifest["row_total"] == 2
    assert manifest["counts_by_detector"] == {"H1": 1, "L1": 1}
    assert "unused_diagnostic" not in manifest["rows"][0]
    assert manifest["scientific_boundary"]["outcomes_or_scores_included"] is False


def test_index_consumption_manifest_rejects_noncontiguous_order() -> None:
    summary = {
        "run_key": "a" * 64,
        "contract_digest": "b" * 64,
        "cohort_artifact_digest": "c" * 64,
        "cohort_row_total": 1,
        "counts_by_detector": {"H1": 1, "L1": 0},
        "replay_ledger": {},
    }
    row = {
        "cohort_index": 1,
        "detector": "H1",
        "gps_start": 1000.0,
        "identity_digest": "1" * 64,
        "clean_window_sha256": "2" * 64,
        "context_sources_digest": "3" * 64,
        "raw_context_sha256": "4" * 64,
        "image_sha256": "5" * 64,
        "patch_tokens_sha256": "6" * 64,
    }
    with pytest.raises(ContractError, match="cohort order"):
        remediation.build_index_consumption_manifest(summary, [row])


def test_stage_contract_routing_is_restored() -> None:
    module = SimpleNamespace(CONTRACT_REL=Path("legacy.json"))
    with remediation.use_stage_contract(module, "remediation.json"):
        assert module.CONTRACT_REL == Path("remediation.json")
    assert module.CONTRACT_REL == Path("legacy.json")


def test_tracked_clean_uses_shared_checkout_normalization() -> None:
    with patch(
        "src.dante_light.o4a_canonical_provenance_rerun.subprocess.check_output",
        return_value="",
    ) as check:
        remediation.require_tracked_clean(ROOT)
    command = check.call_args.args[0]
    assert command[:4] == ["git", "-c", "core.autocrlf=true", "status"]
