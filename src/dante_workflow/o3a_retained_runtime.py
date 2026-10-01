"""Explicit author waiver of driver metadata for retained-only readers.

Never used by productive dante_light entrypoints. Frozen identities remain
unchanged; the actual driver/fingerprint are disclosed, not called equivalent.
"""

from __future__ import annotations

import copy
import json

from .o3a_initial_verification import InitialEvidenceError, _Evidence, _existing, _json

POLICY_REL = "config/dante_workflow_o3a_retained_driver_waiver_v1.json"
POLICY = {
    "schema_version": 1,
    "status": "AUTHOR_APPROVED_O3A_RETAINED_DRIVER_METADATA_WAIVER_V1",
    "author_authorization": {
        "date": "2026-10-01",
        "instruction": "lascia perdere la versione nvidia",
        "scope": "explicit_opt_in_read_only_retained_O3a_evidence",
    },
    "ignored_metadata_fields": ["cuda_device.driver_version"],
    "derived_digest_handling": "validate_both_then_recompute_after_single_field_normalization",
    "other_runtime_fields": "exact_frozen_equality",
    "during_replay_runtime": "exact_observed_fingerprint_stability",
    "boundary": {
        "numerical_driver_equivalence_proved": False,
        "productive_runtime_contract_changed": False,
        "fresh_scoring_authorized": False,
        "fresh_sensor_or_null_replay_authorized": False,
        "full_workflow_verified": False,
    },
}


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def compare_retained_runtime(frozen, observed):
    """Allow exactly the named driver field, not arbitrary CUDA/runtime drift."""
    from src.dante_light.contracts import canonical_json_sha256

    for value in (frozen, observed):
        body = copy.deepcopy(value)
        digest = body.pop("environment_digest", None)
        if digest != canonical_json_sha256(body):
            raise InitialEvidenceError("retained runtime environment seal changed")
        driver = body["cuda_device"]["driver_version"]
        if not isinstance(driver, str) or not driver.strip():
            raise InitialEvidenceError("retained runtime driver metadata is absent")
    normalized = copy.deepcopy(observed)
    normalized.pop("environment_digest")
    normalized["cuda_device"]["driver_version"] = frozen["cuda_device"][
        "driver_version"
    ]
    normalized["environment_digest"] = canonical_json_sha256(normalized)
    if _encoded(normalized) != _encoded(frozen):
        raise InitialEvidenceError("retained runtime differs beyond driver metadata")
    return {
        "policy_id": POLICY["status"],
        "driver_version_comparison_waived": True,
        "driver_version_changed": frozen["cuda_device"]["driver_version"]
        != observed["cuda_device"]["driver_version"],
        "frozen_driver_version": frozen["cuda_device"]["driver_version"],
        "observed_driver_version": observed["cuda_device"]["driver_version"],
        "frozen_environment_digest": frozen["environment_digest"],
        "observed_environment_digest": observed["environment_digest"],
        "other_runtime_fields_match": True,
        "boundary": copy.deepcopy(POLICY["boundary"]),
    }


class RetainedRuntimeEvidence(_Evidence):
    """Per-invocation opt-in, shared by existing read-only parent gates."""

    def __init__(self, root):
        super().__init__()
        value = _json(self.read("retained_driver_policy", _existing(root, POLICY_REL)))
        if _encoded(value) != _encoded(POLICY):
            raise InitialEvidenceError("retained driver waiver policy changed")
        self._observed = None
        self._qualification = None

    def load_runtime(self, loader, *, root):
        from src.dante_light.o3a_native_contract import _capture_o3a_runtime

        frozen = loader(root=root, require_current=False)
        observed = _capture_o3a_runtime("cuda")
        qualification = compare_retained_runtime(
            frozen["runtime_environment"], observed
        )
        if self._observed is not None and observed != self._observed:
            raise InitialEvidenceError("runtime changed during retained replay")
        if self._qualification is not None and qualification != self._qualification:
            raise InitialEvidenceError(
                "frozen runtime changed between retained parents"
            )
        self._observed = copy.deepcopy(observed)
        self._qualification = copy.deepcopy(qualification)
        # Historical keys and parent bindings must retain the original identity.
        return frozen

    def unchanged(self):
        super().unchanged()
        if self._observed is None:
            raise InitialEvidenceError("retained runtime was never checked")
        from src.dante_light.o3a_native_contract import _capture_o3a_runtime

        if _capture_o3a_runtime("cuda") != self._observed:
            raise InitialEvidenceError("runtime changed during retained replay")

    def qualification(self):
        if self._qualification is None:
            raise InitialEvidenceError("retained runtime was never checked")
        value = copy.deepcopy(self._qualification)
        value["policy_sha256"] = self.inputs["retained_driver_policy"]["sha256"]
        return value


def load_runtime(evidence, loader, *, root):
    if isinstance(evidence, RetainedRuntimeEvidence):
        return evidence.load_runtime(loader, root=root)
    return loader(root=root, require_current=True)


def new_evidence(root, *, allow_retained_driver_drift=False):
    if type(allow_retained_driver_drift) is not bool:
        raise InitialEvidenceError("retained driver opt-in must be boolean")
    return RetainedRuntimeEvidence(root) if allow_retained_driver_drift else _Evidence()


def receipt_fields(evidence):
    if isinstance(evidence, RetainedRuntimeEvidence):
        return {"retained_runtime_qualification": evidence.qualification()}
    return {}
