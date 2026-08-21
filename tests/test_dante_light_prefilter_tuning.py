from __future__ import annotations

import hashlib
import json

from src.dante_light.contracts import WindowIdentity
from src.dante_light.prefilter_tuning import tune_prefilter


SPLIT_HASHES = {
    "background": "1" * 64,
    "robust_candidate": "2" * 64,
    "known_glitch": "3" * 64,
    "injection": "4" * 64,
}


def _ledger(tmp_path, role, rows):
    directory = tmp_path / role
    directory.mkdir()
    rows_path = directory / "rows.jsonl"
    rows_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    payload = {
        "schema_version": 1,
        "status": "complete",
        "role": role,
        "representation_sha256": "a" * 64,
        "cohort_split_sha256_by_role": {role: SPLIT_HASHES[role]},
        "row_count": len(rows),
        "rows_path": rows_path.name,
        "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
    }
    path = directory / "ledger.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _row(index, *, role, detector="H1", morphology="unknown", positive=True):
    window = WindowIdentity("O4A", detector, 1369000000 + index * 32)
    return {
        "window": window.to_dict(),
        "roles": [role],
        "partition": "development",
        "detector": detector,
        "morphology": morphology,
        "retention_target": positive,
        "features": {
            "rms": 1.0,
            "crest_factor": 10.0 if positive else 1.0,
            "peak_band_fraction": 0.01,
            "high_quantile_power": 2.0,
        },
    }


def test_tuning_uses_only_development_and_keeps_routing_disabled(tmp_path):
    background = [
        _row(i + 80 * d, role="background", detector=detector, positive=False)
        for d, detector in enumerate(("H1", "L1"))
        for i in range(40)
    ]
    robust = [
        _row(1000 + i, role="robust_candidate", detector=detector)
        for detector in ("H1", "L1")
        for i in range(20)
    ]
    known = [
        _row(
            2000 + 100 * d + 20 * m + i,
            role="known_glitch",
            detector=detector,
            morphology=morphology,
        )
        for d, detector in enumerate(("H1", "L1"))
        for m, morphology in enumerate(("Blip", "KoiFish", "ScatteredLight"))
        for i in range(12)
    ]
    injection = [
        _row(
            3000 + 200 * d + 50 * m + i,
            role="injection",
            detector=detector,
            morphology=morphology,
        )
        for d, detector in enumerate(("H1", "L1"))
        for m, morphology in enumerate(("BBH_30_30", "BBH_10_10", "NSBH_10_1.4"))
        for i in range(35)
    ]
    paths = {
        role: _ledger(tmp_path, role, rows)
        for role, rows in {
            "background": background,
            "robust_candidate": robust,
            "known_glitch": known,
            "injection": injection,
        }.items()
    }
    result = tune_prefilter(
        ledgers=paths,
        expected_split_hashes=SPLIT_HASHES,
        grid_cells=9,
        minimum_background_per_detector=20,
    )
    assert result["status"] == "PASS"
    assert result["routing_enabled"] is False
    assert result["evaluation_outcomes_used"] == []
    assert result["operating_point"]["effective_background_reduction"] >= 0.5
    assert all(
        value["rate"] == 1.0
        for value in result["operating_point"]["development_groups"].values()
    )
