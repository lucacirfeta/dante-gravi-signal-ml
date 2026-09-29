"""Fail-closed, separate-run execution of the frozen common-channel PEM test.

The measurement and null remain in their historical core. This module binds
verified inputs, saves one immutable event receipt at a time, and verifies
completed outputs without selecting or tuning scientific parameters.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_pem import (
    _event_strain as o3a_event_strain,
    load_contract as load_o3a_contract,
    preflight_inputs as preflight_o3a_inputs,
)
from src.dante_light.o3a_o4a_common_pem_acquisition import sealed_json
from src.dante_light.o3a_o4a_common_pem_aux_reader import verify_target_bindings
from src.dante_light.o3a_o4a_common_pem_contract import (
    _host_path,
    load_contract as load_common_contract,
    select_o4a_inputs,
)
from src.dante_light.o3a_o4a_common_pem_contract_v2 import (
    load_contract as load_common_v2_contract,
)
from src.dante_light.o3a_o4a_common_pem_gate import verify_o3a_cat1_equivalence
from src.dante_light.o3a_o4a_common_pem_measurement import measure_event
from src.dante_light.o3a_o4a_common_pem_strain import (
    o4a_event_strain,
    verified_o4a_frames,
)
from src.dante_light.o4a_corrected_native_pem import (
    load_native_pem_contract as load_o4a_contract,
)
from src.pipeline_v2_production.pem_null_calibration import tier_verdict

ROOT = Path(__file__).resolve().parents[2]
CONFIG_REL = Path("config/dante_o3a_o4a_common_pem_execution_v1.json")
SOURCE_FILES = (
    str(CONFIG_REL),
    "src/dante_light/o3a_o4a_common_pem_execution.py",
    "src/dante_light/o3a_o4a_common_pem_measurement.py",
    "src/dante_light/o3a_o4a_common_pem_span_reader.py",
    "src/dante_light/o3a_o4a_common_pem_aux_reader.py",
    "src/dante_light/o3a_o4a_common_pem_strain.py",
    "scripts/run_dante_o3a_o4a_common_pem_execution.py",
)
PLAN_STATUS = "FROZEN_COMMON_PEM_EXECUTION_PLAN_NO_OUTCOMES"
COMPLETE_STATUS = "PASS_COMPLETE_COMMON_PEM_DIAGNOSTIC_V1"
VERIFIED_STATUS = "PASS_VERIFIED_COMMON_PEM_DIAGNOSTIC_V1"


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    if temporary.exists() or path.exists():
        raise ContractError(f"common PEM output already exists: {path}")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _seal(body: Mapping[str, Any]) -> dict[str, Any]:
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def _config(root: Path) -> dict[str, Any]:
    value = json.loads((root / CONFIG_REL).read_text(encoding="utf-8"))
    common = load_common_contract(root=root)
    v2 = load_common_v2_contract(root=root)
    if (
        value.get("schema_version") != 1
        or value.get("contract_id") != "dante-o3a-o4a-common-pem-execution-v1"
        or value.get("status") != "FROZEN_PAIRED_DIAGNOSTIC_EXECUTION_NO_OUTCOMES"
        or value.get("common_contract_digest") != common["contract_digest"]
        or value.get("common_v2_contract_digest") != v2["contract_digest"]
        or value.get("run_policy")
        != {
            "separate_run_keys": True,
            "verified_receipt_resume_only": True,
            "failure_requires_manual_diagnosis": True,
            "source_freeze_before_outcomes": True,
            "primary_and_diagnostic_separate": True,
            "global_significance_claim": False,
            "astrophysical_confirmation_claim": False,
        }
    ):
        raise ContractError("common PEM execution contract changed")
    return value


def _paths(root: Path, config: Mapping[str, Any]) -> dict[str, Path]:
    paths = {
        key: _host_path(root, value) for key, value in config["input_roots"].items()
    }
    if set(paths) != {
        "o4a_raw_replay",
        "background_acquisition",
        "background_spans",
        "auxiliary_samples",
        "auxiliary_availability",
    } or any(not path.is_dir() for path in paths.values()):
        raise ContractError("common PEM verified input roots changed")
    paths["output"] = _host_path(root, config["output_root"])
    if paths["output"].name != "comparative_pem":
        raise ContractError("common PEM output root changed")
    return paths


def _inputs(root: Path, common: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    o3a_spec = common["runs"]["O3a"]
    o3a_summary = _host_path(root, o3a_spec["pem_summary"]["path"])
    _, o3a_targets, o3a_exclusion = preflight_o3a_inputs(
        root=root, external_root=o3a_summary.parent.parent
    )
    o4a_contract = load_o4a_contract(root)
    references = o4a_contract["references"]
    coincidence = json.loads(
        (root / references["native_coincidence"]["path"]).read_text()
    )
    classification = json.loads(
        (root / references["native_classification"]["path"]).read_text()
    )
    coincidence_root = _host_path(root, coincidence["external_run"]["directory"]).parent
    classification_root = _host_path(
        root, classification["external_run"]["directory"]
    ).parent
    o4a_targets, o4a_exclusion, _ = select_o4a_inputs(
        root=root,
        contract=o4a_contract,
        coincidence_external_root=coincidence_root,
        classification_external_root=classification_root,
    )
    result = {
        "O3a": {"targets": o3a_targets, "exclusion": o3a_exclusion},
        "O4a": {"targets": o4a_targets, "exclusion": o4a_exclusion},
    }
    for run, content in result.items():
        spec = common["runs"][run]
        targets, exclusion = content["targets"], content["exclusion"]
        if (
            len(targets) != spec["targets"]["expected_count"]
            or canonical_json_sha256(targets)
            != canonical_json_sha256(
                [
                    json.loads(line)
                    for line in _host_path(root, spec["targets"]["path"])
                    .read_text()
                    .splitlines()
                    if line
                ]
            )
            or len(exclusion) != spec["candidate_exclusion"]["expected_count"]
            or canonical_json_sha256(exclusion) != spec["candidate_exclusion"]["digest"]
            or not np.isfinite(exclusion).all()
        ):
            raise ContractError(f"common PEM {run} target/exclusion identity changed")
    return result


def _parent_receipts(paths: Mapping[str, Path]) -> dict[str, str]:
    names = {
        "background_acquisition": "PASS_ACQUIRED_BACKGROUND_FRAME_BYTES_V2_ONLY",
        "background_spans": "PASS_BACKGROUND_SPAN_REPLAY_COMPLETE_ONLY",
        "auxiliary_samples": "PASS_AUX_NATIVE_SAMPLES_COMPLETE_ONLY",
        "auxiliary_availability": "PASS_AUX_METADATA_COVERAGE_COMPLETE_ONLY",
    }
    found: dict[str, str] = {}
    for label, status in names.items():
        directory = paths[label]
        if any(
            (directory / name).exists() for name in ("failure.json", "controller.lock")
        ):
            raise ContractError(f"common PEM {label} source failed or active")
        summary = sealed_json(directory / "summary.json")
        if summary.get("status") != status:
            raise ContractError(f"common PEM {label} summary changed")
        found[label] = summary["receipt_digest"]
    return found


def build_plan(*, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recheck frozen parents and CAT1 before any comparative outcome access."""
    root = root.resolve()
    config = _config(root)
    paths = _paths(root, config)
    common = load_common_contract(root=root)
    inputs = _inputs(root, common)
    cat1 = verify_o3a_cat1_equivalence(root=root)
    parents = _parent_receipts(paths)
    bound = verify_target_bindings(
        auxiliary_run_dir=paths["auxiliary_samples"],
        availability_run_dir=paths["auxiliary_availability"],
    )
    if bound != sum(len(data["targets"]) for data in inputs.values()):
        raise ContractError("common PEM auxiliary target accounting changed")
    raw_contract, frames = verified_o4a_frames(paths["o4a_raw_replay"], root=root)
    raw_summary_path = paths["o4a_raw_replay"] / "summary.json"
    if (
        raw_contract["historical_targets"]["sha256"]
        != common["runs"]["O4a"]["targets"]["sha256"]
    ):
        raise ContractError("common PEM O4a raw target source changed")
    span_plan = sealed_json(paths["background_spans"] / "plan.json")
    for run, content in inputs.items():
        expected = {
            (row["detector"], row["gps_start"]) for row in span_plan["spans"][run]
        }
        observed = {(row["detector"], row["gps_start"]) for row in content["targets"]}
        if expected != observed or len(expected) != len(content["targets"]):
            raise ContractError(f"common PEM {run} background target set changed")
    source_sha = {path: sha256_file(root / path) for path in SOURCE_FILES}
    for relative in SOURCE_FILES:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=root,
            capture_output=True,
            check=False,
        )
        changed = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if tracked.returncode != 0 or changed.returncode != 0:
            raise ContractError(f"common PEM source is not frozen in Git: {relative}")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    body = {
        "status": PLAN_STATUS,
        "config_digest": canonical_json_sha256(config),
        "common_contract_digest": common["contract_digest"],
        "source_sha256": source_sha,
        "source_revision": revision,
        "parent_summary_digests": parents,
        "o4a_raw_replay_summary_sha256": sha256_file(raw_summary_path),
        "o4a_verified_frame_count": len(frames),
        "cat1_report": cat1,
        "targets": {
            run: {
                "count": len(content["targets"]),
                "digest": canonical_json_sha256(content["targets"]),
                "exclusion_count": len(content["exclusion"]),
                "exclusion_digest": canonical_json_sha256(content["exclusion"]),
            }
            for run, content in inputs.items()
        },
        "background_spans": span_plan["spans"],
        "diagnostic_only": True,
    }
    return _seal(body), {
        "config": config,
        "paths": paths,
        "common": common,
        "inputs": inputs,
        "raw_contract": raw_contract,
        "frames": frames,
    }


