"""Fail-closed input contract for a new five-channel O3a/O4a PEM comparison.

This freezes parent identities and method parity; it does not run PEM or
reinterpret the historical O4a verdicts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
from typing import Any

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_pem import (
    load_contract as load_o3a_contract,
    preflight_inputs as preflight_o3a_inputs,
)
from src.dante_light.o4a_corrected_native_pem import (
    _external_inputs as select_o4a_inputs,
    load_native_pem_contract as load_o4a_contract,
)
from src.dante_light.o4a_pem_raw_replay import load_contract as load_raw_replay_contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o3a_o4a_common_pem_v1.json")


def _host_path(root: Path, value: str) -> Path:
    if re.fullmatch(r"[A-Za-z]:/.*", value):
        if os.name == "nt":
            return Path(value).resolve()
        return (Path("/mnt") / value[0].lower() / value[3:]).resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ContractError("common PEM repository reference escapes root")
    return path


def _verified(root: Path, reference: Mapping[str, Any]) -> Path:
    path = _host_path(root, str(reference["path"]))
    if not path.is_file() or sha256_file(path) != reference["sha256"]:
        raise ContractError(f"common PEM reference digest mismatch: {path}")
    return path


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"common PEM expected JSON object: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if not all(isinstance(row, dict) for row in rows):
        raise ContractError(f"common PEM expected JSONL objects: {path}")
    return rows


def _check_method(
    value: Mapping[str, Any], *, root: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    o3a = load_o3a_contract(root=root)
    o4a = load_o4a_contract(root=root)
    refs = value["method"]
    if (
        _verified(root, refs["o3a_contract"])
        != root / "config/dante_o3a_native_pem_v1.json"
        or _verified(root, refs["o4a_contract"])
        != root / "config/dante_o4a_corrected_native_pem_v1.json"
    ):
        raise ContractError("common PEM method contract paths changed")
    o4a_measurement = {
        key: item
        for key, item in o4a["measurement"].items()
        if key != "candidate_exclusion_population"
    }
    if (
        refs["measurement"] != o3a["measurement"]
        or refs["measurement"] != o4a_measurement
    ):
        raise ContractError("common PEM measurement parity changed")
    channels = refs["channels"]
    if set(channels) != {"H1", "L1", "explicitly_excluded"}:
        raise ContractError("common PEM channel schema changed")
    for detector in ("H1", "L1"):
        common = [
            channel
            for channel in o4a["channels"][detector]
            if channel in o3a["channels"][detector]
        ]
        if (
            channels[detector] != o3a["channels"][detector]
            or channels[detector] != common
            or len(common) != o3a["channels"]["channel_count_per_detector"]
        ):
            raise ContractError("common PEM channel intersection changed")
    if (
        channels["explicitly_excluded"] != o3a["channels"]["explicitly_excluded"]
        or channels["explicitly_excluded"] != o4a["channels"]["explicitly_excluded"]
    ):
        raise ContractError("common PEM excluded channels changed")
    return o3a, o4a


def _check_targets(
    run: str,
    spec: Mapping[str, Any],
    *,
    root: Path,
    parent_contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    compact = _json(_verified(root, spec["pem_compact"]))
    summary_path = _verified(root, spec["pem_summary"])
    target_path = _verified(root, spec["targets"])
    _verified(root, spec["classification"])
    summary, targets = _json(summary_path), _jsonl(target_path)
    if (
        compact.get("status") != spec["pem_compact"]["status"]
        or compact.get("contract_digest") != parent_contract["contract_digest"]
        or summary.get("contract_digest") != parent_contract["contract_digest"]
    ):
        raise ContractError(f"common PEM {run} parent seal or status changed")
    expected_status = {
        "O3a": "PASS_COMPLETE_O3A_NATIVE_PEM_V1",
        "O4a": "PASS_COMPLETE_NATIVE_PEM_V1",
    }[run]
    if summary.get("status") != expected_status:
        raise ContractError(f"common PEM {run} full summary status changed")
    expected_run_key = (
        compact["run_key"] if run == "O3a" else compact["external_run"]["run_key"]
    )
    expected_prefix = "native_pem_o3a_" if run == "O3a" else "native_pem_"
    if (
        summary.get("run_key") != expected_run_key
        or target_path.parent != summary_path.parent
        or target_path.parent.name != expected_prefix + expected_run_key
    ):
        raise ContractError(f"common PEM {run} external run identity changed")
    output = summary["outputs"]["targets"]
    if (
        len(targets) != spec["targets"]["expected_count"]
        or output["row_total"] != len(targets)
        or output["sha256"] != spec["targets"]["sha256"]
        or output["row_digest"] != canonical_json_sha256(targets)
    ):
        raise ContractError(f"common PEM {run} target ledger changed")
    if run == "O4a":
        compact_target = compact["outputs"]["targets"]
        if (
            any(compact_target.get(key) != item for key, item in output.items())
            or compact_target["size_bytes"] != target_path.stat().st_size
        ):
            raise ContractError("common PEM O4a compact target receipt changed")
    identities: set[tuple[str, float]] = set()
    for population, native_class in (
        ("primary", "ROBUST"),
        ("diagnostic", "AMBIGUOUS"),
    ):
        rows = [row for row in targets if row["population"] == population]
        counts = Counter(row["detector"] for row in rows)
        expected = spec[population]
        if (
            {key: counts[key] for key in ("H1", "L1")}
            != {key: expected[key] for key in ("H1", "L1")}
            or len(rows) != expected["total"]
            or any(row["native_class"] != native_class for row in rows)
        ):
            raise ContractError(f"common PEM {run} {population} population changed")
        for row in rows:
            key = str(row["detector"]), float(row["gps_start"])
            if key in identities:
                raise ContractError(f"common PEM {run} target identity duplicated")
            identities.add(key)
    exclusion_digest = (
        summary["candidate_exclusion_digest"]
        if run == "O3a"
        else summary["sources"]["candidate_exclusion_digest"]
    )
    exclusion_total = spec["candidate_exclusion"]["expected_count"]
    classification = _json(_verified(root, spec["classification"]))
    observed_total = (
        classification["row_total"]
        if run == "O3a"
        else classification["output"]["row_total"]
    )
    if (
        run == "O4a"
        and summary["sources"]["candidate_exclusion_total"] != observed_total
    ):
        raise ContractError("common PEM O4a candidate-exclusion count changed")
    if (
        exclusion_digest != spec["candidate_exclusion"]["digest"]
        or observed_total != exclusion_total
    ):
        raise ContractError(f"common PEM {run} candidate-exclusion receipt changed")
    return targets, exclusion_digest


def _check_full_selections(
    value: Mapping[str, Any], *, root: Path, o4a: Mapping[str, Any]
) -> None:
    o3a_preflight, o3a_targets, o3a_exclusion = preflight_o3a_inputs(root=root)
    o3a_spec = value["runs"]["O3a"]
    if (
        o3a_preflight["target_digest"] != canonical_json_sha256(o3a_targets)
        or len(o3a_targets) != o3a_spec["targets"]["expected_count"]
        or len(o3a_exclusion) != o3a_spec["candidate_exclusion"]["expected_count"]
        or canonical_json_sha256(o3a_exclusion)
        != o3a_spec["candidate_exclusion"]["digest"]
        or o3a_targets != _jsonl(_verified(root, o3a_spec["targets"]))
    ):
        raise ContractError("common PEM O3a full target/exclusion selection changed")
    o4a_spec = value["runs"]["O4a"]
    coincidence = _json(root / o4a["references"]["native_coincidence"]["path"])
    classification = _json(root / o4a["references"]["native_classification"]["path"])
    coincidence_root = _host_path(root, coincidence["external_run"]["directory"]).parent
    classification_root = _host_path(
        root, classification["external_run"]["directory"]
    ).parent
    o4a_targets, o4a_exclusion, _ = select_o4a_inputs(
        root=root,
        contract=o4a,
        coincidence_external_root=coincidence_root,
        classification_external_root=classification_root,
    )
    if (
        len(o4a_targets) != o4a_spec["targets"]["expected_count"]
        or len(o4a_exclusion) != o4a_spec["candidate_exclusion"]["expected_count"]
        or canonical_json_sha256(o4a_exclusion)
        != o4a_spec["candidate_exclusion"]["digest"]
        or o4a_targets != _jsonl(_verified(root, o4a_spec["targets"]))
    ):
        raise ContractError("common PEM O4a full target/exclusion selection changed")


def validate_contract(value: Mapping[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    body = json.loads(json.dumps(value, allow_nan=False))
    digest = body.pop("contract_digest", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("common PEM contract digest changed")
    if (
        body.get("schema_version") != 1
        or body.get("contract_id") != "dante-o3a-o4a-common-pem-v1"
        or body.get("status") != "FROZEN_INPUTS_NO_COMPARATIVE_RESULTS"
    ):
        raise ContractError("common PEM contract identity changed")
    if body["comparison_boundary"] != {
        "diagnostic_only": True,
        "same_five_public_channels_per_detector": True,
        "run_specific_target_and_candidate_exclusion_populations": True,
        "fresh_five_channel_family_wise_null_per_run": True,
        "historical_outputs_immutable": True,
        "primary_and_diagnostic_separate": True,
        "unreleased_sensors_cleared": False,
        "global_significance_claim": False,
        "astrophysical_confirmation_claim": False,
        "a2_promoted": False,
    }:
        raise ContractError("common PEM interpretation boundary changed")
    o3a, o4a = _check_method(body, root=root)
    for reference in body["source_references"].values():
        _verified(root, reference)
    raw_contract = load_raw_replay_contract(root=root)
    if (
        body["source_references"]["o4a_raw_replay_contract"]["sha256"]
        != sha256_file(root / "config/dante_o4a_pem_raw_replay_v1.json")
        or raw_contract["historical_targets"]["sha256"]
        != body["runs"]["O4a"]["targets"]["sha256"]
    ):
        raise ContractError("common PEM O4a raw replay parent changed")
    for run, parent in (("O3a", o3a), ("O4a", o4a)):
        spec = body["runs"][run]
        if (
            spec["primary"]
            != {
                key: parent["population"]["primary"][key]
                for key in ("H1", "L1", "total")
            }
            or spec["diagnostic"]
            != {
                key: parent["population"]["diagnostic"][key]
                for key in ("H1", "L1", "total")
            }
            or spec["targets"]["expected_count"] != parent["population"]["exact_total"]
        ):
            raise ContractError(f"common PEM {run} frozen population changed")
        _check_targets(run, spec, root=root, parent_contract=parent)
    _check_full_selections(body, root=root, o4a=o4a)
    return {**body, "contract_digest": digest}


def load_contract(*, root: Path = ROOT) -> dict[str, Any]:
    return validate_contract(_json(root / CONTRACT_REL), root=root)
