#!/usr/bin/env python3
"""Acquire and independently replay common-PEM native auxiliary samples only."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dante_o3a_o4a_common_pem_aux_availability as parent  # noqa: E402
from scripts import run_dante_o3a_o4a_common_pem_background_acquisition as legacy  # noqa: E402
from src.core.index_contract import sha256_file  # noqa: E402
from src.dante_light.contracts import ContractError, canonical_json_sha256  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_acquisition import (  # noqa: E402
    _atomic_json,
    sealed_json,
)
from src.dante_light.o3a_o4a_common_pem_aux_samples import (  # noqa: E402
    InfrastructureError,
    acquire_series,
    data_path,
    sample_specs,
    verify_series,
)
from src.dante_light.o3a_o4a_common_pem_contract import _host_path  # noqa: E402

CONFIG_PATH = "config/dante_o3a_o4a_common_pem_aux_samples_v1.json"
SOURCE_FILES = (
    CONFIG_PATH,
    "src/dante_light/o3a_o4a_common_pem_aux_samples.py",
    "scripts/run_dante_o3a_o4a_common_pem_aux_samples.py",
)
EXTERNAL_ROOT = "E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/aux_samples"
EXPECTED_PARENT = "E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/aux_availability"


def _seal(body: dict) -> dict:
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def _receipt_path(run_dir: Path, spec: dict) -> Path:
    return run_dir / "receipts" / f"{spec['key']}.json"


def _parent(parent_dir: Path, config: dict) -> tuple[dict, dict]:
    if parent_dir.parent != _host_path(ROOT, EXPECTED_PARENT).resolve():
        raise ContractError("common PEM auxiliary sample parent root changed")
    if (parent_dir / "controller.lock").exists() or (
        parent_dir / "failure.json"
    ).exists():
        raise ContractError("common PEM auxiliary metadata parent active or failed")
    plan = sealed_json(parent_dir / "plan.json")
    summary = sealed_json(parent_dir / "summary.json")
    if plan.get("source_sha256") != {
        path: sha256_file(ROOT / path) for path in parent.SOURCE_FILES
    }:
        raise ContractError("common PEM auxiliary metadata source bytes changed")
    if (
        parent_dir.name != f"aux_availability_{plan['receipt_digest']}"
        or config.get("parent_availability_run_key") != plan["receipt_digest"]
        or config.get("parent_availability_summary_digest") != summary["receipt_digest"]
        or summary.get("status") != "PASS_AUX_METADATA_COVERAGE_COMPLETE_ONLY"
        or summary.get("plan_digest") != plan["receipt_digest"]
        or summary.get("receipt_count") != len(plan["requirements"])
        or len(plan["requirements"]) != 77
    ):
        raise ContractError("common PEM auxiliary sample parent seal changed")
    expected = {parent._receipt_path(parent_dir, row) for row in plan["requirements"]}
    if set((parent_dir / "receipts").glob("*.json")) != expected:
        raise ContractError("common PEM auxiliary metadata receipt set changed")
    for row in plan["requirements"]:
        receipt = sealed_json(parent._receipt_path(parent_dir, row))
        if (
            receipt.get("status") != "PASS_AUX_METADATA_COVERAGE_ONLY"
            or receipt.get("identity") != row
        ):
            raise ContractError("common PEM auxiliary metadata identity changed")
        for role in ("event", "background"):
            interval = receipt.get("intervals", {}).get(role, {})
            if (
                interval.get("interval_gps") != row[f"{role}_interval_gps"]
                or [item.get("channel") for item in interval.get("channels", [])]
                != row["channels"]
                or any(
                    any(
                        segment.get("gps_start") > row[f"{role}_interval_gps"][0]
                        or segment.get("gps_end") < row[f"{role}_interval_gps"][1]
                        for segment in item.get("segments", [])
                    )
                    for item in interval.get("channels", [])
                )
            ):
                raise ContractError("common PEM auxiliary metadata interval changed")
    return plan, summary


def _plan(parent_dir: Path) -> dict:
    config = json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
    if (
        config.get("schema_version") != 1
        or config.get("contract_id") != "dante-o3a-o4a-common-pem-aux-native-samples-v1"
        or config.get("source_policy")
        != "NDS2_NATIVE_FLOAT32_SAMPLES_LOCAL_REPLAY_NO_SECOND_FETCH"
        or config.get("scientific_boundary")
        != {
            "native_samples_no_resampling_or_cast": True,
            "local_replay_not_second_source_acquisition": True,
            "five_channel_null_opened": False,
            "paired_pem_outcomes_opened": False,
            "global_significance_claim": False,
        }
        or set(config.get("sample_rate_hz", {})) != {"H1", "L1"}
        or set(config.get("execution", {}))
        != {
            "chunk_seconds",
            "fetch_retries",
            "backoff_base_s",
            "minimum_free_space_multiplier",
        }
    ):
        raise ContractError("common PEM auxiliary native sample contract changed")
    parent_plan, parent_summary = _parent(parent_dir, config)
    specs = sample_specs(parent_plan["requirements"], config["sample_rate_hz"])
    if len(specs) != 750 or sum(len(spec["uses"]) for spec in specs) != 770:
        raise ContractError("common PEM auxiliary native sample coverage changed")
    if len({spec["key"] for spec in specs}) != len(specs):
        raise ContractError("common PEM auxiliary native sample duplicate key")
    return _seal(
        {
            "schema_version": 1,
            "status": "FROZEN_AUX_NATIVE_SAMPLE_PLAN_ONLY",
            "contract_digest": canonical_json_sha256(config),
            "parent_plan_digest": parent_plan["receipt_digest"],
            "parent_summary_digest": parent_summary["receipt_digest"],
            "source_sha256": {path: sha256_file(ROOT / path) for path in SOURCE_FILES},
            "nds_host": parent_plan["nds_host"],
            "execution": config["execution"],
            "series": specs,
            "expected_sample_bytes": sum(spec["sample_count"] * 4 for spec in specs),
        }
    )


def _check_run_dir(run_dir: Path, root: Path, plan: dict) -> None:
    if (
        run_dir.parent != root
        or run_dir.name != f"aux_samples_{plan['receipt_digest']}"
        or sealed_json(run_dir / "plan.json") != plan
    ):
        raise ContractError("common PEM auxiliary native sample run key changed")


def _check_completed(run_dir: Path, plan: dict) -> int:
    specs = {spec["key"]: spec for spec in plan["series"]}
    receipts = list((run_dir / "receipts").glob("*.json"))
    if len(receipts) != len({path.name for path in receipts}):
        raise ContractError("common PEM auxiliary native duplicate receipt")
    if {path.stem for path in receipts} - set(specs):
        raise ContractError("common PEM auxiliary native orphan receipt")
    expected_data = {data_path(run_dir, specs[path.stem]) for path in receipts}
    if (
        set((run_dir / "data").glob("*.npy"))
        - set((run_dir / "data").glob("*.partial.npy"))
        != expected_data
    ):
        raise ContractError("common PEM auxiliary native orphan sample file")
    for path in receipts:
        receipt = sealed_json(path)
        if receipt.get("nds_host") != plan["nds_host"]:
            raise ContractError("common PEM auxiliary native source host changed")
        verify_series(
            specs[path.stem],
            receipt,
            run_dir=run_dir,
            chunk_seconds=plan["execution"]["chunk_seconds"],
        )
    return len(receipts)


def _free_space(run_dir: Path, plan: dict) -> None:
    used = sum(path.stat().st_size for path in (run_dir / "data").glob("*.npy"))
    remaining = max(0, plan["expected_sample_bytes"] - used)
    multiplier = plan["execution"]["minimum_free_space_multiplier"]
    if multiplier < 1 or shutil.disk_usage(run_dir).free < remaining * multiplier:
        raise InfrastructureError(
            "common PEM auxiliary native sample disk headroom insufficient"
        )


def _connect_fetch(channel: str, *, start: int, end: int, host: str) -> object:
    from gwpy.timeseries import TimeSeries

    return TimeSeries.fetch(channel, start, end, host=host)


def main(*, stage: str, parent_dir: Path, root: Path, run_dir: Path | None) -> int:
    parent_dir, root = parent_dir.resolve(), root.resolve()
    plan = _plan(parent_dir)
    if stage == "plan":
        # Metadata-only network replay is the parent gate, not a second sample fetch.
        parent_config = json.loads(
            (ROOT / parent.CONFIG_PATH).read_text(encoding="utf-8")
        )
        span_dir = _host_path(ROOT, parent.parent.EXTERNAL_ROOT) / (
            f"background_spans_{parent_config['parent_span_run_key']}"
        )
        parent.main(
            stage="verify",
            parent_dir=span_dir,
            root=parent_dir.parent,
            run_dir=parent_dir,
        )
        run_dir = root / f"aux_samples_{plan['receipt_digest']}"
        if run_dir.exists() and any(run_dir.iterdir()):
            _check_run_dir(run_dir, root, plan)
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            _atomic_json(run_dir / "plan.json", plan)
        _free_space(run_dir, plan)
        print(
            json.dumps(
                {
                    "status": "PASS_AUX_NATIVE_SAMPLE_PLAN_ONLY",
                    "run_dir": str(run_dir),
                    "series": len(plan["series"]),
                    "expected_sample_bytes": plan["expected_sample_bytes"],
                }
            )
        )
        return 0
    if run_dir is None:
        raise ContractError(
            "common PEM auxiliary native sample needs explicit run directory"
        )
    run_dir = run_dir.resolve()
    _check_run_dir(run_dir, root, plan)
    if stage == "archive-infrastructure-failure":
        failure = sealed_json(run_dir / "failure.json")
        if (
            failure.get("status") != "FAILED_INFRASTRUCTURE"
            or (run_dir / "controller.lock").exists()
        ):
            raise ContractError(
                "common PEM auxiliary native failure not safe to archive"
            )
        _check_completed(run_dir, plan)
        history = run_dir / "failure_history"
        history.mkdir(exist_ok=True)
        destination = history / f"failure_{failure['receipt_digest']}.json"
        if destination.exists():
            raise ContractError(
                "common PEM auxiliary native failure archive already exists"
            )
        partials = list((run_dir / "data").glob("*.partial.npy"))
        if any(
            (history / f"{failure['receipt_digest']}_{partial.name}").exists()
            for partial in partials
        ):
            raise ContractError("common PEM auxiliary native partial archive collision")
        os.replace(run_dir / "failure.json", destination)
        for partial in partials:
            os.replace(partial, history / f"{failure['receipt_digest']}_{partial.name}")
        print(json.dumps({"status": "ARCHIVED_INFRASTRUCTURE_FAILURE_ONLY"}))
        return 0
    if stage == "run":
        if (run_dir / "failure.json").exists() or (run_dir / "summary.json").exists():
            raise ContractError("common PEM auxiliary native run already terminal")
        with legacy._single_controller(run_dir):
            try:
                done = _check_completed(run_dir, plan)
                _free_space(run_dir, plan)
                for spec in plan["series"]:
                    receipt_path = _receipt_path(run_dir, spec)
                    if receipt_path.exists():
                        continue
                    receipt = acquire_series(
                        spec,
                        run_dir=run_dir,
                        nds_host=plan["nds_host"],
                        chunk_seconds=plan["execution"]["chunk_seconds"],
                        retries=plan["execution"]["fetch_retries"],
                        backoff_base_s=plan["execution"]["backoff_base_s"],
                        fetch=_connect_fetch,
                    )
                    _atomic_json(receipt_path, _seal(receipt))
                    done += 1
                    _atomic_json(
                        run_dir / "progress.json",
                        _seal(
                            {
                                "status": "ACQUIRING_AUX_NATIVE_SAMPLES_ONLY",
                                "completed": done,
                                "expected": len(plan["series"]),
                            }
                        ),
                    )
                if _check_completed(run_dir, plan) != len(plan["series"]):
                    raise ContractError(
                        "common PEM auxiliary native sample receipt set incomplete"
                    )
                if list((run_dir / "data").glob("*.partial.npy")):
                    raise ContractError(
                        "common PEM auxiliary native partial samples remain"
                    )
                _atomic_json(
                    run_dir / "summary.json",
                    _seal(
                        {
                            "status": "PASS_AUX_NATIVE_SAMPLES_COMPLETE_ONLY",
                            "plan_digest": plan["receipt_digest"],
                            "series_count": len(plan["series"]),
                            "expected_sample_bytes": plan["expected_sample_bytes"],
                            "five_channel_null_opened": False,
                            "paired_pem_outcomes_opened": False,
                        }
                    ),
                )
            except Exception as exc:
                _atomic_json(
                    run_dir / "failure.json",
                    _seal(
                        {
                            "status": "FAILED_INFRASTRUCTURE"
                            if isinstance(exc, InfrastructureError)
                            else "FAILED_REQUIRES_REVIEW",
                            "plan_digest": plan["receipt_digest"],
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    ),
                )
                raise
        print(json.dumps({"status": "PASS_AUX_NATIVE_SAMPLES_COMPLETE_ONLY"}))
        return 0
    if stage == "verify":
        if (run_dir / "failure.json").exists() or (
            run_dir / "controller.lock"
        ).exists():
            raise ContractError("common PEM auxiliary native sample active or failed")
        expected_summary = _seal(
            {
                "status": "PASS_AUX_NATIVE_SAMPLES_COMPLETE_ONLY",
                "plan_digest": plan["receipt_digest"],
                "series_count": len(plan["series"]),
                "expected_sample_bytes": plan["expected_sample_bytes"],
                "five_channel_null_opened": False,
                "paired_pem_outcomes_opened": False,
            }
        )
        if sealed_json(run_dir / "summary.json") != expected_summary:
            raise ContractError("common PEM auxiliary native sample summary changed")
        if _check_completed(run_dir, plan) != len(plan["series"]):
            raise ContractError("common PEM auxiliary native receipt set incomplete")
        if list((run_dir / "data").glob("*.partial.npy")) or list(
            run_dir.rglob("*.partial")
        ):
            raise ContractError("common PEM auxiliary native partial files remain")
        print(
            json.dumps(
                {
                    "status": "PASS_VERIFIED_AUX_NATIVE_SAMPLES_ONLY",
                    "series_count": len(plan["series"]),
                }
            )
        )
        return 0
    raise ValueError(f"unsupported common PEM auxiliary native stage: {stage}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("plan", "run", "verify", "archive-infrastructure-failure"),
        required=True,
    )
    parser.add_argument("--parent-run-dir", required=True)
    parser.add_argument("--external-root", default=EXTERNAL_ROOT)
    parser.add_argument("--run-dir")
    args = parser.parse_args()
    raise SystemExit(
        main(
            stage=args.stage,
            parent_dir=_host_path(ROOT, args.parent_run_dir),
            root=_host_path(ROOT, args.external_root),
            run_dir=_host_path(ROOT, args.run_dir) if args.run_dir else None,
        )
    )
