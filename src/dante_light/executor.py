"""Bounded, deterministic execution for exact DANTE-Light replay.

CPU preprocessing runs concurrently, while scoring remains single-consumer and
durable writes remain single-writer. Back-pressure bounds both future sets;
scientific windows are never dropped merely because a queue is full.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
import time
from typing import Any, Callable, Generic, Iterable, TypeVar

from src.dante_light.contracts import (
    FailClosedReason,
    LightRecord,
    WindowIdentity,
)


PreparedT = TypeVar("PreparedT")


class DeferredWindow(RuntimeError):
    """A known preflight failure that must become a scoreless DEFER record."""

    def __init__(self, reason: FailClosedReason):
        self.reason = FailClosedReason(reason)
        super().__init__(self.reason.value)


class PipelineWriteError(RuntimeError):
    """Durability failed; the caller must retry from the last checkpoint."""


@dataclass(frozen=True, slots=True)
class WindowTask:
    window: WindowIdentity
    payload: Any = None


@dataclass(frozen=True, slots=True)
class ExecutorFailure:
    sequence: int
    window_id: str
    stage: str
    exception_type: str
    message: str


@dataclass(frozen=True, slots=True)
class ExecutorSummary:
    submitted: int
    written: int
    deferred: int
    batches_scored: int
    batches_written: int
    max_preprocess_in_flight: int
    max_pending_writes: int
    elapsed_s: float
    latency_s: tuple[float, ...] = field(default_factory=tuple)
    failures: tuple[ExecutorFailure, ...] = field(default_factory=tuple)

    @property
    def drops(self) -> int:
        return self.submitted - self.written


class BoundedPipelineExecutor(Generic[PreparedT]):
    """Overlap bounded preprocessing, exact batch scoring, and ordered writes."""

    def __init__(
        self,
        *,
        preprocess: Callable[[WindowTask], PreparedT],
        score_batch: Callable[[list[tuple[WindowTask, PreparedT]]], list[LightRecord]],
        write_batch: Callable[[list[LightRecord]], None],
        defer_record: Callable[[WindowIdentity, FailClosedReason], LightRecord],
        workers: int = 2,
        batch_size: int = 8,
        max_preprocess_in_flight: int = 16,
        max_pending_writes: int = 2,
    ) -> None:
        if workers <= 0 or batch_size <= 0:
            raise ValueError("workers and batch_size must be positive")
        if max_preprocess_in_flight < workers:
            raise ValueError("max_preprocess_in_flight must be at least workers")
        if max_pending_writes <= 0:
            raise ValueError("max_pending_writes must be positive")
        self.preprocess = preprocess
        self.score_batch = score_batch
        self.write_batch = write_batch
        self.defer_record = defer_record
        self.workers = workers
        self.batch_size = batch_size
        self.preprocess_limit = max_preprocess_in_flight
        self.write_limit = max_pending_writes

    @staticmethod
    def _ordered_tasks(tasks: Iterable[WindowTask]) -> list[WindowTask]:
        ordered = sorted(
            tasks,
            key=lambda task: (
                task.window.detector,
                task.window.gps_start,
                task.window.duration_s,
                task.window.window_id,
            ),
        )
        identities = [task.window.window_id for task in ordered]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate detector/GPS window identity")
        return ordered

    def run(self, tasks: Iterable[WindowTask]) -> ExecutorSummary:
        ordered = self._ordered_tasks(tasks)
        started = time.perf_counter()
        failures: list[ExecutorFailure] = []
        deferred = 0
        written = 0
        scored_batches = 0
        written_batches = 0
        peak_preprocess = 0
        peak_writes = 0
        pending_writes: deque[
            tuple[list[LightRecord], tuple[int, ...], Future[float]]
        ] = deque()
        submitted_at: dict[int, float] = {}
        latency_by_sequence: dict[int, float] = {}

        def failure(sequence: int, task: WindowTask, stage: str, exc: Exception) -> None:
            failures.append(
                ExecutorFailure(
                    sequence=sequence,
                    window_id=task.window.window_id,
                    stage=stage,
                    exception_type=type(exc).__name__,
                    message=str(exc),
                )
            )

        def finish_oldest_write() -> None:
            nonlocal written, written_batches
            records, sequences, future = pending_writes.popleft()
            try:
                completed_at = future.result()
            except Exception as exc:
                raise PipelineWriteError(
                    "DANTE-Light durable writer failed; retry from the last "
                    "committed checkpoint"
                ) from exc
            written += len(records)
            written_batches += 1
            for sequence in sequences:
                latency_by_sequence[sequence] = completed_at - submitted_at[sequence]

        with ThreadPoolExecutor(
            max_workers=self.workers, thread_name_prefix="dante-light-preprocess"
        ) as preprocess_pool, ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="dante-light-writer"
        ) as writer_pool:
            futures: dict[int, Future[PreparedT]] = {}
            next_submit = 0

            def fill_preprocess() -> None:
                nonlocal next_submit, peak_preprocess
                while (
                    next_submit < len(ordered)
                    and len(futures) < self.preprocess_limit
                ):
                    submitted_at[next_submit] = time.perf_counter()
                    futures[next_submit] = preprocess_pool.submit(
                        self.preprocess, ordered[next_submit]
                    )
                    next_submit += 1
                    peak_preprocess = max(peak_preprocess, len(futures))

            def durable_write(records: list[LightRecord]) -> float:
                self.write_batch(records)
                return time.perf_counter()

            def submit_write(
                records: list[LightRecord], sequences: tuple[int, ...]
            ) -> None:
                nonlocal peak_writes
                if not records:
                    return
                if len(records) != len(sequences):
                    raise RuntimeError("write batch sequence accounting mismatch")
                while len(pending_writes) >= self.write_limit:
                    finish_oldest_write()
                pending_writes.append(
                    (records, sequences, writer_pool.submit(durable_write, records))
                )
                peak_writes = max(peak_writes, len(pending_writes))

            def score_and_submit(
                batch: list[tuple[int, WindowTask, PreparedT]],
            ) -> None:
                nonlocal deferred, scored_batches
                if not batch:
                    return
                try:
                    records = self.score_batch(
                        [(task, prepared) for _, task, prepared in batch]
                    )
                    if len(records) != len(batch):
                        raise RuntimeError(
                            "score_batch returned a different number of records"
                        )
                    for (_, task, _), record in zip(batch, records, strict=True):
                        if record.window.window_id != task.window.window_id:
                            raise RuntimeError("score_batch reordered window identities")
                except Exception as exc:
                    records = []
                    for sequence, task, _ in batch:
                        failure(sequence, task, "score", exc)
                        records.append(
                            self.defer_record(
                                task.window, FailClosedReason.INTERNAL_ERROR
                            )
                        )
                    deferred += len(records)
                scored_batches += 1
                submit_write(records, tuple(sequence for sequence, _, _ in batch))

            fill_preprocess()
            ready: list[tuple[int, WindowTask, PreparedT]] = []
            for sequence, task in enumerate(ordered):
                future = futures.pop(sequence)
                try:
                    prepared = future.result()
                except DeferredWindow as exc:
                    score_and_submit(ready)
                    ready = []
                    failure(sequence, task, "preflight", exc)
                    submit_write(
                        [self.defer_record(task.window, exc.reason)], (sequence,)
                    )
                    deferred += 1
                except Exception as exc:
                    score_and_submit(ready)
                    ready = []
                    failure(sequence, task, "preprocess", exc)
                    submit_write(
                        [
                            self.defer_record(
                                task.window, FailClosedReason.INTERNAL_ERROR
                            )
                        ],
                        (sequence,),
                    )
                    deferred += 1
                else:
                    ready.append((sequence, task, prepared))
                    if len(ready) == self.batch_size:
                        score_and_submit(ready)
                        ready = []
                fill_preprocess()
            score_and_submit(ready)
            while pending_writes:
                finish_oldest_write()

        summary = ExecutorSummary(
            submitted=len(ordered),
            written=written,
            deferred=deferred,
            batches_scored=scored_batches,
            batches_written=written_batches,
            max_preprocess_in_flight=peak_preprocess,
            max_pending_writes=peak_writes,
            elapsed_s=time.perf_counter() - started,
            latency_s=tuple(
                latency_by_sequence[sequence] for sequence in range(len(ordered))
            ),
            failures=tuple(failures),
        )
        if summary.drops:
            raise RuntimeError(
                f"Executor accounting failure: {summary.drops} silent drops"
            )
        return summary
