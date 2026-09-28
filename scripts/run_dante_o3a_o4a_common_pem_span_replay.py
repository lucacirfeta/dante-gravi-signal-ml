#!/usr/bin/env python3
"""Replay frozen common-PEM background spans from verified frame bytes only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dante_o3a_o4a_common_pem_background_acquisition as legacy  # noqa: E402
from scripts import run_dante_o3a_o4a_common_pem_background_acquisition_v2 as parent  # noqa: E402
from src.core.index_contract import sha256_file  # noqa: E402
from src.dante_light.contracts import ContractError, canonical_json_sha256  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_acquisition import (  # noqa: E402
    _atomic_json,
    sealed_json,
)
from src.dante_light.o3a_o4a_common_pem_background import (  # noqa: E402
    verify_background_receipt,
)
from src.dante_light.o3a_o4a_common_pem_contract import (  # noqa: E402
    _host_path,
    load_contract,
)
from src.dante_light.o3a_o4a_common_pem_gate import (  # noqa: E402
    load_background_source_contract,
)
from src.dante_light.o3a_o4a_common_pem_span_replay import (  # noqa: E402
    produce_span_receipt,
)

CONFIG_PATH = "config/dante_o3a_o4a_common_pem_span_replay_v1.json"
EXTERNAL_ROOT = (
    "E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/background_span_replay"
)
PARENT_ROOT = parent.EXTERNAL_ROOT
SOURCE_FILES = (
    CONFIG_PATH,
    "src/dante_light/o3a_o4a_common_pem_span_replay.py",
    "scripts/run_dante_o3a_o4a_common_pem_span_replay.py",
)


def _seal(body: dict) -> dict:
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def _contract(parent_dir: Path, parent_plan: dict, parent_summary: dict) -> dict:
    contract = json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
    if (
        contract.get("schema_version") != 1
        or contract.get("contract_id")
        != "dante-o3a-o4a-common-pem-background-span-replay-v1"
        or contract.get("parent_acquisition_run_key") != parent_plan["receipt_digest"]
        or contract.get("parent_acquisition_summary_digest")
        != parent_summary["receipt_digest"]
        or parent_dir.name
        != f"background_acquisition_v2_{parent_plan['receipt_digest']}"
        or contract.get("source_policy")
        != "EXISTING_VERIFIED_OFFICIAL_FRAMES_ONLY_NO_DOWNLOAD"
        or contract.get("span_policy")
        != "FROZEN_HISTORICAL_FOUR_HOUR_SPANS_NO_RESELECTION"
        or contract.get("scientific_boundary")
        != {
            "background_span_samples_only": True,
            "auxiliary_channels_verified": False,
            "paired_pem_outcomes_opened": False,
            "global_significance_claim": False,
        }
    ):
        raise ContractError("common PEM span replay contract or parent changed")
    return contract


def _parent(parent_dir: Path) -> tuple[dict, dict, dict[str, dict], dict[str, str]]:
    parent_dir = parent_dir.resolve()
    parent_root = _host_path(ROOT, PARENT_ROOT).resolve()
    if parent_dir.parent != parent_root:
        raise ContractError("common PEM span parent escaped frozen acquisition root")
    if (parent_dir / "controller.lock").exists() or (
        parent_dir / "failure.json"
    ).exists():
        raise ContractError("common PEM span parent is active or failed")
    comparison = load_contract(root=ROOT)
    background = load_background_source_contract(root=ROOT)
    plan = sealed_json(parent_dir / "plan.json")
    summary = sealed_json(parent_dir / "summary.json")
    _contract(parent_dir, plan, summary)
    manifests = parent._saved_manifests(parent_dir, background)
    if parent._plan(comparison, background, manifests) != plan:
        raise ContractError("common PEM span parent plan replay changed")
    expected = parent._seal(
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
        raise ContractError("common PEM span parent summary changed")
    frame_sha256: dict[str, str] = {}
    for run in ("O3a", "O4a"):
        for frame in plan["runs"][run]["frames"]:
            filename = str(frame["filename"])
            receipt = sealed_json(parent_dir / "receipts" / f"{filename}.json")
            probe = receipt.get("probe")
            if (
                receipt.get("status") != "PASS_ACQUIRED_OFFICIAL_FRAME_BYTES_V2_ONLY"
                or receipt.get("frame") != frame
                or not isinstance(probe, dict)
                or probe.get("interval_gps") != frame["probe_interval_gps"]
                or not isinstance(probe.get("frames"), list)
                or len(probe["frames"]) != 1
                or probe["frames"][0].get("filename") != filename
            ):
                raise ContractError("common PEM span parent frame receipt changed")
            frame_sha256[filename] = probe["frames"][0]["sha256"]
    if len(frame_sha256) != sum(
        len(plan["runs"][run]["frames"]) for run in ("O3a", "O4a")
    ):
        raise ContractError("common PEM span parent frame identities collide")
    return plan, summary, manifests, frame_sha256


def _plan(parent_plan: dict, parent_summary: dict, comparison: dict) -> dict:
    spans = {run: parent_plan["runs"][run]["spans"] for run in ("O3a", "O4a")}
    if any(
        len(spans[run]) != comparison["runs"][run]["targets"]["expected_count"]
        for run in ("O3a", "O4a")
    ):
        raise ContractError("common PEM span population changed")
    return _seal(
        {
            "schema_version": 1,
            "status": "FROZEN_BACKGROUND_SPAN_REPLAY_NO_PEM_OUTCOMES",
            "contract_digest": canonical_json_sha256(
                json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
            ),
            "parent_plan_digest": parent_plan["receipt_digest"],
            "parent_summary_digest": parent_summary["receipt_digest"],
            "source_sha256": {path: sha256_file(ROOT / path) for path in SOURCE_FILES},
            "spans": spans,
        }
    )


def _receipt_path(run_dir: Path, run: str, span: dict) -> Path:
    if run not in ("O3a", "O4a") or span["detector"] not in ("H1", "L1"):
        raise ContractError("common PEM span identity is invalid")
    gps = int(span["gps_start"])
    return run_dir / "receipts" / f"{run}_{span['detector']}_{gps}.json"


def _verify_one(
    run_dir: Path,
    run: str,
    span: dict,
    *,
    source: dict,
    manifest: dict,
    parent_dir: Path,
    frame_sha256: dict[str, str],
) -> dict:
    receipt = sealed_json(_receipt_path(run_dir, run, span))
    if (
        receipt.get("status") != "PASS_BACKGROUND_SPAN_REPLAY_ONLY"
        or receipt.get("run") != run
        or receipt.get("target_gps") != int(span["gps_start"])
        or receipt.get("background", {}).get("detector") != span["detector"]
        or receipt.get("background", {}).get("interval_gps") != span["interval_gps"]
    ):
        raise ContractError("common PEM span receipt identity changed")
    if any(
        frame_sha256.get(frame["filename"]) != frame["sha256"]
        for frame in receipt["background"]["frames"]
    ):
        raise ContractError("common PEM span frame differs from parent receipt")
    verified = verify_background_receipt(
        receipt["background"],
        source=source,
        manifest=manifest,
        cache_dir=parent_dir / "frames",
    )
    if verified["status"] != "PASS_VERIFIED_BACKGROUND_SPAN":
        raise ContractError("common PEM span independent replay failed")
    return receipt


def _verify_all(
    run_dir: Path,
    plan: dict,
    background: dict,
    manifests: dict[str, dict],
    parent_dir: Path,
    frame_sha256: dict[str, str],
) -> int:
    expected_paths = {
        _receipt_path(run_dir, run, span)
        for run in ("O3a", "O4a")
        for span in plan["spans"][run]
    }
    actual_paths = set((run_dir / "receipts").glob("*.json"))
    expected_count = sum(len(plan["spans"][run]) for run in ("O3a", "O4a"))
    if actual_paths != expected_paths or len(expected_paths) != expected_count:
        raise ContractError("common PEM span receipt set incomplete or unplanned")
    for run in ("O3a", "O4a"):
        for span in plan["spans"][run]:
            _verify_one(
                run_dir,
                run,
                span,
                source=background["sources"][run],
                manifest=manifests[run],
                parent_dir=parent_dir,
                frame_sha256=frame_sha256,
            )
    return len(expected_paths)


def main(
    *, stage: str, parent_dir: Path, external_root: Path, run_dir: Path | None
) -> int:
    parent_dir = parent_dir.resolve()
    external_root = external_root.resolve()
    parent_plan, parent_summary, manifests, frame_sha256 = _parent(parent_dir)
    comparison = load_contract(root=ROOT)
    background = load_background_source_contract(root=ROOT)
    plan = _plan(parent_plan, parent_summary, comparison)
    if stage == "plan":
        # The parent verifier replays every frame receipt before this new gate.
        parent.main(stage="verify", external_root=parent_dir.parent, run_dir=parent_dir)
        run_dir = external_root / f"background_spans_{plan['receipt_digest']}"
        existing = run_dir / "plan.json"
        if existing.is_file():
            if sealed_json(existing) != plan:
                raise ContractError("common PEM existing span plan changed")
        elif run_dir.exists() and any(run_dir.iterdir()):
            raise ContractError("common PEM span directory exists without plan")
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            _atomic_json(existing, plan)
        print(
            json.dumps(
                {"status": "PASS_BACKGROUND_SPAN_PLAN_ONLY", "run_dir": str(run_dir)},
                sort_keys=True,
            )
        )
        return 0
    if run_dir is None:
        raise ContractError("common PEM span replay requires an explicit run directory")
    run_dir = run_dir.resolve()
    if (
        run_dir.parent != external_root
        or run_dir.name != f"background_spans_{plan['receipt_digest']}"
    ):
        raise ContractError("common PEM span replay run key or root changed")
    if sealed_json(run_dir / "plan.json") != plan:
        raise ContractError("common PEM span replay plan changed")
    if stage == "run":
        if (run_dir / "failure.json").exists() or (run_dir / "summary.json").exists():
            raise ContractError("common PEM span replay failed or already completed")
        with legacy._single_controller(run_dir):
            try:
                completed = 0
                for run in ("O3a", "O4a"):
                    source = background["sources"][run]
                    for span in plan["spans"][run]:
                        path = _receipt_path(run_dir, run, span)
                        if path.is_file():
                            _verify_one(
                                run_dir,
                                run,
                                span,
                                source=source,
                                manifest=manifests[run],
                                parent_dir=parent_dir,
                                frame_sha256=frame_sha256,
                            )
                        else:
                            left, right = (int(value) for value in span["interval_gps"])
                            receipt = produce_span_receipt(
                                detector=str(span["detector"]),
                                start=left,
                                end=right,
                                source=source,
                                manifest=manifests[run],
                                cache_dir=parent_dir / "frames",
                            )
                            if any(
                                frame_sha256.get(frame["filename"]) != frame["sha256"]
                                for frame in receipt["frames"]
                            ):
                                raise ContractError(
                                    "common PEM span frame differs from parent receipt"
                                )
                            verify_background_receipt(
                                receipt,
                                source=source,
                                manifest=manifests[run],
                                cache_dir=parent_dir / "frames",
                            )
                            _atomic_json(
                                path,
                                _seal(
                                    {
                                        "status": "PASS_BACKGROUND_SPAN_REPLAY_ONLY",
                                        "run": run,
                                        "target_gps": int(span["gps_start"]),
                                        "background": receipt,
                                    }
                                ),
                            )
                        completed += 1
                        _atomic_json(
                            run_dir / "progress.json",
                            _seal(
                                {
                                    "status": "REPLAYING_BACKGROUND_SPANS_ONLY",
                                    "completed_spans": completed,
                                    "expected_spans": sum(
                                        len(plan["spans"][item])
                                        for item in ("O3a", "O4a")
                                    ),
                                }
                            ),
                        )
                expected = sum(len(plan["spans"][item]) for item in ("O3a", "O4a"))
                if completed != expected:
                    raise ContractError("common PEM span replay count changed")
                _atomic_json(
                    run_dir / "summary.json",
                    _seal(
                        {
                            "status": "PASS_BACKGROUND_SPAN_REPLAY_COMPLETE_ONLY",
                            "plan_digest": plan["receipt_digest"],
                            "span_counts": {
                                item: len(plan["spans"][item])
                                for item in ("O3a", "O4a")
                            },
                            "paired_outcomes_opened": False,
                        }
                    ),
                )
            except Exception as exc:
                _atomic_json(
                    run_dir / "failure.json",
                    _seal(
                        {
                            "status": "FAILED_SPAN_REPLAY_REQUIRES_REVIEW",
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
                    "status": "PASS_BACKGROUND_SPAN_REPLAY_COMPLETE_ONLY",
                    "run_dir": str(run_dir),
                },
                sort_keys=True,
            )
        )
        return 0
    if stage == "verify":
        if (run_dir / "controller.lock").exists() or (
            run_dir / "failure.json"
        ).exists():
            raise ContractError("common PEM span replay active or failed")
        expected = _seal(
            {
                "status": "PASS_BACKGROUND_SPAN_REPLAY_COMPLETE_ONLY",
                "plan_digest": plan["receipt_digest"],
                "span_counts": {
                    item: len(plan["spans"][item]) for item in ("O3a", "O4a")
                },
                "paired_outcomes_opened": False,
            }
        )
        if sealed_json(run_dir / "summary.json") != expected:
            raise ContractError("common PEM span replay summary changed")
        count = _verify_all(
            run_dir, plan, background, manifests, parent_dir, frame_sha256
        )
        if list(run_dir.rglob("*.partial")):
            raise ContractError("common PEM span replay has partial files")
        print(
            json.dumps(
                {"status": "PASS_VERIFIED_BACKGROUND_SPANS_ONLY", "span_count": count},
                sort_keys=True,
            )
        )
        return 0
    raise ValueError(f"unsupported common PEM span replay stage: {stage}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "run", "verify"), required=True)
    parser.add_argument("--parent-run-dir", required=True)
    parser.add_argument("--external-root", default=EXTERNAL_ROOT)
    parser.add_argument("--run-dir")
    args = parser.parse_args()
    raise SystemExit(
        main(
            stage=args.stage,
            parent_dir=_host_path(ROOT, args.parent_run_dir),
            external_root=_host_path(ROOT, args.external_root),
            run_dir=_host_path(ROOT, args.run_dir) if args.run_dir else None,
        )
    )
