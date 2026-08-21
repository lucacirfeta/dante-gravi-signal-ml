"""Assemble a locked L4 evaluation from frozen, independently built ledgers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter import ExcessEnergyFeatures
from src.dante_light.prefilter_evaluation import FEATURE_SOURCE


CONTROL_ROLES = ("robust_candidate", "known_glitch", "injection")
ALL_SOURCE_ROLES = ("background", "shadow", *CONTROL_ROLES)
KNOWN_MORPHOLOGIES = ("Blip", "KoiFish", "ScatteredLight")
INJECTION_SYSTEMS = ("BBH_30_30", "BBH_10_10", "NSBH_10_1.4")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON artifact is not an object: {path}")
    return value


def _rows(path: Path) -> list[dict[str, Any]]:
    try:
        values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid feature rows {path}: {exc}") from exc
    if not all(isinstance(value, dict) for value in values):
        raise ContractError(f"feature rows must be JSON objects: {path}")
    return values


def _load_source(path: Path, role: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ledger = _json(path)
    ledger_body = dict(ledger)
    declared_digest = ledger_body.pop("ledger_digest", None)
    if declared_digest != canonical_json_sha256(ledger_body):
        raise ContractError(f"source ledger digest mismatch: {path}")
    if ledger.get("status") != "complete":
        raise ContractError(f"source ledger is not complete: {path}")
    if ledger.get("feature_source") != FEATURE_SOURCE:
        raise ContractError(f"source ledger is not canonical: {path}")
    if role != "shadow" and ledger.get("role") != role:
        raise ContractError(f"source ledger role mismatch for {role}: {path}")
    rows_path = path.parent / str(ledger.get("rows_path", ""))
    if not rows_path.is_file() or _sha256(rows_path) != ledger.get("rows_sha256"):
        raise ContractError(f"source feature row hash mismatch: {path}")
    rows = _rows(rows_path)
    if len(rows) != int(ledger.get("row_count", -1)):
        raise ContractError(f"source feature row count mismatch: {path}")
    split_hashes = ledger.get("cohort_split_sha256_by_role")
    if not isinstance(split_hashes, dict) or set(split_hashes) != {role}:
        raise ContractError(f"source split binding mismatch for {role}: {path}")
    split_sha256 = split_hashes[role]
    seen: set[str] = set()
    for row in rows:
        try:
            window = WindowIdentity.from_dict(row["window"])
            ExcessEnergyFeatures(**row["features"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"invalid source feature row for {role}: {path}") from exc
        if window.window_id in seen:
            raise ContractError(f"duplicate source feature identity for {role}: {window.window_id}")
        seen.add(window.window_id)
        if row.get("roles") != [role] or row.get("detector") != window.detector:
            raise ContractError(f"source row annotation mismatch for {role}: {window.window_id}")
        if row.get("partition") not in {"development", "evaluation"}:
            raise ContractError(f"source row partition mismatch for {role}: {window.window_id}")
        if row.get("representation_sha256") != ledger["representation_sha256"]:
            raise ContractError(f"source row representation mismatch for {role}: {window.window_id}")
        if row.get("split_artifact_sha256_by_role") != {role: split_sha256}:
            raise ContractError(f"source row split mismatch for {role}: {window.window_id}")
        if not isinstance(row.get("retention_target"), bool):
            raise ContractError(f"invalid source endpoint or features for {role}: {window.window_id}")
    return ledger, rows


def _validate_tuning(
    tuning: Mapping[str, Any],
    sources: Mapping[str, tuple[Path, dict[str, Any], list[dict[str, Any]]]],
) -> None:
    if tuning.get("status") != "PASS" or tuning.get("routing_enabled") is not False:
        raise ContractError("threshold tuning is not a research-only PASS")
    if tuning.get("scientific_mode") != "development_only_prefilter_tuning":
        raise ContractError("threshold tuning mode is invalid")
    if tuning.get("evaluation_outcomes_used") != []:
        raise ContractError("evaluation outcomes entered threshold tuning")
    body = dict(tuning)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("threshold-tuning artifact digest mismatch")
    expected_splits = {
        role: sources[role][1]["cohort_split_sha256_by_role"][role]
        for role in ("background", *CONTROL_ROLES)
    }
    if tuning.get("cohort_split_sha256_by_role") != expected_splits:
        raise ContractError("threshold tuning is not bound to the source cohort splits")
    records = tuning.get("source_ledgers", [])
    if not isinstance(records, list) or len(records) != 4:
        raise ContractError("threshold tuning has incomplete source provenance")
    expected_records = {
        record["role"]: record for record in tuning.get("source_ledgers", [])
        if isinstance(record, dict) and "role" in record
    }
    if set(expected_records) != {"background", *CONTROL_ROLES}:
        raise ContractError("threshold tuning has incomplete source provenance")
    for role, record in expected_records.items():
        path, ledger, _ = sources[role]
        expected = {
            "role": role,
            "file_name": path.name,
            "sha256": _sha256(path),
            "rows_sha256": ledger["rows_sha256"],
            "role_split_sha256": ledger["cohort_split_sha256_by_role"][role],
        }
        if record != expected:
            raise ContractError(f"threshold tuning source changed for {role}")


def _group_rules(detectors: tuple[str, ...]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for detector in detectors:
        rules.append({
            "name": f"robust_candidate_{detector}",
            "filters": {"role": "robust_candidate", "detector": detector, "retention_target": True},
            "minimum_n": 20,
            "minimum_retention": 0.9,
            "minimum_wilson_lower": 0.8,
        })
    for role, morphologies, minimum_n in (
        ("known_glitch", KNOWN_MORPHOLOGIES, 18),
        ("injection", INJECTION_SYSTEMS, 90),
    ):
        for detector in detectors:
            for morphology in morphologies:
                rules.append({
                    "name": f"{role}_{detector}_{morphology}",
                    "filters": {
                        "role": role,
                        "detector": detector,
                        "morphology": morphology,
                        "retention_target": True,
                    },
                    "minimum_n": minimum_n,
                    "minimum_retention": 0.9,
                    "minimum_wilson_lower": 0.8,
                })
    return rules


def assemble_prefilter_evaluation(
    *,
    ledgers: Mapping[str, str | Path],
    tuning_path: str | Path,
    output_dir: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create the immutable contract and evaluation-only feature ledger."""

    if set(ledgers) != set(ALL_SOURCE_ROLES):
        raise ContractError(f"assembly requires exactly these ledgers: {sorted(ALL_SOURCE_ROLES)}")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    sources: dict[str, tuple[Path, dict[str, Any], list[dict[str, Any]]]] = {}
    for role, raw_path in ledgers.items():
        path = Path(raw_path).resolve()
        ledger, rows = _load_source(path, role)
        sources[role] = (path, ledger, rows)
    representations = {ledger["representation_sha256"] for _, ledger, _ in sources.values()}
    if len(representations) != 1:
        raise ContractError("source ledgers use different representations")
    representation_sha256 = representations.pop()

    tuning_path = Path(tuning_path).resolve()
    tuning = _json(tuning_path)
    _validate_tuning(tuning, sources)
    if tuning.get("representation_sha256") != representation_sha256:
        raise ContractError("threshold tuning representation changed")
    operating_point = tuning.get("operating_point")
    if not isinstance(operating_point, dict):
        raise ContractError("threshold tuning has no operating point")

    evaluation_rows: list[dict[str, Any]] = []
    for role in ("shadow", *CONTROL_ROLES):
        _, _, rows = sources[role]
        selected = rows if role == "shadow" else [row for row in rows if row.get("partition") == "evaluation"]
        if role == "shadow" and any(row.get("partition") != "evaluation" for row in selected):
            raise ContractError("shadow source contains non-evaluation rows")
        evaluation_rows.extend(selected)
    identities = [WindowIdentity.from_dict(row["window"]).window_id for row in evaluation_rows]
    if len(identities) != len(set(identities)):
        raise ContractError("evaluation sources overlap in window identity")
    evaluation_rows.sort(key=lambda row: WindowIdentity.from_dict(row["window"]).window_id)

    shadow_rows = sources["shadow"][2]
    detectors = tuple(sorted({row["detector"] for row in shadow_rows}))
    if detectors != ("H1", "L1"):
        raise ContractError(f"shadow evaluation requires H1 and L1, observed {detectors}")
    starts = {
        detector: min(float(row["window"]["gps_start"]) for row in shadow_rows if row["detector"] == detector)
        for detector in detectors
    }
    split_hashes = {
        role: sources[role][1]["cohort_split_sha256_by_role"][role]
        for role in ("shadow", *CONTROL_ROLES)
    }

    local_tuning = output_dir / "threshold_tuning_v1.json"
    if tuning_path != local_tuning:
        shutil.copyfile(tuning_path, local_tuning)
    tuning_ref = {"path": local_tuning.name, "sha256": _sha256(local_tuning)}
    contract = {
        "schema_version": 1,
        "status": "locked_before_evaluation",
        "contract_id": f"dante-light-l4-{canonical_json_sha256(tuning)[:16]}",
        "feature_source": FEATURE_SOURCE,
        "crest_threshold": float(operating_point["crest_threshold"]),
        "band_fraction_threshold": float(operating_point["band_fraction_threshold"]),
        "audit_fraction": float(tuning["search"]["audit_fraction"]),
        "audit_seed": int(tuning["search"]["audit_seed"]),
        "minimum_compute_reduction": 0.5,
        "minimum_exact_escalates": 18,
        "representation_sha256": representation_sha256,
        "evaluation_start_gps_by_detector": starts,
        "required_detectors": list(detectors),
        "required_morphologies_by_role": {
            "known_glitch": list(KNOWN_MORPHOLOGIES),
            "injection": list(INJECTION_SYSTEMS),
        },
        "cohort_split_sha256_by_role": split_hashes,
        "threshold_tuning_artifact": tuning_ref,
        "required_groups": _group_rules(detectors),
    }
    contract["contract_digest"] = canonical_json_sha256(contract)
    contract_path = output_dir / "evaluation_contract_v1.json"
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    rows_path = output_dir / "evaluation_features_v1.jsonl"
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
        for role, (path, source_ledger, _) in sorted(sources.items())
    ]
    ledger = {
        "schema_version": 1,
        "status": "complete",
        "scientific_mode": "research_only_heldout_prefilter_evaluation",
        "feature_source": FEATURE_SOURCE,
        "outcome_fields_used_for_threshold_selection": [],
        "threshold_tuning_artifact": tuning_ref,
        "representation_sha256": representation_sha256,
        "cohort_split_sha256_by_role": split_hashes,
        "row_count": len(evaluation_rows),
        "rows_path": rows_path.name,
        "rows_sha256": _sha256(rows_path),
        "source_ledgers": source_records,
    }
    ledger["ledger_digest"] = canonical_json_sha256(ledger)
    ledger_path = output_dir / "evaluation_feature_ledger_v1.json"
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return contract, ledger
