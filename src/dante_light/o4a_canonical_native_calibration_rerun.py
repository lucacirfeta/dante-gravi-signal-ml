"""Frozen NATIVE_CALIBRATION continuation for the canonical O4a rerun.

The completed COHORT and INDEX controller remains immutable.  This module
extends the remediation by binding the calibration guard to the exact,
outcome-blind INDEX consumption manifest before delegating to the unchanged
historical calibration implementation.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light import o4a_canonical_provenance_rerun as base


ROOT = base.ROOT
AMENDMENT_REL = Path(
    "config/dante_o4a_canonical_provenance_native_calibration_runtime_amendment_v1.json"
)
INDEX_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/"
    "corrected_native_index.json"
)
EXPECTED_AMENDMENT_DIGEST = (
    "d2ff4cdf0af4df8c1cf7a883e813c1717972b72bb6791e812a5f630d492cccaa"
)
INDEX_ROW_FIELDS = {
    "cohort_index",
    "detector",
    "gps_start",
    "identity_digest",
    "clean_window_sha256",
    "context_sources_digest",
    "raw_context_sha256",
    "image_sha256",
    "patch_tokens_sha256",
}


def load_runtime_amendment(
    *, root: Path = ROOT, require_current: bool = False
) -> dict[str, Any]:
    """Validate the driver-only continuation for NATIVE_CALIBRATION."""

    root = root.resolve()
    path = root / AMENDMENT_REL
    if not path.is_file():
        raise ContractError("native-calibration runtime amendment is absent")
    value = json.loads(path.read_text(encoding="utf-8"))
    payload = dict(value)
    declared = payload.pop("amendment_digest", None)
    if (
        declared != EXPECTED_AMENDMENT_DIGEST
        or declared != canonical_json_sha256(payload)
    ):
        raise ContractError("native-calibration runtime amendment digest mismatch")
    if (
        value.get("schema_version") != base.SCHEMA_VERSION
        or value.get("status")
        != "FROZEN_BEFORE_NATIVE_CALIBRATION_RECOMPUTATION"
        or value.get("scope")
        != {
            "stage": "NATIVE_CALIBRATION",
            "allowed_contract_changes": ["/references/canonical_runtime/**"],
        }
    ):
        raise ContractError("native-calibration runtime amendment scope changed")
    parent_path = base._require_file_reference(
        root,
        value["parent_protocol"],
        label="native-calibration amendment parent protocol",
    )
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    if parent.get("protocol_digest") != value["parent_protocol"]["protocol_digest"]:
        raise ContractError("native-calibration amendment parent protocol mismatch")
    parent_amendment_path = base._require_file_reference(
        root,
        value["parent_runtime_amendment"],
        label="native-calibration parent runtime amendment",
    )
    parent_amendment = json.loads(parent_amendment_path.read_text(encoding="utf-8"))
    if (
        parent_amendment.get("amendment_digest")
        != value["parent_runtime_amendment"]["amendment_digest"]
    ):
        raise ContractError("native-calibration parent amendment digest mismatch")

    historical_path = base._require_file_reference(
        root, value["historical_runtime"], label="historical runtime contract"
    )
    remediation_path = base._require_file_reference(
        root, value["remediation_runtime"], label="remediation runtime contract"
    )
    from src.dante_light.o4a_corrected_runtime import (
        validate_canonical_runtime_contract,
    )

    historical = validate_canonical_runtime_contract(
        json.loads(historical_path.read_text(encoding="utf-8")),
        root=root,
        require_current=False,
    )
    remediation = validate_canonical_runtime_contract(
        json.loads(remediation_path.read_text(encoding="utf-8")),
        root=root,
        require_current=require_current,
        device="cuda",
    )
    for label, runtime, reference in (
        ("historical", historical, value["historical_runtime"]),
        ("remediation", remediation, value["remediation_runtime"]),
    ):
        if (
            runtime["contract_digest"] != reference["contract_digest"]
            or runtime["runtime_environment"]["environment_digest"]
            != reference["environment_digest"]
            or runtime["runtime_environment"]["cuda_device"]["driver_version"]
            != reference["driver_version"]
        ):
            raise ContractError(f"{label} runtime amendment binding mismatch")
    differences = base.json_leaf_differences(
        historical["runtime_environment"], remediation["runtime_environment"]
    )
    if differences != set(value["required_environment_differences"]):
        raise ContractError("native-calibration runtime amendment is not driver-only")
    expected_boundary = {
        "calibration_population_changed": False,
        "guard_geometry_changed": False,
        "outcome_firewall_changed": False,
        "package_versions_changed": False,
        "preprocessing_changed": False,
        "scoring_changed": False,
        "statistical_validation_changed": False,
        "thresholds_changed": False,
        "tolerances_changed": False,
    }
    if value.get("scientific_boundary") != expected_boundary:
        raise ContractError("native-calibration amendment scientific boundary changed")
    return value


def allowed_contract_changes(
    protocol: Mapping[str, Any], *, root: Path = ROOT
) -> list[str]:
    changes = list(base.stage_spec(protocol, "NATIVE_CALIBRATION")["allowed_changes"])
    amendment = load_runtime_amendment(root=root, require_current=False)
    changes.extend(amendment["scope"]["allowed_contract_changes"])
    return changes


def _load_pass_evidence(path: Path, *, status: str) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"verified evidence is absent: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != status:
        raise ContractError(f"verified evidence is not PASS: {path}")
    return value


def build_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Derive the calibration contract without changing scientific fields."""

    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "NATIVE_CALIBRATION")
    baseline = json.loads(
        (root / stage["baseline_contract"]["path"]).read_text(encoding="utf-8")
    )
    cohort_path = (root / base.COHORT_EVIDENCE_REL).resolve()
    index_path = (root / INDEX_EVIDENCE_REL).resolve()
    cohort = _load_pass_evidence(
        cohort_path, status="PASS_VERIFIED_CANONICAL_COHORT"
    )
    index = _load_pass_evidence(index_path, status="PASS_VERIFIED_CANONICAL_INDEX")
    consumption = index.get("consumption_manifest", {})
    if (
        cohort.get("row_total") != 1294
        or cohort.get("counts_by_detector") != {"H1": 647, "L1": 647}
        or index.get("counts_by_detector") != {"H1": 647, "L1": 647}
        or index.get("replay_ledger", {}).get("row_total") != 1294
        or consumption.get("row_total") != 1294
        or index.get("replay_ledger", {}).get("row_digest")
        != consumption.get("row_digest")
        or index.get("comparison_to_historical", {}).get("classification")
        != "SCIENTIFIC_PAYLOAD_BYTE_IDENTICAL"
    ):
        raise ContractError("verified COHORT or INDEX evidence boundary changed")

    amendment = load_runtime_amendment(root=root, require_current=False)
    runtime_reference = amendment["remediation_runtime"]
    candidate = copy.deepcopy(baseline)
    candidate["contract_id"] = (
        "dante-o4a-canonical-provenance-rerun-native-calibration-v1"
    )
    candidate["references"]["corrected_native_cohort"] = {
        "path": base.COHORT_EVIDENCE_REL.as_posix(),
        "sha256": base.sha256_file(cohort_path),
    }
    candidate["references"]["native_index_consumption_manifest"] = {
        "path": INDEX_EVIDENCE_REL.as_posix(),
        "sha256": base.sha256_file(index_path),
        "manifest_sha256": consumption["sha256"],
        "manifest_artifact_digest": consumption["artifact_digest"],
        "manifest_row_digest": consumption["row_digest"],
        "row_total": consumption["row_total"],
    }
    candidate["references"]["canonical_runtime"] = {
        "path": runtime_reference["path"],
        "sha256": runtime_reference["sha256"],
    }
    candidate["references"]["implementation"] = {
        "path": "src/dante_light/o4a_canonical_native_calibration_rerun.py",
        "sha256": base.sha256_file(Path(__file__).resolve()),
    }
    candidate["output"]["root"] = protocol["paths"][
        "remediation_external_roots"
    ][2]
    candidate["remediation"] = {
        "protocol_digest": protocol["protocol_digest"],
        "baseline_contract_sha256": stage["baseline_contract"]["sha256"],
        "runtime_amendment": {
            "path": AMENDMENT_REL.as_posix(),
            "digest": amendment["amendment_digest"],
        },
        "runtime_environment_digest": runtime_reference["environment_digest"],
        "cohort_artifact_digest": cohort["external_artifact_digest"],
        "cohort_ledger_sha256": cohort["ledger"]["sha256"],
        "index_artifact_digest": index["external_artifact_digest"],
        "index_consumption_manifest_sha256": consumption["sha256"],
        "index_consumption_manifest_artifact_digest": consumption["artifact_digest"],
        "index_consumption_manifest_row_digest": consumption["row_digest"],
        "historical_outputs_immutable": True,
        "outcomes_or_scores_read": False,
    }
    candidate["contract_digest"] = base.contract_digest(candidate)
    base.assert_allowed_contract_transition(
        baseline,
        candidate,
        allowed_changes=allowed_contract_changes(protocol, root=root),
    )
    from src.dante_light.o4a_corrected_native_calibration import (
        validate_native_calibration_contract,
    )

    return validate_native_calibration_contract(candidate, root=root)


