from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light import o4a_canonical_provenance_rerun as remediation
from src.dante_light import o4a_canonical_native_calibration_rerun as calibration_remediation
from src.dante_light import o4a_canonical_native_rescore_rerun as rescore_remediation


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


def test_native_calibration_runtime_amendment_is_driver_only_and_stage_scoped() -> None:
    amendment = calibration_remediation.load_runtime_amendment(
        root=ROOT, require_current=False
    )
    assert amendment["scope"] == {
        "stage": "NATIVE_CALIBRATION",
        "allowed_contract_changes": ["/references/canonical_runtime/**"],
    }
    assert amendment["required_environment_differences"] == [
        "/cuda_device/driver_version",
        "/environment_digest",
    ]
    assert amendment["scientific_boundary"]["calibration_population_changed"] is False
    assert amendment["scientific_boundary"]["tolerances_changed"] is False


def test_rescore_runtime_amendment_is_driver_only_and_stage_scoped() -> None:
    amendment = rescore_remediation.load_runtime_amendment(
        root=ROOT, require_current=False
    )
    assert amendment["scope"] == {
        "stage": "RESCORE",
        "allowed_contract_changes": ["/references/canonical_runtime/**"],
    }
    assert amendment["required_environment_differences"] == [
        "/cuda_device/driver_version",
        "/environment_digest",
    ]
    assert amendment["scientific_boundary"]["scoring_changed"] is False
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


def test_runtime_amendment_allowlists_are_stage_scoped() -> None:
    protocol = remediation.load_protocol(root=ROOT, verify_git=True)
    cohort_changes = remediation.stage_allowed_changes(protocol, "COHORT", root=ROOT)
    index_changes = remediation.stage_allowed_changes(protocol, "INDEX", root=ROOT)
    calibration_changes = calibration_remediation.allowed_contract_changes(
        protocol, root=ROOT
    )
    amendment = remediation.load_runtime_amendment(
        root=ROOT, require_current=False
    )
    amendment_changes = amendment["scope"]["allowed_contract_changes"]

    assert cohort_changes == remediation.stage_spec(protocol, "COHORT")[
        "allowed_changes"
    ]
    assert all(change not in cohort_changes for change in amendment_changes)
    assert all(change in index_changes for change in amendment_changes)
    calibration_amendment = calibration_remediation.load_runtime_amendment(
        root=ROOT, require_current=False
    )
    calibration_amendment_changes = calibration_amendment["scope"][
        "allowed_contract_changes"
    ]
    assert all(change not in cohort_changes for change in calibration_amendment_changes)
    assert all(change in calibration_changes for change in calibration_amendment_changes)
    assert "/runtime/canonical_runtime_contract_digest" not in calibration_changes


def test_index_runtime_injection_does_not_mutate_historical_runtime_path() -> None:
    calls: list[dict[str, object]] = []

    def validate(payload: object, **kwargs: object) -> dict[str, object]:
        calls.append({"payload": payload, **kwargs})
        return {"validated": True}

    original_loader = object()
    index_module = SimpleNamespace(load_canonical_runtime_contract=original_loader)
    runtime_module = SimpleNamespace(
        OUTPUT_REL="config/dante_o4a_corrected_runtime_v1.json",
        validate_canonical_runtime_contract=validate,
    )
    amended = {"contract_digest": "a" * 64}

    with remediation.use_index_runtime_contract(
        index_module, runtime_module, amended
    ):
        assert index_module.load_canonical_runtime_contract(
            root=ROOT, require_current=True, device="cuda"
        ) == {"validated": True}
        assert runtime_module.OUTPUT_REL == (
            "config/dante_o4a_corrected_runtime_v1.json"
        )

    assert index_module.load_canonical_runtime_contract is original_loader
    assert calls == [
        {
            "payload": amended,
            "root": ROOT,
            "require_current": True,
            "device": "cuda",
        }
    ]


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


def test_built_native_calibration_contract_preserves_scientific_sections() -> None:
    protocol = remediation.load_protocol(root=ROOT, verify_git=True)
    stage = remediation.stage_spec(protocol, "NATIVE_CALIBRATION")
    baseline = json.loads(
        (ROOT / stage["baseline_contract"]["path"]).read_text(encoding="utf-8")
    )
    candidate = calibration_remediation.build_contract(root=ROOT)
    remediation.assert_allowed_contract_transition(
        baseline,
        candidate,
        allowed_changes=calibration_remediation.allowed_contract_changes(
            protocol, root=ROOT
        ),
    )
    for key in (
        "population",
        "scientific_boundary",
        "future_threshold_contract",
        "execution",
        "gates",
    ):
        assert candidate[key] == baseline[key]
    manifest = candidate["references"]["native_index_consumption_manifest"]
    assert manifest["row_total"] == 1294
    assert candidate["remediation"]["outcomes_or_scores_read"] is False


def test_frozen_native_calibration_contract_matches_deterministic_builder() -> None:
    protocol = remediation.load_protocol(root=ROOT, verify_git=True)
    stage = remediation.stage_spec(protocol, "NATIVE_CALIBRATION")
    frozen = json.loads(
        (ROOT / stage["remediation_contract"]).read_text(encoding="utf-8")
    )
    assert frozen == calibration_remediation.build_contract(root=ROOT)


