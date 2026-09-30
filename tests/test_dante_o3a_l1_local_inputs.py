"""Synthetic DQ/coverage accounting; no real auxiliary outcomes."""

import copy
import json
from types import SimpleNamespace

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_l1_local_followup import CONFIG_PATH, ROOT
from src.dante_light.o3a_l1_local_inputs import (
    assess_inputs,
    auxiliary_metadata,
    covers,
    normalize_segments,
)


@pytest.fixture
def inputs():
    design = json.loads((ROOT / CONFIG_PATH).read_text())
    target = {
        "gps_start": 20000,
        "detector": "L1",
        "identity_digest": "x",
        "same_cat1_segment_gps": [0, 20100],
        "local_offset_interval_s": [16.5, 17.5],
        "candidate_clean_blocks_before_cat2_cat3": 199,
        "candidate_clean_control_blocks_gps": [
            [i * 96 + j * 32 for j in range(3)] for i in range(199)
        ],
    }
    channels = [f"L1:C{i}" for i in range(5)]
    quality = {
        flag: [[0, 20100]] for flag in design["input_preflight"]["quality_flags"]
    }
    auxiliary = {name: {"coverage_segments": [[0, 20100]]} for name in channels}
    return design, target, channels, quality, auxiliary


def assess(value):
    design, target, channels, quality, auxiliary = value
    return assess_inputs(
        target, design=design, channels=channels, quality=quality, auxiliary=auxiliary
    )


def test_full_metadata_pass_not_sample_or_safety_pass(inputs):
    result = assess(inputs)
    assert result["status"] == "PASS_DQ_AUX_METADATA_ONLY"
    assert result["eligible_reference_blocks"] == 199
    assert result["sample_bytes_verified"] is False
    assert result["channel_veto_safety_verified"] is False


def test_fractional_local_region_dq_gap_excludes_whole_block(inputs):
    inputs[3]["L1_BURST_CAT3"] = [[0, 17], [18, 20100]]
    result = assess(inputs)
    assert result["eligible_reference_blocks"] == 198
    assert result["status"] == "INCONCLUSIVE_INPUT_COVERAGE"
    assert result["blocks"][0]["reasons"] == ["L1_BURST_CAT3"]
    assert len(result["blocks"]) == 199


def test_bad_quality_elsewhere_not_local_not_retroactive_veto(inputs):
    inputs[3]["L1_BURST_CAT2"] = [[0, 2], [3, 20100]]
    assert assess(inputs)["eligible_reference_blocks"] == 199


def test_aux_gap_outside_local_but_inside_full_context_excludes_block(inputs):
    inputs[4][inputs[2][0]]["coverage_segments"] = [[0, 2], [3, 20100]]
    result = assess(inputs)
    assert result["eligible_reference_blocks"] == 198
    assert result["blocks"][0]["reasons"] == ["AUX_METADATA_GAP:L1:C0"]


def test_bad_event_coverage_never_negative(inputs):
    inputs[4][inputs[2][0]]["coverage_segments"] = [[0, 20010], [20011, 20100]]
    result = assess(inputs)
    assert result["eligible_reference_blocks"] == 199
    assert result["status"] == "INCONCLUSIVE_INPUT_COVERAGE"


@pytest.mark.parametrize(
    "change", ["cat1", "missing_flag", "wrong_channel", "duplicate_block", "region"]
)
def test_changed_scope_fails_closed(inputs, change):
    design, target, channels, quality, auxiliary = copy.deepcopy(inputs)
    if change == "cat1":
        quality["L1_CBC_CAT1"] = [[0, 100]]
    elif change == "missing_flag":
        del quality["L1_CBC_CAT3"]
    elif change == "wrong_channel":
        auxiliary["H1:C0"] = auxiliary.pop(channels[0])
    elif change == "duplicate_block":
        target["candidate_clean_control_blocks_gps"][1] = target[
            "candidate_clean_control_blocks_gps"
        ][0]
    else:
        target["local_offset_interval_s"] = [-1, 0]
    with pytest.raises(ContractError):
        assess((design, target, channels, quality, auxiliary))


def test_normalize_union_clip_and_half_open_boundary():
    assert normalize_segments([[-1, 3], [3, 5], [6, 15]], [0, 10]) == [[0, 5], [6, 10]]
    assert covers([[0, 5]], [4, 5])
    assert not covers([[0, 5], [6, 10]], [4, 6.1])


