from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v3 import feature_names_by_family
from src.dante_light.prefilter_v3_protocol import load_prefilter_v3_protocol
from src.dante_light.prefilter_v3_screening import screen_prefilter_v3


def _protocol(tmp_path):
    payload = deepcopy(dict(load_prefilter_v3_protocol().payload))
    payload["development"]["cross_validation_folds"] = 4
    payload["development"]["gps_block_duration_s"] = 32
    payload["development"]["minimum_background_per_detector"] = 20
    for role in ("robust_candidate", "known_glitch", "injection"):
        payload["development"]["minimum_group_n_by_role"][role] = 16
    payload["uncertainty"]["gps_block_duration_s"] = 32
    payload["uncertainty"]["n_resamples"] = 100
    payload.pop("protocol_digest")
    payload["protocol_digest"] = canonical_json_sha256(payload)
    path = tmp_path / "protocol_v3.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_prefilter_v3_protocol(path)


def _features(protocol, *, signal: bool, index: int):
    families = feature_names_by_family(protocol.payload["feature_extraction"])
    values = {}
    for family, names in families.items():
        for feature_index, name in enumerate(names):
            if family in {"signed_ordering", "ridge_consistency"}:
                values[name] = (8.0 if signal else 0.0) + 1e-5 * (index + feature_index)
            else:
                values[name] = 1.0 + 1e-5 * ((index * 7 + feature_index) % 17)
    return {"values": values}


def _row(protocol, index, role, detector, morphology, positive, *, signal=True):
    run = "O3B" if role == "known_glitch" else "O4A"
    window = WindowIdentity(run, detector, 1_200_000_000 + index * 64)
    split_hash = protocol.payload["parent_v2"]["split"]["role_split_sha256"][role]
    return {
        "schema_version": 3,
        "window": window.to_dict(),
        "roles": [role],
        "partition": "development",
        "split_artifact_sha256_by_role": {role: split_hash},
        "detector": detector,
        "morphology": morphology,
        "retention_target": positive,
        "exact_disposition": "NOT_APPLICABLE",
        "representation_sha256": "a" * 64,
        "strain_sha256": f"{index + 1:064x}",
        "features": _features(protocol, signal=positive and signal, index=index),
        "timings": {"feature_extraction_s": 0.002},
        "cohort_id": f"{role}:{detector}:{morphology}:{index}",
    }


def _ledger(tmp_path, protocol, role, rows):
    directory = tmp_path / role
    directory.mkdir()
    rows_path = directory / f"{role}_features_v3_development.jsonl"
    rows_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    split = protocol.payload["parent_v2"]["split"]
    split_hash = split["role_split_sha256"][role]
    payload = {
        "schema_version": 3,
        "status": "complete",
        "scientific_mode": "v3_hypothesis_generating_development_feature_extraction",
        "feature_source": f"prefilter-v3:{protocol.payload['protocol_digest']}",
        "outcome_fields_used_for_feature_extraction": [],
        "role": role,
        "representation_sha256": "a" * 64,
        "cohort_split_sha256_by_role": {role: split_hash},
        "row_count": len(rows),
        "rows_path": rows_path.name,
        "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
        "source_split": {
            "path": split["path"],
            "sha256": split["sha256"],
            "role_split_sha256": split_hash,
        },
        "selection_limit": None,
        "extraction_workers": 1,
        "selection_partitions": ["development"],
    }
    payload["ledger_digest"] = canonical_json_sha256(payload)
    path = directory / f"{role}_feature_ledger_v3_development.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fixture_ledgers(tmp_path, protocol, *, positive_signal=True):
    rows = {role: [] for role in ("background", "robust_candidate", "known_glitch", "injection")}
    index = 0
    for detector in ("H1", "L1"):
        for _ in range(24):
            rows["background"].append(
                _row(protocol, index, "background", detector, "clean_background", False)
            )
            index += 1
        for _ in range(16):
            rows["robust_candidate"].append(
                _row(
                    protocol,
                    index,
                    "robust_candidate",
                    detector,
                    "unknown",
                    True,
                    signal=positive_signal,
                )
            )
            index += 1
        for morphology in ("Blip", "KoiFish", "ScatteredLight"):
            for _ in range(16):
                rows["known_glitch"].append(
                    _row(
                        protocol,
                        index,
                        "known_glitch",
                        detector,
                        morphology,
                        True,
                        signal=positive_signal,
                    )
                )
                index += 1
        for morphology in ("BBH_30_30", "BBH_10_10", "NSBH_10_1.4"):
            for _ in range(16):
                rows["injection"].append(
                    _row(
                        protocol,
                        index,
                        "injection",
                        detector,
                        morphology,
                        True,
                        signal=positive_signal,
                    )
                )
                index += 1
    return {
        role: _ledger(tmp_path, protocol, role, role_rows)
        for role, role_rows in rows.items()
    }


