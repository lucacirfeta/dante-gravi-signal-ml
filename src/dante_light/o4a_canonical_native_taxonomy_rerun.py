"""Frozen TAXONOMY continuation for the canonical O4a provenance rerun."""

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
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_rescore_v2 import _load_jsonl
from src.dante_light.o4a_native_provenance import verify_reference_with_reconciliation


ROOT = base.ROOT
AMENDMENT_REL = Path(
    "config/dante_o4a_canonical_provenance_taxonomy_runtime_amendment_v1.json"
)
TAXONOMY_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/"
    "corrected_native_taxonomy.json"
)
HISTORICAL_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/corrected_native_taxonomy.json"
)
EXPECTED_AMENDMENT_DIGEST = (
    "d41831b4540e2e6d86b0adedf4e726369f9487340fe89f7deb28a3f3d06de81b"
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
        raise ContractError("TAXONOMY runtime amendment digest mismatch")
    if (
        value.get("schema_version") != base.SCHEMA_VERSION
        or value.get("status") != "FROZEN_BEFORE_TAXONOMY_RECOMPUTATION"
        or value.get("scope")
        != {"stage": "TAXONOMY", "allowed_contract_changes": []}
    ):
        raise ContractError("TAXONOMY runtime amendment scope changed")
    protocol_path = base._require_file_reference(
        root, value["parent_protocol"], label="TAXONOMY amendment parent protocol"
    )
    if _read_json(protocol_path).get("protocol_digest") != value["parent_protocol"][
        "protocol_digest"
    ]:
        raise ContractError("TAXONOMY amendment parent protocol mismatch")
    parent_path = base._require_file_reference(
        root,
        value["parent_runtime_amendment"],
        label="TAXONOMY parent runtime amendment",
    )
    if _read_json(parent_path).get("amendment_digest") != value[
        "parent_runtime_amendment"
    ]["amendment_digest"]:
        raise ContractError("TAXONOMY parent amendment digest mismatch")

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
            raise ContractError(f"{label} TAXONOMY runtime binding mismatch")
    if base.json_leaf_differences(
        historical["runtime_environment"], remediation["runtime_environment"]
    ) != set(value["required_environment_differences"]):
        raise ContractError("TAXONOMY runtime amendment is not driver-only")
    if value.get("scientific_boundary") != {
        "candidate_population_changed": False,
        "family_naming_changed": False,
        "linkage_or_distance_changed": False,
        "morphology_representation_changed": False,
        "native_scores_or_classes_changed": False,
        "package_versions_changed": False,
        "tolerances_changed": False,
    }:
        raise ContractError("TAXONOMY amendment scientific boundary changed")
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
        raise ContractError("canonical TAXONOMY contract digest mismatch")
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "TAXONOMY")
    baseline = _read_json(root / stage["baseline_contract"]["path"])
    base.assert_allowed_contract_transition(
        baseline, candidate, allowed_changes=stage["allowed_changes"]
    )
    for name, reference in candidate.get("references", {}).items():
        _verify_reference(root, reference, f"TAXONOMY {name}")
    for name in ("historical_taxonomy_evidence", "delegated_implementation"):
        _verify_reference(
            root, candidate["remediation"][name], f"TAXONOMY remediation {name}"
        )
    remediation = candidate.get("remediation", {})
    if (
        remediation.get("historical_outputs_immutable") is not True
        or remediation.get("classification_ledger_byte_identical") is not True
        or remediation.get("coincidence_computed") is not False
        or remediation.get("pem_computed") is not False
    ):
        raise ContractError("TAXONOMY remediation boundary changed")
    return candidate


def _external_path(value: str) -> Path:
    return classification_remediation._external_path(value)


