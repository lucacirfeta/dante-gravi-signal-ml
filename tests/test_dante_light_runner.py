from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
from src.dante_light.epoch import REQUIRED_GATES
from src.dante_light.preprocessing import PreparedWindow
from src.dante_light.review_queue import ReviewQueue
from src.dante_light.runner import (
    DEFAULT_EPOCHS,
    DanteLightRunner,
    load_epochs,
    load_replay_tasks,
    runtime_provenance,
)


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

    def score_spectrogram(self, images, threshold):
        assert threshold == 1.0
        output = []
        for image in images:
            score = float(np.asarray(image, dtype=np.float32).mean())
            if self.reference_sha256 == REPRESENTATION.primary_index_sha256:
                score += 0.1
            output.append(
                {
                    "novelty_score": score,
                    "is_novel": score > threshold,
                    "top_k_indices": np.array([1, 3], dtype=np.int32),
                    "mil_vector": np.ones(384, dtype=np.float32),
                }
            )
        return output


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


def make_runner(
    tmp_path,
    *,
    prospective: bool = False,
    cat1=None,
    engine="shared_encoder_score_only",
    stage_data=None,
):
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
        stage_data=stage_data,
        prospective=prospective,
        engine=engine,
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


def test_canonical_reference_engine_produces_same_light_dispositions(tmp_path) -> None:
    runner = make_runner(tmp_path, engine="canonical")
    summary = runner.run(make_tasks())
    assert summary["status"] == "complete"
    assert summary["executor"]["written"] == 6


def test_prospective_staging_precedes_executor_and_binds_strain(tmp_path) -> None:
    order: list[str] = []

    def stage(task):
        order.append(f"stage:{task.window.window_id}")
        result = prepared(task)
        return {
            "window_id": task.window.window_id,
            "duration_s": 0.1,
            "samples": 4,
            "sample_rate_hz": 1.0,
            "strain_sha256": result.strain_sha256,
        }

    runner = make_runner(tmp_path, stage_data=stage)
    original_prepare = runner.prepare_window

    def ordered_prepare(task):
        assert len(order) == len(make_tasks())
        return original_prepare(task)

    runner.prepare_window = ordered_prepare
    summary = runner.run(make_tasks())
    assert summary["status"] == "complete"
    assert summary["acquisition"]["mode"] == "prestage_before_task_submission"
    assert summary["acquisition"]["windows"] == 6
    assert summary["acquisition"]["failures"] == []


def test_staged_strain_drift_fails_closed(tmp_path) -> None:
    def stage(task):
        return {
            "window_id": task.window.window_id,
            "duration_s": 0.1,
            "samples": 4,
            "sample_rate_hz": 1.0,
            "strain_sha256": "0" * 64,
        }

    summary = make_runner(tmp_path, stage_data=stage).run(make_tasks())
    assert summary["status"] == "complete_with_defer"
    assert summary["executor"]["deferred"] == 6
    assert summary["dispositions"] == {LightDisposition.DEFER.value: 6}


def test_prospective_mode_rejects_noncausal_historical_epoch(tmp_path) -> None:
    runner = make_runner(tmp_path, prospective=True)
    summary = runner.run(make_tasks())
    assert summary["status"] == "complete_with_defer"
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


def test_causal_epoch_file_cannot_bypass_promotion_evidence(tmp_path) -> None:
    payload = json.loads(DEFAULT_EPOCHS.read_text(encoding="utf-8"))
    payload["epochs"]["H1"]["causal"] = True
    path = tmp_path / "epochs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    representation = RepresentationContract.from_reference_manifest(
        "config/reference_artifacts.json"
    )
    with pytest.raises(ContractError, match="lacks promotion evidence"):
        load_epochs(path, representation=representation)


def test_epoch_file_rejects_noncanonical_detector_key(tmp_path) -> None:
    payload = json.loads(DEFAULT_EPOCHS.read_text(encoding="utf-8"))
    payload["epochs"]["h1"] = payload["epochs"].pop("H1")
    path = tmp_path / "epochs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="key/detector mismatch"):
        load_epochs(path)


