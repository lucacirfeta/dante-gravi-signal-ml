"""Frozen PEM continuation for the canonical O4a provenance rerun."""

from __future__ import annotations

import copy
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from src.core.index_contract import sha256_file
from src.dante_light import o4a_canonical_provenance_rerun as base
from src.dante_light import (
    o4a_canonical_native_classification_rerun as classification_remediation,
)
from src.dante_light import (
    o4a_canonical_native_coincidence_rerun as coincidence_remediation,
)
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_rescore_v2 import _load_jsonl
from src.dante_light.o4a_native_provenance import verify_reference_with_reconciliation


ROOT = base.ROOT
AMENDMENT_REL = Path(
    "config/dante_o4a_canonical_provenance_pem_runtime_amendment_v1.json"
)
PEM_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/"
    "corrected_native_pem.json"
)
HISTORICAL_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/corrected_native_pem.json"
)
EXPECTED_AMENDMENT_DIGEST = (
    "9c99663909edfb43e306d08d09020712e59dc34a119cb6668692bcc297616b4d"
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
    value = _read_json(root / AMENDMENT_REL)
    payload = dict(value)
    declared = payload.pop("amendment_digest", None)
    if declared != EXPECTED_AMENDMENT_DIGEST or declared != canonical_json_sha256(
        payload
    ):
        raise ContractError("PEM runtime amendment digest mismatch")
    if (
        value.get("schema_version") != base.SCHEMA_VERSION
        or value.get("status") != "FROZEN_BEFORE_PEM_RECOMPUTATION"
        or value.get("scope") != {"stage": "PEM", "allowed_contract_changes": []}
    ):
        raise ContractError("PEM runtime amendment scope changed")
    protocol_path = base._require_file_reference(
        root, value["parent_protocol"], label="PEM amendment parent protocol"
    )
    if _read_json(protocol_path).get("protocol_digest") != value["parent_protocol"][
        "protocol_digest"
    ]:
        raise ContractError("PEM amendment parent protocol mismatch")
    parent_path = base._require_file_reference(
        root,
        value["parent_runtime_amendment"],
        label="PEM parent runtime amendment",
    )
    if _read_json(parent_path).get("amendment_digest") != value[
        "parent_runtime_amendment"
    ]["amendment_digest"]:
        raise ContractError("PEM parent amendment digest mismatch")

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
        environment = runtime["runtime_environment"]
        if (
            runtime["contract_digest"] != reference["contract_digest"]
            or environment["environment_digest"] != reference["environment_digest"]
            or environment["cuda_device"]["driver_version"]
            != reference["driver_version"]
        ):
            raise ContractError(f"{label} PEM runtime binding mismatch")
    if base.json_leaf_differences(
        historical["runtime_environment"], remediation["runtime_environment"]
    ) != set(value["required_environment_differences"]):
        raise ContractError("PEM runtime amendment is not driver-only")
    if value.get("scientific_boundary") != {
        "bootstrap_changed": False,
        "channel_policy_changed": False,
        "coherence_measurement_changed": False,
        "null_calibration_changed": False,
        "package_versions_changed": False,
        "target_population_changed": False,
        "threshold_or_verdict_rule_changed": False,
        "tolerances_changed": False,
    }:
        raise ContractError("PEM amendment scientific boundary changed")
    return value


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
        raise ContractError("canonical PEM contract digest mismatch")
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "PEM")
    baseline = _read_json(root / stage["baseline_contract"]["path"])
    base.assert_allowed_contract_transition(
        baseline, candidate, allowed_changes=stage["allowed_changes"]
    )
    for name, reference in candidate.get("references", {}).items():
        _verify_reference(root, reference, f"PEM {name}")
    for name in ("historical_pem_evidence", "delegated_implementation"):
        _verify_reference(root, candidate["remediation"][name], f"PEM {name}")
    remediation = candidate.get("remediation", {})
    if (
        remediation.get("historical_outputs_immutable") is not True
        or remediation.get("classification_ledger_byte_identical") is not True
        or remediation.get("coincidence_ledgers_byte_identical") is not True
        or remediation.get("shortlist_population_changed") is not False
        or remediation.get("compare_computed") is not False
    ):
        raise ContractError("PEM remediation boundary changed")
    return candidate


def _verified_evidence(
    path: Path,
    *,
    status: str,
    comparison_key: str,
    accepted_comparison: str,
) -> dict[str, Any]:
    evidence = _read_json(path)
    if (
        evidence.get("status") != status
        or evidence.get("comparison_to_historical", {}).get(comparison_key)
        != accepted_comparison
    ):
        raise ContractError(f"upstream evidence is not verified: {path}")
    return evidence


