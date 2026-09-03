from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o4a_corrected_native_rescore import (
    _calibration_rows,
    _candidate_rows,
    _float32_hex,
    _validate_input_rows,
    load_native_rescore_contract,
    validate_native_rescore_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_native_rescore_contract_freezes_populations_and_score_semantics() -> None:
    contract = load_native_rescore_contract(ROOT)

    assert contract["contract_digest"] == (
        "b551361990aede88077034b6245e02d5afbd832293506b967b72ddf902c0e91a"
    )
    assert contract["scoring"]["top_k"] == 68
    assert contract["scoring"]["output_mode"] == "score_only"
    assert contract["gates"]["exact_total_rows"] == 20_942
    assert contract["scientific_boundary"]["old_native_scores_read"] is False
    assert contract["scientific_boundary"]["old_native_thresholds_read"] is False


def test_native_rescore_contract_rejects_top_k_drift() -> None:
    payload = json.loads(
        (ROOT / "config/dante_o4a_corrected_native_rescore_v1.json").read_text(
            encoding="utf-8"
        )
    )
    payload["scoring"]["top_k"] = 67

    with pytest.raises(ContractError, match="digest mismatch"):
        validate_native_rescore_contract(payload, ROOT)


def test_native_calibration_rows_keep_exact_detector_gps_population() -> None:
    contract = load_native_rescore_contract(ROOT)
    rows = _calibration_rows(root=ROOT, contract=contract)

    assert len(rows) == 10_000
    assert sum(row["detector"] == "H1" for row in rows) == 5000
    assert sum(row["detector"] == "L1" for row in rows) == 5000
    assert all(row["population"] == "native_calibration" for row in rows)
    assert all("calibration_score" not in row for row in rows)


def test_candidate_rows_read_only_identity_and_image_hash(tmp_path: Path) -> None:
    database = tmp_path / "scan.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE windows(detector TEXT,gps_start REAL,is_candidate INTEGER,"
        "identity_digest TEXT,image_sha256 TEXT)"
    )
    connection.executemany(
        "INSERT INTO windows VALUES(?,?,?,?,?)",
        [
            ("L1", 20.0, 1, "l" * 64, "b" * 64),
            ("H1", 10.0, 1, "h" * 64, "a" * 64),
            ("H1", 30.0, 0, "x" * 64, "c" * 64),
        ],
    )
    connection.commit()
    connection.close()

    rows = _candidate_rows(database, offset=100)

    assert [(row["detector"], row["gps_start"]) for row in rows] == [
        ("H1", 10.0),
        ("L1", 20.0),
    ]
    assert [row["input_index"] for row in rows] == [100, 101]
    assert all("primary_score" not in row for row in rows)


def test_input_validator_rejects_cross_population_identity_reuse() -> None:
    contract = {
        "gates": {
            "calibration_rows_by_detector": {"H1": 1, "L1": 0},
            "candidate_rows_by_detector": {"H1": 1, "L1": 0},
        }
    }
    rows = [
        {
            "input_index": 0,
            "population": "native_calibration",
            "detector": "H1",
            "gps_start": 1.0,
        },
        {
            "input_index": 1,
            "population": "primary_candidate",
            "detector": "H1",
            "gps_start": 1.0,
        },
    ]

    with pytest.raises(ContractError, match="identity is invalid"):
        _validate_input_rows(rows, contract=contract)


def test_score_hex_is_float32_and_rejects_nonfinite() -> None:
    assert _float32_hex(0.5) == "0000003f"
    with pytest.raises(ContractError, match="non-finite"):
        _float32_hex(float("nan"))
