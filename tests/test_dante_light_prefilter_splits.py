from __future__ import annotations

from collections import Counter

from src.dante_light.prefilter_splits import (
    build_prefilter_splits,
    load_prefilter_splits,
    write_prefilter_splits,
)
from src.dante_light.prefilter_protocol import load_prefilter_protocol


SEED = int(load_prefilter_protocol().payload["cohort_split_seed"])


def test_prefilter_splits_are_deterministic_disjoint_and_powered():
    first = build_prefilter_splits(root=".", seed=SEED)
    second = build_prefilter_splits(root=".", seed=SEED)
    assert first == second
    assert first == load_prefilter_splits("config/dante_light_prefilter_splits_v1.json")
    assert first["status"] == "locked_before_feature_extraction"

    background = first["cohorts"]["background"]
    assert background["counts"] == {
        "total": 552,
        "development": 552,
        "evaluation": 0,
    }
    assert Counter(row["detector"] for row in background["rows"]) == {
        "H1": 274,
        "L1": 278,
    }

    robust = first["cohorts"]["robust_candidate"]
    assert robust["counts"] == {"total": 80, "development": 40, "evaluation": 40}
    for detector in ("H1", "L1"):
        counts = Counter(
            row["partition"] for row in robust["rows"] if row["detector"] == detector
        )
        assert counts == {"development": 20, "evaluation": 20}

    known = first["cohorts"]["known_glitch"]
    assert known["counts"] == {"total": 180, "development": 72, "evaluation": 108}
    for detector in ("H1", "L1"):
        for morphology in ("Blip", "KoiFish", "ScatteredLight"):
            counts = Counter(
                row["partition"]
                for row in known["rows"]
                if row["detector"] == detector and row["morphology"] == morphology
            )
            assert counts == {"development": 12, "evaluation": 18}

    injection = first["cohorts"]["injection"]
    assert injection["counts"] == {"total": 750, "development": 210, "evaluation": 540}
    for detector in ("H1", "L1"):
        for morphology in ("BBH_30_30", "BBH_10_10", "NSBH_10_1.4"):
            counts = Counter(
                row["partition"]
                for row in injection["rows"]
                if row["detector"] == detector and row["morphology"] == morphology
            )
            assert counts == {"development": 35, "evaluation": 90}

    for cohort in first["cohorts"].values():
        identities = [row["window"]["window_id"] for row in cohort["rows"]]
        assert len(identities) == len(set(identities))


def test_prefilter_split_jsonl_round_trip_is_exact(tmp_path):
    expected = build_prefilter_splits(root=".", seed=SEED)
    path = write_prefilter_splits(expected, tmp_path / "splits.json")
    assert load_prefilter_splits(path) == expected
