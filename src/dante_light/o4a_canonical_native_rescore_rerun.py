"""Frozen RESCORE continuation for the canonical O4a provenance rerun.

This controller binds the unchanged historical native-rescore-v2 algorithm to
the independently verified remediation INDEX and NATIVE_CALIBRATION parents.
It changes only provenance references, the isolated output root, and the
driver-only runtime reference authorized for this stage.
"""

from __future__ import annotations

import copy
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
from typing import Any, Iterator, Mapping

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light import o4a_canonical_provenance_rerun as base
from src.dante_light import o4a_canonical_native_calibration_rerun as calibration_remediation
from src.dante_light.o4a_native_provenance import verify_reference_with_reconciliation


ROOT = base.ROOT
AMENDMENT_REL = Path(
    "config/dante_o4a_canonical_provenance_rescore_runtime_amendment_v1.json"
)
CALIBRATION_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/"
    "corrected_native_calibration.json"
)
INDEX_EVIDENCE_REL = calibration_remediation.INDEX_EVIDENCE_REL
RESCORE_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/"
    "corrected_native_rescore.json"
)
HISTORICAL_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/corrected_native_rescore_v2.json"
)
EXPECTED_AMENDMENT_DIGEST = (
    "a08e3532e3fce9b263e09620a2f83262259b8cd5e4d10afc6685900bae9bb5d9"
)


def _load_pass_evidence(path: Path, *, status: str) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"verified evidence is absent: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != status:
        raise ContractError(f"verified evidence is not PASS: {path}")
    return value


