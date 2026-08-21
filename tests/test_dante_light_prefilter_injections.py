from __future__ import annotations

import csv

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_injections import (
    RAW_FETCH_EDGE_TOLERANCE_S,
    load_injection_trials,
)


def _write_trials(path, rows):
    fields = ["system", "distance_mpc", "trial_index", "snr_H1", "snr_L1"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_load_injection_trials_builds_stable_identity(tmp_path):
    path = tmp_path / "trials.csv"
    _write_trials(
        path,
        [
            {
                "system": "BBH_30_30",
                "distance_mpc": 100.0,
                "trial_index": 2,
                "snr_H1": 10.0,
                "snr_L1": 11.0,
            }
        ],
    )
    rows = load_injection_trials(path)
    assert rows["BBH_30_30:100:2"]["snr_L1"] == "11.0"


def test_load_injection_trials_rejects_duplicate_identity(tmp_path):
    path = tmp_path / "trials.csv"
    row = {
        "system": "BBH_30_30",
        "distance_mpc": 100.0,
        "trial_index": 2,
        "snr_H1": 10.0,
        "snr_L1": 11.0,
    }
    _write_trials(path, [row, row])
    with pytest.raises(ContractError, match="duplicate"):
        load_injection_trials(path)


def test_injection_fetch_does_not_accept_multi_second_padding_gaps():
    assert RAW_FETCH_EDGE_TOLERANCE_S == pytest.approx(1.0 / 4096.0)
