#!/usr/bin/env python3
"""Verify DANTE-Light L4 v2 split, feature, screening and evaluation artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_splits import load_prefilter_splits
from src.dante_light.prefilter_v2 import feature_names_by_family
from src.dante_light.prefilter_v2_assembly import _load_source
from src.dante_light.prefilter_v2_evaluation import evaluate_prefilter_v2
from src.dante_light.prefilter_v2_diagnostics import (
    DEFAULT_DIAGNOSTIC_CONFIG,
    diagnose_prefilter_v2,
    load_diagnostic_config,
)
from src.dante_light.prefilter_v2_protocol import DEFAULT_PROTOCOL_V2_PATH, load_prefilter_v2_protocol


DEVELOPMENT_ROLES = ("background", "robust_candidate", "known_glitch", "injection")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(path: Path | None, label: str) -> Path:
    if path is None or not path.is_file():
        raise ContractError(f"{label} is required and must exist")
    return path.resolve()


def _verify_split(path: Path, protocol: object) -> dict:
    split = load_prefilter_splits(path)
    body = dict(split)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v2 split artifact digest mismatch")
    if split.get("schema_version") != 2 or split.get("status") != "availability_screened_before_feature_extraction":
        raise ContractError("v2 split is not availability-screened and frozen")
    if split.get("protocol") != protocol.reference:
        raise ContractError("v2 split protocol binding changed")
    if split.get("outcome_fields_used_for_partition") != []:
        raise ContractError("outcomes entered v2 split construction")
    if set(split.get("cohorts", {})) != set(DEVELOPMENT_ROLES):
        raise ContractError("v2 split cohort coverage is incomplete")
    return split


def _verify_development(args: argparse.Namespace, protocol: object, split: dict):
    feature_source = f"prefilter-v2:{protocol.payload['protocol_digest']}"
    expected_names = {
        name
        for names in feature_names_by_family(protocol.payload["feature_extraction"]).values()
        for name in names
    }
    paths = {
        "background": _require(args.background, "background ledger"),
        "robust_candidate": _require(args.robust, "robust ledger"),
        "known_glitch": _require(args.known, "known-glitch ledger"),
        "injection": _require(args.injection, "injection ledger"),
    }
    sources = {}
    for role, path in paths.items():
        ledger, rows = _load_source(
            path,
            role,
            feature_source=feature_source,
            expected_feature_names=expected_names,
        )
        expected_split = split["cohorts"][role]["split_sha256"]
        if ledger["cohort_split_sha256_by_role"] != {role: expected_split}:
            raise ContractError(f"v2 {role} ledger is bound to a different split")
        sources[role] = (path, ledger, rows)
    representations = {ledger["representation_sha256"] for _, ledger, _ in sources.values()}
    if len(representations) != 1:
        raise ContractError("v2 development representations differ")
    return sources


def _verify_screening(path: Path, protocol: object, sources: dict) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v2 screening artifact: {exc}") from exc
    body = dict(result)
    if body.pop("artifact_digest", None) != canonical_json_sha256(body):
        raise ContractError("v2 screening artifact digest mismatch")
    if result.get("status") not in {"PASS", "NOT_READY"}:
        raise ContractError("v2 screening status is invalid")
    if (
        result.get("protocol") != protocol.reference
        or result.get("routing_enabled") is not False
        or result.get("o4b_outcomes_used") != []
    ):
        raise ContractError("v2 screening scientific boundary changed")
    expected_splits = {
        role: sources[role][1]["cohort_split_sha256_by_role"][role]
        for role in DEVELOPMENT_ROLES
    }
    if result.get("cohort_split_sha256_by_role") != dict(sorted(expected_splits.items())):
        raise ContractError("v2 screening split provenance changed")
    expected_records = [
        {
            "role": role,
            "file_name": source_path.name,
            "sha256": _sha256(source_path),
            "rows_sha256": ledger["rows_sha256"],
            "role_split_sha256": ledger["cohort_split_sha256_by_role"][role],
        }
        for role, (source_path, ledger, _rows) in sorted(sources.items())
    ]
    if result.get("source_ledgers") != expected_records:
        raise ContractError("v2 screening ledger provenance changed")
    if (result["status"] == "PASS") != isinstance(result.get("selected_operating_point"), dict):
        raise ContractError("v2 screening operating-point status is inconsistent")
    return result


def _verify_summary(path: Path, screening_path: Path, screening: dict, protocol: object, split: dict) -> None:
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v2 compact screening summary: {exc}") from exc
    if (
        summary.get("schema_version") != 2
        or summary.get("status") != screening["status"]
        or summary.get("routing_enabled") is not False
    ):
        raise ContractError("v2 compact summary status changed")
    if summary.get("protocol") != {
        "path": "config/dante_light_prefilter_protocol_v2.json",
        "sha256": protocol.sha256,
        "protocol_digest": protocol.payload["protocol_digest"],
    }:
        raise ContractError("v2 compact summary protocol changed")
    if summary.get("representation_sha256") != screening["representation_sha256"]:
        raise ContractError("v2 compact summary representation changed")
    artifact = summary.get("screening_artifact", {})
    if artifact.get("sha256") != _sha256(screening_path) or artifact.get("artifact_digest") != screening["artifact_digest"]:
        raise ContractError("v2 compact summary screening binding changed")
    candidates = [
        {
            "feature_set": candidate["feature_set"],
            "oof_effective_development_call_reduction": candidate[
                "oof_development_background_call_reduction"
            ],
            "status": candidate["status"],
        }
        for candidate in screening["screening"]["candidates"]
    ]
    if summary.get("candidate_results") != candidates:
        raise ContractError("v2 compact summary candidate metrics changed")
    expected_ledgers = [
        {
            "role": record["role"],
            "ledger_sha256": record["sha256"],
            "rows_sha256": record["rows_sha256"],
        }
        for record in screening["source_ledgers"]
    ]
    if summary.get("source_ledgers") != expected_ledgers:
        raise ContractError("v2 compact summary ledger provenance changed")
    expected_splits = {
        role: cohort["split_sha256"] for role, cohort in split["cohorts"].items()
    }
    split_summary = summary.get("split_artifact", {})
    if (
        split_summary.get("role_split_sha256") != expected_splits
        or split_summary.get("artifact_digest") != split["artifact_digest"]
    ):
        raise ContractError("v2 compact summary split provenance changed")
    expected_coverage = {
        "rows": screening["feature_cost"]["development_n"],
        **{
            role: int(split["cohorts"][role]["counts"]["development"])
            for role in DEVELOPMENT_ROLES
        },
    }
    if summary.get("development_coverage") != expected_coverage:
        raise ContractError("v2 compact summary development coverage changed")
    expected_cost = {
        "median": screening["feature_cost"]["feature_extraction_median_s"],
        "p95": screening["feature_cost"]["feature_extraction_p95_s"],
        "maximum": screening["feature_cost"]["feature_extraction_max_s"],
        "excludes_data_read_and_whitening": True,
    }
    if summary.get("feature_cost_s") != expected_cost:
        raise ContractError("v2 compact summary feature cost changed")


def _verify_diagnostics(
    path: Path,
    *,
    screening_path: Path,
    protocol: object,
    split: dict,
    sources: dict,
    config_path: Path,
) -> None:
    diagnostic_config = load_diagnostic_config(config_path, protocol=protocol)
    expected = diagnose_prefilter_v2(
        ledgers={role: source[0] for role, source in sources.items()},
        expected_split_hashes={
            role: cohort["split_sha256"] for role, cohort in split["cohorts"].items()
        },
        frozen_screening_path=screening_path,
        protocol=protocol,
        diagnostic_config=diagnostic_config,
    )
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v2 diagnostic artifact: {exc}") from exc
    if recorded != expected:
        raise ContractError("recorded v2 diagnostics are not exactly reproducible")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("split", "development", "screening", "diagnostics", "evaluation", "all"),
        default="all",
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V2_PATH)
    parser.add_argument("--split", type=Path, default=ROOT / "config/dante_light_prefilter_splits_v2.json")
    parser.add_argument("--background", type=Path)
    parser.add_argument("--robust", type=Path)
    parser.add_argument("--known", type=Path)
    parser.add_argument("--injection", type=Path)
    parser.add_argument("--screening", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--diagnostics", type=Path)
    parser.add_argument("--diagnostic-config", type=Path, default=DEFAULT_DIAGNOSTIC_CONFIG)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--evaluation-ledger", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    try:
        protocol = load_prefilter_v2_protocol(args.protocol)
        split = _verify_split(_require(args.split, "v2 split"), protocol)
        stages = {args.stage} if args.stage != "all" else {
            "split", "development", "screening", "evaluation"
        }
        sources = None
        screening = None
        if stages & {"development", "screening", "diagnostics"}:
            sources = _verify_development(args, protocol, split)
        if stages & {"screening", "diagnostics"}:
            screening_path = _require(args.screening, "screening result")
            screening = _verify_screening(screening_path, protocol, sources)
            if "screening" in stages and args.summary is not None:
                _verify_summary(_require(args.summary, "compact screening summary"), screening_path, screening, protocol, split)
        if "diagnostics" in stages:
            _verify_diagnostics(
                _require(args.diagnostics, "diagnostic result"),
                screening_path=screening_path,
                protocol=protocol,
                split=split,
                sources=sources,
                config_path=_require(args.diagnostic_config, "diagnostic config"),
            )
        if "evaluation" in stages:
            if screening is not None and screening["status"] != "PASS":
                raise ContractError("held-out evaluation is forbidden after NOT_READY screening")
            result = evaluate_prefilter_v2(
                contract_path=_require(args.contract, "evaluation contract"),
                ledger_path=_require(args.evaluation_ledger, "evaluation ledger"),
            )
            if args.result is not None:
                recorded = json.loads(_require(args.result, "evaluation result").read_text(encoding="utf-8"))
                if recorded != result:
                    raise ContractError("recorded v2 evaluation result is not reproducible")
    except (ContractError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(f"PASS: DANTE-Light L4 v2 {args.stage} artifact verification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
