from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v2 import feature_names_by_family
from src.dante_light.prefilter_v2_assembly import assemble_prefilter_v2_evaluation
from src.dante_light.prefilter_v2_evaluation import evaluate_prefilter_v2
from src.dante_light.prefilter_v2_protocol import load_prefilter_v2_protocol
from src.dante_light.prefilter_v2_screening import screen_prefilter_v2, write_screening_result


ROLES = ("background", "robust_candidate", "known_glitch", "injection")
SPLIT_HASHES = {
    "background": "1" * 64,
    "robust_candidate": "2" * 64,
    "known_glitch": "3" * 64,
    "injection": "4" * 64,
    "shadow": "5" * 64,
}


def _protocol(tmp_path):
    payload = deepcopy(dict(load_prefilter_v2_protocol().payload))
    payload["protocol_id"] = "fixture-prefilter-v2"
    payload["audit"] = {"fraction": 0.05, "seed": 42}
    payload["development"]["cross_validation_folds"] = 2
    payload["development"]["gps_block_duration_s"] = 32
    payload["development"]["minimum_background_per_detector"] = 8
    payload["development"]["minimum_effective_reduction"] = 0.1
    payload["evaluation"]["minimum_compute_reduction"] = 0.1
    payload["evaluation"]["minimum_exact_escalates"] = 2
    for section in ("development", "evaluation"):
        for role in ("robust_candidate", "known_glitch", "injection"):
            payload[section]["minimum_group_n_by_role"][role] = 4
            payload[section]["minimum_wilson_lower_by_role"][role] = 0.3
    payload.pop("protocol_digest")
    payload["protocol_digest"] = canonical_json_sha256(payload)
    path = tmp_path / "protocol_v2.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_prefilter_v2_protocol(path)


def _features(protocol, positive, index):
    values = {}
    for family, names in feature_names_by_family(protocol.payload["feature_extraction"]).items():
        for feature_index, name in enumerate(names):
            if family == "temporal_energy":
                values[name] = (2.0 if positive else 0.0) + 1e-5 * (index + feature_index)
            else:
                values[name] = 1.0 + 1e-5 * ((index + feature_index) % 11)
    return {"values": values}


def _row(protocol, *, index, role, detector, morphology, partition, positive, run=None, exact=None):
    run = run or ("O3B" if role == "known_glitch" else "O4A")
    window = WindowIdentity(run, detector, 1_400_000_000 + index * 64)
    return {
        "schema_version": 2,
        "window": window.to_dict(),
        "roles": [role],
        "partition": partition,
        "split_artifact_sha256_by_role": {role: SPLIT_HASHES[role]},
        "detector": detector,
        "morphology": morphology,
        "retention_target": bool(positive),
        "exact_disposition": exact or "NOT_APPLICABLE",
        "representation_sha256": "a" * 64,
        "strain_sha256": f"{index + 1:064x}"[-64:],
        "features": _features(protocol, positive, index),
        "timings": {"feature_extraction_s": 0.001},
        "cohort_id": f"{role}:{detector}:{morphology}:{index}",
    }


def _ledger(tmp_path, protocol, role, rows):
    directory = tmp_path / role
    directory.mkdir()
    rows_path = directory / f"{role}_features_v2.jsonl"
    rows_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    ledger = {
        "schema_version": 2,
        "status": "complete",
        "scientific_mode": "fixture",
        "feature_source": f"prefilter-v2:{protocol.payload['protocol_digest']}",
        "outcome_fields_used_for_feature_extraction": [],
        "representation_sha256": "a" * 64,
        "cohort_split_sha256_by_role": {role: SPLIT_HASHES[role]},
        "row_count": len(rows),
        "rows_path": rows_path.name,
        "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
    }
    if role != "shadow":
        ledger["role"] = role
    ledger["ledger_digest"] = canonical_json_sha256(ledger)
    path = directory / f"{role}_feature_ledger_v2.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    return path


def _case(tmp_path):
    protocol = _protocol(tmp_path)
    rows = {role: [] for role in (*ROLES, "shadow")}
    index = 0
    known = protocol.payload["required_morphologies_by_role"]["known_glitch"]
    injections = protocol.payload["required_morphologies_by_role"]["injection"]
    for detector in protocol.payload["required_detectors"]:
        for _ in range(12):
            rows["background"].append(
                _row(protocol, index=index, role="background", detector=detector, morphology="clean", partition="development", positive=False)
            )
            index += 1
        for partition in ("development", "evaluation"):
            for _ in range(4):
                rows["robust_candidate"].append(
                    _row(protocol, index=index, role="robust_candidate", detector=detector, morphology="unknown", partition=partition, positive=True)
                )
                index += 1
            for morphology in known:
                for _ in range(4):
                    rows["known_glitch"].append(
                        _row(protocol, index=index, role="known_glitch", detector=detector, morphology=morphology, partition=partition, positive=True)
                    )
                    index += 1
            for morphology in injections:
                for _ in range(4):
                    rows["injection"].append(
                        _row(protocol, index=index, role="injection", detector=detector, morphology=morphology, partition=partition, positive=True)
                    )
                    index += 1
        for shadow_index in range(30):
            exact_positive = shadow_index == 0
            rows["shadow"].append(
                _row(
                    protocol,
                    index=index,
                    role="shadow",
                    detector=detector,
                    morphology=None,
                    partition="evaluation",
                    positive=exact_positive,
                    run="O4B",
                    exact="ESCALATE" if exact_positive else "NOT_ESCALATED",
                )
            )
            index += 1
    ledgers = {role: _ledger(tmp_path, protocol, role, values) for role, values in rows.items()}
    screening = screen_prefilter_v2(
        ledgers={role: ledgers[role] for role in ROLES},
        expected_split_hashes={role: SPLIT_HASHES[role] for role in ROLES},
        protocol=protocol,
    )
    assert screening["status"] == "PASS"
    screening_path = write_screening_result(screening, tmp_path / "screening.json")
    output_dir = tmp_path / "evaluation"
    assemble_prefilter_v2_evaluation(
        ledgers=ledgers,
        screening_path=screening_path,
        output_dir=output_dir,
        protocol=protocol,
    )
    return output_dir / "evaluation_contract_v2.json", output_dir / "evaluation_feature_ledger_v2.json"


def test_v2_heldout_evaluation_passes_without_enabling_routing(tmp_path):
    contract, ledger = _case(tmp_path)
    result = evaluate_prefilter_v2(contract_path=contract, ledger_path=ledger)
    assert result["status"] == "PASS"
    assert result["routing_enabled"] is False
    assert result["coverage"]["exact_escalates"] == 2
    assert result["coverage"]["missed_exact_escalates"] == 0
    assert result["coverage"]["effective_compute_reduction"] >= 0.1


def test_v2_heldout_evaluation_rejects_tampered_rows(tmp_path):
    contract, ledger_path = _case(tmp_path)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["rows_sha256"] = "0" * 64
    body = dict(ledger)
    body.pop("ledger_digest")
    ledger["ledger_digest"] = canonical_json_sha256(body)
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(ContractError, match="row SHA256 mismatch"):
        evaluate_prefilter_v2(contract_path=contract, ledger_path=ledger_path)
