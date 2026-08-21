from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dante_light.contracts import (
    CalibrationEpochContract,
    ContractError,
    RepresentationContract,
)
from src.dante_light.manifest import (
    build_shadow_manifest,
    check_shadow_manifest,
    fetch_dq_snapshot,
    lock_selection_plan,
    select_padded_windows,
    write_locked_json,
    write_shadow_manifest,
)
from src.dante_light.run_config import verify_run_configuration


ROOT = Path(__file__).resolve().parents[1]


def _draft() -> dict:
    return {
        "schema_version": 1,
        "status": "draft",
        "purpose": "Outcome-blind later-run shadow evaluation",
        "run": "O5",
        "official_run_bounds_gps": [1000, 3000],
        "outcome_fields_used_for_selection": [],
        "source": {
            "provider": "GWOSC",
            "release_url": "https://gwosc.org/O5/",
            "flags": {"H1": "H1_CBC_CAT1", "L1": "L1_CBC_CAT1"},
        },
        "selection": {
            "detectors": ["H1", "L1"],
            "window_s": 32,
            "whitening_pad_s": 4,
            "windows_per_detector_block": 2,
            "selection_rule": "uniform_cat1",
            "tuning_interval_gps": [1500, 1600],
            "evaluation_blocks_gps": [[2000, 2200], [2400, 2600]],
        },
    }


def _snapshot(plan: dict) -> dict:
    return fetch_dq_snapshot(
        plan,
        segment_fetcher=lambda _flag, start, end: [(start - 10, end + 10)],
    )


def _files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    config = tmp_path / "config"
    plan_path = config / "plan.json"
    snapshot_path = config / "snapshot.json"
    output_path = config / "shadow.json"
    reference = config / "reference_artifacts.json"
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_bytes((ROOT / "config/reference_artifacts.json").read_bytes())
    return plan_path, snapshot_path, output_path, reference


def test_generic_manifest_is_outcome_blind_deterministic_and_checkable(
    tmp_path: Path,
) -> None:
    plan_path, snapshot_path, output_path, reference = _files(tmp_path)
    plan = lock_selection_plan(_draft())
    snapshot = _snapshot(plan)
    write_locked_json(plan_path, plan)
    write_locked_json(snapshot_path, snapshot)

    first, entries = build_shadow_manifest(
        plan_path=plan_path,
        snapshot_path=snapshot_path,
        output_path=output_path,
        reference_manifest_path=reference,
        root=tmp_path,
    )
    second, repeated = build_shadow_manifest(
        plan_path=plan_path,
        snapshot_path=snapshot_path,
        output_path=output_path,
        reference_manifest_path=reference,
        root=tmp_path,
    )

    assert first == second
    assert entries == repeated
    assert first["counts"]["entries"] == 8
    assert first["counts"]["unique_windows"] == 8
    assert first["outcome_fields_used_for_selection"] == []
    assert all(row["expected"] == {} for row in entries)
    assert {row["window"]["run"] for row in entries} == {"O5"}
    write_shadow_manifest(output_path, first, entries)
    check_shadow_manifest(output_path, first, entries)


def test_plan_rejects_tuning_overlap_with_evaluation() -> None:
    draft = _draft()
    draft["selection"]["tuning_interval_gps"] = [1500, 2050]
    with pytest.raises(ContractError, match="before held-out evaluation"):
        lock_selection_plan(draft)


def test_plan_rejects_unsupported_detector_set() -> None:
    draft = _draft()
    draft["selection"]["detectors"] = ["H1", "L1", "V1"]
    draft["source"]["flags"]["V1"] = "V1_CBC_CAT1"
    with pytest.raises(ContractError, match="requires H1 and L1"):
        lock_selection_plan(draft)


def test_uniform_cat1_selection_spans_the_eligible_block() -> None:
    uniform = select_padded_windows(
        [[0, 324]],
        0,
        324,
        count=3,
        window_s=32,
        pad_s=4,
        selection_rule="uniform_cat1",
    )
    first = select_padded_windows(
        [[0, 324]],
        0,
        324,
        count=3,
        window_s=32,
        pad_s=4,
        selection_rule="first_aligned",
    )

    assert first == [32, 64, 96]
    assert uniform[0] > first[0]
    assert uniform[-1] > first[-1]


def test_manifest_rejects_tampered_plan(tmp_path: Path) -> None:
    plan_path, snapshot_path, output_path, reference = _files(tmp_path)
    plan = lock_selection_plan(_draft())
    snapshot = _snapshot(plan)
    plan["purpose"] = "changed after locking"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    write_locked_json(snapshot_path, snapshot)

    with pytest.raises(ContractError, match="plan self-hash"):
        build_shadow_manifest(
            plan_path=plan_path,
            snapshot_path=snapshot_path,
            output_path=output_path,
            reference_manifest_path=reference,
            root=tmp_path,
        )


