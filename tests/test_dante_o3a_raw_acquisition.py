from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_raw_acquisition import (
    build_acquisition_plan,
    build_source_inventory,
    load_acquisition_plan,
    load_source_inventory,
    normalize_source_urls,
    validate_source_inventory,
)


ROOT = Path(__file__).resolve().parents[1]


def test_source_inventory_is_public_metadata_only_and_reproducible() -> None:
    stored = load_source_inventory(root=ROOT)
    urls = {
        detector: list(stored["urls_by_detector"][detector])
        for detector in stored["detectors"]
    }

    def frozen_fetcher(detector: str, start: int, end: int) -> list[str]:
        assert [start, end] == stored["source_query"][
            "query_bounds_by_detector"
        ][detector]
        return list(reversed(urls[detector]))

    assert build_source_inventory(root=ROOT, url_fetcher=frozen_fetcher) == stored
    assert stored["summaries"]["H1"]["frame_count"] == 3_051
    assert stored["summaries"]["L1"]["frame_count"] == 3_266
    assert stored["execution_boundary"] == {
        "public_file_metadata_only": True,
        "downloaded_bytes": 0,
        "strain_data_accessed": False,
        "outcome_data_accessed": False,
    }


def test_acquisition_plan_covers_every_provisional_block_context() -> None:
    value = load_acquisition_plan(root=ROOT)
    assert value == build_acquisition_plan(root=ROOT)
    assert value["summary"] == {
        "provisional_block_count": 590,
        "unique_source_frame_count": 726,
        "downloaded_bytes": 0,
    }
    assert {
        detector: plan["required_source_frame_count"]
        for detector, plan in value["detector_plans"].items()
    } == {"H1": 365, "L1": 361}

    for detector, detector_plan in value["detector_plans"].items():
        frames = {
            item["filename"]: item for item in detector_plan["source_frames"]
        }
        assert len(detector_plan["blocks"]) == 295
        for block in detector_plan["blocks"]:
            selected = [frames[name] for name in block["source_frame_filenames"]]
            left, right = block["required_raw_interval_gps"]
            assert selected[0]["gps_start"] <= left
            assert selected[-1]["gps_end"] >= right
            assert all(
                current["gps_end"] >= following["gps_start"]
                for current, following in zip(selected, selected[1:])
            )


def test_acquisition_plan_does_not_authorize_download_or_scoring() -> None:
    value = load_acquisition_plan(root=ROOT)
    assert value["acquisition_scope"]["fallback_candidates_included"] is False
    assert value["acquisition_scope"][
        "fallback_acquisition_requires_versioned_plan_extension"
    ] is True
    assert value["execution_boundary"] == {
        "download_authorized_by_this_freeze": False,
        "raw_files_opened": False,
        "strain_data_accessed": False,
        "raw_acceptance_executed": False,
        "scoring_executed": False,
        "outcome_data_accessed": False,
    }


def test_source_inventory_rejects_url_and_digest_drift() -> None:
    with pytest.raises(ContractError, match="untrusted"):
        normalize_source_urls(
            ["https://example.org/H-H1_GWOSC_O3a_4KHZ_R1-1-4096.hdf5"],
            "H1",
        )
    value = load_source_inventory(root=ROOT)
    mutated = copy.deepcopy(value)
    mutated["urls_by_detector"]["H1"][0] += "?drift=1"
    with pytest.raises(ContractError, match="self-digest mismatch"):
        validate_source_inventory(mutated, root=ROOT)