def _verified_classification(
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    evidence = _read_json(path)
    if (
        evidence.get("status") != "PASS_VERIFIED_CANONICAL_CLASSIFICATION"
        or evidence.get("comparison_to_historical", {}).get("classification")
        != "BYTE_IDENTICAL"
        or evidence.get("row_total") != 10942
        or evidence.get("verification", {}).get(
            "taxonomy_or_coincidence_or_pem_computed"
        )
        is not False
    ):
        raise ContractError("canonical CLASSIFY evidence is not byte-identical")
    external = evidence["external_run"]
    summary_path = _external_path(external["directory"]) / external["summary_filename"]
    if sha256_file(summary_path) != external["summary_sha256"]:
        raise ContractError("canonical CLASSIFY external summary hash changed")
    summary = _read_json(summary_path)
    if (
        summary.get("artifact_digest") != evidence["external_artifact_digest"]
        or summary.get("contract_digest") != evidence["contract_digest"]
        or summary.get("run_key") != evidence["run_key"]
        or summary.get("output") != evidence["output"]
    ):
        raise ContractError("canonical CLASSIFY compact/external evidence diverged")
    return evidence, summary, summary_path


def build_contract(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "TAXONOMY")
    baseline = _read_json(root / stage["baseline_contract"]["path"])
    classification_path = root / classification_remediation.CLASSIFICATION_EVIDENCE_REL
    classification, classification_summary, _ = _verified_classification(
        classification_path
    )
    amendment = load_runtime_amendment(root=root, require_current=False)

    candidate = copy.deepcopy(baseline)
    candidate["contract_id"] = "dante-o4a-canonical-provenance-rerun-taxonomy-v1"
    candidate["parent_native_classification"] = {
        "compact_artifact_digest": classification["artifact_digest"],
        "run_artifact_digest": classification["external_artifact_digest"],
        "contract_digest": classification["contract_digest"],
        "run_key": classification["run_key"],
        "summary_sha256": classification["external_run"]["summary_sha256"],
        "output_filename": classification["output"]["filename"],
        "output_sha256": classification["output"]["sha256"],
        "output_row_digest": classification["output"]["row_digest"],
        "counts_by_detector_and_class": classification[
            "counts_by_detector_and_class"
        ],
    }
    candidate["references"]["native_classification"] = {
        "path": classification_remediation.CLASSIFICATION_EVIDENCE_REL.as_posix(),
        "sha256": sha256_file(classification_path),
    }
    candidate["references"]["implementation"] = {
        "path": "src/dante_light/o4a_canonical_native_taxonomy_rerun.py",
        "sha256": sha256_file(Path(__file__).resolve()),
    }
    candidate["output"]["root"] = protocol["paths"][
        "remediation_external_roots"
    ][6]
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
        "historical_taxonomy_evidence": {
            "path": HISTORICAL_EVIDENCE_REL.as_posix(),
            "sha256": sha256_file(root / HISTORICAL_EVIDENCE_REL),
        },
        "delegated_implementation": {
            "path": "src/dante_light/o4a_corrected_native_taxonomy.py",
            "sha256": sha256_file(
                root / "src/dante_light/o4a_corrected_native_taxonomy.py"
            ),
        },
        "historical_outputs_immutable": True,
        "classification_ledger_byte_identical": True,
        "classification_external_artifact_digest": classification_summary[
            "artifact_digest"
        ],
        "primary_scan_immutable": True,
        "coincidence_computed": False,
        "pem_computed": False,
    }
    candidate["contract_digest"] = base.contract_digest(candidate)
    return validate_contract(candidate, root=root)


def write_frozen_contract(*, root: Path = ROOT) -> Path:
    protocol = base.load_protocol(root=root, verify_git=True)
    target = base._inside_root(
        root,
        base.stage_spec(protocol, "TAXONOMY")["remediation_contract"],
        label="TAXONOMY remediation contract",
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
        base.stage_spec(protocol, "TAXONOMY")["remediation_contract"],
        label="TAXONOMY remediation contract",
    )
    if not path.is_file():
        raise ContractError("TAXONOMY remediation contract is not frozen")
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


@contextmanager
def _patched_module(
    *, root: Path, contract: Mapping[str, Any], device: str
) -> Iterator[Any]:
    from src.dante_light import o4a_corrected_native_taxonomy as module

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
            ("load_native_taxonomy_contract", load_contract),
            ("load_canonical_runtime_contract", load_runtime),
        ):
            stack.enter_context(base.use_module_attribute(module, attribute, value))
        yield module


