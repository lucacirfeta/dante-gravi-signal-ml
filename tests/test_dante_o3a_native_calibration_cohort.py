"""Identity-only regression gates for the O3a native calibration selector."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_native_calibration_cohort import (
    build_cohort_contract,
    load_amendment,
    select_native_calibration_rows,
)


ROOT = Path(__file__).resolve().parents[1]


def _grid(count: int = 12) -> list[tuple[str, int, bool]]:
    return [(detector, i * 64, False) for detector in ("H1", "L1") for i in range(count)]


def _sources(detector: str, gps: int) -> list[dict[str, int | str]]:
    return [{"detector": detector, "gps_start": gps - 4, "gps_end": gps + 36}]


def _select(
    identities: list[tuple[str, int, bool]],
    index: list[tuple[str, int]] | None = None,
    *,
    context=_sources,
) -> tuple[list[dict], dict]:
    return select_native_calibration_rows(
        identities,
        index or [],
        target_rows=4,
        block_length=2,
        window_s=32,
        stride_s=64,
        guard_delta_s=128,
        context_sources=context,
    )


def test_amendment_binds_the_approved_native_only_decision() -> None:
    amendment = load_amendment(root=ROOT)
    assert amendment["selection"]["algorithm"].startswith("O4A_NATIVE_V2_")
    contract = build_cohort_contract(root=ROOT)
    assert contract["selection"]["target_rows_per_detector"] == 5000
    assert contract["selection"]["bootstrap_rows_per_detector"] == 4998
    assert contract["selection"]["candidate_and_index_guard_start_delta_s"] == 128


def test_evenly_spaced_complete_blocks_and_chronological_output() -> None:
    rows, audit = _select(_grid())
    for detector in ("H1", "L1"):
        starts = [row["gps_start"] for row in rows if row["detector"] == detector]
        assert starts == [0, 64, 640, 704]
        assert audit[detector]["available_nonoverlapping_blocks"] == 6
        assert audit[detector]["accepted_complete_blocks"] == 2
    assert not any("score" in row or "class" in row for row in rows)


def test_candidate_and_index_guards_are_cross_detector_and_inclusive() -> None:
    identities = _grid()
    identities[12] = ("L1", 0, True)
    rows, _ = _select(identities, [("L1", 704)])
    for detector in ("H1", "L1"):
        starts = [row["gps_start"] for row in rows if row["detector"] == detector]
        assert len(starts) == 4
        assert all(128 < gps < 704 - 128 for gps in starts)


def test_incomplete_context_uses_deterministic_next_block() -> None:
    def incomplete(detector: str, gps: int) -> list[dict[str, int | str]]:
        if gps == 640:
            raise ContractError("missing context")
        return _sources(detector, gps)

    rows, audit = _select(_grid(), context=incomplete)
    for detector in ("H1", "L1"):
        starts = [row["gps_start"] for row in rows if row["detector"] == detector]
        assert starts == [0, 64, 128, 192]
        assert audit[detector]["context_rejected_blocks"] == 1


def test_insufficient_blocks_fail_closed() -> None:
    with pytest.raises(ContractError, match="complete guarded blocks"):
        _select(_grid(2))
