"""Synthetic localized-coherence and finite-reference decision tests."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_l1_local_followup import (
    CONFIG_PATH,
    ROOT,
    control_blocks,
    load_design,
    local_coherence_max,
    reference_screen,
)


@pytest.fixture
def design():
    return json.loads((ROOT / CONFIG_PATH).read_text())


def test_candidate_is_blocked_before_real_outcomes():
    design = load_design()
    assert design["execution"]["gate_c_enabled"] is False
    assert design["scientific_boundary"]["post_hoc_target_selection"] is True
    assert design["decision"]["p_value_or_formal_fwer_claim"] is False


def test_changed_parent_hash_rejected(tmp_path, design):
    (tmp_path / "config").mkdir()
    design["parents"] = {"test": {"path": "config/parent.json", "sha256": "0" * 64}}
    (tmp_path / "config/parent.json").write_text("{}")
    (tmp_path / CONFIG_PATH).write_text(json.dumps(design))
    with pytest.raises(ContractError, match="parent hash"):
        load_design(tmp_path)


@pytest.mark.parametrize(
    "change", ["duplicate", "wrong_detector", "enable_gate", "reduce_family"]
)
def test_changed_design_scope_rejected(tmp_path, design, change):
    (tmp_path / "config").mkdir()
    if change == "duplicate":
        design["targets"][1] = design["targets"][0].copy()
    elif change == "wrong_detector":
        design["targets"][0]["detector"] = "H1"
    elif change == "enable_gate":
        design["execution"]["gate_c_enabled"] = True
    else:
        design["decision"]["family_target_count"] = 1
    (tmp_path / CONFIG_PATH).write_text(json.dumps(design))
    with pytest.raises(ContractError, match="scope/execution"):
        load_design(tmp_path)


def test_cutoff_equality_positive_and_ties_conservative(design):
    n = design["controls"]["minimum_reference_blocks"]
    at_boundary = reference_screen(0.9, [0.1] * n, design)
    assert at_boundary["corrected_reference_tail_fraction"] == 0.01
    assert at_boundary["status"] == design["decision"]["screen_positive"]
    null = [0.1] * n
    null[0] = 0.9
    assert (
        reference_screen(0.9, null, design)["status"]
        == design["decision"]["screen_negative"]
    )


def test_insufficient_blocks_never_negative(design):
    result = reference_screen(1.0, [0.0] * 198, design)
    assert result["status"] == "INCONCLUSIVE"
    assert "corrected_reference_tail_fraction" not in result


@pytest.mark.parametrize(
    "observed,null", [(np.nan, [0.1]), (1.1, [0.1]), (0.1, [np.inf]), (0.1, [-0.1])]
)
def test_invalid_scores_fail_closed(design, observed, null):
    with pytest.raises(ContractError):
        reference_screen(observed, null, design)


def test_block_boundaries_no_stitching(design):
    assert control_blocks([0, 192], [], design["controls"]) == [
        [0, 32, 64],
        [96, 128, 160],
    ]
    assert control_blocks([0, 191], [], design["controls"]) == [[0, 32, 64]]
    assert control_blocks([0, 384], [128], design["controls"]) == [[288, 320, 352]]


def test_candidate_exclusion_includes_full_context_and_guard(design):
    assert control_blocks([0, 384], [64], design["controls"]) == [
        [192, 224, 256],
        [288, 320, 352],
    ]


def test_wrong_geometry_rejected(design):
    controls = copy.deepcopy(design["controls"])
    controls["contexts_per_block"] += 1
    with pytest.raises(ContractError):
        control_blocks([0, 384], [], controls)


@pytest.fixture
def arrays(design):
    fs = design["measurement"]["sample_rate_hz"]
    rng = np.random.default_rng(4)
    x = rng.normal(size=fs)
    names = [f"L1:TEST_{i}" for i in range(5)]
    aux = {name: rng.normal(size=fs) for name in names}
    return x, names, aux


def test_synthetic_shared_signal_detectable(design, arrays):
    x, names, aux = arrays
    aux[names[0]] = x.copy()
    result = local_coherence_max(
        x, aux, channels=names, band=(20, 55), measurement=design["measurement"]
    )
    assert result == pytest.approx(1.0)


def test_one_second_has_multiple_welch_segments(design, arrays):
    x, names, aux = arrays
    result = local_coherence_max(
        x, aux, channels=names, band=(20, 55), measurement=design["measurement"]
    )
    assert 0 < result < 1


def test_new_lag_search_rejected(design, arrays):
    x, names, aux = arrays
    design["measurement"]["lag_s"] = 0.1
    with pytest.raises(ContractError):
        local_coherence_max(
            x, aux, channels=names, band=(20, 55), measurement=design["measurement"]
        )


@pytest.mark.parametrize(
    "fault", ["missing", "nonfinite", "short", "constant", "wrong_detector"]
)
def test_channel_faults_never_negative(design, arrays, fault):
    x, names, aux = arrays
    if fault == "missing":
        del aux[names[0]]
    elif fault == "nonfinite":
        aux[names[0]][0] = np.nan
    elif fault == "short":
        aux[names[0]] = aux[names[0]][:-1]
    elif fault == "constant":
        aux[names[0]] = np.zeros_like(x)
    else:
        aux["H1:TEST_0"] = aux.pop(names[0])
    with pytest.raises(ContractError):
        local_coherence_max(
            x, aux, channels=names, band=(20, 55), measurement=design["measurement"]
        )


def test_short_region_rejected(design, arrays):
    x, names, aux = arrays
    with pytest.raises(ContractError, match="resolution"):
        local_coherence_max(
            x[:256],
            {k: v[:256] for k, v in aux.items()},
            channels=names,
            band=(20, 55),
            measurement=design["measurement"],
        )


def test_unresolvable_frequency_band_rejected(design, arrays):
    x, names, aux = arrays
    with pytest.raises(ContractError, match="resolution"):
        local_coherence_max(
            x, aux, channels=names, band=(2, 15), measurement=design["measurement"]
        )