def build_contract(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "PEM")
    baseline = _read_json(root / stage["baseline_contract"]["path"])

    classification_path = root / classification_remediation.CLASSIFICATION_EVIDENCE_REL
    classification = _verified_evidence(
        classification_path,
        status="PASS_VERIFIED_CANONICAL_CLASSIFICATION",
        comparison_key="classification",
        accepted_comparison="BYTE_IDENTICAL",
    )
    coincidence_path = root / coincidence_remediation.COINCIDENCE_EVIDENCE_REL
    coincidence = _verified_evidence(
        coincidence_path,
        status="PASS_VERIFIED_CANONICAL_COINCIDENCE",
        comparison_key="classification",
        accepted_comparison="BYTE_IDENTICAL",
    )
    if (
        coincidence.get("outputs", {}).get("primary", {}).get("sha256")
        != baseline["parents"]["native_coincidence_primary_sha256"]
        or coincidence.get("outputs", {}).get("diagnostic", {}).get("sha256")
        != baseline["parents"]["native_coincidence_diagnostic_sha256"]
        or classification.get("output", {}).get("sha256")
        != baseline["parents"]["native_classification_sha256"]
    ):
        raise ContractError("canonical PEM inputs are not byte-identical")

    amendment = load_runtime_amendment(root=root, require_current=False)
    candidate = copy.deepcopy(baseline)
    candidate["contract_id"] = "dante-o4a-canonical-provenance-rerun-pem-v1"
    candidate["parents"] = {
        "native_classification_artifact_digest": classification[
            "external_artifact_digest"
        ],
        "native_classification_row_digest": classification["output"]["row_digest"],
        "native_classification_sha256": classification["output"]["sha256"],
        "native_coincidence_artifact_digest": coincidence[
            "external_artifact_digest"
        ],
        "native_coincidence_contract_digest": coincidence["contract_digest"],
        "native_coincidence_diagnostic_sha256": coincidence["outputs"][
            "diagnostic"
        ]["sha256"],
        "native_coincidence_primary_sha256": coincidence["outputs"]["primary"][
            "sha256"
        ],
    }
    candidate["references"]["native_classification"] = {
        "path": classification_remediation.CLASSIFICATION_EVIDENCE_REL.as_posix(),
        "sha256": sha256_file(classification_path),
    }
    candidate["references"]["native_coincidence"] = {
        "path": coincidence_remediation.COINCIDENCE_EVIDENCE_REL.as_posix(),
        "sha256": sha256_file(coincidence_path),
    }
    candidate["references"]["implementation"] = {
        "path": "src/dante_light/o4a_canonical_native_pem_rerun.py",
        "sha256": sha256_file(Path(__file__).resolve()),
    }
    candidate["output"]["root"] = protocol["paths"][
        "remediation_external_roots"
    ][8]
    candidate["remediation"] = {
        "protocol_digest": protocol["protocol_digest"],
        "baseline_contract_sha256": stage["baseline_contract"]["sha256"],
        "runtime_amendment": {
            "path": AMENDMENT_REL.as_posix(),
            "digest": amendment["amendment_digest"],
        },
        "runtime_environment_digest": amendment["remediation_runtime"][
            "environment_digest"
        ],
        "historical_pem_evidence": {
            "path": HISTORICAL_EVIDENCE_REL.as_posix(),
            "sha256": sha256_file(root / HISTORICAL_EVIDENCE_REL),
        },
        "delegated_implementation": {
            "path": "src/dante_light/o4a_corrected_native_pem.py",
            "sha256": sha256_file(
                root / "src/dante_light/o4a_corrected_native_pem.py"
            ),
        },
        "historical_outputs_immutable": True,
        "classification_ledger_byte_identical": True,
        "coincidence_ledgers_byte_identical": True,
        "shortlist_population_changed": False,
        "compare_computed": False,
    }
    candidate["contract_digest"] = base.contract_digest(candidate)
    return validate_contract(candidate, root=root)


