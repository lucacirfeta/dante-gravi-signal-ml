"""Frozen THRESHOLDS continuation for the canonical O4a provenance rerun."""

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
from src.dante_light import o4a_canonical_native_rescore_rerun as rescore_remediation
from src.dante_light.o4a_native_provenance import verify_reference_with_reconciliation


ROOT = base.ROOT
AMENDMENT_REL = Path(
    "config/dante_o4a_canonical_provenance_thresholds_runtime_amendment_v1.json"
)
RESCORE_EVIDENCE_REL = rescore_remediation.RESCORE_EVIDENCE_REL
THRESHOLDS_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/"
    "corrected_native_thresholds.json"
)
HISTORICAL_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/corrected_native_thresholds.json"
)
EXPECTED_AMENDMENT_DIGEST = (
    "754e62f2af1ba47e996382c2527cb1636206c506daa7f7fbec91f14e4502421d"
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"required JSON evidence is absent: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def load_runtime_amendment(
    *, root: Path = ROOT, require_current: bool = False
) -> dict[str, Any]:
    root = root.resolve()
    path = root / AMENDMENT_REL
    value = _read_json(path)
    payload = dict(value)
    declared = payload.pop("amendment_digest", None)
    if (
        declared != EXPECTED_AMENDMENT_DIGEST
        or declared != canonical_json_sha256(payload)
    ):
        raise ContractError("THRESHOLDS runtime amendment digest mismatch")
    if (
        value.get("schema_version") != base.SCHEMA_VERSION
        or value.get("status") != "FROZEN_BEFORE_THRESHOLDS_RECOMPUTATION"
        or value.get("scope")
        != {
            "stage": "THRESHOLDS",
            "allowed_contract_changes": ["/references/canonical_runtime/**"],
        }
    ):
        raise ContractError("THRESHOLDS runtime amendment scope changed")
    protocol_path = base._require_file_reference(
        root,
        value["parent_protocol"],
        label="THRESHOLDS amendment parent protocol",
    )
    protocol = _read_json(protocol_path)
    if protocol.get("protocol_digest") != value["parent_protocol"]["protocol_digest"]:
        raise ContractError("THRESHOLDS amendment parent protocol mismatch")
    parent_path = base._require_file_reference(
        root,
        value["parent_runtime_amendment"],
        label="THRESHOLDS parent runtime amendment",
    )
    parent = _read_json(parent_path)
    if (
        parent.get("amendment_digest")
        != value["parent_runtime_amendment"]["amendment_digest"]
    ):
        raise ContractError("THRESHOLDS parent amendment digest mismatch")

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
        _read_json(historical_path), root=root, require_current=False
    )
    remediation = validate_canonical_runtime_contract(
        _read_json(remediation_path),
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
            raise ContractError(f"{label} THRESHOLDS runtime binding mismatch")
    if base.json_leaf_differences(
        historical["runtime_environment"], remediation["runtime_environment"]
    ) != set(value["required_environment_differences"]):
        raise ContractError("THRESHOLDS runtime amendment is not driver-only")
    if value.get("scientific_boundary") != {
        "bootstrap_changed": False,
        "calibration_population_changed": False,
        "classification_computed": False,
        "package_versions_changed": False,
        "point_estimator_changed": False,
        "threshold_definition_changed": False,
        "thresholds_changed_before_recomputation": False,
        "tolerances_changed": False,
    }:
        raise ContractError("THRESHOLDS amendment scientific boundary changed")
    return value


def allowed_contract_changes(
    protocol: Mapping[str, Any], *, root: Path = ROOT
) -> list[str]:
    changes = list(base.stage_spec(protocol, "THRESHOLDS")["allowed_changes"])
    amendment = load_runtime_amendment(root=root, require_current=False)
    changes.extend(amendment["scope"]["allowed_contract_changes"])
    return changes


def _verify_reference(root: Path, reference: Mapping[str, Any], label: str) -> Path:
    path = base._inside_root(root, reference["path"], label=label)
    verify_reference_with_reconciliation(
        root=root,
        path=path,
        expected_sha256=str(reference["sha256"]),
        raw_hasher=sha256_file,
    )
    return path


def validate_contract(
    contract: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    root = root.resolve()
    candidate = json.loads(json.dumps(contract))
    if candidate.get("contract_digest") != base.contract_digest(candidate):
        raise ContractError("canonical THRESHOLDS contract digest mismatch")
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "THRESHOLDS")
    baseline = _read_json(root / stage["baseline_contract"]["path"])
    base.assert_allowed_contract_transition(
        baseline,
        candidate,
        allowed_changes=allowed_contract_changes(protocol, root=root),
    )
    for name, reference in candidate.get("references", {}).items():
        _verify_reference(root, reference, f"THRESHOLDS {name}")
    remediation = candidate.get("remediation", {})
    for name in ("historical_thresholds_evidence", "delegated_implementation"):
        _verify_reference(
            root, remediation[name], f"THRESHOLDS remediation {name}"
        )
    if (
        remediation.get("historical_outputs_immutable") is not True
        or remediation.get("classification_computed") is not False
    ):
        raise ContractError("THRESHOLDS remediation boundary changed")
    return candidate


def _external_path(value: str) -> Path:
    normalized = value.replace("\\", "/")
    if os.name == "nt" and normalized.startswith("/mnt/"):
        parts = normalized.lstrip("/").split("/", 2)
        if len(parts) == 3 and parts[0] == "mnt" and len(parts[1]) == 1:
            return Path(f"{parts[1].upper()}:/") / parts[2]
    if os.name != "nt" and len(normalized) >= 3 and normalized[1:3] == ":/":
        return Path("/mnt") / normalized[0].lower() / normalized[3:]
    return Path(normalized)


def build_contract(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "THRESHOLDS")
    baseline = _read_json(root / stage["baseline_contract"]["path"])
    evidence_path = (root / RESCORE_EVIDENCE_REL).resolve()
    evidence = _read_json(evidence_path)
    if (
        evidence.get("status") != "PASS_VERIFIED_CANONICAL_RESCORE"
        or evidence.get("row_total") != 20_942
        or evidence.get("comparison_to_historical", {}).get("classification")
        != "BYTE_IDENTICAL"
        or evidence.get("verification", {}).get("thresholds_or_classes_computed")
        is not False
    ):
        raise ContractError("verified RESCORE evidence boundary changed")
    run_dir = _external_path(evidence["external_run"]["directory"])
    summary_path = run_dir / evidence["external_run"]["summary_filename"]
    if sha256_file(summary_path) != evidence["external_run"]["summary_sha256"]:
        raise ContractError("verified RESCORE summary hash changed")
    run_summary = _read_json(summary_path)
    amendment = load_runtime_amendment(root=root, require_current=False)
    runtime_reference = amendment["remediation_runtime"]

    candidate = copy.deepcopy(baseline)
    candidate["contract_id"] = "dante-o4a-canonical-provenance-rerun-thresholds-v1"
    candidate["parent_native_rescore"] = {
        "compact_artifact_digest": evidence["artifact_digest"],
        "contract_digest": evidence["contract_digest"],
        "run_artifact_digest": run_summary["artifact_digest"],
        "run_summary_sha256": evidence["external_run"]["summary_sha256"],
        "run_key": evidence["run_key"],
    }
    candidate["references"]["native_rescore_v2"] = {
        "path": RESCORE_EVIDENCE_REL.as_posix(),
        "sha256": sha256_file(evidence_path),
    }
    candidate["references"]["canonical_runtime"] = {
        "path": runtime_reference["path"],
        "sha256": runtime_reference["sha256"],
    }
    candidate["references"]["implementation"] = {
        "path": "src/dante_light/o4a_canonical_native_thresholds_rerun.py",
        "sha256": sha256_file(Path(__file__).resolve()),
    }
    candidate["output"]["root"] = protocol["paths"][
        "remediation_external_roots"
    ][4]
    candidate["remediation"] = {
        "protocol_digest": protocol["protocol_digest"],
        "baseline_contract_sha256": stage["baseline_contract"]["sha256"],
        "runtime_amendment": {
            "path": AMENDMENT_REL.as_posix(),
            "digest": amendment["amendment_digest"],
        },
        "runtime_environment_digest": runtime_reference["environment_digest"],
        "rescore_evidence_sha256": sha256_file(evidence_path),
        "historical_thresholds_evidence": {
            "path": HISTORICAL_EVIDENCE_REL.as_posix(),
            "sha256": sha256_file((root / HISTORICAL_EVIDENCE_REL).resolve()),
        },
        "delegated_implementation": {
            "path": "src/dante_light/o4a_corrected_native_thresholds.py",
            "sha256": sha256_file(
                root / "src/dante_light/o4a_corrected_native_thresholds.py"
            ),
        },
        "historical_outputs_immutable": True,
        "rescore_ledgers_byte_identical": True,
        "classification_computed": False,
    }
    candidate["contract_digest"] = base.contract_digest(candidate)
    return validate_contract(candidate, root=root)


def write_frozen_contract(*, root: Path = ROOT) -> Path:
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "THRESHOLDS")
    target = base._inside_root(
        root, stage["remediation_contract"], label="THRESHOLDS remediation contract"
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


def _load_runtime(
    *, root: Path, require_current: bool, device: str
) -> dict[str, Any]:
    amendment = load_runtime_amendment(root=root, require_current=False)
    reference = amendment["remediation_runtime"]
    path = base._inside_root(root, reference["path"], label="THRESHOLDS runtime")
    from src.dante_light.o4a_corrected_runtime import (
        validate_canonical_runtime_contract,
    )

    return validate_canonical_runtime_contract(
        _read_json(path),
        root=root,
        require_current=require_current,
        device=device,
    )


@contextmanager
def _patched_thresholds_module(
    *, root: Path, contract: Mapping[str, Any], device: str
) -> Iterator[Any]:
    from src.dante_light import o4a_corrected_native_thresholds as module

    rescore_summary, rescore_dir = rescore_remediation.run(
        root=root, device=device, verify_only=True
    )
    runtime = _load_runtime(root=root, require_current=True, device=device)

    def load_contract(_root: Path = ROOT) -> dict[str, Any]:
        del _root
        return copy.deepcopy(dict(contract))

    def verify_rescore(**_kwargs: Any) -> tuple[dict[str, Any], Path]:
        return rescore_summary, rescore_dir

    def load_runtime(
        *, root: Path = ROOT, require_current: bool = False, device: str = "cuda"
    ) -> dict[str, Any]:
        del root, require_current, device
        return copy.deepcopy(runtime)

    with ExitStack() as stack:
        for attribute, value in (
            ("load_native_threshold_contract", load_contract),
            ("verify_native_rescore_v2", verify_rescore),
            ("load_canonical_runtime_contract", load_runtime),
        ):
            stack.enter_context(base.use_module_attribute(module, attribute, value))
        yield module


def _frozen_contract(*, root: Path) -> dict[str, Any]:
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "THRESHOLDS")
    path = base._inside_root(
        root, stage["remediation_contract"], label="THRESHOLDS remediation contract"
    )
    if not path.is_file():
        raise ContractError("THRESHOLDS remediation contract is not frozen")
    return validate_contract(_read_json(path), root=root)


