#!/usr/bin/env python3
"""Acquire official PEM background frames without opening comparative outcomes.

Plan is sealed before transfer. Run is restartable only across already verified
frame receipts; a failed invocation remains preserved for diagnosis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.index_contract import sha256_file  # noqa: E402
from src.dante_light.contracts import ContractError, canonical_json_sha256  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_acquisition import (  # noqa: E402
    _atomic_json,
    acquire_frame,
    required_frames,
    sealed_json,
    verify_frame,
)
from src.dante_light.o3a_o4a_common_pem_contract import (  # noqa: E402
    _host_path,
    load_contract,
)
from src.dante_light.o3a_o4a_common_pem_gate import (  # noqa: E402
    load_background_source_contract,
    parse_official_frame_manifest,
)
from src.pipeline_v2_production.pem_null_calibration import (  # noqa: E402
    _pick_background_span,
)
from scripts.preflight_dante_o3a_o4a_common_pem_background import (  # noqa: E402
    _full_exclusion,
    _load_targets,
)

EXTERNAL_ROOT = (
    "E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/background_acquisition"
)
SOURCE_FILES = (
    "scripts/run_dante_o3a_o4a_common_pem_background_acquisition.py",
    "scripts/preflight_dante_o3a_o4a_common_pem_background.py",
    "src/dante_light/o3a_o4a_common_pem_acquisition.py",
    "src/dante_light/o3a_o4a_common_pem_background.py",
    "src/dante_light/o3a_o4a_common_pem_gate.py",
)


def _seal(body: dict) -> dict:
    return {**body, "receipt_digest": canonical_json_sha256(body)}


@contextmanager
def _single_controller(run_dir: Path):
    """Refuse a second writer; a crash leaves a lock for explicit diagnosis."""
    path = run_dir / "controller.lock"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ContractError("common PEM acquisition controller already exists") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(f"{os.getpid()}\n")
        yield
    finally:
        path.unlink()


def _load_manifests(run_dir: Path, background: dict) -> dict[str, dict]:
    manifests: dict[str, dict] = {}
    for run in ("O3a", "O4a"):
        source = background["sources"][run]
        path = run_dir / f"{run}_strain_hdf_md5.txt"
        if not path.is_file() or sha256_file(path) != source["manifest_sha256"]:
            raise ContractError(f"common PEM {run} saved manifest changed")
        manifests[run] = parse_official_frame_manifest(
            path.read_bytes(),
            release=source["release"],
            frame_duration_s=int(source["frame_duration_s"]),
        )
    return manifests


def _plan(comparison: dict, background: dict, manifests: dict[str, dict]) -> dict:
    runs: dict[str, dict] = {}
    block = int(comparison["method"]["measurement"]["background_block_s"])
    minimum = int(comparison["method"]["measurement"]["minimum_clean_windows"])
    for run in ("O3a", "O4a"):
        spec = comparison["runs"][run]
        targets = _load_targets(_host_path(ROOT, spec["targets"]["path"]))
        exclusion = _full_exclusion(run)
        if (
            len(targets) != spec["targets"]["expected_count"]
            or len(exclusion) != spec["candidate_exclusion"]["expected_count"]
            or canonical_json_sha256(exclusion) != spec["candidate_exclusion"]["digest"]
        ):
            raise ContractError(f"common PEM {run} target/exclusion population changed")
        spans: list[dict] = []
        for target in targets:
            detector = str(target["detector"])
            gps = int(target["gps_start"])
            null_path = _host_path(ROOT, spec["pem_summary"]["path"]).parent / (
                f"null_calibration_{detector}_{gps}.json"
            )
            null = json.loads(null_path.read_text(encoding="utf-8"))
            if (
                null["run"] != run
                or null["detector"] != detector
                or int(null["event_gps"]) != gps
                or null["candidate_exclusion_digest"]
                != spec["candidate_exclusion"]["digest"]
                or null["candidate_exclusion_population"] != len(exclusion)
            ):
                raise ContractError(
                    f"common PEM {run} historical null identity changed"
                )
            import numpy as np

            start, end, windows = _pick_background_span(
                detector,
                float(gps),
                float(block),
                run,
                min_clean_windows=minimum,
                candidate_gps=np.asarray(exclusion, dtype=np.float64),
            )
            if (
                null["background_span"] != [start, end]
                or len(windows) != null["n_windows"]
                or len(windows) < minimum
            ):
                raise ContractError(f"common PEM {run} background span replay changed")
            spans.append(
                {"detector": detector, "gps_start": gps, "interval_gps": [start, end]}
            )
        frames = required_frames(
            spans,
            manifest=manifests[run],
            frame_duration_s=int(background["sources"][run]["frame_duration_s"]),
        )
        if (
            len(frames)
            != background["sources"][run]["required_unique_frames_preflight"]
        ):
            raise ContractError(f"common PEM {run} required frame total changed")
        runs[run] = {"spans": spans, "frames": frames}
    body = {
        "schema_version": 1,
        "status": "FROZEN_BACKGROUND_BYTES_PLAN_NO_PEM_OUTCOMES",
        "comparison_contract_digest": comparison["contract_digest"],
        "background_contract_digest": background["contract_digest"],
        "manifest_sha256": {
            run: background["sources"][run]["manifest_sha256"] for run in ("O3a", "O4a")
        },
        "source_sha256": {path: sha256_file(ROOT / path) for path in SOURCE_FILES},
        "runs": runs,
    }
    return _seal(body)


def _check_plan(plan: dict, comparison: dict, background: dict) -> None:
    if (
        plan["status"] != "FROZEN_BACKGROUND_BYTES_PLAN_NO_PEM_OUTCOMES"
        or plan["comparison_contract_digest"] != comparison["contract_digest"]
        or plan["background_contract_digest"] != background["contract_digest"]
        or plan["source_sha256"]
        != {path: sha256_file(ROOT / path) for path in SOURCE_FILES}
        or plan["manifest_sha256"]
        != {
            run: background["sources"][run]["manifest_sha256"] for run in ("O3a", "O4a")
        }
    ):
        raise ContractError("common PEM acquisition plan source or parent changed")
    for run in ("O3a", "O4a"):
        if (
            len(plan["runs"][run]["spans"])
            != comparison["runs"][run]["targets"]["expected_count"]
            or len(plan["runs"][run]["frames"])
            != background["sources"][run]["required_unique_frames_preflight"]
        ):
            raise ContractError("common PEM acquisition plan counts changed")


def _verify_existing_receipts(
    run_dir: Path, plan: dict, background: dict, manifests: dict[str, dict]
) -> int:
    count = 0
    for run in ("O3a", "O4a"):
        source = background["sources"][run]
        for frame in plan["runs"][run]["frames"]:
            path = run_dir / "receipts" / f"{frame['filename']}.json"
            if path.is_file():
                verify_frame(
                    frame, source=source, manifest=manifests[run], run_dir=run_dir
                )
                count += 1
    actual = list((run_dir / "receipts").glob("*.json"))
    if count != len(actual):
        raise ContractError("common PEM acquisition has an unplanned frame receipt")
    return count


def main(*, stage: str, external_root: Path, run_dir: Path | None = None) -> int:
    comparison = load_contract(root=ROOT)
    background = load_background_source_contract(root=ROOT)
    external_root = external_root.resolve()
    if stage == "plan":
        external_root.mkdir(parents=True, exist_ok=True)
        manifests: dict[str, dict] = {}
        manifest_bytes: dict[str, bytes] = {}
        for run in ("O3a", "O4a"):
            source = background["sources"][run]
            with urlopen(source["manifest_url"], timeout=60) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != source["manifest_sha256"]:
                raise ContractError(f"common PEM {run} public manifest changed")
            manifest_bytes[run] = data
            manifests[run] = parse_official_frame_manifest(
                data,
                release=source["release"],
                frame_duration_s=int(source["frame_duration_s"]),
            )
        plan = _plan(comparison, background, manifests)
        run_dir = external_root / f"background_acquisition_{plan['receipt_digest']}"
        plan_path = run_dir / "plan.json"
        if plan_path.exists():
            if sealed_json(plan_path) != plan:
                raise ContractError("common PEM existing acquisition plan changed")
        elif run_dir.exists() and any(run_dir.iterdir()):
            raise ContractError("common PEM acquisition directory exists without plan")
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            for run, data in manifest_bytes.items():
                (run_dir / f"{run}_strain_hdf_md5.txt").write_bytes(data)
            _atomic_json(plan_path, plan)
        print(
            json.dumps(
                {
                    "status": "PASS_BACKGROUND_BYTES_PLAN",
                    "run_dir": str(run_dir),
                    "frame_counts": {
                        run: len(plan["runs"][run]["frames"]) for run in ("O3a", "O4a")
                    },
                },
                sort_keys=True,
            )
        )
        return 0

    if run_dir is None:
        raise ContractError(
            "common PEM acquisition requires an explicit frozen run directory"
        )
    run_dir = run_dir.resolve()
    if not run_dir.is_relative_to(external_root) or run_dir.parent != external_root:
        raise ContractError(
            "common PEM acquisition run directory escaped external root"
        )
    plan = sealed_json(run_dir / "plan.json")
    if run_dir.name != f"background_acquisition_{plan['receipt_digest']}":
        raise ContractError("common PEM acquisition run key changed")
    _check_plan(plan, comparison, background)
    manifests = _load_manifests(run_dir, background)
    if _plan(comparison, background, manifests) != plan:
        raise ContractError("common PEM acquisition independent span plan changed")
    if stage == "archive-infrastructure-failure":
        if (run_dir / "controller.lock").exists():
            raise ContractError(
                "common PEM acquisition controller remains active or stale"
            )
        failure_path = run_dir / "failure.json"
        failure = sealed_json(failure_path)
        if (
            failure["status"] != "FAILED_INFRASTRUCTURE"
            or failure["plan_digest"] != plan["receipt_digest"]
            or (run_dir / "summary.json").exists()
        ):
            raise ContractError("common PEM acquisition failure is not resumable")
        _verify_existing_receipts(run_dir, plan, background, manifests)
        history = run_dir / "failure_history"
        history.mkdir(exist_ok=True)
        archived = history / f"failure_{failure['receipt_digest']}.json"
        if archived.exists():
            raise ContractError("common PEM acquisition failure archive exists")
        failure_path.replace(archived)
        print(
            json.dumps(
                {
                    "status": "PASS_INFRASTRUCTURE_FAILURE_ARCHIVED",
                    "run_dir": str(run_dir),
                },
                sort_keys=True,
            )
        )
        return 0
    if stage == "run":
        if (run_dir / "failure.json").exists():
            raise ContractError("common PEM acquisition has an unresolved failure")
        if (run_dir / "summary.json").exists():
            raise ContractError("common PEM acquisition already has a summary")
        with _single_controller(run_dir):
            try:
                completed = _acquire_all(run_dir, plan, background, manifests)
                if completed != sum(
                    len(plan["runs"][name]["frames"]) for name in ("O3a", "O4a")
                ):
                    raise ContractError(
                        "common PEM acquisition completion count changed"
                    )
                _atomic_json(
                    run_dir / "summary.json",
                    _seal(
                        {
                            "status": "PASS_ACQUIRED_BACKGROUND_FRAME_BYTES_ONLY",
                            "plan_digest": plan["receipt_digest"],
                            "frame_counts": {
                                run: len(plan["runs"][run]["frames"])
                                for run in ("O3a", "O4a")
                            },
                            "paired_outcomes_opened": False,
                        }
                    ),
                )
            except Exception as exc:
                infrastructure = isinstance(exc, (HTTPError, URLError, TimeoutError))
                _atomic_json(
                    run_dir / "failure.json",
                    _seal(
                        {
                            "status": "FAILED_INFRASTRUCTURE"
                            if infrastructure
                            else "FAILED_STRUCTURAL",
                            "plan_digest": plan["receipt_digest"],
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    ),
                )
                raise
        print(
            json.dumps(
                {
                    "status": "PASS_ACQUIRED_BACKGROUND_FRAME_BYTES_ONLY",
                    "run_dir": str(run_dir),
                },
                sort_keys=True,
            )
        )
        return 0
    if stage == "verify":
        if (run_dir / "controller.lock").exists():
            raise ContractError(
                "common PEM acquisition controller remains active or stale"
            )
        if (run_dir / "failure.json").exists():
            raise ContractError("common PEM acquisition has an unresolved failure")
        summary = sealed_json(run_dir / "summary.json")
        if summary != _seal(
            {
                "status": "PASS_ACQUIRED_BACKGROUND_FRAME_BYTES_ONLY",
                "plan_digest": plan["receipt_digest"],
                "frame_counts": {
                    run: len(plan["runs"][run]["frames"]) for run in ("O3a", "O4a")
                },
                "paired_outcomes_opened": False,
            }
        ):
            raise ContractError("common PEM acquisition summary changed")
        if _verify_existing_receipts(run_dir, plan, background, manifests) != sum(
            len(plan["runs"][name]["frames"]) for name in ("O3a", "O4a")
        ):
            raise ContractError("common PEM acquisition frame set is incomplete")
        if list((run_dir / "frames").glob("*.partial")):
            raise ContractError("common PEM acquisition has incomplete frame transfers")
        print(
            json.dumps(
                {
                    "status": "PASS_VERIFIED_BACKGROUND_FRAME_BYTES_ONLY",
                    "run_dir": str(run_dir),
                },
                sort_keys=True,
            )
        )
        return 0
    raise ValueError(f"unsupported acquisition stage: {stage}")


def _acquire_all(run_dir: Path, plan: dict, background: dict, manifests: dict) -> int:
    completed = 0
    for run in ("O3a", "O4a"):
        source = background["sources"][run]
        for frame in plan["runs"][run]["frames"]:
            acquire_frame(
                frame, source=source, manifest=manifests[run], run_dir=run_dir
            )
            completed += 1
            _atomic_json(
                run_dir / "progress.json",
                _seal(
                    {
                        "status": "ACQUIRING_BACKGROUND_FRAME_BYTES_ONLY",
                        "completed_frames": completed,
                        "expected_frames": sum(
                            len(plan["runs"][name]["frames"]) for name in ("O3a", "O4a")
                        ),
                    }
                ),
            )
    return completed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("plan", "run", "verify", "archive-infrastructure-failure"),
        required=True,
    )
    parser.add_argument("--external-root", default=EXTERNAL_ROOT)
    parser.add_argument("--run-dir")
    arguments = parser.parse_args()
    raise SystemExit(
        main(
            stage=arguments.stage,
            external_root=_host_path(ROOT, arguments.external_root),
            run_dir=_host_path(ROOT, arguments.run_dir) if arguments.run_dir else None,
        )
    )
