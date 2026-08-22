from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from src.dante_light.contracts import WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v2 import feature_names_by_family
from src.dante_light.prefilter_v2_protocol import load_prefilter_v2_protocol
from src.dante_light.prefilter_v2_screening import (
    _candidate_sort_key,
    screen_prefilter_v2,
)


SPLIT_HASHES = {
    "background": "1" * 64,
    "robust_candidate": "2" * 64,
    "known_glitch": "3" * 64,
    "injection": "4" * 64,
}


def _protocol(tmp_path):
    payload = deepcopy(dict(load_prefilter_v2_protocol().payload))
    payload["development"]["cross_validation_folds"] = 4
    payload["development"]["gps_block_duration_s"] = 32
    payload["development"]["minimum_background_per_detector"] = 20
    for role in ("robust_candidate", "known_glitch", "injection"):
        payload["development"]["minimum_group_n_by_role"][role] = 16
    payload.pop("protocol_digest")
    payload["protocol_digest"] = canonical_json_sha256(payload)
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_prefilter_v2_protocol(path)


def _features(protocol, positive, index):
    by_family = feature_names_by_family(protocol.payload["feature_extraction"])
    values = {}
    for family, names in by_family.items():
        for feature_index, name in enumerate(names):
            if family == "temporal_energy":
                values[name] = (10.0 if positive else 0.1) + 1e-4 * (index + feature_index)
            else:
                values[name] = 1.0 + 1e-4 * ((index * 7 + feature_index) % 19)
    return {"values": values}


def _row(protocol, index, role, detector, morphology, positive):
    run = "O3B" if role == "known_glitch" else "O4A"
    window = WindowIdentity(run, detector, 1_200_000_000 + index * 64)
    return {
        "schema_version": 2,
        "window": window.to_dict(),
        "roles": [role],
        "partition": "development",
        "split_artifact_sha256_by_role": {role: SPLIT_HASHES[role]},
        "detector": detector,
        "morphology": morphology,
        "retention_target": positive,
        "exact_disposition": "NOT_APPLICABLE",
        "representation_sha256": "a" * 64,
        "strain_sha256": f"{index + 1:064x}",
        "features": _features(protocol, positive, index),
        "timings": {"feature_extraction_s": 0.001},
        "cohort_id": f"{role}:{detector}:{morphology}:{index}",
    }


def _ledger(tmp_path, protocol, role, rows):
    directory = tmp_path / role
    directory.mkdir()
    rows_path = directory / f"{role}_features_v2.jsonl"
    rows_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    payload = {
        "schema_version": 2,
        "status": "complete",
        "scientific_mode": "research_only_v2_development_feature_extraction",
        "feature_source": f"prefilter-v2:{protocol.payload['protocol_digest']}",
        "role": role,
        "representation_sha256": "a" * 64,
        "cohort_split_sha256_by_role": {role: SPLIT_HASHES[role]},
        "row_count": len(rows),
        "rows_path": rows_path.name,
        "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
    }
    payload["ledger_digest"] = canonical_json_sha256(payload)
    path = directory / f"{role}_feature_ledger_v2.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_v2_screening_uses_block_oof_and_selects_separable_family(tmp_path):
    protocol = _protocol(tmp_path)
    rows = {role: [] for role in SPLIT_HASHES}
    index = 0
    for detector in ("H1", "L1"):
        for _ in range(20):
            rows["background"].append(_row(protocol, index, "background", detector, "clean_background", False))
            index += 1
        for _ in range(16):
            rows["robust_candidate"].append(_row(protocol, index, "robust_candidate", detector, "unknown", True))
            index += 1
        for morphology in ("Blip", "KoiFish", "ScatteredLight"):
            for _ in range(16):
                rows["known_glitch"].append(_row(protocol, index, "known_glitch", detector, morphology, True))
                index += 1
        for morphology in ("BBH_30_30", "BBH_10_10", "NSBH_10_1.4"):
            for _ in range(16):
                rows["injection"].append(_row(protocol, index, "injection", detector, morphology, True))
                index += 1
    ledgers = {role: _ledger(tmp_path, protocol, role, values) for role, values in rows.items()}
    result = screen_prefilter_v2(
        ledgers=ledgers,
        expected_split_hashes=SPLIT_HASHES,
        protocol=protocol,
    )
    assert result["status"] == "PASS"
    assert result["routing_enabled"] is False
    assert result["o4b_outcomes_used"] == []
    assert result["screening"]["cross_validation_method"] == "shuffled_group_k_fold"
    assert result["selected_operating_point"]["feature_set"] == "temporal_energy"
    assert result["selected_operating_point"]["oof_development_background_call_reduction"] >= 0.5
    for detector in ("H1", "L1"):
        assert all(
            group["status"] == "PASS"
            for group in result["selected_operating_point"]["detectors"][detector]["groups"].values()
        )


def test_candidate_tie_break_prefers_fewer_features_then_lexicographic_name():
    candidates = [
        {
            "feature_set": "wavelet_sparse",
            "feature_names": ["a"],
            "oof_development_background_call_reduction": 0.6,
        },
        {
            "feature_set": "temporal_energy",
            "feature_names": ["a"],
            "oof_development_background_call_reduction": 0.6,
        },
        {
            "feature_set": "tf_cluster",
            "feature_names": ["a", "b"],
            "oof_development_background_call_reduction": 0.6,
        },
    ]
    selected = min(candidates, key=_candidate_sort_key)
    assert selected["feature_set"] == "temporal_energy"