def run(
    *, root: Path = ROOT, device: str = "cuda", verify_only: bool = False
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    contract = _frozen_contract(root=root)
    roots = protocol["paths"]["remediation_external_roots"]
    common = {
        "root": root,
        "primary_external_root": Path(protocol["paths"]["primary_external_root_wsl"]),
        "classification_external_root": Path(roots[5]),
        "external_root": Path(roots[6]),
        "device": device,
    }
    with _patched_module(root=root, contract=contract, device=device) as module:
        if verify_only:
            return module.verify_native_taxonomy(**common)
        return module.run_native_taxonomy(**common)


def _partition_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    families: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        families.setdefault(str(row["global_family_id"]), []).append(
            (str(row["detector"]), float(row["gps_start"]))
        )
    partition = sorted(
        (sorted(members) for members in families.values()),
        key=lambda members: (len(members), members),
    )
    return canonical_json_sha256(partition)


def compare_to_historical(
    *, root: Path, summary: Mapping[str, Any], run_dir: Path
) -> dict[str, Any]:
    contract = _frozen_contract(root=root)
    historical_path = _verify_reference(
        root,
        contract["remediation"]["historical_taxonomy_evidence"],
        "historical TAXONOMY evidence",
    )
    historical = _read_json(historical_path)
    if historical.get("status") != "PASS_VERIFIED_NATIVE_TAXONOMY_V1":
        raise ContractError("historical TAXONOMY evidence is not PASS")
    historical_dir = _external_path(historical["external_run"]["directory"])
    historical_summary_path = historical_dir / historical["external_run"][
        "summary_filename"
    ]
    if (
        sha256_file(historical_summary_path)
        != historical["external_run"]["summary_sha256"]
    ):
        raise ContractError("historical TAXONOMY summary hash changed")
    historical_summary = _read_json(historical_summary_path)
    current_output = run_dir / summary["output"]["filename"]
    historical_output = historical_dir / historical["output"]["filename"]
    if sha256_file(historical_output) != historical["output"]["sha256"]:
        raise ContractError("historical TAXONOMY output hash changed")
    current_rows = _load_jsonl(current_output)
    historical_rows = _load_jsonl(historical_output)
    current_partition = _partition_digest(current_rows)
    historical_partition = _partition_digest(historical_rows)
    checks = {
        "output_bytes_equal": current_output.read_bytes()
        == historical_output.read_bytes(),
        "partition_equal": current_partition == historical_partition,
        "taxonomy_equal": summary["taxonomy"] == historical_summary["taxonomy"],
        "family_metrics_equal": summary["family_metrics"]
        == historical_summary["family_metrics"],
        "counts_equal": (
            summary["counts_by_detector"] == historical_summary["counts_by_detector"]
            and summary["counts_by_native_class"]
            == historical_summary["counts_by_native_class"]
        ),
        "gates_equal": summary["gates"] == historical_summary["gates"],
        "sources_equal": summary["sources"] == historical_summary["sources"],
    }
    all_equal = all(checks.values())
    return {
        "classification": "BYTE_IDENTICAL" if all_equal else "OUTPUT_CHANGED",
        "all_taxonomy_outputs_identical": all_equal,
        "partition_digest": {
            "current": current_partition,
            "historical": historical_partition,
        },
        "checks": checks,
    }


def write_verified_evidence(*, root: Path = ROOT, device: str = "cuda") -> Path:
    root = root.resolve()
    summary, run_dir = run(root=root, device=device, verify_only=True)
    contract = _frozen_contract(root=root)
    comparison = compare_to_historical(root=root, summary=summary, run_dir=run_dir)
    protocol = base.load_protocol(root=root, verify_git=True)
    contract_path = root / base.stage_spec(protocol, "TAXONOMY")[
        "remediation_contract"
    ]
    summary_path = run_dir / contract["output"]["summary_filename"]
    body = {
        "schema_version": base.SCHEMA_VERSION,
        "status": "PASS_VERIFIED_CANONICAL_TAXONOMY",
        "run_key": summary["run_key"],
        "contract_digest": summary["contract_digest"],
        "external_artifact_digest": summary["artifact_digest"],
        "runtime_environment_digest": summary["runtime_environment_digest"],
        "taxonomy": summary["taxonomy"],
        "scientific_boundary": summary["scientific_boundary"],
        "row_total": summary["row_total"],
        "counts_by_detector": summary["counts_by_detector"],
        "counts_by_native_class": summary["counts_by_native_class"],
        "family_metrics": summary["family_metrics"],
        "sources": summary["sources"],
        "output": summary["output"],
        "gates": summary["gates"],
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
            "coincidence_or_pem_computed": False,
        },
    }
    evidence = {**body, "artifact_digest": canonical_json_sha256(body)}
    target = root / TAXONOMY_EVIDENCE_REL
    base._atomic_json(target, evidence)
    return target


__all__ = [
    "AMENDMENT_REL",
    "EXPECTED_AMENDMENT_DIGEST",
    "TAXONOMY_EVIDENCE_REL",
    "build_contract",
    "compare_to_historical",
    "load_runtime_amendment",
    "run",
    "validate_contract",
    "write_frozen_contract",
    "write_verified_evidence",
]