def load_runtime_amendment(
    *, root: Path = ROOT, require_current: bool = False
) -> dict[str, Any]:
    """Validate the stage-scoped driver-only RESCORE continuation."""

    root = root.resolve()
    path = root / AMENDMENT_REL
    if not path.is_file():
        raise ContractError("RESCORE runtime amendment is absent")
    value = json.loads(path.read_text(encoding="utf-8"))
    payload = dict(value)
    declared = payload.pop("amendment_digest", None)
    if (
        declared != EXPECTED_AMENDMENT_DIGEST
        or declared != canonical_json_sha256(payload)
    ):
        raise ContractError("RESCORE runtime amendment digest mismatch")
    if (
        value.get("schema_version") != base.SCHEMA_VERSION
        or value.get("status") != "FROZEN_BEFORE_RESCORE_RECOMPUTATION"
        or value.get("scope")
        != {
            "stage": "RESCORE",
            "allowed_contract_changes": ["/references/canonical_runtime/**"],
        }
    ):
        raise ContractError("RESCORE runtime amendment scope changed")
    protocol_path = base._require_file_reference(
        root, value["parent_protocol"], label="RESCORE amendment parent protocol"
    )
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("protocol_digest") != value["parent_protocol"]["protocol_digest"]:
        raise ContractError("RESCORE amendment parent protocol mismatch")
    parent_path = base._require_file_reference(
        root,
        value["parent_runtime_amendment"],
        label="RESCORE parent runtime amendment",
    )
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    if (
        parent.get("amendment_digest")
        != value["parent_runtime_amendment"]["amendment_digest"]
    ):
        raise ContractError("RESCORE parent amendment digest mismatch")

    from src.dante_light.o4a_corrected_runtime import (
        validate_canonical_runtime_contract,
    )

    historical_path = base._require_file_reference(
        root, value["historical_runtime"], label="historical runtime contract"
    )
    remediation_path = base._require_file_reference(
        root, value["remediation_runtime"], label="remediation runtime contract"
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
            raise ContractError(f"{label} RESCORE runtime binding mismatch")
    differences = base.json_leaf_differences(
        historical["runtime_environment"], remediation["runtime_environment"]
    )
    if differences != set(value["required_environment_differences"]):
        raise ContractError("RESCORE runtime amendment is not driver-only")
    expected_boundary = {
        "candidate_population_changed": False,
        "calibration_population_changed": False,
        "index_scientific_payload_changed": False,
        "package_versions_changed": False,
        "preprocessing_changed": False,
        "scoring_changed": False,
        "thresholds_or_classes_computed": False,
        "thresholds_changed": False,
        "tolerances_changed": False,
    }
    if value.get("scientific_boundary") != expected_boundary:
        raise ContractError("RESCORE amendment scientific boundary changed")
    return value


def allowed_contract_changes(
    protocol: Mapping[str, Any], *, root: Path = ROOT
) -> list[str]:
    changes = list(base.stage_spec(protocol, "RESCORE")["allowed_changes"])
    amendment = load_runtime_amendment(root=root, require_current=False)
    changes.extend(amendment["scope"]["allowed_contract_changes"])
    return changes


def validate_contract(
    contract: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    """Validate the frozen transition without the historical hard-coded parents."""

    root = root.resolve()
    candidate = json.loads(json.dumps(contract))
    declared = candidate.get("contract_digest")
    if declared != base.contract_digest(candidate):
        raise ContractError("canonical RESCORE contract digest mismatch")
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "RESCORE")
    baseline = json.loads(
        (root / stage["baseline_contract"]["path"]).read_text(encoding="utf-8")
    )
    base.assert_allowed_contract_transition(
        baseline,
        candidate,
        allowed_changes=allowed_contract_changes(protocol, root=root),
    )
    for name, reference in candidate.get("references", {}).items():
        path = base._inside_root(
            root, reference["path"], label=f"RESCORE {name}"
        )
        verify_reference_with_reconciliation(
            root=root,
            path=path,
            expected_sha256=str(reference["sha256"]),
            raw_hasher=sha256_file,
        )
    remediation = candidate.get("remediation", {})
    for name in ("historical_rescore_evidence", "delegated_implementation"):
        reference = remediation[name]
        path = base._inside_root(
            root, reference["path"], label=f"RESCORE remediation {name}"
        )
        verify_reference_with_reconciliation(
            root=root,
            path=path,
            expected_sha256=str(reference["sha256"]),
            raw_hasher=sha256_file,
        )
    if remediation.get("historical_outputs_immutable") is not True:
        raise ContractError("RESCORE historical outputs are not immutable")
    if remediation.get("thresholds_or_classes_computed") is not False:
        raise ContractError("RESCORE attempted to compute thresholds or classes")
    return candidate


def build_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Derive the RESCORE contract while preserving all scientific fields."""

    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "RESCORE")
    baseline = json.loads(
        (root / stage["baseline_contract"]["path"]).read_text(encoding="utf-8")
    )
    calibration_path = (root / CALIBRATION_EVIDENCE_REL).resolve()
    index_path = (root / INDEX_EVIDENCE_REL).resolve()
    calibration = _load_pass_evidence(
        calibration_path, status="PASS_VERIFIED_CANONICAL_NATIVE_CALIBRATION"
    )
    index = _load_pass_evidence(
        index_path, status="PASS_VERIFIED_CANONICAL_INDEX"
    )
    if (
        calibration.get("row_total") != 10_000
        or calibration.get("counts_by_detector") != {"H1": 5000, "L1": 5000}
        or calibration.get("comparison_to_historical", {}).get("classification")
        != "BYTE_IDENTICAL"
        or index.get("comparison_to_historical", {}).get("classification")
        != "SCIENTIFIC_PAYLOAD_BYTE_IDENTICAL"
        or index.get("index", {}).get("centroid_shape") != [1216, 384]
    ):
        raise ContractError("verified RESCORE parent evidence boundary changed")
    amendment = load_runtime_amendment(root=root, require_current=False)
    runtime_reference = amendment["remediation_runtime"]

    candidate = copy.deepcopy(baseline)
    candidate["contract_id"] = "dante-o4a-canonical-provenance-rerun-rescore-v1"
    candidate["parent_native_calibration"] = {
        "contract_digest": calibration["contract_digest"],
        "artifact_digest": calibration["external_artifact_digest"],
        "ledger_sha256": calibration["ledger"]["sha256"],
    }
    candidate["parent_native_index"] = {
        "contract_digest": index["contract_digest"],
        "artifact_digest": index["external_artifact_digest"],
        "index_sha256": index["index"]["sha256"],
    }
    candidate["references"]["corrected_native_calibration_v2"] = {
        "path": CALIBRATION_EVIDENCE_REL.as_posix(),
        "sha256": sha256_file(calibration_path),
    }
    candidate["references"]["corrected_native_index"] = {
        "path": INDEX_EVIDENCE_REL.as_posix(),
        "sha256": sha256_file(index_path),
    }
    candidate["references"]["canonical_runtime"] = {
        "path": runtime_reference["path"],
        "sha256": runtime_reference["sha256"],
    }
    candidate["references"]["implementation"] = {
        "path": "src/dante_light/o4a_canonical_native_rescore_rerun.py",
        "sha256": sha256_file(Path(__file__).resolve()),
    }
    candidate["output"]["root"] = protocol["paths"][
        "remediation_external_roots"
    ][3]
    candidate["remediation"] = {
        "protocol_digest": protocol["protocol_digest"],
        "baseline_contract_sha256": stage["baseline_contract"]["sha256"],
        "runtime_amendment": {
            "path": AMENDMENT_REL.as_posix(),
            "digest": amendment["amendment_digest"],
        },
        "runtime_environment_digest": runtime_reference["environment_digest"],
        "calibration_evidence_sha256": sha256_file(calibration_path),
        "index_evidence_sha256": sha256_file(index_path),
        "historical_rescore_evidence": {
            "path": HISTORICAL_EVIDENCE_REL.as_posix(),
            "sha256": sha256_file((root / HISTORICAL_EVIDENCE_REL).resolve()),
        },
        "delegated_implementation": {
            "path": "src/dante_light/o4a_corrected_native_rescore_v2.py",
            "sha256": sha256_file(
                root / "src/dante_light/o4a_corrected_native_rescore_v2.py"
            ),
        },
        "historical_outputs_immutable": True,
        "index_scientific_payload_byte_identical": True,
        "thresholds_or_classes_computed": False,
    }
    candidate["contract_digest"] = base.contract_digest(candidate)
    return validate_contract(candidate, root=root)


def write_frozen_contract(*, root: Path = ROOT) -> Path:
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "RESCORE")
    target = base._inside_root(
        root, stage["remediation_contract"], label="RESCORE remediation contract"
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


def _load_runtime_contract(
    *, root: Path, require_current: bool, device: str
) -> dict[str, Any]:
    amendment = load_runtime_amendment(root=root, require_current=False)
    reference = amendment["remediation_runtime"]
    path = base._inside_root(root, reference["path"], label="RESCORE runtime")
    from src.dante_light.o4a_corrected_runtime import (
        validate_canonical_runtime_contract,
    )

    return validate_canonical_runtime_contract(
        json.loads(path.read_text(encoding="utf-8")),
        root=root,
        require_current=require_current,
        device=device,
    )


def _verified_parents(
    *, root: Path, device: str
) -> tuple[
    dict[str, Any], Path, dict[str, Any], Path, dict[str, Any], Path, dict[str, Any]
]:
    calibration_summary, calibration_dir, _manifest = calibration_remediation.run(
        root=root, device=device, verify_only=True
    )
    index_summary, index_dir = base.run_index(
        root=root, device=device, verify_only=True
    )
    from src.dante_light.o4a_corrected_execution import verify_primary_scan

    protocol = base.load_protocol(root=root, verify_git=True)
    scan_summary, scan_dir = verify_primary_scan(
        root=root,
        external_root=Path(protocol["paths"]["primary_external_root_wsl"]),
    )
    runtime = _load_runtime_contract(
        root=root, require_current=True, device=device
    )
    return (
        calibration_summary,
        calibration_dir,
        index_summary,
        index_dir,
        scan_summary,
        scan_dir,
        runtime,
    )


@contextmanager
def _patched_rescore_module(
    *, root: Path, contract: Mapping[str, Any], device: str
) -> Iterator[Any]:
    from src.dante_light import o4a_corrected_native_rescore_v2 as module

    parents = _verified_parents(root=root, device=device)

    def load_contract(_root: Path = ROOT) -> dict[str, Any]:
        del _root
        return copy.deepcopy(dict(contract))

    def verify_calibration(**_kwargs: Any) -> tuple[dict[str, Any], Path]:
        return parents[0], parents[1]

    def verify_index(**_kwargs: Any) -> tuple[dict[str, Any], Path]:
        return parents[2], parents[3]

    def verify_scan(**_kwargs: Any) -> tuple[dict[str, Any], Path]:
        return parents[4], parents[5]

    def load_runtime(
        *, root: Path = ROOT, require_current: bool = False, device: str = "cuda"
    ) -> dict[str, Any]:
        del root, require_current, device
        return copy.deepcopy(parents[6])

    with ExitStack() as stack:
        for attribute, value in (
            ("load_native_rescore_v2_contract", load_contract),
            ("verify_native_calibration_cohort", verify_calibration),
            ("verify_native_index", verify_index),
            ("verify_primary_scan", verify_scan),
            ("load_canonical_runtime_contract", load_runtime),
        ):
            stack.enter_context(base.use_module_attribute(module, attribute, value))
        yield module


def _frozen_contract(*, root: Path) -> dict[str, Any]:
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "RESCORE")
    path = base._inside_root(
        root, stage["remediation_contract"], label="RESCORE remediation contract"
    )
    if not path.is_file():
        raise ContractError("RESCORE remediation contract is not frozen")
    return validate_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def run(
    *, root: Path = ROOT, device: str = "cuda", verify_only: bool = False
) -> tuple[dict[str, Any], Path]:
    """Run or verify RESCORE using only verified remediation parents."""

    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    contract = _frozen_contract(root=root)
    common = {
        "root": root,
        "primary_external_root": Path(
            protocol["paths"]["primary_external_root_wsl"]
        ),
        "native_external_root": Path(
            protocol["paths"]["remediation_external_roots"][0]
        ),
        "calibration_external_root": Path(
            protocol["paths"]["remediation_external_roots"][2]
        ),
        "index_external_root": Path(
            protocol["paths"]["remediation_external_roots"][1]
        ),
        "external_root": Path(protocol["paths"]["remediation_external_roots"][3]),
        "device": device,
    }
    with _patched_rescore_module(root=root, contract=contract, device=device) as module:
        if verify_only:
            return module.verify_native_rescore_v2(**common)
        return module.run_native_rescore_v2(
            raw_root=Path(protocol["paths"]["raw_root_wsl"]),
            workers=int(contract["execution"]["workers"]),
            batch_size=int(contract["execution"]["batch_size"]),
            **common,
        )


def _external_path(value: str) -> Path:
    normalized = value.replace("\\", "/")
    if os.name != "nt" and len(normalized) >= 3 and normalized[1:3] == ":/":
        return Path("/mnt") / normalized[0].lower() / normalized[3:]
    return Path(normalized)


def compare_to_historical(
    *, root: Path, summary: Mapping[str, Any], run_dir: Path
) -> dict[str, Any]:
    """Compare verified output ledgers without deriving downstream decisions."""

    contract = _frozen_contract(root=root)
    reference = contract["remediation"]["historical_rescore_evidence"]
    historical_path = base._require_file_reference(
        root, reference, label="historical RESCORE evidence"
    )
    historical = _load_pass_evidence(
        historical_path, status="PASS_VERIFIED_NATIVE_RESCORE_V2"
    )
    historical_dir = _external_path(historical["external_run"]["directory"])
    comparisons: dict[str, Any] = {}
    all_bytes_equal = True
    for name, current_meta in summary["outputs"].items():
        historical_meta = historical["outputs"][name]
        current_path = run_dir / str(current_meta["filename"])
        old_path = historical_dir / str(historical_meta["filename"])
        if not old_path.is_file():
            raise ContractError(f"historical RESCORE output is absent: {old_path}")
        old_sha = sha256_file(old_path)
        if old_sha != historical_meta["sha256"]:
            raise ContractError("historical RESCORE output SHA-256 changed")
        bytes_equal = current_path.read_bytes() == old_path.read_bytes()
        all_bytes_equal = all_bytes_equal and bytes_equal
        comparisons[name] = {
            "row_total": int(current_meta["row_total"]),
            "historical_sha256": old_sha,
            "new_sha256": sha256_file(current_path),
            "bytes_equal": bytes_equal,
            "historical_row_digest": historical_meta["row_digest"],
            "new_row_digest": current_meta["row_digest"],
        }
    return {
        "classification": "BYTE_IDENTICAL" if all_bytes_equal else "OUTPUT_CHANGED",
        "all_output_ledgers_byte_identical": all_bytes_equal,
        "outputs": comparisons,
        "thresholds_or_classes_compared": False,
    }


def write_verified_evidence(*, root: Path = ROOT, device: str = "cuda") -> Path:
    """Persist compact RESCORE evidence only after independent verification."""

    root = root.resolve()
    summary, run_dir = run(root=root, device=device, verify_only=True)
    contract = _frozen_contract(root=root)
    comparison = compare_to_historical(
        root=root, summary=summary, run_dir=run_dir
    )
    contract_path = root / base.stage_spec(
        base.load_protocol(root=root, verify_git=True), "RESCORE"
    )["remediation_contract"]
    body = {
        "schema_version": base.SCHEMA_VERSION,
        "status": "PASS_VERIFIED_CANONICAL_RESCORE",
        "run_key": summary["run_key"],
        "contract_digest": summary["contract_digest"],
        "runtime_environment_digest": summary["runtime_environment_digest"],
        "calibration_artifact_digest": summary["calibration_artifact_digest"],
        "index_artifact_digest": summary["index_artifact_digest"],
        "primary_scan_artifact_digest": summary["primary_scan_artifact_digest"],
        "row_total": summary["row_total"],
        "input_counts": summary["input_counts"],
        "outputs": summary["outputs"],
        "gates": summary["gates"],
        "comparison_to_historical": comparison,
        "scientific_boundary": contract["scientific_boundary"],
        "external_run": {
            "directory": os.fspath(run_dir),
            "summary_filename": "native_rescore_summary.json",
            "summary_sha256": sha256_file(run_dir / "native_rescore_summary.json"),
        },
        "references": {
            "contract": {
                "path": contract_path.relative_to(root).as_posix(),
                "sha256": sha256_file(contract_path),
            },
            "implementation": contract["references"]["implementation"],
            "runtime_amendment": {
                "path": AMENDMENT_REL.as_posix(),
                "sha256": sha256_file(root / AMENDMENT_REL),
                "digest": EXPECTED_AMENDMENT_DIGEST,
            },
        },
        "verification": {
            "independent_verifier": "PASS",
            "failure_artifact_absent": not (run_dir / "failure.json").is_file(),
            "thresholds_or_classes_computed": False,
        },
    }
    evidence = {**body, "artifact_digest": canonical_json_sha256(body)}
    target = root / RESCORE_EVIDENCE_REL
    base._atomic_json(target, evidence)
    return target


__all__ = [
    "AMENDMENT_REL",
    "EXPECTED_AMENDMENT_DIGEST",
    "RESCORE_EVIDENCE_REL",
    "allowed_contract_changes",
    "build_contract",
    "compare_to_historical",
    "load_runtime_amendment",
    "run",
    "validate_contract",
    "write_frozen_contract",
    "write_verified_evidence",
]
