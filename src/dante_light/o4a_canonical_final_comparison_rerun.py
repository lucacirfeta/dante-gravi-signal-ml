"""Frozen final comparison for the canonical O4a provenance rerun."""

from __future__ import annotations

import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import Any, Iterator, Mapping

from src.core.index_contract import sha256_file
from src.dante_light import o4a_canonical_provenance_rerun as base
from src.dante_light import (
    o4a_canonical_native_classification_rerun as classification_remediation,
)
from src.dante_light import (
    o4a_canonical_native_coincidence_rerun as coincidence_remediation,
)
from src.dante_light import o4a_canonical_native_pem_rerun as pem_remediation
from src.dante_light import (
    o4a_canonical_native_taxonomy_rerun as taxonomy_remediation,
)
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_native_provenance import verify_reference_with_reconciliation


ROOT = base.ROOT
COMPARE_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/"
    "corrected_final_comparison_v2.json"
)
HISTORICAL_EVIDENCE_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/corrected_final_comparison_v2.json"
)
SUPERSEDED_CONTRACT_DIGEST = (
    "f7b7d226a78c80a687822ab55dc8427d40edac0bdab041e5131ba9b3fd25dbe9"
)
SUPERSEDED_RUN_KEY = (
    "1f1c19882e5b0a45e44e5d2dc23d130f1a73f9a8dc84231399315ec38efefa25"
)
SUPERSEDED_LINE_ENDING_CONTRACT_DIGEST = (
    "65f3cdc45b43e95765b2e87e47a7065bea94768d0dcf627d27ba172470ee8207"
)
SUPERSEDED_LINE_ENDING_RUN_KEY = (
    "faaf9cd6253b02a557c76ec2117159a94573059be5c8c91e8312744c707e5951"
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"required JSON evidence is absent: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
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


def _verified_upstream(
    path: Path,
    *,
    status: str,
) -> dict[str, Any]:
    evidence = _read_json(path)
    if (
        evidence.get("status") != status
        or evidence.get("comparison_to_historical", {}).get("classification")
        != "BYTE_IDENTICAL"
    ):
        raise ContractError(f"upstream evidence is not byte-identical: {path}")
    external = evidence.get("external_run", {})
    summary_path = _external_path(external["directory"]) / external[
        "summary_filename"
    ]
    if sha256_file(summary_path) != external["summary_sha256"]:
        raise ContractError(f"upstream external summary changed: {path}")
    summary = _read_json(summary_path)
    if (
        summary.get("run_key") != evidence.get("run_key")
        or summary.get("contract_digest") != evidence.get("contract_digest")
        or summary.get("artifact_digest") != evidence.get("external_artifact_digest")
    ):
        raise ContractError(f"upstream compact/external evidence diverged: {path}")
    return evidence


def _external_path(value: str | Path) -> Path:
    return classification_remediation._external_path(str(value))


def _upstream_evidence(root: Path) -> dict[str, dict[str, Any]]:
    specs = {
        "classification": (
            root / classification_remediation.CLASSIFICATION_EVIDENCE_REL,
            "PASS_VERIFIED_CANONICAL_CLASSIFICATION",
        ),
        "taxonomy": (
            root / taxonomy_remediation.TAXONOMY_EVIDENCE_REL,
            "PASS_VERIFIED_CANONICAL_TAXONOMY",
        ),
        "coincidence": (
            root / coincidence_remediation.COINCIDENCE_EVIDENCE_REL,
            "PASS_VERIFIED_CANONICAL_COINCIDENCE",
        ),
        "pem": (
            root / pem_remediation.PEM_EVIDENCE_REL,
            "PASS_VERIFIED_CANONICAL_PEM",
        ),
    }
    return {
        name: _verified_upstream(path, status=status)
        for name, (path, status) in specs.items()
    }


def validate_contract(
    contract: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    root = root.resolve()
    candidate = json.loads(json.dumps(contract))
    if candidate.get("contract_digest") != base.contract_digest(candidate):
        raise ContractError("canonical COMPARE contract digest mismatch")
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "COMPARE")
    baseline = _read_json(root / stage["baseline_contract"]["path"])
    base.assert_allowed_contract_transition(
        baseline, candidate, allowed_changes=stage["allowed_changes"]
    )
    for name, reference in candidate.get("references", {}).items():
        _verify_reference(root, reference, f"COMPARE {name}")
    for name in ("historical_comparison_evidence", "delegated_implementation"):
        _verify_reference(
            root, candidate["remediation"][name], f"COMPARE remediation {name}"
        )
    remediation = candidate.get("remediation", {})
    if (
        remediation.get("historical_outputs_immutable") is not True
        or remediation.get("all_upstream_scientific_ledgers_byte_identical")
        is not True
        or remediation.get("runtime_reexecution_required") is not False
        or remediation.get("scientific_method_changed") is not False
        or remediation.get("new_tolerance_introduced") is not False
    ):
        raise ContractError("COMPARE remediation boundary changed")
    return candidate


def build_contract(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    stage = base.stage_spec(protocol, "COMPARE")
    baseline = _read_json(root / stage["baseline_contract"]["path"])
    upstream = _upstream_evidence(root)
    historical_refs = {
        name: _read_json(root / baseline["references"][f"corrected_{name}"]["path"])
        for name in ("classification", "taxonomy", "coincidence", "pem")
    }
    if (
        upstream["classification"]["output"]["sha256"]
        != historical_refs["classification"]["output"]["sha256"]
        or upstream["taxonomy"]["output"]["sha256"]
        != historical_refs["taxonomy"]["output"]["sha256"]
        or any(
            upstream["coincidence"]["outputs"][name]["sha256"]
            != historical_refs["coincidence"]["outputs"][name]["sha256"]
            for name in ("primary", "diagnostic")
        )
        or any(
            upstream["pem"]["outputs"][name]["sha256"]
            != historical_refs["pem"]["outputs"][name]["sha256"]
            for name in ("targets", "primary", "diagnostic")
        )
    ):
        raise ContractError("canonical COMPARE inputs are not byte-identical")

    candidate = copy.deepcopy(baseline)
    candidate["contract_id"] = "dante-o4a-canonical-provenance-rerun-compare-v3"
    roots = protocol["paths"]["remediation_external_roots"]
    candidate["external_roots"] = {
        "classification": roots[5],
        "taxonomy": roots[6],
        "coincidence": roots[7],
        "pem": roots[8],
    }
    evidence_paths = {
        "classification": classification_remediation.CLASSIFICATION_EVIDENCE_REL,
        "taxonomy": taxonomy_remediation.TAXONOMY_EVIDENCE_REL,
        "coincidence": coincidence_remediation.COINCIDENCE_EVIDENCE_REL,
        "pem": pem_remediation.PEM_EVIDENCE_REL,
    }
    for name, path in evidence_paths.items():
        candidate["references"][f"corrected_{name}"] = {
            "path": path.as_posix(),
            "sha256": sha256_file(root / path),
        }
    candidate["references"]["implementation"] = {
        "path": "src/dante_light/o4a_canonical_final_comparison_rerun.py",
        "sha256": sha256_file(Path(__file__).resolve()),
    }
    candidate["output"]["root"] = roots[9]
    candidate["remediation"] = {
        "protocol_digest": protocol["protocol_digest"],
        "baseline_contract_sha256": stage["baseline_contract"]["sha256"],
        "historical_comparison_evidence": {
            "path": HISTORICAL_EVIDENCE_REL.as_posix(),
            "sha256": sha256_file(root / HISTORICAL_EVIDENCE_REL),
        },
        "delegated_implementation": {
            "path": "src/dante_light/o4a_corrected_final_comparison.py",
            "sha256": sha256_file(
                root / "src/dante_light/o4a_corrected_final_comparison.py"
            ),
        },
        "upstream_run_keys": {
            name: evidence["run_key"] for name, evidence in upstream.items()
        },
        "historical_outputs_immutable": True,
        "all_upstream_scientific_ledgers_byte_identical": True,
        "runtime_reexecution_required": False,
        "runtime_environment_digest_preserved_as_historical_contract_metadata": True,
        "scientific_method_changed": False,
        "new_tolerance_introduced": False,
        "supersedes_failed_contract_digest": SUPERSEDED_CONTRACT_DIGEST,
        "supersedes_failed_run_key": SUPERSEDED_RUN_KEY,
        "superseded_failure_scope": "adapter_row_total_metadata_only",
        "supersedes_line_ending_contract_digest": (
            SUPERSEDED_LINE_ENDING_CONTRACT_DIGEST
        ),
        "supersedes_line_ending_run_key": SUPERSEDED_LINE_ENDING_RUN_KEY,
        "line_ending_remediation": "explicit_crlf_for_historical_byte_identity",
    }
    candidate["contract_digest"] = base.contract_digest(candidate)
    return validate_contract(candidate, root=root)


def write_frozen_contract(*, root: Path = ROOT) -> Path:
    protocol = base.load_protocol(root=root, verify_git=True)
    target = base._inside_root(
        root,
        base.stage_spec(protocol, "COMPARE")["remediation_contract"],
        label="COMPARE remediation contract",
    )
    candidate = build_contract(root=root)
    serialized = json.dumps(candidate, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if target.is_file():
        if target.read_text(encoding="utf-8") != serialized:
            previous = _read_json(target)
            failed_run = _external_path(
                Path(candidate["output"]["root"])
                / f"final_comparison_{SUPERSEDED_RUN_KEY}"
            )
            scientific_outputs = {
                candidate["output"][name]
                for name in (
                    "summary_filename",
                    "shared_filename",
                    "removed_filename",
                    "new_filename",
                    "singletons_filename",
                )
            }
            failed_contract = (
                previous.get("contract_digest") == SUPERSEDED_CONTRACT_DIGEST
                and (failed_run / "failure.json").is_file()
                and not any((failed_run / name).exists() for name in scientific_outputs)
            )
            line_ending_run = _external_path(
                Path(candidate["output"]["root"])
                / f"final_comparison_{SUPERSEDED_LINE_ENDING_RUN_KEY}"
            )
            line_ending_contract = (
                previous.get("contract_digest")
                == SUPERSEDED_LINE_ENDING_CONTRACT_DIGEST
                and (line_ending_run / "superseded.json").is_file()
                and all((line_ending_run / name).is_file() for name in scientific_outputs)
            )
            if not (failed_contract or line_ending_contract):
                raise ContractError(f"refusing divergent frozen contract: {target}")
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            temporary.write_text(serialized, encoding="utf-8", newline="\n")
            temporary.replace(target)
            return target
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
        base.stage_spec(protocol, "COMPARE")["remediation_contract"],
        label="COMPARE remediation contract",
    )
    if not path.is_file():
        raise ContractError("COMPARE remediation contract is not frozen")
    return validate_contract(_read_json(path), root=root)


def _canonical_load_inputs(root: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    from src.dante_light import o4a_corrected_final_comparison as module

    refs = contract["references"]
    historical_taxonomy = module._read_csv(root / refs["historical_taxonomy"]["path"])
    historical_scores = module._read_csv(root / refs["historical_scores"]["path"])
    historical_coincidence = module._read_json(
        root / refs["historical_coincidence"]["path"]
    )
    historical_pem_targets = module._read_csv(
        root / refs["historical_pem_targets"]["path"]
    )
    historical_pem_verdicts = module._read_csv(
        root / refs["historical_pem_verdicts"]["path"]
    )
    module._validate_historical_score_consistency(
        historical_taxonomy, historical_scores
    )

    upstream = _upstream_evidence(root)
    classification_dir = _external_path(
        upstream["classification"]["external_run"]["directory"]
    )
    taxonomy_dir = _external_path(upstream["taxonomy"]["external_run"]["directory"])
    coincidence_dir = _external_path(
        upstream["coincidence"]["external_run"]["directory"]
    )
    pem_dir = _external_path(upstream["pem"]["external_run"]["directory"])
    corrected_classification_spec = _output_with_row_total(
        upstream["classification"]
    )
    corrected_classification = module._load_and_verify_jsonl(
        classification_dir / upstream["classification"]["output"]["filename"],
        corrected_classification_spec,
    )
    corrected_taxonomy_spec = _output_with_row_total(upstream["taxonomy"])
    corrected_taxonomy = module._load_and_verify_jsonl(
        taxonomy_dir / upstream["taxonomy"]["output"]["filename"],
        corrected_taxonomy_spec,
    )
    corrected_coincidence: list[dict[str, Any]] = []
    for population in ("primary", "diagnostic"):
        spec = upstream["coincidence"]["outputs"][population]
        corrected_coincidence.extend(
            module._load_and_verify_jsonl(coincidence_dir / spec["filename"], spec)
        )
    corrected_pem_targets = module._load_and_verify_jsonl(
        pem_dir / upstream["pem"]["outputs"]["targets"]["filename"],
        upstream["pem"]["outputs"]["targets"],
    )
    corrected_pem: list[dict[str, Any]] = []
    for population in ("primary", "diagnostic"):
        spec = upstream["pem"]["outputs"][population]
        corrected_pem.extend(
            module._load_and_verify_jsonl(pem_dir / spec["filename"], spec)
        )
    return {
        "historical_taxonomy": historical_taxonomy,
        "historical_scores": historical_scores,
        "historical_coincidence": historical_coincidence,
        "historical_pem_targets": historical_pem_targets,
        "historical_pem_verdicts": historical_pem_verdicts,
        "corrected_classification": corrected_classification,
        "corrected_taxonomy": corrected_taxonomy,
        "corrected_coincidence": corrected_coincidence,
        "corrected_pem_targets": corrected_pem_targets,
        "corrected_pem": corrected_pem,
    }


def _output_with_row_total(evidence: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(evidence["output"])
    row_total = evidence.get("row_total")
    if not isinstance(row_total, int) or row_total < 0:
        raise ContractError("canonical upstream output row total is invalid")
    output["row_total"] = row_total
    return output


def _atomic_json_crlf(path: Path, value: Mapping[str, Any]) -> None:
    """Write the historical Windows JSON byte representation explicitly."""

    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    payload = serialized.replace("\n", "\r\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


@contextmanager
def _patched_module(
    *, root: Path, contract: Mapping[str, Any]
) -> Iterator[Any]:
    from src.dante_light import o4a_corrected_final_comparison as module

    def load_contract(_root: Path = ROOT) -> dict[str, Any]:
        del _root
        return copy.deepcopy(dict(contract))

    with (
        base.use_module_attribute(module, "load_final_comparison_contract", load_contract),
        base.use_module_attribute(module, "_load_inputs", _canonical_load_inputs),
        base.use_module_attribute(module, "_atomic_json", _atomic_json_crlf),
    ):
        yield module


def run(
    *, root: Path = ROOT, verify_only: bool = False
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    contract = _frozen_contract(root=root)
    external_root = Path(protocol["paths"]["remediation_external_roots"][9])
    with _patched_module(root=root, contract=contract) as module:
        if verify_only:
            return module.verify_final_comparison(
                root=root, external_root=external_root
            )
        return module.run_final_comparison(root=root, external_root=external_root)


def compare_to_historical(
    *, root: Path, summary: Mapping[str, Any], run_dir: Path
) -> dict[str, Any]:
    contract = _frozen_contract(root=root)
    historical_path = _verify_reference(
        root,
        contract["remediation"]["historical_comparison_evidence"],
        "historical COMPARE evidence",
    )
    historical = _read_json(historical_path)
    if historical.get("status") != "PASS_VERIFIED_O4A_FINAL_COMPARISON_V2":
        raise ContractError("historical COMPARE evidence is not PASS")
    historical_dir = _external_path(historical["external_run"]["directory"])
    historical_summary_path = historical_dir / historical["external_run"][
        "summary_filename"
    ]
    if sha256_file(historical_summary_path) != historical["external_run"][
        "summary_sha256"
    ]:
        raise ContractError("historical COMPARE summary hash changed")
    historical_summary = _read_json(historical_summary_path)
    checks = {
        "metrics_equal": summary["metrics"] == historical_summary["metrics"],
        "historical_singletons_equal": summary["historical_singletons"]
        == historical_summary["historical_singletons"],
        "scientific_boundary_equal": summary["scientific_boundary"]
        == historical_summary["scientific_boundary"],
    }
    output_mapping = {
        "shared": "shared",
        "removed": "historical_only",
        "new": "corrected_only",
        "singletons": "singletons",
    }
    for current_name, compact_name in output_mapping.items():
        current_spec = summary["outputs"][current_name]
        historical_spec = historical_summary["outputs"][current_name]
        current_path = run_dir / current_spec["filename"]
        historical_output_path = historical_dir / historical_spec["filename"]
        if sha256_file(historical_output_path) != historical["outputs"][compact_name][
            "sha256"
        ]:
            raise ContractError(f"historical COMPARE {current_name} output changed")
        checks[f"{current_name}_bytes_equal"] = (
            current_path.read_bytes() == historical_output_path.read_bytes()
        )
    identical = all(checks.values())
    return {
        "classification": "BYTE_IDENTICAL" if identical else "OUTPUT_CHANGED",
        "all_final_comparison_outputs_identical": identical,
        "checks": checks,
        "changed_identity_counts": {
            "shared": 0 if checks["shared_bytes_equal"] else None,
            "historical_only": 0 if checks["removed_bytes_equal"] else None,
            "corrected_only": 0 if checks["new_bytes_equal"] else None,
            "singletons": 0 if checks["singletons_bytes_equal"] else None,
        },
        "new_tolerance_introduced": False,
    }


def write_verified_evidence(*, root: Path = ROOT) -> Path:
    root = root.resolve()
    summary, run_dir = run(root=root, verify_only=True)
    comparison = compare_to_historical(root=root, summary=summary, run_dir=run_dir)
    if comparison["classification"] != "BYTE_IDENTICAL":
        raise ContractError("canonical COMPARE output changed")
    protocol = base.load_protocol(root=root, verify_git=True)
    contract = _frozen_contract(root=root)
    contract_path = root / base.stage_spec(protocol, "COMPARE")[
        "remediation_contract"
    ]
    summary_path = run_dir / contract["output"]["summary_filename"]
    body = {
        "schema_version": base.SCHEMA_VERSION,
        "status": "PASS_VERIFIED_CANONICAL_FINAL_COMPARISON",
        "run_key": summary["run_key"],
        "contract_digest": summary["contract_digest"],
        "runtime_environment_digest": summary["runtime_environment_digest"],
        "external_artifact_digest": summary["artifact_digest"],
        "metrics": summary["metrics"],
        "historical_singletons": summary["historical_singletons"],
        "scientific_boundary": summary["scientific_boundary"],
        "outputs": summary["outputs"],
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
            "historical_comparison_evidence": contract["remediation"][
                "historical_comparison_evidence"
            ],
        },
        "verification": {
            "independent_verifier": "PASS_EXACT_LEDGER_AND_DIGEST_REPLAY",
            "failure_artifact_absent": not (run_dir / "failure.json").is_file(),
            "all_ten_stages_complete": True,
        },
    }
    evidence = {**body, "artifact_digest": canonical_json_sha256(body)}
    target = root / COMPARE_EVIDENCE_REL
    base._atomic_json(target, evidence)
    return target


__all__ = [
    "COMPARE_EVIDENCE_REL",
    "build_contract",
    "compare_to_historical",
    "run",
    "validate_contract",
    "write_frozen_contract",
    "write_verified_evidence",
]