def _plan_path(paths: Mapping[str, Path], plan: Mapping[str, Any]) -> Path:
    return paths["output"] / f"plan_{plan['receipt_digest']}.json"


def freeze_plan(*, root: Path = ROOT) -> tuple[dict[str, Any], Path]:
    plan, context = build_plan(root=root)
    path = _plan_path(context["paths"], plan)
    if path.is_file():
        if sealed_json(path) != plan:
            raise ContractError("common PEM execution plan changed")
    else:
        _atomic_json(path, plan)
    return plan, path


def _event_dir(run_dir: Path, target: Mapping[str, Any]) -> Path:
    if target["population"] not in ("primary", "diagnostic"):
        raise ContractError("common PEM target population changed")
    return (
        run_dir
        / "events"
        / (f"{target['population']}_{target['detector']}_{int(target['gps_start'])}")
    )


def _check_event(
    path: Path,
    *,
    target: Mapping[str, Any],
    run: str,
    plan: Mapping[str, Any],
    common: Mapping[str, Any],
) -> dict[str, Any]:
    receipt = sealed_json(path)
    event = receipt.get("event")
    if not isinstance(event, dict):
        raise ContractError("common PEM event receipt invalid")
    channels = common["method"]["channels"][target["detector"]]
    expected_null_name = (
        f"null_calibration_{target['detector']}_{int(target['gps_start'])}.json"
    )
    if event["calibration"]["filename"] != expected_null_name:
        raise ContractError("common PEM null path changed")
    null_path = path.parent / expected_null_name
    calibration = json.loads(null_path.read_text(encoding="utf-8"))
    rows = event["channels"]
    top = max(rows, key=lambda row: row["max_coherence"])
    cmax = float(top["max_coherence"])
    threshold = float(calibration["threshold_fw"])
    zero = float(calibration["zero_lag_control"]["q99"])
    matching_spans = [
        row
        for row in plan["background_spans"][run]
        if row["detector"] == target["detector"]
        and row["gps_start"] == target["gps_start"]
    ]
    if (
        receipt.get("status") != "PASS_COMMON_PEM_EVENT_ONLY"
        or receipt.get("plan_digest") != plan["receipt_digest"]
        or event.get("target") != dict(target)
        or event.get("run") != run
        or event.get("candidate_exclusion_digest")
        != common["runs"][run]["candidate_exclusion"]["digest"]
        or [row["aux_channel"] for row in rows] != channels
        or any(row["data_available"] is not True for row in rows)
        or event["calibration"]["sha256"] != sha256_file(null_path)
        or calibration["channels"] != channels
        or calibration["m_channels"] != len(channels)
        or calibration["candidate_exclusion_digest"]
        != common["runs"][run]["candidate_exclusion"]["digest"]
        or calibration["candidate_exclusion_population"]
        != common["runs"][run]["candidate_exclusion"]["expected_count"]
        or float(calibration["alpha_family_wise"])
        != float(common["method"]["measurement"]["alpha_family_wise"])
        or calibration["n_windows"]
        < common["method"]["measurement"]["minimum_clean_windows"]
        or len(matching_spans) != 1
        or calibration["background_span"] != matching_spans[0]["interval_gps"]
        or event["top_channel"] != top["aux_channel"]
        or float(event["cmax_observed"]) != cmax
        or float(event["threshold_time_shift_q99"]) != threshold
        or float(event["threshold_zero_lag_q99"]) != zero
        or event["verdict_time_shift"]
        != ("COUPLED" if cmax > threshold else "NO_CORRELATION")
        or event["verdict_tier"] != tier_verdict(cmax, threshold, zero)
        or event["scientific_interpretation"]
        != "PEM_DIAGNOSTIC_ONLY_NOT_ASTROPHYSICAL_CONFIRMATION"
        or any(path.parent.joinpath(name).exists() for name in ("failure.json",))
        or any(path.is_file() for path in (path.parent / "transient_raw").rglob("*"))
        or any(path.is_file() for path in (path.parent / "event_aux_cache").rglob("*"))
        or any(
            path.is_file() for path in (path.parent / "background_aux_cache").rglob("*")
        )
    ):
        raise ContractError("common PEM event receipt or null changed")
    return event