def write_frozen_contract(*, root: Path = ROOT) -> Path:
    protocol = base.load_protocol(root=root, verify_git=True)
    target = base._inside_root(
        root,
        base.stage_spec(protocol, "PEM")["remediation_contract"],
        label="PEM remediation contract",
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


def _frozen_contract(*, root: Path) -> dict[str, Any]:
    protocol = base.load_protocol(root=root, verify_git=True)
    path = base._inside_root(
        root,
        base.stage_spec(protocol, "PEM")["remediation_contract"],
        label="PEM remediation contract",
    )
    if not path.is_file():
        raise ContractError("PEM remediation contract is not frozen")
    return validate_contract(_read_json(path), root=root)


def _load_runtime(
    *, root: Path, require_current: bool, device: str
) -> dict[str, Any]:
    amendment = load_runtime_amendment(root=root, require_current=False)
    reference = amendment["remediation_runtime"]
    from src.dante_light.o4a_corrected_runtime import (
        validate_canonical_runtime_contract,
    )

    return validate_canonical_runtime_contract(
        _read_json(root / reference["path"]),
        root=root,
        require_current=require_current,
        device=device,
    )


def _external_path(value: str) -> Path:
    return classification_remediation._external_path(value)


def _canonical_external_inputs(
    *,
    root: Path,
    contract: Mapping[str, Any],
    coincidence_external_root: Path,
    classification_external_root: Path,
) -> tuple[list[dict[str, Any]], list[float], Path]:
    del coincidence_external_root, classification_external_root
    from src.dante_light import o4a_corrected_native_pem as module

    coincidence = _read_json(root / contract["references"]["native_coincidence"]["path"])
    coincidence_dir = _external_path(coincidence["external_run"]["directory"])
    observed: dict[str, list[dict[str, Any]]] = {}
    for name in ("primary", "diagnostic"):
        spec = coincidence["outputs"][name]
        path = coincidence_dir / spec["filename"]
        rows = _load_jsonl(path)
        if (
            sha256_file(path) != spec["sha256"]
            or canonical_json_sha256(rows) != spec["row_digest"]
        ):
            raise ContractError(f"canonical PEM coincidence {name} changed")
        observed[name] = rows
    targets = module.select_pem_targets(
        observed["primary"], observed["diagnostic"], contract=contract
    )

    classification = _read_json(
        root / contract["references"]["native_classification"]["path"]
    )
    classification_dir = _external_path(classification["external_run"]["directory"])
    classification_path = classification_dir / classification["output"]["filename"]
    classification_rows = _load_jsonl(classification_path)
    if (
        sha256_file(classification_path)
        != contract["parents"]["native_classification_sha256"]
        or canonical_json_sha256(classification_rows)
        != contract["parents"]["native_classification_row_digest"]
        or len(classification_rows) != 10_942
    ):
        raise ContractError("canonical PEM exclusion ledger changed")
    exclusion = [float(row["gps_start"]) for row in classification_rows]
    return targets, exclusion, classification_path


@contextmanager
def _patched_module(
    *, root: Path, contract: Mapping[str, Any], device: str
) -> Iterator[Any]:
    from src.dante_light import o4a_corrected_native_pem as module

    runtime = _load_runtime(root=root, require_current=True, device=device)

    def load_contract(_root: Path = ROOT) -> dict[str, Any]:
        del _root
        return copy.deepcopy(dict(contract))

    def load_runtime(
        *, root: Path = ROOT, require_current: bool = False, device: str = "cuda"
    ) -> dict[str, Any]:
        del root, require_current, device
        return copy.deepcopy(runtime)

    with ExitStack() as stack:
        for attribute, value in (
            ("load_native_pem_contract", load_contract),
            ("load_canonical_runtime_contract", load_runtime),
            ("_external_inputs", _canonical_external_inputs),
        ):
            stack.enter_context(base.use_module_attribute(module, attribute, value))
        yield module


def run(
    *,
    root: Path = ROOT,
    device: str = "cuda",
    verify_only: bool = False,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    contract = _frozen_contract(root=root)
    roots = protocol["paths"]["remediation_external_roots"]
    common = {
        "root": root,
        "coincidence_external_root": Path(roots[7]),
        "classification_external_root": Path(roots[5]),
        "external_root": Path(roots[8]),
    }
    with _patched_module(root=root, contract=contract, device=device) as module:
        if verify_only:
            return module.verify_native_pem(**common)
        return module.run_native_pem(
            **common, raw_root=Path(protocol["paths"]["raw_root_wsl"])
        )


def _rows_by_identity(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, float], Mapping[str, Any]]:
    return {
        (
            str(row["target"]["population"]),
            str(row["target"]["detector"]),
            float(row["target"]["gps_start"]),
        ): row
        for row in rows
    }


def compare_to_historical(
    *, root: Path, summary: Mapping[str, Any], run_dir: Path
) -> dict[str, Any]:
    contract = _frozen_contract(root=root)
    historical_path = _verify_reference(
        root,
        contract["remediation"]["historical_pem_evidence"],
        "historical PEM evidence",
    )
    historical = _read_json(historical_path)
    if historical.get("status") != "PASS_VERIFIED_NATIVE_PEM_V1":
        raise ContractError("historical PEM evidence is not PASS complete")
    historical_summary_path = _external_path(
        historical["external_run"]["directory"]
    ) / historical["external_run"]["summary_filename"]
    if (
        sha256_file(historical_summary_path)
        != historical["external_run"]["summary_sha256"]
    ):
        raise ContractError("historical PEM summary hash changed")
    historical_summary = _read_json(historical_summary_path)

    checks: dict[str, bool] = {
        "event_summary_equal": summary.get("event_summary")
        == historical_summary.get("event_summary"),
        "gates_equal": summary.get("gates") == historical_summary.get("gates"),
        "measurement_equal": summary.get("measurement")
        == historical_summary.get("measurement"),
        "population_equal": summary.get("population")
        == historical_summary.get("population"),
        "scientific_boundary_equal": summary.get("scientific_boundary")
        == historical_summary.get("scientific_boundary"),
        "candidate_exclusion_equal": {
            key: summary.get("sources", {}).get(key)
            for key in (
                "classification_sha256",
                "candidate_exclusion_total",
                "candidate_exclusion_digest",
            )
        }
        == {
            key: historical_summary.get("sources", {}).get(key)
            for key in (
                "classification_sha256",
                "candidate_exclusion_total",
                "candidate_exclusion_digest",
            )
        },
    }
    changed_identities: dict[str, int] = {}
    for name in ("targets", "primary", "diagnostic"):
        current_spec = summary["outputs"][name]
        historical_spec = historical["outputs"][name]
        current_path = run_dir / current_spec["filename"]
        historical_output_path = historical_summary_path.parent / historical_spec["filename"]
        checks[f"{name}_bytes_equal"] = sha256_file(current_path) == historical_spec[
            "sha256"
        ]
        current_rows = _load_jsonl(current_path)
        historical_rows = _load_jsonl(historical_output_path)
        if name == "targets":
            changed_identities[name] = 0 if current_rows == historical_rows else len(
                set(map(canonical_json_sha256, current_rows))
                ^ set(map(canonical_json_sha256, historical_rows))
            )
        else:
            left = _rows_by_identity(current_rows)
            right = _rows_by_identity(historical_rows)
            changed_identities[name] = sum(
                left.get(identity) != right.get(identity)
                for identity in set(left) | set(right)
            )
    identical = all(checks.values()) and not any(changed_identities.values())
    return {
        "classification": "BYTE_IDENTICAL" if identical else "OUTPUT_CHANGED",
        "all_outputs_identical": identical,
        "checks": checks,
        "changed_identity_counts": changed_identities,
        "new_tolerance_introduced": False,
    }


def write_verified_evidence(*, root: Path = ROOT, device: str = "cuda") -> Path:
    root = root.resolve()
    summary, run_dir = run(root=root, device=device, verify_only=True)
    comparison = compare_to_historical(root=root, summary=summary, run_dir=run_dir)
    if comparison["classification"] == "OUTPUT_CHANGED":
        raise ContractError("canonical PEM output changed")
    protocol = base.load_protocol(root=root, verify_git=True)
    contract = _frozen_contract(root=root)
    contract_path = root / base.stage_spec(protocol, "PEM")["remediation_contract"]
    summary_path = run_dir / contract["output"]["summary_filename"]
    body = {
        "schema_version": base.SCHEMA_VERSION,
        "status": "PASS_VERIFIED_CANONICAL_PEM",
        "run_key": summary["run_key"],
        "contract_digest": summary["contract_digest"],
        "runtime_environment_digest": summary["runtime_environment_digest"],
        "external_artifact_digest": summary["artifact_digest"],
        "population": summary["population"],
        "measurement": summary["measurement"],
        "scientific_boundary": summary["scientific_boundary"],
        "event_summary": summary["event_summary"],
        "gates": summary["gates"],
        "sources": summary["sources"],
        "outputs": summary["outputs"],
        "comparison_to_historical": comparison,
        "external_run": {
            "directory": str(run_dir),
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
            "failure_artifact_absent": not (run_dir / "failure.json").is_file(),
            "all_65_targets_accounted": True,
            "compare_computed": False,
        },
    }
    evidence = {**body, "artifact_digest": canonical_json_sha256(body)}
    target = root / PEM_EVIDENCE_REL
    base._atomic_json(target, evidence)
    return target


__all__ = [
    "AMENDMENT_REL",
    "EXPECTED_AMENDMENT_DIGEST",
    "PEM_EVIDENCE_REL",
    "build_contract",
    "compare_to_historical",
    "load_runtime_amendment",
    "run",
    "validate_contract",
    "write_frozen_contract",
    "write_verified_evidence",
]