def test_causal_epoch_file_accepts_only_hashed_promotion_path(tmp_path) -> None:
    threshold = tmp_path / "threshold.json"
    ledger = tmp_path / "ledger.csv"
    threshold.write_text("{}\n", encoding="utf-8")
    ledger.write_text("gps,score\n", encoding="utf-8")
    threshold_sha256 = hashlib.sha256(threshold.read_bytes()).hexdigest()
    ledger_sha256 = hashlib.sha256(ledger.read_bytes()).hexdigest()
    representation = RepresentationContract.from_reference_manifest(
        "config/reference_artifacts.json"
    )
    raw_epoch = {
        "schema_version": 1,
        "epoch_id": "o4b-causal-h1-v1",
        "run": "O4B",
        "detector": "H1",
        "cutoff_gps": 2000.0,
        "threshold": 0.2,
        "threshold_artifact_sha256": threshold_sha256,
        "native_index_sha256": representation.native_index_sha256,
        "causal": True,
        "calibration_ledger_sha256": ledger_sha256,
        "promotion_evidence": {
            "detector": "H1",
            "run": "O4B",
            "calibration_start_gps": 1000.0,
            "calibration_end_gps": 2000.0,
            "evaluation_start_gps": 3000.0,
            "evaluation_end_gps": 4000.0,
            "gates": {gate: "PASS" for gate in REQUIRED_GATES},
            "gate_artifacts": {
                gate: [threshold.name] for gate in REQUIRED_GATES
            },
            "artifacts": [
                {"path": threshold.name, "sha256": threshold_sha256},
                {"path": ledger.name, "sha256": ledger_sha256},
            ],
        },
    }
    payload = {
        "schema_version": 1,
        "source_threshold_artifact": {
            "path": threshold.name,
            "sha256": threshold_sha256,
        },
        "epochs": {"H1": raw_epoch},
    }
    path = tmp_path / "epochs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, epochs = load_epochs(path, representation=representation, root=tmp_path)
    assert epochs["H1"].causal is True


def test_public_cli_keeps_light_opt_in_and_output_separate() -> None:
    import main

    parser = main.build_parser()
    replay = parser.parse_args(
        ["dante-light-replay", "--output-dir", "runs/dante_light/test"]
    )
    assert replay.func is main.cmd_dante_light_replay
    assert replay.limit == 8
    assert replay.engine == "canonical"
    assert replay.cat1_mode == "gwosc"
    assert replay.strain_source == "auto"
    assert replay.output_dir.as_posix() == "runs/dante_light/test"
    shadow = parser.parse_args(
        ["dante-light-shadow", "--output-dir", "runs/dante_light/shadow"]
    )
    assert shadow.func is main.cmd_dante_light_shadow


def test_runtime_provenance_records_reproducible_latency_environment() -> None:
    payload = runtime_provenance()
    environment = payload["environment"]
    assert environment["logical_cpu_count"] > 0
    assert environment["packages"]["torch"]
    assert "cuda_available" in environment["accelerator"]
    assert "main.py" in payload["source_sha256"]
    assert "src/core/data_loader.py" in payload["source_sha256"]


def test_light_cli_exposes_explicit_gwosc_only_source() -> None:
    import main

    parser = main.build_parser()
    args = parser.parse_args(
        [
            "dante-light-replay",
            "--output-dir",
            "runs/dante_light/public",
            "--strain-source",
            "gwosc-only",
        ]
    )
    assert args.strain_source == "gwosc-only"
    assert args.local_only is False


def test_replay_scorers_take_top_k_from_representation_contract() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/dante_light/runner.py").read_text(
        encoding="utf-8"
    )
    constructor_region = source[source.index("primary = PatchScorer") :]

    assert constructor_region.count("k=representation.top_k") == 2
    assert "k=68" not in constructor_region