def test_manifest_rejects_snapshot_from_another_plan(tmp_path: Path) -> None:
    plan_path, snapshot_path, output_path, reference = _files(tmp_path)
    plan = lock_selection_plan(_draft())
    other = _draft()
    other["purpose"] = "another locked selection"
    snapshot = _snapshot(lock_selection_plan(other))
    write_locked_json(plan_path, plan)
    write_locked_json(snapshot_path, snapshot)

    with pytest.raises(ContractError, match="different selection plan"):
        build_shadow_manifest(
            plan_path=plan_path,
            snapshot_path=snapshot_path,
            output_path=output_path,
            reference_manifest_path=reference,
            root=tmp_path,
        )


def test_manifest_fails_when_cat1_context_is_insufficient(tmp_path: Path) -> None:
    plan_path, snapshot_path, output_path, reference = _files(tmp_path)
    plan = lock_selection_plan(_draft())
    snapshot = fetch_dq_snapshot(
        plan,
        segment_fetcher=lambda _flag, _start, _end: [(2000, 2040)],
    )
    write_locked_json(plan_path, plan)
    write_locked_json(snapshot_path, snapshot)

    with pytest.raises(ContractError, match="provides only"):
        build_shadow_manifest(
            plan_path=plan_path,
            snapshot_path=snapshot_path,
            output_path=output_path,
            reference_manifest_path=reference,
            root=tmp_path,
        )


def test_run_preflight_links_generic_manifest_to_causal_epochs(tmp_path: Path) -> None:
    plan_path, snapshot_path, output_path, reference = _files(tmp_path)
    plan = lock_selection_plan(_draft())
    write_locked_json(plan_path, plan)
    write_locked_json(snapshot_path, _snapshot(plan))
    manifest, entries = build_shadow_manifest(
        plan_path=plan_path,
        snapshot_path=snapshot_path,
        output_path=output_path,
        reference_manifest_path=reference,
        root=tmp_path,
    )
    write_shadow_manifest(output_path, manifest, entries)
    epochs_path = tmp_path / "config/epochs.json"
    epochs_path.write_text("{}", encoding="utf-8")
    representation = RepresentationContract.from_reference_manifest(reference)

    def causal_loader(*_args, **_kwargs):
        return {"status": "causal_promoted"}, {
            detector: CalibrationEpochContract(
                epoch_id=f"past-only-{detector.lower()}",
                run="O5",
                detector=detector,
                cutoff_gps=1600,
                threshold=0.2,
                threshold_artifact_sha256="a" * 64,
                native_index_sha256=representation.native_index_sha256,
                causal=True,
            )
            for detector in ("H1", "L1")
        }

    result = verify_run_configuration(
        manifest_path=output_path,
        epochs_path=epochs_path,
        root=tmp_path,
        reference_manifest_path=reference,
        epoch_loader=causal_loader,
    )

    assert result["status"] == "PASS"
    assert result["windows"] == 8
    assert set(result["detectors"]) == {"H1", "L1"}


def test_run_preflight_rejects_epoch_lookahead(tmp_path: Path) -> None:
    plan_path, snapshot_path, output_path, reference = _files(tmp_path)
    plan = lock_selection_plan(_draft())
    write_locked_json(plan_path, plan)
    write_locked_json(snapshot_path, _snapshot(plan))
    manifest, entries = build_shadow_manifest(
        plan_path=plan_path,
        snapshot_path=snapshot_path,
        output_path=output_path,
        reference_manifest_path=reference,
        root=tmp_path,
    )
    write_shadow_manifest(output_path, manifest, entries)
    epochs_path = tmp_path / "config/epochs.json"
    epochs_path.write_text("{}", encoding="utf-8")
    representation = RepresentationContract.from_reference_manifest(reference)

    def lookahead_loader(*_args, **_kwargs):
        return {"status": "causal_promoted"}, {
            detector: CalibrationEpochContract(
                epoch_id=f"invalid-{detector.lower()}",
                run="O5",
                detector=detector,
                cutoff_gps=2050,
                threshold=0.2,
                threshold_artifact_sha256="a" * 64,
                native_index_sha256=representation.native_index_sha256,
                causal=True,
            )
            for detector in ("H1", "L1")
        }

    with pytest.raises(ContractError, match="cutoff is not before evaluation"):
        verify_run_configuration(
            manifest_path=output_path,
            epochs_path=epochs_path,
            root=tmp_path,
            reference_manifest_path=reference,
            epoch_loader=lookahead_loader,
        )