@pytest.mark.parametrize("bad", [[[2, 1]], [[float("nan"), 3]], [[1.5, 2]], [[1]]])
def test_malformed_source_coverage_rejected(bad):
    with pytest.raises(ContractError):
        normalize_segments(bad, [0, 10])


def test_missing_nds_channel_preserved_as_unavailable():
    item = SimpleNamespace(
        name="L1:A", data=[SimpleNamespace(gps_start=0, gps_stop=20, frame_type="X")]
    )
    result = auxiliary_metadata([item], ["L1:A", "L1:B"], [0, 20])
    assert result["L1:A"]["coverage_segments"] == [[0, 20]]
    assert result["L1:B"] == {
        "present": False,
        "source_segments": [],
        "coverage_segments": [],
    }


def test_duplicate_nds_channel_rejected():
    item = SimpleNamespace(name="L1:A", data=[])
    with pytest.raises(ContractError):
        auxiliary_metadata([item, item], ["L1:A"], [0, 20])


def test_saved_metadata_replay_and_no_terminal_rerun(tmp_path, monkeypatch, inputs):
    import sys

    import gwosc.timeline

    from scripts import preflight_dante_o3a_l1_local_inputs as runner
    from src.dante_light.o3a_o4a_common_pem_acquisition import _atomic_json, sealed_json

    design, target, _, quality, _ = inputs
    design = copy.deepcopy(design)
    design["input_preflight"]["output_root"] = "."
    (tmp_path / "config").mkdir()
    for key in ("common_method", "native_pem"):
        relative = design["parents"][key]["path"]
        (tmp_path / relative).write_bytes((ROOT / relative).read_bytes())
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    common = json.loads((ROOT / design["parents"]["common_method"]["path"]).read_text())
    channels = common["method"]["channels"]["L1"]
    target["tail_resolution_possible"] = True
    first = {
        "gps_start": 1238508320,
        "detector": "L1",
        "tail_resolution_possible": False,
        "candidate_clean_blocks_before_cat2_cat3": 31,
    }
    frozen = runner.seal(
        {
            "status": "FROZEN_LOCAL_INPUT_METADATA_PLAN_ONLY",
            "feasibility": {"targets": [first, target]},
        }
    )
    monkeypatch.setattr(runner, "load_design", lambda _: design)
    monkeypatch.setattr(runner, "plan", lambda: frozen)
    connection = SimpleNamespace(
        set_epoch=lambda *_: True,
        get_availability=lambda _: [
            SimpleNamespace(
                name=name,
                data=[SimpleNamespace(gps_start=0, gps_stop=20100, frame_type="X")],
            )
            for name in channels
        ],
    )
    monkeypatch.setitem(
        sys.modules, "nds2", SimpleNamespace(connection=lambda *_: connection)
    )
    monkeypatch.setattr(gwosc.timeline, "get_segments", lambda flag, *_: quality[flag])
    assert runner.main("plan", None) == 0
    path = tmp_path / f"inputs_{frozen['receipt_digest']}"
    assert runner.main("run", str(path)) == 0
    monkeypatch.setattr(
        gwosc.timeline, "get_segments", lambda *_: pytest.fail("verify must be offline")
    )
    assert runner.main("verify", str(path)) == 0
    summary = sealed_json(path / "summary.json")
    assert summary["targets"][0]["status"] == "INCONCLUSIVE"
    assert summary["targets"][1]["eligible_reference_blocks"] == 199
    with pytest.raises(ContractError, match="already terminal"):
        runner.main("run", str(path))
    summary.pop("receipt_digest")
    summary["targets"][1]["eligible_reference_blocks"] = 200
    _atomic_json(path / "summary.json", runner.seal(summary))
    with pytest.raises(ContractError, match="summary replay"):
        runner.main("verify", str(path))


def test_input_snapshot_identity_changed_rejected(inputs):
    from scripts import preflight_dante_o3a_l1_local_inputs as runner

    design, target, *_ = inputs
    target["tail_resolution_possible"] = True
    with pytest.raises(ContractError, match="identity/accounting"):
        runner.replay({"feasibility": {"targets": [target]}}, [], design)