def test_v3_screening_uses_only_predeclared_ab_primary(tmp_path):
    protocol = _protocol(tmp_path)
    result = screen_prefilter_v3(
        ledgers=_fixture_ledgers(tmp_path, protocol),
        protocol=protocol,
    )
    assert result["status"] == "READY_FOR_CONFIRMATION"
    assert result["routing_enabled"] is False
    assert result["o4b_outcomes_used"] == []
    assert result["confirmation_values_used"] == []
    assert result["can_authorize_operational_pass"] is False
    assert result["selected_operating_point"]["feature_set"] == "signed_plus_ridge"
    assert result["selected_operating_point"]["selection_basis"] == "predeclared_primary_only"
    candidates = result["screening"]["candidates"]
    assert sum(candidate["eligible_for_selection"] for candidate in candidates) == 1
    assert next(candidate for candidate in candidates if candidate["eligible_for_selection"])[
        "feature_set"
    ] == "signed_plus_ridge"
    nsbh = [
        item
        for item in next(
            candidate for candidate in candidates if candidate["feature_set"] == "signed_plus_ridge"
        )["auc_diagnostics"]["by_protected_stratum"]
        if item["morphology"] == "NSBH_10_1.4"
    ]
    assert len(nsbh) == 2
    assert all(item["auc"] == 1.0 and item["eligible_for_gate"] is False for item in nsbh)


def test_v3_screening_is_deterministic_with_block_bootstrap(tmp_path):
    protocol = _protocol(tmp_path)
    ledgers = _fixture_ledgers(tmp_path, protocol)
    first = screen_prefilter_v3(ledgers=ledgers, protocol=protocol)
    second = screen_prefilter_v3(ledgers=ledgers, protocol=protocol)
    assert first == second
    primary = next(
        candidate
        for candidate in first["screening"]["candidates"]
        if candidate["feature_set"] == "signed_plus_ridge"
    )
    assert primary["auc_diagnostics"]["overall"]["method"] == "detector_gps_block_bootstrap"
    assert primary["auc_diagnostics"]["overall"]["requested_resamples"] == 100


def test_v3_screening_stops_without_opening_confirmation_when_primary_not_ready(tmp_path):
    protocol = _protocol(tmp_path)
    result = screen_prefilter_v3(
        ledgers=_fixture_ledgers(tmp_path, protocol, positive_signal=False),
        protocol=protocol,
    )
    assert result["status"] == "NOT_READY"
    assert result["selected_operating_point"] is None
    assert result["next_stage"] == "stop_without_opening_reserved_confirmation_or_o4b"


def test_v3_screening_rejects_reserved_confirmation_rows(tmp_path):
    protocol = _protocol(tmp_path)
    ledgers = _fixture_ledgers(tmp_path, protocol)
    path = ledgers["injection"]
    ledger = json.loads(path.read_text(encoding="utf-8"))
    rows_path = path.parent / ledger["rows_path"]
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["partition"] = "evaluation"
    rows_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    ledger["rows_sha256"] = hashlib.sha256(rows_path.read_bytes()).hexdigest()
    ledger.pop("ledger_digest")
    ledger["ledger_digest"] = canonical_json_sha256(ledger)
    path.write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(ContractError, match="reserved confirmation row exposed"):
        screen_prefilter_v3(ledgers=ledgers, protocol=protocol)
