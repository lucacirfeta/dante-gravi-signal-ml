from __future__ import annotations

from copy import deepcopy

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v6_phase_c_power import (
    analyze_power,
    bonett_wright_lower,
    load_power_contract,
)


def test_frozen_phase_c_power_recomputes_outcome_blind() -> None:
    result = analyze_power(load_power_contract())
    frozen = result["frozen_recommendation"]
    assert result["status"] == "FROZEN_PHASE_C_FIDELITY_POWER_VERIFIED"
    assert frozen["n_blocks"] == 60
    assert frozen["approximate_pass_probability_at_true_alternative"] == pytest.approx(
        0.9764284791664606
    )
    assert frozen["lower_bound_at_true_alternative"] == pytest.approx(
        0.9169178713929138
    )
    assert result["outcomes_accessed"] == []
    assert result["interpretation"]["familywise_pass_probability_claimed"] is False


def test_small_historical_counts_do_not_meet_power_target() -> None:
    rows = {
        row["n_blocks"]: row
        for row in analyze_power(load_power_contract())["candidate_results"]
    }
    assert rows[18]["approximate_pass_probability_at_true_alternative"] < 0.9
    assert rows[20]["approximate_pass_probability_at_true_alternative"] < 0.9
    assert rows[25]["approximate_pass_probability_at_true_alternative"] < 0.9
    assert rows[40]["approximate_pass_probability_at_true_alternative"] < 0.9
    assert rows[45]["approximate_pass_probability_at_true_alternative"] > 0.9


def test_lower_bound_rejects_invalid_independence_count() -> None:
    with pytest.raises(ContractError, match="n_blocks > 3"):
        bonett_wright_lower(0.95, n_blocks=3, confidence=0.95)


def test_power_contract_rejects_more_than_one_window_per_block(tmp_path) -> None:
    payload = deepcopy(load_power_contract())
    payload["sampling_contract"]["windows_per_block"] = 8
    payload.pop("contract_digest")
    from src.dante_light.contracts import canonical_json_sha256
    payload["contract_digest"] = canonical_json_sha256(payload)
    path = tmp_path / "bad.json"
    import json
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="one observation per block"):
        load_power_contract(path)
