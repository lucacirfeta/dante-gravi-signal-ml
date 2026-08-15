from __future__ import annotations

import hashlib

import numpy as np
import pytest

from src.dante_light.contracts import (
    CalibrationEpochContract,
    ContractError,
    LightDisposition,
    RepresentationContract,
    WindowIdentity,
)
from src.dante_light.executor import WindowTask
from src.dante_light.preprocessing import PreparedWindow
from src.dante_light.review_queue import ReviewQueue
from src.dante_light.runner import DanteLightRunner, load_epochs, load_replay_tasks


REPRESENTATION = RepresentationContract.from_reference_manifest(
    "config/reference_artifacts.json"
)


class FakeScorer:
    def __init__(self, reference_sha256: str):
        self.reference_sha256 = reference_sha256

    def score_multi_index(self, images, _targets, *, output_modes):
        assert output_modes == {"native": "score_only"}
        primary = []
        native = []
        for image in images:
            score = float(np.asarray(image, dtype=np.float32).mean())
            primary.append(
                {
                    "novelty_score": score + 0.1,
                    "top_k_indices": np.array([1, 3], dtype=np.int32),
                    "mil_vector": np.ones(384, dtype=np.float32),
                }
            )
            native.append({"novelty_score": score, "is_novel": score > 1.0})
        return {"primary": primary, "native": native}


def epoch(detector: str, *, causal: bool = False) -> CalibrationEpochContract:
    return CalibrationEpochContract(
        epoch_id=f"fixture-{detector.lower()}",
        run="O4A",
        detector=detector,
        cutoff_gps=900.0,
        threshold=0.5,
        threshold_artifact_sha256="a" * 64,
        native_index_sha256=REPRESENTATION.native_index_sha256,
        causal=causal,
    )


def make_tasks() -> list[WindowTask]:
    return [
        WindowTask(
            WindowIdentity("O4A", "H1" if index % 2 else "L1", 1000 + index),
            {"case_ids": [f"case-{index}"], "roles": ["fixture"], "expected": []},
        )
        for index in range(6)
    ]


def prepared(task: WindowTask) -> PreparedWindow:
    value = (int(task.window.gps_start) % 3) / 2.0
    image = np.full((2, 2, 3), value, dtype=np.float32)
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    return PreparedWindow(image, digest, digest, {"fixture_s": 0.0})


def make_runner(tmp_path, *, prospective: bool = False, cat1=None):
    primary = FakeScorer(REPRESENTATION.primary_index_sha256)
    native = FakeScorer(REPRESENTATION.native_index_sha256)
    queue = ReviewQueue(
        tmp_path,
        {
            "schema_version": 1,
            "mode": "shadow" if prospective else "historical_replay",
            "representation": REPRESENTATION.to_dict(),
        },
    )
    return DanteLightRunner(
        representation=REPRESENTATION,
        epochs={"H1": epoch("H1"), "L1": epoch("L1")},
        primary=primary,
        native=native,
        review_queue=queue,
        cat1_active=cat1 or (lambda _window: True),
        prepare=prepared,
        prospective=prospective,
        workers=2,
        batch_size=2,
        max_preprocess_in_flight=4,
    )


def test_exact_runner_writes_traceable_records_and_resumes(tmp_path) -> None:
    runner = make_runner(tmp_path)
    first = runner.run(make_tasks())
    assert first["status"] == "complete"
    assert first["executor"]["submitted"] == 6
    assert first["executor"]["drops"] == 0
    assert first["records_total"] == 6
    assert set(first["dispositions"]) <= {
        LightDisposition.ESCALATE.value,
        LightDisposition.NOT_ESCALATED.value,
    }

    lines = runner.queue.records_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6
    assert all("primary_top_k_sha256" in line for line in lines)
    assert all("decision_threshold" in line for line in lines)

    resumed = make_runner(tmp_path).run(make_tasks())
    assert resumed["executor"]["submitted"] == 0
    assert resumed["records_total"] == 6
    assert len(runner.queue.records_path.read_text(encoding="utf-8").splitlines()) == 6
    assert len((tmp_path / "attempts.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_prospective_mode_rejects_noncausal_historical_epoch(tmp_path) -> None:
    runner = make_runner(tmp_path, prospective=True)
    summary = runner.run(make_tasks())
    assert summary["executor"]["deferred"] == 6
    assert summary["dispositions"] == {LightDisposition.DEFER.value: 6}
    assert "NON_CAUSAL_EPOCH" in runner.queue.records_path.read_text(encoding="utf-8")


def test_cat1_and_dependency_failures_are_explicit_defer(tmp_path) -> None:
    def cat1(window):
        if window.gps_start == 1000:
            return False
        if window.gps_start == 1001:
            return None
        return True

    runner = make_runner(tmp_path, cat1=cat1)
    summary = runner.run(make_tasks())
    text = runner.queue.records_path.read_text(encoding="utf-8")
    assert summary["executor"]["deferred"] == 2
    assert "MISSING_CAT1" in text
    assert "DEPENDENCY_UNAVAILABLE" in text


def test_review_queue_refuses_divergent_manifest_and_record(tmp_path) -> None:
    queue = ReviewQueue(tmp_path, {"schema_version": 1, "mode": "fixture"})
    record = {
        "window": WindowIdentity("O4A", "H1", 1000).to_dict(),
        "disposition": "NOT_ESCALATED",
    }
    assert queue.append([record]) == 1
    assert queue.append([record]) == 0
    divergent = dict(record)
    divergent["disposition"] = "ESCALATE"
    with pytest.raises(ContractError, match="Divergent replay"):
        queue.append([divergent])
    with pytest.raises(ContractError, match="divergent run manifest"):
        ReviewQueue(tmp_path, {"schema_version": 1, "mode": "other"})


def test_frozen_epoch_and_replay_files_are_self_consistent() -> None:
    payload, epochs = load_epochs()
    assert payload["status"] == "historical_replay_only"
    assert set(epochs) == {"H1", "L1"}
    assert all(not epoch_value.causal for epoch_value in epochs.values())
    header, replay = load_replay_tasks(roles={"forum_candidate"})
    assert header["status"] == "frozen"
    assert len(replay) == 1
    assert replay[0].window.detector == "L1"
    assert replay[0].window.gps_start == 1382955232.0


def test_public_cli_keeps_light_opt_in_and_output_separate() -> None:
    import main

    parser = main.build_parser()
    replay = parser.parse_args(
        ["dante-light-replay", "--output-dir", "runs/dante_light/test"]
    )
    assert replay.func is main.cmd_dante_light_replay
    assert replay.limit == 8
    assert replay.cat1_mode == "gwosc"
    assert replay.output_dir.as_posix() == "runs/dante_light/test"
    shadow = parser.parse_args(
        ["dante-light-shadow", "--output-dir", "runs/dante_light/shadow"]
    )
    assert shadow.func is main.cmd_dante_light_shadow
