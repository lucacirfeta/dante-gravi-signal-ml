from __future__ import annotations

import threading
import time

import pytest

from src.dante_light.contracts import (
    FailClosedReason,
    LightDisposition,
    LightRecord,
    RepresentationContract,
    WindowIdentity,
)
from src.dante_light.executor import (
    BoundedPipelineExecutor,
    DeferredWindow,
    PipelineWriteError,
    WindowTask,
)


REPRESENTATION = RepresentationContract.from_reference_manifest(
    "config/reference_artifacts.json"
)


def deferred(window: WindowIdentity, reason: FailClosedReason) -> LightRecord:
    return LightRecord.deferred(window, REPRESENTATION, reason)


def scored(task: WindowTask, value: float) -> LightRecord:
    return LightRecord(
        window=task.window,
        representation_sha256=REPRESENTATION.contract_sha256,
        disposition=LightDisposition.ESCALATE,
        epoch_id="fixture",
        scores=(("native", value),),
    )


def tasks(count: int = 40) -> list[WindowTask]:
    return [
        WindowTask(WindowIdentity("O4A", "H1" if index % 2 else "L1", 1000 + index))
        for index in range(count)
    ]


def test_bounded_executor_preserves_order_and_never_drops_under_backpressure() -> None:
    written: list[LightRecord] = []
    lock = threading.Lock()

    def preprocess(task: WindowTask) -> float:
        time.sleep(0.0002 * (7 - int(task.window.gps_start) % 7))
        return task.window.gps_start / 1000.0

    def score_batch(batch):
        return [scored(task, value) for task, value in batch]

    def write_batch(records):
        time.sleep(0.002)
        with lock:
            written.extend(records)

    executor = BoundedPipelineExecutor(
        preprocess=preprocess,
        score_batch=score_batch,
        write_batch=write_batch,
        defer_record=deferred,
        workers=3,
        batch_size=5,
        max_preprocess_in_flight=6,
        max_pending_writes=2,
    )
    summary = executor.run(reversed(tasks()))

    expected = sorted(
        tasks(), key=lambda task: (task.window.detector, task.window.gps_start)
    )
    assert [record.window.window_id for record in written] == [
        task.window.window_id for task in expected
    ]
    assert summary.submitted == summary.written == 40
    assert summary.drops == 0
    assert summary.deferred == 0
    assert summary.max_preprocess_in_flight <= 6
    assert summary.max_pending_writes <= 2
    assert len(summary.latency_s) == summary.written
    assert all(latency > 0 for latency in summary.latency_s)


def test_known_and_unknown_preprocess_failures_are_scoreless_defer() -> None:
    written = []

    def preprocess(task: WindowTask) -> float:
        gps = int(task.window.gps_start)
        if gps == 1003:
            raise DeferredWindow(FailClosedReason.MISSING_CAT1)
        if gps == 1005:
            raise ValueError("broken fixture")
        return float(gps)

    executor = BoundedPipelineExecutor(
        preprocess=preprocess,
        score_batch=lambda batch: [scored(task, value) for task, value in batch],
        write_batch=written.extend,
        defer_record=deferred,
        workers=2,
        batch_size=3,
        max_preprocess_in_flight=4,
    )
    summary = executor.run(tasks(8))

    by_gps = {record.window.gps_start: record for record in written}
    assert by_gps[1003].disposition is LightDisposition.DEFER
    assert by_gps[1003].defer_reason is FailClosedReason.MISSING_CAT1
    assert by_gps[1005].defer_reason is FailClosedReason.INTERNAL_ERROR
    assert by_gps[1003].scores == by_gps[1005].scores == ()
    assert summary.written == 8
    assert summary.deferred == 2
    assert len(summary.latency_s) == 8
    assert {failure.stage for failure in summary.failures} == {
        "preflight",
        "preprocess",
    }


def test_scoring_failure_defers_the_whole_batch_without_loss() -> None:
    written = []

    def fail_score(_batch):
        raise RuntimeError("GPU unavailable")

    executor = BoundedPipelineExecutor(
        preprocess=lambda task: task.window.gps_start,
        score_batch=fail_score,
        write_batch=written.extend,
        defer_record=deferred,
        workers=1,
        batch_size=2,
        max_preprocess_in_flight=2,
    )
    summary = executor.run(tasks(5))
    assert summary.written == summary.deferred == 5
    assert len(summary.latency_s) == 5
    assert all(record.defer_reason is FailClosedReason.INTERNAL_ERROR for record in written)
    assert all(record.scores == () for record in written)
    assert {failure.stage for failure in summary.failures} == {"score"}


def test_writer_failure_is_fatal_and_duplicate_identity_is_rejected() -> None:
    executor = BoundedPipelineExecutor(
        preprocess=lambda task: task.window.gps_start,
        score_batch=lambda batch: [scored(task, value) for task, value in batch],
        write_batch=lambda _records: (_ for _ in ()).throw(OSError("disk full")),
        defer_record=deferred,
        workers=1,
        batch_size=2,
        max_preprocess_in_flight=2,
    )
    with pytest.raises(PipelineWriteError, match="durable writer failed"):
        executor.run(tasks(3))

    duplicate = tasks(1)[0]
    with pytest.raises(ValueError, match="Duplicate"):
        executor.run([duplicate, duplicate])
