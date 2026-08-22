"""Assemble immutable inputs for the held-out DANTE-Light L4 v2 evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v2 import PrefilterFeaturesV2, feature_names_by_family
from src.dante_light.prefilter_v2_protocol import PrefilterProtocolV2


CONTROL_ROLES = ("robust_candidate", "known_glitch", "injection")
ALL_SOURCE_ROLES = ("background", "shadow", *CONTROL_ROLES)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError(f"JSON artifact is not an object: {path}")
    return payload


def _load_source(
    path: Path,
    role: str,
    *,
    feature_source: str,
    expected_feature_names: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ledger = _json(path)
    body = dict(ledger)
    if body.pop("ledger_digest", None) != canonical_json_sha256(body):
        raise ContractError(f"v2 source ledger digest mismatch: {path}")
    if ledger.get("schema_version") != 2 or ledger.get("status") != "complete":
        raise ContractError(f"v2 source ledger is incomplete: {path}")
    if ledger.get("feature_source") != feature_source:
        raise ContractError(f"v2 source feature contract changed: {path}")
    if role != "shadow" and ledger.get("role") != role:
        raise ContractError(f"v2 source role mismatch for {role}: {path}")
    if ledger.get("outcome_fields_used_for_feature_extraction") != []:
        raise ContractError(f"outcomes entered v2 feature extraction: {path}")
    split_hashes = ledger.get("cohort_split_sha256_by_role")
    if not isinstance(split_hashes, dict) or set(split_hashes) != {role}:
        raise ContractError(f"v2 source split binding mismatch for {role}: {path}")
    rows_path = path.parent / str(ledger.get("rows_path", ""))
    if not rows_path.is_file() or _sha256(rows_path) != ledger.get("rows_sha256"):
        raise ContractError(f"v2 source rows changed: {path}")
    try:
        rows = [
            json.loads(line)
            for line in rows_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid v2 source rows: {rows_path}") from exc
    if len(rows) != int(ledger.get("row_count", -1)):
        raise ContractError(f"v2 source row count mismatch: {path}")
    seen: set[str] = set()
    split_hash = split_hashes[role]
    for row in rows:
        try:
            window = WindowIdentity.from_dict(row["window"])
            features = PrefilterFeaturesV2(**row["features"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"invalid v2 source feature row: {path}") from exc
        if set(features.values) != expected_feature_names:
            raise ContractError(f"v2 source feature schema changed: {window.window_id}")
        if window.window_id in seen:
            raise ContractError(f"duplicate v2 source identity: {window.window_id}")
        seen.add(window.window_id)
        if row.get("roles") != [role] or row.get("detector") != window.detector:
            raise ContractError(f"v2 source annotation mismatch: {window.window_id}")
        if row.get("partition") not in {"development", "evaluation"}:
            raise ContractError(f"v2 source partition mismatch: {window.window_id}")
        if row.get("split_artifact_sha256_by_role") != {role: split_hash}:
            raise ContractError(f"v2 source row split mismatch: {window.window_id}")
        if row.get("representation_sha256") != ledger.get("representation_sha256"):
            raise ContractError(f"v2 source representation mismatch: {window.window_id}")
        if not isinstance(row.get("retention_target"), bool):
            raise ContractError(f"v2 retention target is not boolean: {window.window_id}")
    return ledger, rows


def _validate_screening(
    screening: Mapping[str, Any],
    screening_path: Path,
    sources: Mapping[str, tuple[Path, dict[str, Any], list[dict[str, Any]]]],
    protocol: PrefilterProtocolV2,
) -> None:
    body = dict(screening)
    if body.pop("artifact_digest", None) != canonical_json_sha256(body):
        raise ContractError("v2 screening artifact digest mismatch")
    if screening.get("schema_version") != 2 or screening.get("status") != "PASS":
        raise ContractError("v2 development screening is not PASS")
    if screening.get("scientific_mode") != "development_only_block_cross_validated_prefilter_screening":
        raise ContractError("v2 screening mode changed")
    if screening.get("routing_enabled") is not False or screening.get("o4b_outcomes_used") != []:
        raise ContractError("v2 screening violated the frozen scientific boundary")
    if screening.get("protocol") != protocol.reference:
        raise ContractError("v2 screening protocol binding changed")
    expected_splits = {
        role: sources[role][1]["cohort_split_sha256_by_role"][role]
        for role in ("background", *CONTROL_ROLES)
    }
    if screening.get("cohort_split_sha256_by_role") != expected_splits:
        raise ContractError("v2 screening source splits changed")
    expected_records = []
    for role in sorted(("background", *CONTROL_ROLES)):
        path, ledger, _rows = sources[role]
        expected_records.append(
            {
                "role": role,
                "file_name": path.name,
                "sha256": _sha256(path),
                "rows_sha256": ledger["rows_sha256"],
                "role_split_sha256": ledger["cohort_split_sha256_by_role"][role],
            }
        )
    if screening.get("source_ledgers") != expected_records:
        raise ContractError("v2 screening source ledger provenance changed")
    selected = screening.get("selected_operating_point")
    if not isinstance(selected, dict) or set(selected.get("models", {})) != set(protocol.payload["required_detectors"]):
        raise ContractError("v2 screening has no complete operating point")


def _group_rules(detectors: tuple[str, ...], protocol: PrefilterProtocolV2) -> list[dict[str, Any]]:
    evaluation = protocol.payload["evaluation"]
    morphologies = protocol.payload["required_morphologies_by_role"]
    rules = []
    for detector in detectors:
        role = "robust_candidate"
        rules.append(
            {
                "name": f"{role}_{detector}",
                "filters": {"role": role, "detector": detector, "retention_target": True},
                "minimum_n": int(evaluation["minimum_group_n_by_role"][role]),
                "minimum_retention": float(evaluation["minimum_retention_by_role"][role]),
                "minimum_wilson_lower": float(evaluation["minimum_wilson_lower_by_role"][role]),
            }
        )
    for role in ("known_glitch", "injection"):
        for detector in detectors:
            for morphology in morphologies[role]:
                rules.append(
                    {
                        "name": f"{role}_{detector}_{morphology}",
                        "filters": {
                            "role": role,
                            "detector": detector,
                            "morphology": morphology,
                            "retention_target": True,
                        },
                        "minimum_n": int(evaluation["minimum_group_n_by_role"][role]),
                        "minimum_retention": float(evaluation["minimum_retention_by_role"][role]),
                        "minimum_wilson_lower": float(evaluation["minimum_wilson_lower_by_role"][role]),
                    }
                )
    return rules


def assemble_prefilter_v2_evaluation(
    *,
    ledgers: Mapping[str, str | Path],
    screening_path: str | Path,
    output_dir: str | Path,
    protocol: PrefilterProtocolV2,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lock the v2 screening result and evaluation-only feature rows."""

    if set(ledgers) != set(ALL_SOURCE_ROLES):
        raise ContractError(f"v2 assembly requires exactly {sorted(ALL_SOURCE_ROLES)}")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    feature_source = f"prefilter-v2:{protocol.payload['protocol_digest']}"
    expected_names = {
        name
        for names in feature_names_by_family(protocol.payload["feature_extraction"]).values()
        for name in names
    }
    sources = {}
    for role, raw_path in ledgers.items():
        path = Path(raw_path).resolve()
        ledger, rows = _load_source(
            path,
            role,
            feature_source=feature_source,
            expected_feature_names=expected_names,
        )
        sources[role] = (path, ledger, rows)
    representations = {ledger["representation_sha256"] for _, ledger, _ in sources.values()}
    if len(representations) != 1:
        raise ContractError("v2 source representations differ")
    representation_sha256 = representations.pop()

    screening_path = Path(screening_path).resolve()
    screening = _json(screening_path)
    _validate_screening(screening, screening_path, sources, protocol)
    if screening.get("representation_sha256") != representation_sha256:
        raise ContractError("v2 screening representation changed")

    evaluation_rows = []
    for role in ("shadow", *CONTROL_ROLES):
        rows = sources[role][2]
        selected = rows if role == "shadow" else [row for row in rows if row["partition"] == "evaluation"]
        if role == "shadow" and any(row["partition"] != "evaluation" for row in selected):
            raise ContractError("v2 shadow source contains development rows")
        evaluation_rows.extend(selected)
    identities = [WindowIdentity.from_dict(row["window"]).window_id for row in evaluation_rows]
    if len(identities) != len(set(identities)):
        raise ContractError("v2 evaluation sources overlap")
    evaluation_rows.sort(key=lambda row: WindowIdentity.from_dict(row["window"]).window_id)

    shadow_rows = sources["shadow"][2]
    detectors = tuple(sorted({row["detector"] for row in shadow_rows}))
    if detectors != tuple(sorted(protocol.payload["required_detectors"])):
        raise ContractError("v2 shadow detector coverage is incomplete")
    starts = {
        detector: min(float(row["window"]["gps_start"]) for row in shadow_rows if row["detector"] == detector)
        for detector in detectors
    }
    split_hashes = {
        role: sources[role][1]["cohort_split_sha256_by_role"][role]
        for role in ("shadow", *CONTROL_ROLES)
    }
    local_screening = output_dir / "screening_result_v2.json"
    if screening_path != local_screening:
        shutil.copyfile(screening_path, local_screening)
    screening_ref = {"path": local_screening.name, "sha256": _sha256(local_screening)}
    local_protocol = output_dir / protocol.path.name
    if protocol.path != local_protocol:
        shutil.copyfile(protocol.path, local_protocol)
    protocol_ref = {
        "path": local_protocol.name,
        "sha256": protocol.sha256,
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_digest": protocol.payload["protocol_digest"],
    }
    evaluation = protocol.payload["evaluation"]
    selected = screening["selected_operating_point"]
    contract = {
        "schema_version": 2,
        "status": "locked_before_evaluation",
        "contract_id": f"dante-light-l4-v2-{screening['artifact_digest'][:16]}",
        "feature_source": feature_source,
        "models_by_detector": selected["models"],
        "audit_fraction": float(protocol.payload["audit"]["fraction"]),
        "audit_seed": int(protocol.payload["audit"]["seed"]),
        "minimum_compute_reduction": float(evaluation["minimum_compute_reduction"]),
        "minimum_exact_escalates": int(evaluation["minimum_exact_escalates"]),
        "wilson_confidence": float(evaluation["wilson_confidence"]),
        "representation_sha256": representation_sha256,
        "evaluation_start_gps_by_detector": starts,
        "required_detectors": list(protocol.payload["required_detectors"]),
        "required_morphologies_by_role": protocol.payload["required_morphologies_by_role"],
        "cohort_split_sha256_by_role": split_hashes,
        "screening_artifact": screening_ref,
        "protocol_artifact": protocol_ref,
        "required_groups": _group_rules(detectors, protocol),
    }
    contract["contract_digest"] = canonical_json_sha256(contract)
    contract_path = output_dir / "evaluation_contract_v2.json"
    contract_path.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    rows_path = output_dir / "evaluation_features_v2.jsonl"
    rows_path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in evaluation_rows),
        encoding="utf-8",
        newline="\n",
    )
    source_records = [
        {
            "role": role,
            "file_name": path.name,
            "sha256": _sha256(path),
            "rows_sha256": source_ledger["rows_sha256"],
        }
        for role, (path, source_ledger, _rows) in sorted(sources.items())
    ]
    ledger = {
        "schema_version": 2,
        "status": "complete",
        "scientific_mode": "research_only_heldout_prefilter_v2_evaluation",
        "feature_source": feature_source,
        "outcome_fields_used_for_threshold_selection": [],
        "screening_artifact": screening_ref,
        "protocol_artifact": protocol_ref,
        "representation_sha256": representation_sha256,
        "cohort_split_sha256_by_role": split_hashes,
        "row_count": len(evaluation_rows),
        "rows_path": rows_path.name,
        "rows_sha256": _sha256(rows_path),
        "source_ledgers": source_records,
    }
    ledger["ledger_digest"] = canonical_json_sha256(ledger)
    ledger_path = output_dir / "evaluation_feature_ledger_v2.json"
    ledger_path.write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return contract, ledger