def test_built_rescore_contract_preserves_scientific_sections() -> None:
    protocol = remediation.load_protocol(root=ROOT, verify_git=True)
    stage = remediation.stage_spec(protocol, "RESCORE")
    baseline = json.loads(
        (ROOT / stage["baseline_contract"]["path"]).read_text(encoding="utf-8")
    )
    candidate = rescore_remediation.build_contract(root=ROOT)
    remediation.assert_allowed_contract_transition(
        baseline,
        candidate,
        allowed_changes=rescore_remediation.allowed_contract_changes(
            protocol, root=ROOT
        ),
    )
    for key in (
        "scientific_boundary",
        "preprocessing",
        "scoring",
        "execution",
        "gates",
    ):
        assert candidate[key] == baseline[key]
    assert candidate["parent_native_calibration"]["contract_digest"] == (
        "e79fe3f6fef1af5d84e9aab6e535761cd52f13c61ac7a588eeebad7ec5c32327"
    )
    assert candidate["parent_native_index"]["contract_digest"] == (
        "7c2446b50f4c3abe2d182954ef9d9ed460b84ffb7f37271efea6ceca75c4eaa9"
    )
    assert candidate["remediation"]["thresholds_or_classes_computed"] is False


def test_frozen_rescore_contract_matches_deterministic_builder() -> None:
    protocol = remediation.load_protocol(root=ROOT, verify_git=True)
    stage = remediation.stage_spec(protocol, "RESCORE")
    frozen = json.loads(
        (ROOT / stage["remediation_contract"]).read_text(encoding="utf-8")
    )
    assert frozen == rescore_remediation.build_contract(root=ROOT)


def _index_manifest_fixture(tmp_path: Path) -> tuple[dict, Path, list[dict]]:
    rows = []
    for cohort_index in range(1294):
        detector = "H1" if cohort_index < 647 else "L1"
        rows.append(
            {
                "cohort_index": cohort_index,
                "detector": detector,
                "gps_start": float(1000 + cohort_index * 64),
                "identity_digest": f"{cohort_index + 1:064x}",
                "clean_window_sha256": f"{cohort_index + 2:064x}",
                "context_sources_digest": f"{cohort_index + 3:064x}",
                "raw_context_sha256": f"{cohort_index + 4:064x}",
                "image_sha256": f"{cohort_index + 5:064x}",
                "patch_tokens_sha256": f"{cohort_index + 6:064x}",
            }
        )
    body = {
        "schema_version": 1,
        "status": "PASS_INDEX_CONSUMPTION_MANIFEST",
        "row_total": len(rows),
        "counts_by_detector": {"H1": 647, "L1": 647},
        "rows": rows,
        "row_digest": canonical_json_sha256(rows),
        "scientific_boundary": {
            "derived_from_verified_index_replay_only": True,
            "outcomes_or_scores_included": False,
            "window_identity_changed": False,
        },
    }
    manifest = {**body, "artifact_digest": canonical_json_sha256(body)}
    path = tmp_path / "native_index_consumption_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    contract = {
        "references": {
            "native_index_consumption_manifest": {
                "manifest_sha256": remediation.sha256_file(path),
                "manifest_artifact_digest": manifest["artifact_digest"],
                "manifest_row_digest": manifest["row_digest"],
                "row_total": len(rows),
            }
        }
    }
    cohort_rows = [
        {
            "detector": row["detector"],
            "gps_start": row["gps_start"],
            "identity_digest": row["identity_digest"],
        }
        for row in rows
    ]
    return contract, path, cohort_rows


def test_native_calibration_replays_exact_outcome_blind_index_manifest(
    tmp_path: Path,
) -> None:
    contract, path, cohort_rows = _index_manifest_fixture(tmp_path)
    evidence = calibration_remediation.verify_consumption_manifest(
        contract=contract,
        manifest_path=path,
        cohort_rows=cohort_rows,
    )
    assert evidence["row_total"] == 1294
    assert evidence["outcomes_or_scores_included"] is False
    assert evidence["identity_set_equals_cohort"] is True


def test_native_calibration_rejects_outcome_in_index_manifest(tmp_path: Path) -> None:
    contract, path, cohort_rows = _index_manifest_fixture(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["rows"][0]["score"] = 1.0
    body = dict(manifest)
    body.pop("artifact_digest")
    manifest["row_digest"] = canonical_json_sha256(manifest["rows"])
    body = dict(manifest)
    body.pop("artifact_digest")
    manifest["artifact_digest"] = canonical_json_sha256(body)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    reference = contract["references"]["native_index_consumption_manifest"]
    reference["manifest_sha256"] = remediation.sha256_file(path)
    reference["manifest_artifact_digest"] = manifest["artifact_digest"]
    reference["manifest_row_digest"] = manifest["row_digest"]
    with pytest.raises(ContractError, match="boundary changed"):
        calibration_remediation.verify_consumption_manifest(
            contract=contract,
            manifest_path=path,
            cohort_rows=cohort_rows,
        )


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
