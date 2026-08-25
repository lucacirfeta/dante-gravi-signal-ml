from __future__ import annotations

import json
from collections import defaultdict

from src.dante_light.prefilter_v5_protocol import ROOT
from scripts.verify_dante_light_prefilter_v5_freeze import verify


def test_v5_freeze_recomputes_and_confirmation_is_unopened() -> None:
    result = verify()
    assert result["status"] == "PASS_IDENTITY_ONLY_NOT_OPENED"
    assert result["rows"] > 0
    assert result["trials"] == 1440


def test_nsbh_stress_trials_are_latin_hypercube_stratified() -> None:
    path = ROOT / "config/dante_light_prefilter_v5_injection_trials.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    grouped = defaultdict(list)
    for row in rows:
        if row["population"] == "aligned_tidal_nsbh_stress":
            grouped[(row["detector"], row["partition"], row["distance_mpc"])].append(row)
    assert len(grouped) == 2 * 2 * 5
    ranges = {
        "mass_1_msun": (5.0, 20.0), "mass_2_msun": (1.2, 2.0),
        "spin_1z": (-0.5, 0.75), "lambda_2": (100.0, 1000.0),
    }
    for cell in grouped.values():
        assert len(cell) == 18
        for field, (low, high) in ranges.items():
            bins = sorted(int((row[field] - low) / (high - low) * 18) for row in cell)
            assert bins == list(range(18))
        assert {row["spin_2z"] for row in cell} == {0.0}
