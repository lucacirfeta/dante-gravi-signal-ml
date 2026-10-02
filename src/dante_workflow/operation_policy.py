"""Run-independent execution permissions and bounded retained receipt checks.

This policy constrains orchestration. It neither certifies a reader as read-only
nor replaces its scientific verifier; adapters must explicitly support it.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .schema import WorkflowSchemaError, canonical_json_sha256, _exact_keys, _identifier
from .schema_v2 import strict_json_object


EXECUTE_AND_VERIFY = "EXECUTE_AND_VERIFY"
VERIFY_RETAINED_ONLY = "VERIFY_RETAINED_ONLY"
RETAINED_PASS = "PASS_VERIFIED_RETAINED_WORKFLOW_EVIDENCE"


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    mode: str
    stage_receipts: Mapping[str, Mapping[str, str]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "stage_receipts",
            MappingProxyType(
                {
                    stage: MappingProxyType(dict(claim))
                    for stage, claim in self.stage_receipts.items()
                }
            ),
        )


def validate_operation_policy(value: Any, stages: list[dict]) -> OperationPolicy:
    if not isinstance(value, Mapping):
        raise WorkflowSchemaError("operation policy must be an object")
    _exact_keys(value, {"mode", "stage_receipts"}, "operation policy")
    mode = value["mode"]
    if mode not in (EXECUTE_AND_VERIFY, VERIFY_RETAINED_ONLY):
        raise WorkflowSchemaError("unsupported operation policy mode")
    claims = value["stage_receipts"]
    if not isinstance(claims, Mapping):
        raise WorkflowSchemaError("stage receipt policies must be an object")
    if mode == EXECUTE_AND_VERIFY:
        if claims:
            raise WorkflowSchemaError(
                "execution policy cannot declare retained receipts"
            )
    else:
        if set(claims) != {stage["name"] for stage in stages}:
            raise WorkflowSchemaError("retained receipt policy must cover every stage")
        for stage, claim in claims.items():
            if not isinstance(claim, Mapping):
                raise WorkflowSchemaError(
                    "retained stage receipt policy must be an object"
                )
            _exact_keys(claim, {"status", "verification_level", "seal_field"}, stage)
            status = _identifier(claim["status"], "retained PASS status")
            if not status.startswith("PASS_") or status in {
                "PASS_VERIFIED_WORKFLOW",
                RETAINED_PASS,
            }:
                raise WorkflowSchemaError(
                    "retained stage requires a scoped PASS status"
                )
            _identifier(claim["verification_level"], "retained verification level")
            if not isinstance(claim["seal_field"], str) or claim["seal_field"] not in {
                "receipt_digest",
                "artifact_digest",
            }:
                raise WorkflowSchemaError("unsupported retained receipt seal field")
        # Every stage needs a wrapper as well as any semantic population manifest.
        for stage in stages:
            if not set(stage["expected_outputs"]) - {
                "native_cohort_manifest",
                "index_window_manifest",
            }:
                raise WorkflowSchemaError(
                    "retained stage requires a scoped wrapper output"
                )
    return OperationPolicy(mode, claims)


def retained_stage_evidence(spec, stage: str, stdout: str) -> dict[str, Any]:
    """Admit only the stage's sealed, frozen, explicitly bounded PASS payload."""
    policy = spec.graph_profile.operation_policy
    claim = policy.stage_receipts[stage]
    value = strict_json_object(stdout, label=f"{stage} retained verifier output")
    if value.get("status") != claim["status"]:
        raise WorkflowSchemaError(f"{stage} retained verifier PASS status differs")
    if value.get("verification_level") != claim["verification_level"]:
        raise WorkflowSchemaError(f"{stage} retained verification level differs")
    if value.get("full_workflow_verified") is not False:
        raise WorkflowSchemaError(f"{stage} retained verifier scope is not bounded")
    body = dict(value)
    seal = body.pop(claim["seal_field"], None)
    if seal != canonical_json_sha256(body):
        raise WorkflowSchemaError(f"{stage} retained verifier receipt seal mismatch")
    return {
        "status": value["status"],
        "verification_level": value["verification_level"],
        "full_workflow_verified": False,
        "seal_field": claim["seal_field"],
        "receipt_digest": seal,
    }
