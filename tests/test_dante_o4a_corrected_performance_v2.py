from __future__ import annotations

from src.dante_light.evidence import SCORE_ATOL
from src.dante_light import o4a_corrected_performance_v2 as performance


def test_persistent_pool_matrix_is_frozen_before_outcomes() -> None:
    assert SCORE_ATOL == 2.0e-7
    assert [row["id"] for row in performance.CONFIGURATIONS] == [
        "serial_2x8",
        "serial_8x32",
        "parallel_4x16",
        "parallel_8x32",
    ]
    assert [row["detector_mode"] for row in performance.CONFIGURATIONS] == [
        "serial",
        "serial",
        "parallel_shared_scorer",
        "parallel_shared_scorer",
    ]


def test_persistent_pool_decision_requires_prefrozen_speedup() -> None:
    contract = {
        "benchmark": {
            "configurations": list(performance.CONFIGURATIONS),
            "promotion": {"minimum_speedup_over_baseline": 2.0},
        }
    }
    records = []
    rates = {
        "serial_2x8": 5.0,
        "serial_8x32": 9.0,
        "parallel_4x16": 11.0,
        "parallel_8x32": 10.0,
    }
    for repetition in range(2):
        for configuration in performance.CONFIGURATIONS:
            records.append(
                {
                    "phase": "measured",
                    "configuration": dict(configuration),
                    "timing": {
                        "end_to_end_windows_per_s": rates[configuration["id"]]
                    },
                }
            )
    medians, speedups, selected, status = performance._decision(records, contract)
    assert medians == rates
    assert speedups["parallel_4x16"] == 2.2
    assert selected["id"] == "parallel_4x16"
    assert status == "PASS_EQUIVALENCE_AND_PERSISTENT_SELECTION"
