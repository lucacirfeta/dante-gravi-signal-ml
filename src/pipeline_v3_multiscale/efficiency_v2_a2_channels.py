"""Verified two-channel projection for multiscale-efficiency-v2 A2.

The detector-native 32 s result remains the only production decision.  The
frozen A1 joint-max result is exposed as a separate diagnostic channel and is
never OR-combined with, or allowed to override, the native result.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import (
    ROOT,
    _atomic_json,
    _atomic_jsonl,
    _read_jsonl,
    sha256_file,
)
from src.pipeline_v3_multiscale.efficiency_v2_a1_runner import verify_heldout

A2_CONTRACT_REL = Path("config/dante_multiscale_efficiency_v2_a2.json")
SCHEMA_VERSION = 1
PASS_STATUS = "PASS_A2_SEPARATE_DIAGNOSTIC_CHANNELS"
FORBIDDEN_OUTPUT_FIELDS = {
    "combined_recovered",
    "union_recovered",
    "promoted_candidate",
    "production_or_diagnostic",
}


def _assert_file_reference(
    root: Path, reference: Mapping[str, Any], label: str
) -> None:
    path = root / str(reference.get("path", ""))
    if not path.is_file() or sha256_file(path) != str(reference.get("sha256", "")):
        raise ContractError(f"A2 {label} mismatch")


def validate_a2_contract(
    payload: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(payload))
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("A2 contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported A2 schema")
    if value.get("contract_id") != "dante-multiscale-efficiency-v2-a2":
        raise ContractError("A2 contract id changed")
    if value.get("status") != "APPROVED_SEPARATE_DIAGNOSTIC_CHANNELS":
        raise ContractError("A2 option 1 is not approved")
    if value.get("authorization") != {
        "authorized_on": "2026-09-18",
        "decision": "option_1_separate_diagnostic_channels",
    }:
        raise ContractError("A2 authorization changed")

    root = root.resolve()
    for label, reference in value.get("repository_inputs", {}).items():
        _assert_file_reference(root, reference, label)
    for label, reference in value.get("references", {}).items():
        _assert_file_reference(root, reference, label)

    expected_channels = {
        "production": {
            "name": "detector_native_32s",
            "source_field": "baseline_32_recovered",
            "threshold_field": "baseline_32_threshold",
            "score_field": "scores.primary_32",
            "threshold_changed": False,
            "decision_authority": True,
        },
        "diagnostic": {
            "name": "multiscale_a1_joint_max",
            "source_field": "a1_recovered",
            "threshold_field": "joint_threshold",
            "score_field": "joint_surprise",
            "threshold_changed": False,
            "decision_authority": False,
        },
    }
    if value.get("channels") != expected_channels:
        raise ContractError("A2 channel separation changed")
    if value.get("combination_policy") != {
        "logical_or_allowed": False,
        "diagnostic_may_override_production": False,
        "diagnostic_may_promote_candidate": False,
        "unified_false_positive_claim_allowed": False,
        "production_output_equals_native_32s": True,
    }:
        raise ContractError("A2 combination policy changed")
    if value.get("scientific_boundary") != {
        "new_thresholds_fit": False,
        "heldout_used_for_tuning": False,
        "production_endpoint_changed": False,
        "global_detection_significance_established": False,
        "o3_transfer_validity_established": False,
        "interpretation": "separate simulation-specific diagnostic channel",
    }:
        raise ContractError("A2 scientific boundary changed")
    return value


def load_a2_contract(
    path: Path | None = None, *, root: Path = ROOT
) -> dict[str, Any]:
    target = path or root / A2_CONTRACT_REL
    return validate_a2_contract(
        json.loads(target.read_text(encoding="utf-8")), root=root
    )


def project_trial(row: Mapping[str, Any]) -> dict[str, Any]:
    endpoint = row.get("endpoint")
    if not isinstance(endpoint, Mapping):
        raise ContractError("A2 source trial lacks endpoint evidence")
    scores = endpoint.get("scores")
    probabilities = endpoint.get("tail_probability_by_endpoint")
    if not isinstance(scores, Mapping) or not isinstance(probabilities, Mapping):
        raise ContractError("A2 source trial lacks score evidence")
    if "primary_32" not in scores:
        raise ContractError("A2 source trial lacks native 32 s score")
    native = endpoint.get("baseline_32_recovered")
    diagnostic = endpoint.get("a1_recovered")
    if not isinstance(native, bool) or not isinstance(diagnostic, bool):
        raise ContractError("A2 source decisions must be booleans")

    projected = {
        "schema_version": SCHEMA_VERSION,
        "trial_id": str(row["trial_id"]),
        "identity_digest": str(row["identity_digest"]),
        "detector": str(row["detector"]),
        "role": str(row["role"]),
        "role_index": int(row["role_index"]),
        "morphology": str(row["morphology"]),
        "target_snr": float(row["target_snr"]),
        "production": {
            "channel": "detector_native_32s",
            "recovered": native,
            "score": float(scores["primary_32"]),
            "threshold": float(endpoint["baseline_32_threshold"]),
        },
        "diagnostic": {
            "channel": "multiscale_a1_joint_max",
            "triggered": diagnostic,
            "joint_surprise": float(endpoint["joint_surprise"]),
            "joint_threshold": float(endpoint["joint_threshold"]),
            "tail_probability_by_endpoint": {
                str(key): float(value) for key, value in probabilities.items()
            },
        },
        "separation": {
            "production_changed": False,
            "diagnostic_has_decision_authority": False,
        },
    }
    if FORBIDDEN_OUTPUT_FIELDS.intersection(projected):
        raise ContractError("A2 projection contains a forbidden combined decision")
    return projected


def _summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
        lambda: {
            "rows": 0,
            "production_recovered": 0,
            "diagnostic_triggered": 0,
            "both": 0,
            "production_only": 0,
            "diagnostic_only": 0,
        }
    )
    for row in rows:
        key = (str(row["detector"]), str(row["role"]), str(row["morphology"]))
        values = grouped[key]
        production = bool(row["production"]["recovered"])
        diagnostic = bool(row["diagnostic"]["triggered"])
        values["rows"] += 1
        values["production_recovered"] += int(production)
        values["diagnostic_triggered"] += int(diagnostic)
        values["both"] += int(production and diagnostic)
        values["production_only"] += int(production and not diagnostic)
        values["diagnostic_only"] += int(diagnostic and not production)
    return {
        "|".join(key): grouped[key]
        for key in sorted(grouped)
    }


def _run_key(
    *, contract_digest: str, heldout_artifact: str, joint_null_artifact: str
) -> str:
    return canonical_json_sha256(
        {
            "stage": "multiscale_efficiency_v2_a2_separate_channels",
            "contract_digest": contract_digest,
            "heldout_artifact_digest": heldout_artifact,
            "joint_null_artifact_digest": joint_null_artifact,
        }
    )


def build_two_channel_evidence(
    *,
    heldout_run_dir: Path,
    joint_null_run_dir: Path,
    output_root: Path,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    contract = load_a2_contract(root=root)
    heldout = verify_heldout(
        run_dir=heldout_run_dir,
        joint_null_run_dir=joint_null_run_dir,
        root=root,
    )
    frozen = contract["frozen_inputs"]
    if (
        heldout["run_key"] != frozen["heldout_run_key"]
        or heldout["artifact_digest"] != frozen["heldout_artifact_digest"]
        or heldout["joint_null_artifact_digest"]
        != frozen["joint_null_artifact_digest"]
    ):
        raise ContractError("A2 frozen A1 evidence changed")
    run_key = _run_key(
        contract_digest=contract["contract_digest"],
        heldout_artifact=heldout["artifact_digest"],
        joint_null_artifact=heldout["joint_null_artifact_digest"],
    )
    run_dir = output_root.resolve() / f"separate_channels_{run_key}"
    summary_path = run_dir / "a2_channels_summary.json"
    if summary_path.is_file():
        return (
            verify_two_channel_evidence(
                run_dir=run_dir,
                heldout_run_dir=heldout_run_dir,
                joint_null_run_dir=joint_null_run_dir,
                root=root,
            ),
            run_dir,
        )

    source_path = heldout_run_dir / heldout["trials"]["filename"]
    source_rows = _read_jsonl(source_path)
    projected = [project_trial(row) for row in source_rows]
    ledger_path = run_dir / "a2_separate_channels.jsonl"
    _atomic_jsonl(ledger_path, projected)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": PASS_STATUS,
        "contract_digest": contract["contract_digest"],
        "run_key": run_key,
        "heldout_artifact_digest": heldout["artifact_digest"],
        "joint_null_artifact_digest": heldout["joint_null_artifact_digest"],
        "source_trials_sha256": sha256_file(source_path),
        "ledger": {
            "filename": ledger_path.name,
            "sha256": sha256_file(ledger_path),
            "rows": len(projected),
        },
        "channel_counts": _summarize(projected),
        "separation_invariants": {
            "production_decision_source": "detector_native_32s_only",
            "diagnostic_decision_authority": False,
            "combined_decision_emitted": False,
            "production_threshold_changed": False,
            "diagnostic_threshold_changed": False,
        },
        "scientific_boundary": contract["scientific_boundary"],
    }
    _atomic_json(
        summary_path,
        {**body, "artifact_digest": canonical_json_sha256(body)},
    )
    return (
        verify_two_channel_evidence(
            run_dir=run_dir,
            heldout_run_dir=heldout_run_dir,
            joint_null_run_dir=joint_null_run_dir,
            root=root,
        ),
        run_dir,
    )


def verify_two_channel_evidence(
    *,
    run_dir: Path,
    heldout_run_dir: Path,
    joint_null_run_dir: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    contract = load_a2_contract(root=root)
    heldout = verify_heldout(
        run_dir=heldout_run_dir,
        joint_null_run_dir=joint_null_run_dir,
        root=root,
    )
    summary_path = run_dir / "a2_channels_summary.json"
    if not summary_path.is_file():
        raise ContractError("A2 summary is absent")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("A2 summary artifact digest mismatch")
    expected_key = _run_key(
        contract_digest=contract["contract_digest"],
        heldout_artifact=heldout["artifact_digest"],
        joint_null_artifact=heldout["joint_null_artifact_digest"],
    )
    if (
        summary.get("status") != PASS_STATUS
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("run_key") != expected_key
        or run_dir.name != f"separate_channels_{expected_key}"
    ):
        raise ContractError("A2 run identity changed")

    source_path = heldout_run_dir / heldout["trials"]["filename"]
    ledger_path = run_dir / summary["ledger"]["filename"]
    if (
        sha256_file(source_path) != summary["source_trials_sha256"]
        or not ledger_path.is_file()
        or sha256_file(ledger_path) != summary["ledger"]["sha256"]
    ):
        raise ContractError("A2 input or ledger digest mismatch")
    expected_rows = [project_trial(row) for row in _read_jsonl(source_path)]
    actual_rows = _read_jsonl(ledger_path)
    if actual_rows != expected_rows:
        raise ContractError("A2 two-channel projection replay mismatch")
    if len(actual_rows) != int(summary["ledger"]["rows"]):
        raise ContractError("A2 ledger cardinality changed")
    if summary["channel_counts"] != _summarize(actual_rows):
        raise ContractError("A2 channel counts changed")
    for row in actual_rows:
        if row["separation"] != {
            "production_changed": False,
            "diagnostic_has_decision_authority": False,
        }:
            raise ContractError("A2 separation invariant changed")
        if FORBIDDEN_OUTPUT_FIELDS.intersection(row):
            raise ContractError("A2 emitted a forbidden combined decision")
    return summary


__all__ = [
    "build_two_channel_evidence",
    "load_a2_contract",
    "project_trial",
    "validate_a2_contract",
    "verify_two_channel_evidence",
]
