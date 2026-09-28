"""Synthetic fail-closed checks for the metadata-only auxiliary preflight."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_o4a_common_pem_aux_availability import (
    check_availability,
    requirements,
)
from scripts.run_dante_o3a_o4a_common_pem_aux_availability import _check_one


def _available(name: str, *intervals: tuple[int, int]) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        data=[
            SimpleNamespace(gps_start=a, gps_stop=b, frame_type="AUX_FRAME")
            for a, b in intervals
        ],
    )


def test_exact_gap_free_channel_availability() -> None:
    rows = check_availability(
        [_available("H1:A", (100, 110), (110, 120)), _available("H1:B", (99, 121))],
        ["H1:A", "H1:B"],
        100,
        120,
    )
    assert [row["channel"] for row in rows] == ["H1:A", "H1:B"]
    assert rows[0]["segments"][1]["gps_start"] == 110


@pytest.mark.parametrize(
    "items",
    [
        [_available("H1:A", (100, 109), (110, 120))],
        [_available("H1:A", (100, 119))],
        [_available("H1:OTHER", (100, 120))],
        [_available("H1:A", (100, 120)), _available("H1:A", (100, 120))],
    ],
)
def test_gap_short_or_wrong_channel_fails_closed(items: list[SimpleNamespace]) -> None:
    with pytest.raises(ContractError):
        check_availability(items, ["H1:A"], 100, 120)


def test_requirements_use_frozen_population_and_intervals() -> None:
    plan = {
        "spans": {
            "O3a": [{"detector": "H1", "gps_start": 100, "interval_gps": [300, 400]}],
            "O4a": [{"detector": "L1", "gps_start": 200, "interval_gps": [500, 600]}],
        }
    }
    comparison = {
        "method": {
            "measurement": {"event_window_s": 32},
            "channels": {"H1": ["H1:A"], "L1": ["L1:B"]},
        },
        "runs": {
            "O3a": {"targets": {"expected_count": 1}},
            "O4a": {"targets": {"expected_count": 1}},
        },
    }
    rows = requirements(plan, comparison)
    assert rows[0]["event_interval_gps"] == [100, 132]
    assert rows[0]["background_interval_gps"] == [300, 400]
    assert rows[1]["channels"] == ["L1:B"]
    comparison["runs"]["O4a"]["targets"]["expected_count"] = 2
    with pytest.raises(ContractError, match="population changed"):
        requirements(plan, comparison)


def test_receipt_checks_event_and_background_separately() -> None:
    class Connection:
        def __init__(self) -> None:
            self.epoch = (0, 0)
            self.calls: list[tuple[int, int]] = []

        def set_epoch(self, start: int, end: int) -> bool:
            self.epoch = start, end
            self.calls.append(self.epoch)
            return True

        def get_availability(self, channels: list[str]) -> list[SimpleNamespace]:
            return [_available(channels[0], self.epoch)]

    row = {
        "run": "O3a",
        "detector": "H1",
        "target_gps": 100,
        "channels": ["H1:A"],
        "event_interval_gps": [100, 132],
        "background_interval_gps": [300, 400],
    }
    connection = Connection()
    receipt = _check_one(connection, row)
    assert connection.calls == [(100, 132), (300, 400)]
    assert receipt["status"] == "PASS_AUX_METADATA_COVERAGE_ONLY"
    assert receipt["intervals"]["background"]["interval_gps"] == [300, 400]
