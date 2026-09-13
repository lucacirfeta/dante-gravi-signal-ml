"""Independent verifier for the frozen canonical O4a COINCIDENCE replay."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.core.index_contract import sha256_file
from src.dante_light import o4a_canonical_native_coincidence_rerun as stage
from src.dante_light import o4a_canonical_provenance_rerun as base
from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = base.ROOT


def verify(
    *, root: Path = ROOT, device: str = "cuda"
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    protocol = base.load_protocol(root=root, verify_git=True)
    contract = stage._frozen_contract(root=root)
    roots = protocol["paths"]["remediation_external_roots"]
    common = {
        "root": root,
        "primary_external_root": Path(protocol["paths"]["primary_external_root_wsl"]),
        "classification_external_root": Path(roots[5]),
        "index_external_root": Path(roots[1]),
        "external_root": Path(roots[7]),
        "device": device,
    }
    with stage._patched_module(root=root, contract=contract, device=device) as module:
        return module.verify_native_coincidence(**common)


def write_verified_evidence(*, root: Path = ROOT, device: str = "cuda") -> Path:
    root = root.resolve()
    summary, run_dir = verify(root=root, device=device)
    contract = stage._frozen_contract(root=root)
    comparison = stage.compare_to_historical(
        root=root, summary=summary, run_dir=run_dir
    )
    if comparison["classification"] == "OUTPUT_CHANGED":
        raise ContractError("canonical COINCIDENCE output changed")
    protocol = base.load_protocol(root=root, verify_git=True)
    contract_path = root / base.stage_spec(protocol, "COINCIDENCE")[
        "remediation_contract"
    ]
    summary_path = run_dir / contract["output"]["summary_filename"]
    body = {
        "schema_version": base.SCHEMA_VERSION,
        "status": "PASS_VERIFIED_CANONICAL_COINCIDENCE",
        "run_key": summary["run_key"],
        "contract_digest": summary["contract_digest"],
        "external_artifact_digest": summary["artifact_digest"],
        "runtime_environment_digest": summary["runtime_environment_digest"],
        "population": summary["population"],
        "measurement": summary["measurement"],
        "scientific_boundary": summary["scientific_boundary"],
        "event_summary": summary["event_summary"],
        "historical_anchor_check": summary["historical_anchor_check"],
        "sources": summary["sources"],
        "outputs": summary["outputs"],
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
            "independent_verifier": {
                "path": (
                    "src/dante_light/"
                    "o4a_canonical_native_coincidence_verifier.py"
                ),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
            "runtime_amendment": {
                "path": stage.AMENDMENT_REL.as_posix(),
                "sha256": sha256_file(root / stage.AMENDMENT_REL),
                "digest": stage.EXPECTED_AMENDMENT_DIGEST,
            },
        },
        "verification": {
            "independent_verifier": "PASS_EXACT_LEDGER_AND_DIGEST_REPLAY",
            "failure_artifact_absent": not (run_dir / "failure.json").is_file(),
            "pem_computed": False,
        },
    }
    evidence = {**body, "artifact_digest": canonical_json_sha256(body)}
    target = root / stage.COINCIDENCE_EVIDENCE_REL
    base._atomic_json(target, evidence)
    return target


__all__ = ["verify", "write_verified_evidence"]