def run(
    *, root: Path = ROOT, device: str = "cuda", verify_only: bool = False
) -> tuple[dict[str, Any], Path]:
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
        "rescore_external_root": Path(
            protocol["paths"]["remediation_external_roots"][3]
        ),
        "external_root": Path(protocol["paths"]["remediation_external_roots"][4]),
        "device": device,
    }
    with _patched_thresholds_module(
        root=root, contract=contract, device=device
    ) as module:
        if verify_only:
            return module.verify_native_thresholds(**common)
        return module.run_native_thresholds(**common)


def compare_to_historical(
    *, root: Path, summary: Mapping[str, Any]
) -> dict[str, Any]:
    contract = _frozen_contract(root=root)
    historical_path = _verify_reference(
        root,
        contract["remediation"]["historical_thresholds_evidence"],
        "historical THRESHOLDS evidence",
    )
    historical = _read_json(historical_path)
    if historical.get("status") != "PASS_VERIFIED_NATIVE_THRESHOLDS_V1":
        raise ContractError("historical THRESHOLDS evidence is not PASS")
    historical_run = historical.get("external_run", {})
    historical_summary_path = _external_path(
        historical_run["directory"]
    ) / historical_run["summary_filename"]
    if sha256_file(historical_summary_path) != historical_run["summary_sha256"]:
        raise ContractError("historical THRESHOLDS summary hash changed")
    historical_summary = _read_json(historical_summary_path)
    comparisons = {
        "method_equal": summary.get("method") == historical_summary.get("method"),
        "thresholds_equal": summary.get("thresholds")
        == historical_summary.get("thresholds"),
        "gates_equal": summary.get("gates") == historical_summary.get("gates"),
    }
    for detector in ("H1", "L1"):
        comparisons[f"{detector}_input_score_vector_equal"] = (
            summary["inputs"][detector]["score_vector_float64_sha256"]
            == historical_summary["inputs"][detector][
                "score_vector_float64_sha256"
            ]
        )
        comparisons[f"{detector}_identity_score_digest_equal"] = (
            summary["inputs"][detector]["identity_score_digest"]
            == historical_summary["inputs"][detector]["identity_score_digest"]
        )
    all_equal = all(comparisons.values())
    return {
        "classification": (
            "SCIENTIFIC_OUTPUT_IDENTICAL" if all_equal else "OUTPUT_CHANGED"
        ),
        "all_scientific_values_identical": all_equal,
        "checks": comparisons,
    }