def _purge_transient(event_dir: Path, target: Mapping[str, Any], *, run: str) -> None:
    if run == "O3a":
        source_root = event_dir / "transient_raw" / target["detector"]
        expected = {
            str(row["filename"]): row["sha256"] for row in target["context_sources"]
        }
        observed = {path.name for path in source_root.glob("*") if path.is_file()}
        if observed != set(expected):
            raise ContractError("common PEM O3a transient source set changed")
        for filename, digest in expected.items():
            path = source_root / filename
            if (
                path.parent.resolve() != source_root.resolve()
                or sha256_file(path) != digest
            ):
                raise ContractError("common PEM O3a transient source changed")
            path.unlink()
    cache = event_dir / "event_aux_cache"
    for path in cache.glob("*"):
        if not path.is_file() or path.parent.resolve() != cache.resolve():
            raise ContractError("common PEM auxiliary transient path changed")
        path.unlink()


def _run_key(plan: Mapping[str, Any], run: str) -> str:
    return canonical_json_sha256({"plan_digest": plan["receipt_digest"], "run": run})


def run_one(*, run: str, root: Path = ROOT) -> tuple[dict[str, Any], Path]:
    if run not in ("O3a", "O4a"):
        raise ContractError("common PEM run must be O3a or O4a")
    root = root.resolve()
    plan, context = build_plan(root=root)
    if sealed_json(_plan_path(context["paths"], plan)) != plan:
        raise ContractError("common PEM execution plan was not frozen")
    common, inputs, paths = context["common"], context["inputs"], context["paths"]
    run_dir = paths["output"] / f"common_pem_{run}_{_run_key(plan, run)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "failure.json").exists():
        raise ContractError("common PEM failed run requires manual diagnosis")
    if (run_dir / "summary.json").exists():
        return verify_one(run=run, root=root)
    lock = run_dir / "controller.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ContractError("common PEM controller is already active or stale") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        if run == "O3a":
            o3a_contract = load_o3a_contract(root=root)
        else:
            o3a_contract = None
        for target in inputs[run]["targets"]:
            if plan["source_sha256"] != {
                path: sha256_file(root / path) for path in SOURCE_FILES
            }:
                raise ContractError("common PEM source changed during execution")
            event_dir = _event_dir(run_dir, target)
            event_path = event_dir / "event.json"
            if event_path.is_file():
                _check_event(
                    event_path, target=target, run=run, plan=plan, common=common
                )
                continue
            if event_dir.exists() and any(event_dir.iterdir()):
                raise ContractError(
                    "common PEM incomplete event requires manual diagnosis"
                )
            event_dir.mkdir(parents=True, exist_ok=True)
            if run == "O3a":

                def strain_reader() -> tuple[Any, str]:
                    return o3a_event_strain(
                        target, run_dir=event_dir, contract=o3a_contract
                    )
            else:

                def strain_reader() -> tuple[Any, str]:
                    return o4a_event_strain(
                        target,
                        frames=context["frames"],
                        source=context["raw_contract"]["source"],
                        measurement=common["method"]["measurement"],
                    )

            native_execution = (
                o3a_contract if run == "O3a" else load_o4a_contract(root)
            )["execution"]
            execution = {
                **native_execution,
                **context["config"]["execution_transport"][run],
            }
            event = measure_event(
                target,
                run=run,
                comparison=common,
                execution=execution,
                run_dir=event_dir,
                auxiliary_run_dir=paths["auxiliary_samples"],
                background_span_run_dir=paths["background_spans"],
                background_acquisition_run_dir=paths["background_acquisition"],
                candidate_exclusion_gps=inputs[run]["exclusion"],
                strain_reader=strain_reader,
            )
            _purge_transient(event_dir, target, run=run)
            _atomic_json(
                event_path,
                _seal(
                    {
                        "status": "PASS_COMMON_PEM_EVENT_ONLY",
                        "plan_digest": plan["receipt_digest"],
                        "event": event,
                    }
                ),
            )
            _check_event(event_path, target=target, run=run, plan=plan, common=common)
        events = [
            _check_event(
                _event_dir(run_dir, target) / "event.json",
                target=target,
                run=run,
                plan=plan,
                common=common,
            )
            for target in inputs[run]["targets"]
        ]
        body = {
            "status": COMPLETE_STATUS,
            "run": run,
            "run_key": _run_key(plan, run),
            "plan_digest": plan["receipt_digest"],
            "target_count": len(events),
            "event_receipt_digests": [
                sealed_json(_event_dir(run_dir, target) / "event.json")[
                    "receipt_digest"
                ]
                for target in inputs[run]["targets"]
            ],
            "population_counts": {
                bucket: dict(
                    Counter(
                        event["target"]["detector"]
                        for event in events
                        if event["target"]["population"] == bucket
                    )
                )
                for bucket in ("primary", "diagnostic")
            },
            "diagnostic_only": True,
        }
        summary = _seal(body)
        _atomic_json(run_dir / "summary.json", summary)
        return summary, run_dir
    except Exception as exc:
        if not (run_dir / "summary.json").exists():
            _atomic_json(
                run_dir / "failure.json",
                _seal(
                    {
                        "status": "FAILED_REQUIRES_REVIEW",
                        "type": type(exc).__name__,
                        "detail": str(exc),
                    }
                ),
            )
        raise
    finally:
        lock.unlink()


