from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.dante_workflow.schema import (
    REQUIRED_STAGE_NAMES,
    WorkflowSchemaError,
    canonical_json_sha256,
    load_workflow_spec,
    validate_workflow_spec,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/dante_workflow_productization_v1.json"
FINAL_IMPACT_CONFIG = ROOT / "config/dante_o4a_final_impact_attribution_v1.json"


def _payload() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _resign(payload: dict) -> dict:
    body = deepcopy(payload)
    body.pop("contract_digest", None)
    payload["contract_digest"] = canonical_json_sha256(body)
    return payload


def _stage(payload: dict, name: str) -> dict:
    return next(stage for stage in payload["stages"] if stage["name"] == name)


def _all_mapping_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested
            for child in value.values()
            for nested in _all_mapping_keys(child)
        }
    if isinstance(value, list):
        return {
            nested for child in value for nested in _all_mapping_keys(child)
        }
    return set()


def test_frozen_o4a_workflow_validates_with_exact_stage_graph() -> None:
    spec = load_workflow_spec(CONFIG_PATH, root=ROOT)

    assert spec.topological_stage_names() == REQUIRED_STAGE_NAMES
    assert spec.workflow_id == "dante-o4a-corrected-productization-v1"
    assert spec.adapter == "o4a_corrected"
    assert len(spec.scientific_configs) == 14
    assert all(spec.policies.values())
    with pytest.raises(TypeError):
        spec.scientific_configs["protocol"] = spec.scientific_configs[  # type: ignore[index]
            "runtime"
        ]


def test_final_impact_contract_is_bound_to_portable_lf_bytes() -> None:
    payload = _payload()
    reference = payload["scientific_configs"]["final_impact_attribution"]
    content = FINAL_IMPACT_CONFIG.read_bytes()

    assert b"\r\n" not in content
    assert hashlib.sha256(content).hexdigest() == reference["sha256"]
    assert (
        "config/dante_o4a_final_impact_attribution_v1.json text eol=lf"
        in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    )


def test_native_calibration_uses_digested_index_window_manifest_gate() -> None:
    spec = load_workflow_spec(CONFIG_PATH, root=ROOT)
    native = spec.stage("NATIVE_CALIBRATION")
    gates = {(item.stage, item.gate, item.artifact) for item in native.dependencies}

    assert ("COHORT", "VERIFIED_STAGE", None) in gates
    assert (
        "INDEX",
        "CONTENT_DIGESTED_ARTIFACT",
        "index_window_manifest",
    ) in gates
    assert "index_window_manifest" in native.required_inputs
    assert "index_window_manifest" in spec.stage("INDEX").expected_outputs

    rescore_gates = {
        (item.stage, item.gate) for item in spec.stage("RESCORE").dependencies
    }
    assert rescore_gates == {
        ("INDEX", "VERIFIED_STAGE"),
        ("NATIVE_CALIBRATION", "VERIFIED_STAGE"),
    }


def test_native_provenance_is_bound_before_native_execution() -> None:
    spec = load_workflow_spec(CONFIG_PATH, root=ROOT)

    assert "native_provenance" in spec.stage("PREFLIGHT").config_refs
    assert "native_provenance" in spec.stage("COHORT").config_refs
    assert "native_provenance" in spec.stage("INDEX").config_refs


def test_workflow_references_science_without_copying_scientific_fields() -> None:
    payload = _payload()
    forbidden_copied_fields = {
        "K",
        "top_k",
        "percentile",
        "forbidden_guard_s",
        "equivalent_start_delta_s",
        "temporal_block_length",
        "target_rows_by_detector",
        "thresholds",
        "null_distribution",
    }

    assert not (forbidden_copied_fields & _all_mapping_keys(payload))
    assert all(
        set(reference) == {"path", "sha256"}
        for reference in payload["scientific_configs"].values()
    )


def test_unknown_workflow_field_fails_closed() -> None:
    payload = _payload()
    payload["scientific_override"] = {"top_k": 1}

    with pytest.raises(WorkflowSchemaError, match="unknown=.*scientific_override"):
        validate_workflow_spec(payload, root=ROOT)


def test_missing_scientific_config_digest_fails_closed() -> None:
    payload = _payload()
    payload["scientific_configs"]["native_calibration"].pop("sha256")
    _resign(payload)

    with pytest.raises(WorkflowSchemaError, match="missing=.*sha256"):
        validate_workflow_spec(payload, root=ROOT)


def test_changed_scientific_config_digest_fails_closed() -> None:
    payload = _payload()
    payload["scientific_configs"]["native_calibration"]["sha256"] = "0" * 64
    _resign(payload)

    with pytest.raises(WorkflowSchemaError, match="digest mismatch"):
        validate_workflow_spec(payload, root=ROOT)


def test_missing_native_index_manifest_gate_fails_closed() -> None:
    payload = _payload()
    native = _stage(payload, "NATIVE_CALIBRATION")
    native["dependencies"] = [
        dependency
        for dependency in native["dependencies"]
        if dependency["stage"] != "INDEX"
    ]
    native["required_inputs"].remove("index_window_manifest")
    _resign(payload)

    with pytest.raises(
        WorkflowSchemaError,
        match="content-digested INDEX window manifest",
    ):
        validate_workflow_spec(payload, root=ROOT)


def test_artifact_gate_must_name_an_upstream_declared_output() -> None:
    payload = _payload()
    native = _stage(payload, "NATIVE_CALIBRATION")
    dependency = next(
        item for item in native["dependencies"] if item["stage"] == "INDEX"
    )
    dependency["artifact"] = "unpublished_index_population"
    native["required_inputs"].append("unpublished_index_population")
    _resign(payload)

    with pytest.raises(WorkflowSchemaError, match="undeclared artifact"):
        validate_workflow_spec(payload, root=ROOT)


def test_missing_required_stage_fails_closed() -> None:
    payload = _payload()
    payload["stages"] = [
        stage for stage in payload["stages"] if stage["name"] != "REPORT"
    ]
    _resign(payload)

    with pytest.raises(WorkflowSchemaError, match="exactly the frozen 15-stage"):
        validate_workflow_spec(payload, root=ROOT)


def test_contract_digest_tampering_fails_closed() -> None:
    payload = _payload()
    payload["workflow_id"] = "tampered-workflow"

    with pytest.raises(WorkflowSchemaError, match="contract digest mismatch"):
        validate_workflow_spec(payload, root=ROOT)


def test_missing_verifier_program_fails_closed() -> None:
    payload = _payload()
    _stage(payload, "REPORT")["verifier_command"][1] = "scripts/not_present.py"
    _resign(payload)

    with pytest.raises(WorkflowSchemaError, match="verifier is absent"):
        validate_workflow_spec(payload, root=ROOT)


def test_disabled_product_policy_fails_closed() -> None:
    payload = _payload()
    payload["policies"]["hide_outcomes_until_verified"] = False
    _resign(payload)

    with pytest.raises(WorkflowSchemaError, match="policy must remain enabled|policies.*enabled|every frozen"):
        validate_workflow_spec(payload, root=ROOT)