def write_verified_evidence(*, root: Path = ROOT, device: str = "cuda") -> Path:
    root = root.resolve()
    summary, run_dir = run(root=root, device=device, verify_only=True)
    contract = _frozen_contract(root=root)
    comparison = compare_to_historical(root=root, summary=summary)
    contract_path = root / base.stage_spec(
        base.load_protocol(root=root, verify_git=True), "THRESHOLDS"
    )["remediation_contract"]
    summary_path = run_dir / contract["output"]["summary_filename"]
    body = {
        "schema_version": base.SCHEMA_VERSION,
        "status": "PASS_VERIFIED_CANONICAL_THRESHOLDS",
        "run_key": summary["run_key"],
        "contract_digest": summary["contract_digest"],
        "external_artifact_digest": summary["artifact_digest"],
        "native_rescore_artifact_digest": summary[
            "native_rescore_artifact_digest"
        ],
        "runtime_environment_digest": summary["runtime_environment_digest"],
        "method": summary["method"],
        "inputs": summary["inputs"],
        "thresholds": summary["thresholds"],
        "gates": summary["gates"],
        "scientific_boundary": summary["scientific_boundary"],
        "comparison_to_historical": comparison,
        "external_run": {
            "directory": os.fspath(run_dir),
            "summary_filename": summary_path.name,
            "summary_sha256": sha256_file(summary_path),
            "summary_size_bytes": summary_path.stat().st_size,
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
            "independent_verifier": "PASS_EXACT_REPLAY",
            "failure_artifact_absent": not (run_dir / "failure.json").is_file(),
            "classification_computed": False,
        },
    }
    evidence = {**body, "artifact_digest": canonical_json_sha256(body)}
    target = root / THRESHOLDS_EVIDENCE_REL
    base._atomic_json(target, evidence)
    return target


__all__ = [
    "AMENDMENT_REL",
    "EXPECTED_AMENDMENT_DIGEST",
    "THRESHOLDS_EVIDENCE_REL",
    "allowed_contract_changes",
    "build_contract",
    "compare_to_historical",
    "load_runtime_amendment",
    "run",
    "validate_contract",
    "write_frozen_contract",
    "write_verified_evidence",
]
