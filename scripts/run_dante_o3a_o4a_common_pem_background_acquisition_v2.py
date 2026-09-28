#!/usr/bin/env python3
"""Acquire common-PEM background frames with a span-bound probe (v2).

The v1 failed run is immutable. This distinct plan/run key checks official
frame bytes and one deterministic second inside a planned background span;
it does not calculate complete spans, PEM nulls, or comparative verdicts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dante_o3a_o4a_common_pem_background_acquisition as legacy  # noqa: E402
from src.core.index_contract import sha256_file  # noqa: E402
from src.dante_light.contracts import ContractError, canonical_json_sha256  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_acquisition import (  # noqa: E402
    _atomic_json,
    sealed_json,
)
from src.dante_light.o3a_o4a_common_pem_acquisition_v2 import (  # noqa: E402
    acquire_frame_v2,
    required_frames_with_probes,
    verify_frame_v2,
)
from src.dante_light.o3a_o4a_common_pem_contract import (  # noqa: E402
    _host_path,
    load_contract,
)
from src.dante_light.o3a_o4a_common_pem_gate import (  # noqa: E402
    load_background_source_contract,
    parse_official_frame_manifest,
)

EXTERNAL_ROOT = legacy.EXTERNAL_ROOT
CONFIG_PATH = "config/dante_o3a_o4a_common_pem_background_acquisition_v2.json"
SOURCE_FILES = (
    *legacy.SOURCE_FILES,
    CONFIG_PATH,
    "src/dante_light/o3a_o4a_common_pem_acquisition_v2.py",
    "scripts/run_dante_o3a_o4a_common_pem_background_acquisition_v2.py",
)


def _seal(body: dict) -> dict:
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def _load_v2_contract(background: dict) -> dict:
    contract = json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
    if (
        contract.get("schema_version") != 2
        or contract.get("contract_id")
        != "dante-o3a-o4a-common-pem-background-acquisition-v2"
        or contract.get("parent_background_contract_digest")
        != background["contract_digest"]
        or contract.get("superseded_failed_run_key")
        != "5308cec1e4d935cdd5b7c93b4df60369e9814fc2a63fe0741c8208abb40edb9e"
        or contract.get("probe_policy")
        != "FIRST_ONE_SECOND_OF_EARLIEST_PLANNED_SPAN_OVERLAP_PER_OFFICIAL_FRAME"
        or contract.get("probe_duration_s") != 1
        or contract.get("scientific_boundary")
        != {
            "transport_only": True,
            "full_background_span_verified": False,
            "auxiliary_channels_verified": False,
            "paired_pem_outcomes_opened": False,
            "global_significance_claim": False,
        }
        or contract["expected_unique_frames"]
        != {
            run: background["sources"][run]["required_unique_frames_preflight"]
            for run in ("O3a", "O4a")
        }
    ):
        raise ContractError("common PEM v2 acquisition contract changed")
    return contract


def _plan(comparison: dict, background: dict, manifests: dict[str, dict]) -> dict:
    contract = _load_v2_contract(background)
    parent = legacy._plan(comparison, background, manifests)
    runs = {
        run: {
            "spans": parent["runs"][run]["spans"],
            "frames": required_frames_with_probes(
                parent["runs"][run]["spans"],
                manifest=manifests[run],
                frame_duration_s=int(background["sources"][run]["frame_duration_s"]),
            ),
        }
        for run in ("O3a", "O4a")
    }
    for run in ("O3a", "O4a"):
        if len(runs[run]["frames"]) != contract["expected_unique_frames"][run]:
            raise ContractError("common PEM v2 frame count changed")
    return _seal(
        {
            "schema_version": 2,
            "status": "FROZEN_BACKGROUND_BYTES_V2_PLAN_NO_PEM_OUTCOMES",
            "comparison_contract_digest": comparison["contract_digest"],
            "background_contract_digest": background["contract_digest"],
            "v2_contract_digest": canonical_json_sha256(contract),
            "parent_plan_digest": parent["receipt_digest"],
            "manifest_sha256": {
                run: background["sources"][run]["manifest_sha256"]
                for run in ("O3a", "O4a")
            },
            "source_sha256": {path: sha256_file(ROOT / path) for path in SOURCE_FILES},
            "probe_policy": contract["probe_policy"],
            "runs": runs,
        }
    )


def _saved_manifests(run_dir: Path, background: dict) -> dict[str, dict]:
    return legacy._load_manifests(run_dir, background)


def _verify_existing_receipts(
    run_dir: Path, plan: dict, background: dict, manifests: dict[str, dict]
) -> int:
    count = 0
    for run in ("O3a", "O4a"):
        source = background["sources"][run]
        for frame in plan["runs"][run]["frames"]:
            path = run_dir / "receipts" / f"{frame['filename']}.json"
            if path.is_file():
                verify_frame_v2(
                    frame, source=source, manifest=manifests[run], run_dir=run_dir
                )
                count += 1
    if count != len(list((run_dir / "receipts").glob("*.json"))):
        raise ContractError("common PEM v2 acquisition has an unplanned receipt")
    return count


def _expected_count(plan: dict) -> int:
    return sum(len(plan["runs"][run]["frames"]) for run in ("O3a", "O4a"))


def _acquire_all(
    run_dir: Path, plan: dict, background: dict, manifests: dict[str, dict]
) -> int:
    completed = 0
    for run in ("O3a", "O4a"):
        source = background["sources"][run]
        for frame in plan["runs"][run]["frames"]:
            acquire_frame_v2(
                frame, source=source, manifest=manifests[run], run_dir=run_dir
            )
            completed += 1
            _atomic_json(
                run_dir / "progress.json",
                _seal(
                    {
                        "status": "ACQUIRING_BACKGROUND_FRAME_BYTES_V2_ONLY",
                        "completed_frames": completed,
                        "expected_frames": _expected_count(plan),
                    }
                ),
            )
    return completed


def main(*, stage: str, external_root: Path, run_dir: Path | None = None) -> int:
    comparison = load_contract(root=ROOT)
    background = load_background_source_contract(root=ROOT)
    _load_v2_contract(background)
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
                raise ContractError(f"common PEM v2 {run} public manifest changed")
            manifest_bytes[run] = data
            manifests[run] = parse_official_frame_manifest(
                data,
                release=source["release"],
                frame_duration_s=int(source["frame_duration_s"]),
            )
        plan = _plan(comparison, background, manifests)
        run_dir = external_root / f"background_acquisition_v2_{plan['receipt_digest']}"
        plan_path = run_dir / "plan.json"
        if plan_path.exists():
            if sealed_json(plan_path) != plan:
                raise ContractError("common PEM v2 existing plan changed")
        elif run_dir.exists() and any(run_dir.iterdir()):
            raise ContractError("common PEM v2 directory exists without plan")
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            for run, data in manifest_bytes.items():
                (run_dir / f"{run}_strain_hdf_md5.txt").write_bytes(data)
            _atomic_json(plan_path, plan)
        print(
            json.dumps(
                {
                    "status": "PASS_BACKGROUND_BYTES_V2_PLAN",
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
        raise ContractError("common PEM v2 requires an explicit run directory")
    run_dir = run_dir.resolve()
    if not run_dir.is_relative_to(external_root) or run_dir.parent != external_root:
        raise ContractError("common PEM v2 run directory escaped external root")
    plan = sealed_json(run_dir / "plan.json")
    if run_dir.name != f"background_acquisition_v2_{plan['receipt_digest']}":
        raise ContractError("common PEM v2 acquisition run key changed")
    manifests = _saved_manifests(run_dir, background)
    if _plan(comparison, background, manifests) != plan:
        raise ContractError("common PEM v2 acquisition independent plan changed")

    if stage == "archive-infrastructure-failure":
        if (run_dir / "controller.lock").exists():
            raise ContractError("common PEM v2 controller remains active or stale")
        failure_path = run_dir / "failure.json"
        failure = sealed_json(failure_path)
        if (
            failure.get("status") != "FAILED_INFRASTRUCTURE"
            or failure.get("plan_digest") != plan["receipt_digest"]
            or (run_dir / "summary.json").exists()
        ):
            raise ContractError("common PEM v2 failure is not resumable")
        _verify_existing_receipts(run_dir, plan, background, manifests)
        history = run_dir / "failure_history"
        history.mkdir(exist_ok=True)
        archived = history / f"failure_{failure['receipt_digest']}.json"
        if archived.exists():
            raise ContractError("common PEM v2 failure archive already exists")
        failure_path.replace(archived)
        print(
            json.dumps(
                {
                    "status": "PASS_INFRASTRUCTURE_FAILURE_ARCHIVED_V2",
                    "run_dir": str(run_dir),
                },
                sort_keys=True,
            )
        )
        return 0

    if stage == "run":
        if (run_dir / "failure.json").exists() or (run_dir / "summary.json").exists():
            raise ContractError("common PEM v2 has a failure or completed summary")
        with legacy._single_controller(run_dir):
            try:
                completed = _acquire_all(run_dir, plan, background, manifests)
                if completed != _expected_count(plan):
                    raise ContractError("common PEM v2 completion count changed")
                _atomic_json(
                    run_dir / "summary.json",
                    _seal(
                        {
                            "status": "PASS_ACQUIRED_BACKGROUND_FRAME_BYTES_V2_ONLY",
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
                    "status": "PASS_ACQUIRED_BACKGROUND_FRAME_BYTES_V2_ONLY",
                    "run_dir": str(run_dir),
                },
                sort_keys=True,
            )
        )
        return 0

    if stage == "verify":
        if (run_dir / "controller.lock").exists():
            raise ContractError("common PEM v2 controller remains active or stale")
        if (run_dir / "failure.json").exists():
            raise ContractError("common PEM v2 has an unresolved failure")
        summary = sealed_json(run_dir / "summary.json")
        expected = _seal(
            {
                "status": "PASS_ACQUIRED_BACKGROUND_FRAME_BYTES_V2_ONLY",
                "plan_digest": plan["receipt_digest"],
                "frame_counts": {
                    run: len(plan["runs"][run]["frames"]) for run in ("O3a", "O4a")
                },
                "paired_outcomes_opened": False,
            }
        )
        if summary != expected:
            raise ContractError("common PEM v2 summary changed")
        if _verify_existing_receipts(
            run_dir, plan, background, manifests
        ) != _expected_count(plan):
            raise ContractError("common PEM v2 frame set incomplete")
        if list((run_dir / "frames").glob("*.partial")):
            raise ContractError("common PEM v2 has incomplete frame transfers")
        print(
            json.dumps(
                {
                    "status": "PASS_VERIFIED_BACKGROUND_FRAME_BYTES_V2_ONLY",
                    "run_dir": str(run_dir),
                },
                sort_keys=True,
            )
        )
        return 0
    raise ValueError(f"unsupported common PEM v2 stage: {stage}")


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