def verify_one(*, run: str, root: Path = ROOT) -> tuple[dict[str, Any], Path]:
    if run not in ("O3a", "O4a"):
        raise ContractError("common PEM run must be O3a or O4a")
    root = root.resolve()
    plan, context = build_plan(root=root)
    paths, inputs, common = context["paths"], context["inputs"], context["common"]
    if sealed_json(_plan_path(paths, plan)) != plan:
        raise ContractError("common PEM execution plan changed")
    run_dir = paths["output"] / f"common_pem_{run}_{_run_key(plan, run)}"
    if any((run_dir / name).exists() for name in ("failure.json", "controller.lock")):
        raise ContractError("common PEM run failed or still active")
    summary = sealed_json(run_dir / "summary.json")
    targets = inputs[run]["targets"]
    expected_paths = {_event_dir(run_dir, target) / "event.json" for target in targets}
    observed_paths = set((run_dir / "events").glob("*/event.json"))
    if expected_paths != observed_paths or list(run_dir.rglob("*.partial")):
        raise ContractError("common PEM event receipt set incomplete")
    events = [
        _check_event(
            _event_dir(run_dir, target) / "event.json",
            target=target,
            run=run,
            plan=plan,
            common=common,
        )
        for target in targets
    ]
    if (
        summary.get("status") != COMPLETE_STATUS
        or summary.get("run") != run
        or summary.get("run_key") != _run_key(plan, run)
        or summary.get("plan_digest") != plan["receipt_digest"]
        or summary.get("target_count") != len(targets)
        or summary.get("event_receipt_digests")
        != [
            sealed_json(_event_dir(run_dir, target) / "event.json")["receipt_digest"]
            for target in targets
        ]
        or summary.get("diagnostic_only") is not True
        or len(events) != len(targets)
        or summary.get("population_counts")
        != {
            bucket: dict(
                Counter(
                    event["target"]["detector"]
                    for event in events
                    if event["target"]["population"] == bucket
                )
            )
            for bucket in ("primary", "diagnostic")
        }
    ):
        raise ContractError("common PEM completed summary changed")
    return _seal(
        {
            "status": VERIFIED_STATUS,
            "run": run,
            "run_key": summary["run_key"],
            "summary_digest": summary["receipt_digest"],
            "target_count": len(targets),
            "diagnostic_only": True,
        }
    ), run_dir
