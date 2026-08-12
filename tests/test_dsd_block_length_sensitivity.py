from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.run_dsd_block_length_sensitivity import (
    classify_population,
    summarize_transition,
)
from src.pipeline_v2_production.background_calibration import (
    block_bootstrap_p99_ci,
)


def test_bootstrap_accepts_explicit_block_length_without_changing_default() -> None:
    scores = np.linspace(0.0, 1.0, 125, dtype=np.float64)
    default = block_bootstrap_p99_ci(scores, B=100, seed=7, chunk_size=17)
    explicit = block_bootstrap_p99_ci(
        scores,
        B=100,
        seed=7,
        chunk_size=17,
        block_length=4,
    )
    assert default == explicit
    assert explicit["block_length"] == 4
    assert explicit["n_complete_blocks"] == 31


def test_bootstrap_rejects_invalid_explicit_block_length() -> None:
    scores = np.linspace(0.0, 1.0, 20, dtype=np.float64)
    for invalid in (0, -1, 11):
        with np.testing.assert_raises(ValueError):
            block_bootstrap_p99_ci(scores, B=10, block_length=invalid)


def test_transition_summary_is_detector_aware_and_exact() -> None:
    frame = pd.DataFrame(
        {
            "detector": ["H1", "H1", "L1", "L1"],
            "dsd_score": [0.1, 0.3, 0.2, 0.4],
        }
    )
    reference = classify_population(
        frame,
        {"H1": (0.15, 0.25), "L1": (0.25, 0.35)},
    )
    alternative = classify_population(
        frame,
        {"H1": (0.05, 0.35), "L1": (0.15, 0.45)},
    )
    summary = summarize_transition(reference, alternative)
    assert summary["n_total"] == 4
    assert summary["n_changed"] == 4
    assert summary["changed_fraction"] == 1.0
    assert summary["matrix"]["BACKGROUND"]["AMBIGUOUS"] == 2
    assert summary["matrix"]["ROBUST"]["AMBIGUOUS"] == 2
