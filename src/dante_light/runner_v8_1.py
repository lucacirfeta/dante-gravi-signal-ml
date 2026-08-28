"""Versioned v8.1 exact replay entry point.

The historical ``runner.py`` remains byte-stable because the frozen v5-v7
contracts bind that source file.  This module changes only the scorer
construction source of truth and otherwise delegates to the historical runner.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from src.core.patch_scorer import PatchScorer
from src.dante_light.contracts import ContractError, RepresentationContract
from src.dante_light.preprocessing import prepare_canonical_window, stage_canonical_strain
from src.dante_light.review_queue import ReviewQueue
from src.dante_light.runner import (
    ROOT,
    DEFAULT_EPOCHS,
    DEFAULT_REPLAY,
    PRIMARY_INDEX,
    NATIVE_INDEX,
    DanteLightRunner,
    gwosc_cat1_provider,
    load_epochs,
    load_replay_tasks,
    runtime_provenance as _historical_runtime_provenance,
)


def runtime_provenance() -> dict[str, Any]:
    provenance = _historical_runtime_provenance()
    source = Path(__file__).resolve()
    normalized = (
        source.read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .encode("utf-8")
    )
    provenance["source_sha256"][source.relative_to(ROOT).as_posix()] = (
        hashlib.sha256(normalized).hexdigest()
    )
    return provenance


def run_replay(args) -> dict[str, Any]:
    representation = RepresentationContract.from_reference_manifest(
        ROOT / "config/reference_artifacts.json"
    )
    epoch_payload, epochs = load_epochs(
        args.epochs, representation=representation, root=ROOT
    )
    replay_header, tasks = load_replay_tasks(
        args.manifest,
        roles=set(args.role),
        limit=args.limit,
        limit_per_detector=args.limit_per_detector,
    )
    strain_source = getattr(args, "strain_source", "auto")
    latency_objective = getattr(args, "latency_objective_s", None)
    if latency_objective is not None:
        latency_objective = float(latency_objective)
        if not math.isfinite(latency_objective) or latency_objective <= 0:
            raise ContractError("--latency-objective-s must be finite and positive")
    if args.local_only:
        if strain_source != "auto":
            raise ContractError(
                "--local-only cannot be combined with an explicit --strain-source"
            )
        strain_source = "local-only"
    local_only = strain_source == "local-only"
    remote_only = strain_source == "gwosc-only"
    if args.cat1_mode == "frozen-replay-attestation":
        cat1_active = lambda _window: True
        cat1_provenance = (
            "frozen corpus source attestation; not valid for prospective operation"
        )
    else:
        cat1_active = gwosc_cat1_provider(tasks)
        cat1_provenance = "GWOSC CBC_CAT1 whole-window containment"

    primary = PatchScorer(
        PRIMARY_INDEX,
        device=args.device,
        k=representation.top_k,
    )
    native = PatchScorer(
        NATIVE_INDEX,
        device=args.device,
        k=representation.top_k,
        model=(primary.model if args.engine == "shared_encoder_score_only" else None),
    )
    run_manifest = {
        "schema_version": 1,
        "mode": "shadow" if args.prospective else "historical_replay",
        "scientific_engine": args.engine,
        "prefilter": "none",
        "prospective": bool(args.prospective),
        "representation": representation.to_dict(),
        "epochs": epoch_payload,
        "replay_manifest_sha256": replay_header["manifest_sha256"],
        "replay_entries_file_sha256": replay_header["entries_file_sha256"],
        "roles": sorted(set(args.role)),
        "limit": args.limit,
        "limit_per_detector": args.limit_per_detector,
        "cat1_provenance": cat1_provenance,
        "local_only": local_only,
        "strain_source": strain_source,
        "data_availability_mode": (
            "prestage_before_task_submission" if args.prospective else "inline"
        ),
        "pre_registered_latency_objective_s": latency_objective,
        "executor_config": {
            "requested_device": args.device,
            "workers": args.workers,
            "batch_size": args.batch_size,
            "max_preprocess_in_flight": args.max_in_flight,
            "max_pending_writes": args.max_pending_writes,
        },
        "runtime_provenance": runtime_provenance(),
    }
    queue = ReviewQueue(args.output_dir, run_manifest)
    runner = DanteLightRunner(
        representation=representation,
        epochs=epochs,
        primary=primary,
        native=native,
        review_queue=queue,
        cat1_active=cat1_active,
        prepare=lambda task: prepare_canonical_window(
            task.window, local_only=local_only, remote_only=remote_only
        ),
        stage_data=(
            (
                lambda task: stage_canonical_strain(
                    task.window, local_only=local_only, remote_only=remote_only
                )
            )
            if args.prospective
            else None
        ),
        prospective=args.prospective,
        engine=args.engine,
        workers=args.workers,
        batch_size=args.batch_size,
        max_preprocess_in_flight=args.max_in_flight,
        max_pending_writes=args.max_pending_writes,
    )
    return runner.run(tasks)
