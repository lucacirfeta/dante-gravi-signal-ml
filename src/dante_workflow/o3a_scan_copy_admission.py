"""Explicit receipt-pinned isolated SCAN SQL input for retained-only readers."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re

from . import o3a_scan_copy as transport
from .o3a_initial_verification import InitialEvidenceError, _Evidence
from .o3a_locking import clean_native_parent
from .o3a_retained_runtime import RetainedRuntimeEvidence


def source_bindings(root):
    result = transport._sources(root)
    relative = "src/dante_workflow/o3a_scan_copy_admission.py"
    value = transport._sha(Path(__file__).read_bytes())
    if transport._sha((root / relative).read_bytes()) != value:
        raise InitialEvidenceError("executed scan copy admission source mismatch")
    result[relative] = value
    return result


class _Admission:
    def __init__(self, root, directory, expected_sha256):
        if not isinstance(expected_sha256, str) or not re.fullmatch(
            "[0-9a-f]{64}", expected_sha256
        ):
            raise InitialEvidenceError(
                "scan copy receipt SHA256 must be explicit lowercase hex"
            )
        self.root, self.directory = root, Path(directory)
        self.expected_sha256 = expected_sha256
        self.receipt = self.stack = self.origin = self.output_pins = None

    def _held(self):
        if self.origin.resolve() not in getattr(self.stack, "_dante_native_locks", {}):
            raise InitialEvidenceError(
                "isolated scan admission requires original held SCAN lock"
            )
        clean_native_parent(self.origin, stack=self.stack)

    def select(self, *, evidence, path, summary, stack):
        from src.dante_light.contracts import canonical_json_sha256

        if self.receipt is not None:
            raise InitialEvidenceError("isolated scan input admitted twice")
        self.origin, self.stack = path.parent, stack
        self._held()
        transport._safe_output(self.directory, self.origin, self.root)
        self.output_identity = transport._directory_identity(self.directory)
        self.policy, policy_sha = transport._policy(self.root)
        payload, self.receipt_pin = transport._read(
            self.directory / "receipt.json", self.policy["limits"]["metadata_bytes"]
        )
        if transport._sha(payload) != self.expected_sha256:
            raise InitialEvidenceError("isolated scan external receipt hash mismatch")
        receipt = json.loads(payload)
        body = dict(receipt)
        seal = body.pop("receipt_digest", None)
        if seal != canonical_json_sha256(body):
            raise InitialEvidenceError("isolated scan receipt seal changed")
        observed_summary, payloads, pins = transport._observe(self.origin, self.policy)
        if transport._encoded(observed_summary) != transport._encoded(summary):
            raise InitialEvidenceError(
                "isolated scan summary differs from retained gate"
            )
        sources = transport._sources(self.root)
        expected = {
            "schema_version": 1,
            "status": transport.STATUS,
            "run_key": summary["run_key"],
            "contract_digest": summary["contract_digest"],
            "source_run_dir": str(self.origin),
            "summary_artifact_digest": summary["artifact_digest"],
            "policy_sha256": policy_sha,
            "source_bindings": sources,
            "origin_pins": pins,
            "lock_input": evidence.inputs["scan_lock"],
            "files": {
                transport.FILES[name]: {
                    "sha256": pins[name]["sha256"],
                    "size_bytes": pins[name]["size_bytes"],
                }
                for name in payloads
            },
            "boundary": self.policy["boundary"],
        }
        if transport._encoded(body) != transport._encoded(expected):
            raise InitialEvidenceError(
                "isolated scan receipt origin/policy/source identity mismatch"
            )
        self.output_pins = transport._verify_files(
            self.directory, body["files"], self.policy, receipt_present=True
        )
        self.receipt = receipt
        self.database_filename = summary["database"]["filename"]
        evidence.inputs["scan_copy_receipt"] = {
            "path": str(self.directory / "receipt.json"),
            "sha256": self.expected_sha256,
        }
        evidence.inputs["scan_copy_policy"] = {
            "path": str(self.root / transport.POLICY_REL),
            "sha256": policy_sha,
        }
        for name, pin in self.output_pins.items():
            evidence.inputs["scan_copy_file:" + name] = {
                "path": str(self.directory / name),
                "sha256": pin["sha256"],
            }
        self.unchanged()
        return self.directory / transport.FILES["database"]

    def unchanged(self):
        if self.receipt is None:
            raise InitialEvidenceError("isolated scan input was never admitted")
        self._held()
        if (
            transport._observe(self.origin, self.policy)[2]
            != self.receipt["origin_pins"]
            or transport._sources(self.root) != self.receipt["source_bindings"]
        ):
            raise InitialEvidenceError("isolated scan original evidence/source changed")
        if (
            transport._verify_files(
                self.directory, self.receipt["files"], self.policy, receipt_present=True
            )
            != self.output_pins
            or transport._directory_identity(self.directory) != self.output_identity
        ):
            raise InitialEvidenceError("isolated scan copy evidence changed")
        payload, pin = transport._read(
            self.directory / "receipt.json", self.policy["limits"]["metadata_bytes"]
        )
        if pin != self.receipt_pin or transport._sha(payload) != self.expected_sha256:
            raise InitialEvidenceError("isolated scan copy receipt changed")

    def qualification(self):
        if self.receipt is None:
            raise InitialEvidenceError("isolated scan input was never admitted")
        return {
            "status": "ADMITTED_BYTE_IDENTICAL_ISOLATED_SCAN_SQL_INPUT_ONLY_V1",
            "directory": str(self.directory),
            "receipt_sha256": self.expected_sha256,
            "receipt_digest": self.receipt["receipt_digest"],
            "source_run_dir": str(self.origin),
            "database_sha256": self.receipt["origin_pins"]["database"]["sha256"],
            "database_size_bytes": self.receipt["origin_pins"]["database"][
                "size_bytes"
            ],
            "historical_database_filename": self.database_filename,
            "original_sidecar_pins": copy.deepcopy(
                {
                    k: self.receipt["origin_pins"][k]
                    for k in ("-wal", "-shm", "-journal")
                }
            ),
            "transport_boundary": copy.deepcopy(self.policy["boundary"]),
        }


class _CopyMixin:
    def unchanged(self):
        super().unchanged()
        self._scan_copy.unchanged()

    def scan_copy_qualification(self):
        return self._scan_copy.qualification()


class ScanCopyEvidence(_CopyMixin, _Evidence):
    pass


class RuntimeScanCopyEvidence(_CopyMixin, RetainedRuntimeEvidence):
    pass


def new_copy_evidence(root, *, directory, expected_sha256, allow_retained_driver_drift):
    evidence = (
        RuntimeScanCopyEvidence(root)
        if allow_retained_driver_drift
        else ScanCopyEvidence()
    )
    evidence._scan_copy = _Admission(root, directory, expected_sha256)
    return evidence


def select_scan_database(evidence, *, path, summary, stack):
    if isinstance(evidence, _CopyMixin):
        return evidence._scan_copy.select(
            evidence=evidence, path=path, summary=summary, stack=stack
        )
    return path


def scan_database_filename(evidence, path):
    """Physical isolated name is not a new historical SCAN container identity."""
    if isinstance(evidence, _CopyMixin):
        admission = evidence._scan_copy
        if (
            admission.receipt is None
            or path != admission.directory / transport.FILES["database"]
        ):
            raise InitialEvidenceError(
                "isolated scan SQL path differs from admitted input"
            )
        return admission.database_filename
    return path.name