def write_frozen_contract(*, root: Path = ROOT) -> Path:
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "NATIVE_CALIBRATION")
    target = base._inside_root(
        root,
        stage["remediation_contract"],
        label="NATIVE_CALIBRATION remediation contract",
    )
    candidate = build_contract(root=root)
    serialized = json.dumps(candidate, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if target.is_file():
        if target.read_text(encoding="utf-8") != serialized:
            raise ContractError(f"refusing divergent frozen contract: {target}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    temporary.replace(target)
    return target


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def verify_consumption_manifest(
    *,
    contract: Mapping[str, Any],
    manifest_path: Path,
    cohort_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Prove INDEX consumed exactly the guarded cohort, without outcomes."""

    reference = contract["references"]["native_index_consumption_manifest"]
    manifest_path = manifest_path.resolve()
    if (
        not manifest_path.is_file()
        or base.sha256_file(manifest_path) != reference["manifest_sha256"]
    ):
        raise ContractError("native index consumption manifest SHA-256 mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    body = dict(manifest)
    declared = body.pop("artifact_digest", None)
    rows = manifest.get("rows")
    boundary = manifest.get("scientific_boundary", {})
    if (
        declared != canonical_json_sha256(body)
        or declared != reference["manifest_artifact_digest"]
        or manifest.get("status") != "PASS_INDEX_CONSUMPTION_MANIFEST"
        or not isinstance(rows, list)
        or len(rows) != int(reference["row_total"])
        or manifest.get("row_total") != len(rows)
        or manifest.get("row_digest") != canonical_json_sha256(rows)
        or manifest.get("row_digest") != reference["manifest_row_digest"]
        or manifest.get("counts_by_detector") != {"H1": 647, "L1": 647}
        or boundary
        != {
            "derived_from_verified_index_replay_only": True,
            "outcomes_or_scores_included": False,
            "window_identity_changed": False,
        }
        or any(not isinstance(row, dict) or set(row) != INDEX_ROW_FIELDS for row in rows)
        or [int(row["cohort_index"]) for row in rows] != list(range(len(rows)))
    ):
        raise ContractError("native index consumption manifest boundary changed")
    cohort_identities = {
        (str(row["detector"]), float(row["gps_start"]), str(row["identity_digest"]))
        for row in cohort_rows
    }
    manifest_identities = {
        (str(row["detector"]), float(row["gps_start"]), str(row["identity_digest"]))
        for row in rows
    }
    if (
        len(cohort_identities) != len(cohort_rows)
        or len(manifest_identities) != len(rows)
        or manifest_identities != cohort_identities
    ):
        raise ContractError("INDEX consumption identities differ from COHORT")
    return {
        "filename": manifest_path.name,
        "sha256": reference["manifest_sha256"],
        "artifact_digest": declared,
        "row_digest": manifest["row_digest"],
        "row_total": len(rows),
        "outcomes_or_scores_included": False,
        "identity_set_equals_cohort": True,
    }


@contextmanager
def _use_runtime_contract(
    calibration_module: Any,
    runtime_module: Any,
    runtime_contract: Mapping[str, Any],
):
    def load_amended_runtime(
        *, root: Path = ROOT, require_current: bool = False, device: str = "cuda"
    ) -> dict[str, Any]:
        return runtime_module.validate_canonical_runtime_contract(
            copy.deepcopy(dict(runtime_contract)),
            root=root,
            require_current=require_current,
            device=device,
        )

    with base.use_module_attribute(
        calibration_module, "load_canonical_runtime_contract", load_amended_runtime
    ):
        yield


def _stage_inputs(
    *, root: Path, device: str
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "NATIVE_CALIBRATION")
    contract_path = base._inside_root(
        root, stage["remediation_contract"], label="NATIVE_CALIBRATION contract"
    )
    if not contract_path.is_file():
        raise ContractError("NATIVE_CALIBRATION remediation contract is not frozen")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    baseline = json.loads(
        (root / stage["baseline_contract"]["path"]).read_text(encoding="utf-8")
    )
    base.assert_allowed_contract_transition(
        baseline,
        contract,
        allowed_changes=allowed_contract_changes(protocol, root=root),
    )
    amendment = load_runtime_amendment(root=root, require_current=False)
    runtime_reference = amendment["remediation_runtime"]
    if contract["references"]["canonical_runtime"] != {
        "path": runtime_reference["path"],
        "sha256": runtime_reference["sha256"],
    }:
        raise ContractError("NATIVE_CALIBRATION runtime binding mismatch")
    runtime_path = base._inside_root(
        root, runtime_reference["path"], label="remediation runtime contract"
    )
    runtime_contract = json.loads(runtime_path.read_text(encoding="utf-8"))
    return protocol, contract_path, runtime_contract


def run(
    *, root: Path = ROOT, device: str = "cuda", verify_only: bool = False
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    """Run or verify NATIVE_CALIBRATION after the INDEX-consumption gate."""

    root = root.resolve()
    protocol, contract_path, runtime_contract = _stage_inputs(
        root=root, device=device
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    index = _load_pass_evidence(
        (root / INDEX_EVIDENCE_REL).resolve(),
        status="PASS_VERIFIED_CANONICAL_INDEX",
    )
    manifest_path = Path(index["external_run"]["directory"]) / str(
        index["consumption_manifest"]["filename"]
    )
    cohort = _load_pass_evidence(
        (root / base.COHORT_EVIDENCE_REL).resolve(),
        status="PASS_VERIFIED_CANONICAL_COHORT",
    )
    cohort_path = Path(cohort["external_run"]["directory"]) / str(
        cohort["external_run"]["ledger_filename"]
    )
    if base.sha256_file(cohort_path) != cohort["ledger"]["sha256"]:
        raise ContractError("verified remediation COHORT ledger changed")
    manifest_evidence = verify_consumption_manifest(
        contract=contract,
        manifest_path=manifest_path,
        cohort_rows=_load_jsonl(cohort_path),
    )

    from src.dante_light import o4a_corrected_native as cohort_module
    from src.dante_light import o4a_corrected_native_calibration as calibration_module
    from src.dante_light import o4a_corrected_runtime as runtime_module

    cohort_stage = base.stage_spec(protocol, "COHORT")
    stage = base.stage_spec(protocol, "NATIVE_CALIBRATION")
    common = {
        "root": root,
        "primary_external_root": Path(
            protocol["paths"]["primary_external_root_wsl"]
        ),
        "native_external_root": Path(
            protocol["paths"]["remediation_external_roots"][0]
        ),
        "external_root": Path(protocol["paths"]["remediation_external_roots"][2]),
        "device": device,
    }
    with base.use_stage_contract(cohort_module, cohort_stage["remediation_contract"]):
        with _use_runtime_contract(
            calibration_module, runtime_module, runtime_contract
        ):
            with base.use_stage_contract(
                calibration_module, stage["remediation_contract"]
            ):
                if verify_only:
                    summary, run_dir = (
                        calibration_module.verify_native_calibration_cohort(**common)
                    )
                else:
                    summary, run_dir = (
                        calibration_module.freeze_native_calibration_cohort(
                            raw_root=Path(protocol["paths"]["raw_root_wsl"]),
                            **common,
                        )
                    )
    return summary, run_dir, manifest_evidence


__all__ = [
    "AMENDMENT_REL",
    "EXPECTED_AMENDMENT_DIGEST",
    "INDEX_EVIDENCE_REL",
    "allowed_contract_changes",
    "build_contract",
    "load_runtime_amendment",
    "run",
    "verify_consumption_manifest",
    "write_frozen_contract",
]
