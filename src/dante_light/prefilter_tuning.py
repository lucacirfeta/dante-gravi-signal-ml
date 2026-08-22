"""Outcome-blind development-only tuning for the L4 cheap prefilter."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter import ExcessEnergyFeatures, PrefilterContract
from src.dante_light.prefilter_protocol import PrefilterProtocol


REQUIRED_ROLES = {"background", "robust_candidate", "known_glitch", "injection"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_ledger(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
        ledger_body = dict(ledger)
        declared_digest = ledger_body.pop("ledger_digest", None)
        if declared_digest != canonical_json_sha256(ledger_body):
            raise ContractError(f"feature ledger digest mismatch: {path}")
        rows_path = path.parent / ledger["rows_path"]
        if ledger.get("status") != "complete":
            raise ContractError(f"feature ledger is not complete: {path}")
        if _sha256(rows_path) != ledger["rows_sha256"]:
            raise ContractError(f"feature row SHA256 mismatch: {path}")
        rows = [
            json.loads(line)
            for line in rows_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise ContractError(f"invalid feature ledger {path}: {exc}") from exc
    if len(rows) != int(ledger["row_count"]):
        raise ContractError(f"feature row count mismatch: {path}")
    return ledger, rows


def _grid(values: np.ndarray, cells: int) -> np.ndarray:
    if cells < 2:
        raise ContractError("threshold grid requires at least two cells")
    quantiles = np.linspace(0.0, 1.0, cells)
    observed = np.unique(np.quantile(values, quantiles))
    return np.r_[observed, np.nextafter(observed[-1], np.inf)]


def _validate_rows(
    rows: list[dict[str, Any]], ledger: Mapping[str, Any], role: str, split_sha256: str
) -> None:
    seen: set[str] = set()
    for row in rows:
        try:
            window = WindowIdentity.from_dict(row["window"])
            features = ExcessEnergyFeatures(**row["features"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"invalid feature row in {role}") from exc
        if window.window_id in seen:
            raise ContractError(f"duplicate feature identity in {role}: {window.window_id}")
        seen.add(window.window_id)
        if row.get("roles") != [role] or row.get("detector") != window.detector:
            raise ContractError(f"feature row annotation mismatch in {role}: {window.window_id}")
        if row.get("partition") not in {"development", "evaluation"}:
            raise ContractError(f"invalid feature partition in {role}: {window.window_id}")
        if row.get("representation_sha256") != ledger["representation_sha256"]:
            raise ContractError(f"feature row representation mismatch in {role}: {window.window_id}")
        if row.get("split_artifact_sha256_by_role") != {role: split_sha256}:
            raise ContractError(f"feature row split mismatch in {role}: {window.window_id}")
        if not isinstance(row.get("retention_target"), bool):
            raise ContractError(f"invalid retention target in {role}: {window.window_id}")


def tune_prefilter(
    *,
    ledgers: Mapping[str, str | Path],
    expected_split_hashes: Mapping[str, str],
    protocol: PrefilterProtocol,
) -> dict[str, Any]:
    """Select one global OR operating point using development rows only."""

    if set(ledgers) != REQUIRED_ROLES:
        raise ContractError(f"tuning requires exactly these roles: {sorted(REQUIRED_ROLES)}")
    if set(expected_split_hashes) != REQUIRED_ROLES:
        raise ContractError(
            f"tuning requires split hashes for exactly these roles: {sorted(REQUIRED_ROLES)}"
        )
    protocol_payload = protocol.payload
    detectors = tuple(protocol_payload["required_detectors"])
    morphologies = protocol_payload["required_morphologies_by_role"]
    audit = protocol_payload["audit"]
    tuning_rules = protocol_payload["tuning"]
    audit_fraction = float(audit["fraction"])
    audit_seed = int(audit["seed"])
    grid_cells = int(tuning_rules["grid_cells"])
    minimum_development_retention = float(
        tuning_rules["minimum_development_retention"]
    )
    minimum_effective_reduction = float(
        tuning_rules["minimum_effective_reduction"]
    )
    minimum_background_per_detector = int(
        tuning_rules["minimum_background_per_detector"]
    )
    required_group_sizes = tuning_rules["minimum_group_n_by_role"]
    expected_positive_groups = {
        *(("robust_candidate", detector, "unknown") for detector in detectors),
        *(
            (role, detector, morphology)
            for role in ("known_glitch", "injection")
            for detector in detectors
            for morphology in morphologies[role]
        ),
    }
    source_records = []
    all_rows: list[dict[str, Any]] = []
    representations = set()
    for role, raw_path in sorted(ledgers.items()):
        path = Path(raw_path).resolve()
        ledger, rows = _load_ledger(path)
        if ledger.get("role") != role:
            raise ContractError(f"feature ledger role mismatch: {path}")
        observed_split = ledger.get("cohort_split_sha256_by_role", {}).get(role)
        if observed_split != expected_split_hashes[role]:
            raise ContractError(f"feature ledger split hash mismatch for {role}: {path}")
        _validate_rows(rows, ledger, role, observed_split)
        representations.add(ledger["representation_sha256"])
        source_records.append(
            {
                "role": role,
                "file_name": path.name,
                "sha256": _sha256(path),
                "rows_sha256": ledger["rows_sha256"],
                "role_split_sha256": observed_split,
            }
        )
        all_rows.extend(row for row in rows if row.get("partition") == "development")
    if len(representations) != 1:
        raise ContractError("development ledgers use different representations")
    identities = [row["window"]["window_id"] for row in all_rows]
    if len(identities) != len(set(identities)):
        raise ContractError("development feature ledgers overlap in window identity")
    background = [row for row in all_rows if row["roles"] == ["background"]]
    positives = [row for row in all_rows if row.get("retention_target") is True]
    if not background or not positives:
        raise ContractError("tuning requires development background and positive controls")
    for detector in detectors:
        count = sum(row["detector"] == detector for row in background)
        if count < minimum_background_per_detector:
            raise ContractError(
                f"underpowered development background for {detector}: {count}"
            )

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in positives:
        role = row["roles"][0]
        groups[(role, row["detector"], row["morphology"])].append(row)
    if set(groups) != expected_positive_groups:
        missing = sorted(expected_positive_groups - set(groups))
        extra = sorted(set(groups) - expected_positive_groups)
        raise ContractError(
            f"unexpected development positive-group coverage; missing={missing}, extra={extra}"
        )
    for (role, detector, morphology), rows in groups.items():
        if len(rows) < required_group_sizes[role]:
            raise ContractError(
                f"underpowered development group {role}/{detector}/{morphology}: {len(rows)}"
            )
    crest_values = np.asarray([row["features"]["crest_factor"] for row in all_rows])
    band_values = np.asarray([row["features"]["peak_band_fraction"] for row in all_rows])
    crest_grid = _grid(crest_values, grid_cells)
    band_grid = _grid(band_values, grid_cells)
    best: dict[str, Any] | None = None
    for crest_threshold in crest_grid:
        for band_threshold in band_grid:
            group_rates = {}
            valid = True
            for key, rows in groups.items():
                retained = int(sum(
                    row["features"]["crest_factor"] >= crest_threshold
                    or row["features"]["peak_band_fraction"] >= band_threshold
                    for row in rows
                ))
                rate = float(retained / len(rows))
                group_rates["/".join(key)] = {"retained": retained, "n": len(rows), "rate": rate}
                if rate < minimum_development_retention:
                    valid = False
                    break
            if not valid:
                continue
            contract = PrefilterContract(
                contract_id="l4-development-search",
                status="research_only",
                crest_threshold=float(crest_threshold),
                band_fraction_threshold=float(band_threshold),
                audit_fraction=float(audit_fraction),
                seed=int(audit_seed),
            )
            calls = 0
            for row in background:
                features = ExcessEnergyFeatures(**row["features"])
                window = WindowIdentity.from_dict(row["window"])
                selected = contract.would_escalate(features)
                calls += bool(selected or ((not selected) and contract.audit_selected(window)))
            reduction = float(1.0 - calls / len(background))
            candidate = {
                "crest_threshold": float(crest_threshold),
                "band_fraction_threshold": float(band_threshold),
                "effective_background_reduction": reduction,
                "would_call_dino": int(calls),
                "background_n": len(background),
                "development_groups": group_rates,
            }
            rank = (
                reduction,
                min(value["rate"] for value in group_rates.values()),
                -float(crest_threshold),
                -float(band_threshold),
            )
            if best is None or rank > best["_rank"]:
                best = {**candidate, "_rank": rank}
    if best is None:
        status = "NOT_READY"
        operating_point = None
    else:
        best.pop("_rank")
        operating_point = best
        status = (
            "PASS"
            if best["effective_background_reduction"] >= minimum_effective_reduction
            else "NOT_READY"
        )
    result = {
        "schema_version": 1,
        "status": status,
        "scientific_mode": "development_only_prefilter_tuning",
        "routing_enabled": False,
        "outcome_fields_used": ["retention_target", "role", "detector", "morphology"],
        "evaluation_outcomes_used": [],
        "protocol": protocol.reference,
        "representation_sha256": representations.pop(),
        "cohort_split_sha256_by_role": dict(sorted(expected_split_hashes.items())),
        "source_ledgers": source_records,
        "search": {
            "feature_rule": "crest_factor >= crest OR peak_band_fraction >= band",
            "grid_method": "equally_spaced_empirical_quantiles",
            "grid_cells_requested": int(grid_cells),
            "crest_grid_n": int(len(crest_grid)),
            "band_grid_n": int(len(band_grid)),
            "minimum_development_retention": float(minimum_development_retention),
            "minimum_effective_reduction": float(minimum_effective_reduction),
            "minimum_background_per_detector": int(minimum_background_per_detector),
            "audit_fraction": float(audit_fraction),
            "audit_seed": int(audit_seed),
        },
        "operating_point": operating_point,
    }
    result["artifact_digest"] = canonical_json_sha256(result)
    return result


def write_tuning_result(result: Mapping[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination
