#!/usr/bin/env python3
"""Check frozen common-PEM auxiliary coverage via NDS2 metadata only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dante_o3a_o4a_common_pem_background_acquisition as legacy  # noqa: E402
from scripts import run_dante_o3a_o4a_common_pem_span_replay as parent  # noqa: E402
from src.core.index_contract import sha256_file  # noqa: E402
from src.dante_light.contracts import ContractError, canonical_json_sha256  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_acquisition import (  # noqa: E402
    _atomic_json,
    sealed_json,
)
from src.dante_light.o3a_o4a_common_pem_aux_availability import (  # noqa: E402
    check_availability,
    requirements,
)
from src.dante_light.o3a_o4a_common_pem_contract import (  # noqa: E402
    _host_path,
    load_contract,
)

CONFIG_PATH = "config/dante_o3a_o4a_common_pem_aux_availability_v1.json"
SOURCE_FILES = (
    CONFIG_PATH,
    "src/dante_light/o3a_o4a_common_pem_aux_availability.py",
    "scripts/run_dante_o3a_o4a_common_pem_aux_availability.py",
)
EXTERNAL_ROOT = "E:/dante_cache/dante_light/o3a_o4a_common_pem_v1/aux_availability"


def _seal(body: dict) -> dict:
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def _parent(parent_dir: Path) -> tuple[dict, dict, dict]:
    parent_dir = parent_dir.resolve()
    if parent_dir.parent != _host_path(ROOT, parent.EXTERNAL_ROOT).resolve():
        raise ContractError("common PEM auxiliary parent root changed")
    if (parent_dir / "controller.lock").exists() or (
        parent_dir / "failure.json"
    ).exists():
        raise ContractError("common PEM auxiliary parent active or failed")
    span_plan = sealed_json(parent_dir / "plan.json")
    span_summary = sealed_json(parent_dir / "summary.json")
    config = json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
    if (
        config.get("schema_version") != 1
        or config.get("contract_id") != "dante-o3a-o4a-common-pem-aux-availability-v1"
        or config.get("parent_span_run_key") != span_plan["receipt_digest"]
        or config.get("parent_span_summary_digest") != span_summary["receipt_digest"]
        or parent_dir.name != f"background_spans_{span_plan['receipt_digest']}"
        or span_summary.get("status") != "PASS_BACKGROUND_SPAN_REPLAY_COMPLETE_ONLY"
        or span_summary.get("plan_digest") != span_plan["receipt_digest"]
        or config.get("source_policy") != "NDS2_METADATA_COVERAGE_ONLY_NO_SAMPLE_FETCH"
        or config.get("scientific_boundary")
        != {
            "auxiliary_samples_verified": False,
            "paired_pem_outcomes_opened": False,
            "global_significance_claim": False,
        }
    ):
        raise ContractError(
            "common PEM auxiliary availability parent or contract changed"
        )
    expected_receipts = {
        parent._receipt_path(parent_dir, run, span)
        for run in ("O3a", "O4a")
        for span in span_plan["spans"][run]
    }
    if set((parent_dir / "receipts").glob("*.json")) != expected_receipts:
        raise ContractError("common PEM auxiliary parent receipt set changed")
    for run in ("O3a", "O4a"):
        for span in span_plan["spans"][run]:
            receipt = sealed_json(parent._receipt_path(parent_dir, run, span))
            if (
                receipt.get("status") != "PASS_BACKGROUND_SPAN_REPLAY_ONLY"
                or receipt.get("run") != run
                or receipt.get("target_gps") != span["gps_start"]
                or receipt.get("background", {}).get("detector") != span["detector"]
                or receipt.get("background", {}).get("interval_gps")
                != span["interval_gps"]
            ):
                raise ContractError("common PEM auxiliary parent receipt changed")
    return span_plan, span_summary, config


def _plan(parent_dir: Path) -> dict:
    span_plan, span_summary, config = _parent(parent_dir)
    comparison = load_contract(root=ROOT)
    o3a = json.loads((ROOT / "config/dante_o3a_native_pem_v1.json").read_text())
    o4a = json.loads(
        (ROOT / "config/dante_o4a_corrected_native_pem_v1.json").read_text()
    )
    hosts = {o3a["execution"]["nds_host"], o4a["execution"]["nds_host"]}
    if len(hosts) != 1:
        raise ContractError("common PEM auxiliary NDS host differs between runs")
    return _seal(
        {
            "schema_version": 1,
            "status": "FROZEN_AUX_AVAILABILITY_PLAN_NO_SAMPLES",
            "contract_digest": canonical_json_sha256(config),
            "parent_plan_digest": span_plan["receipt_digest"],
            "parent_summary_digest": span_summary["receipt_digest"],
            "source_sha256": {path: sha256_file(ROOT / path) for path in SOURCE_FILES},
            "nds_host": hosts.pop(),
            "requirements": requirements(span_plan, comparison),
        }
    )


def _receipt_path(run_dir: Path, row: dict) -> Path:
    return (
        run_dir
        / "receipts"
        / (f"{row['run']}_{row['detector']}_{row['target_gps']}.json")
    )


def _check_one(connection: object, row: dict) -> dict:
    intervals: dict[str, dict] = {}
    for label in ("event", "background"):
        start, end = row[f"{label}_interval_gps"]
        if not connection.set_epoch(start, end):
            raise ContractError("common PEM auxiliary NDS epoch unavailable")
        found = connection.get_availability(row["channels"])
        intervals[label] = {
            "interval_gps": [start, end],
            "channels": check_availability(found, row["channels"], start, end),
        }
    return _seal(
        {
            "status": "PASS_AUX_METADATA_COVERAGE_ONLY",
            "identity": row,
            "intervals": intervals,
        }
    )


def _connect(host: str) -> object:
    import nds2

    return nds2.connection(host, 31200)


def main(*, stage: str, parent_dir: Path, root: Path, run_dir: Path | None) -> int:
    parent_dir = parent_dir.resolve()
    root = root.resolve()
    plan = _plan(parent_dir)
    if stage == "plan":
        # Verify complete parent numerical strain independently before this gate.
        acquisition_key = sealed_json(parent_dir / "plan.json")["parent_plan_digest"]
        acquisition_dir = _host_path(ROOT, parent.PARENT_ROOT) / (
            f"background_acquisition_v2_{acquisition_key}"
        )
        parent.main(
            stage="verify",
            parent_dir=acquisition_dir,
            external_root=parent_dir.parent,
            run_dir=parent_dir,
        )
        run_dir = root / f"aux_availability_{plan['receipt_digest']}"
        if run_dir.exists() and any(run_dir.iterdir()):
            if sealed_json(run_dir / "plan.json") != plan:
                raise ContractError("common PEM auxiliary existing plan changed")
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            _atomic_json(run_dir / "plan.json", plan)
        print(
            json.dumps(
                {"status": "PASS_AUX_AVAILABILITY_PLAN_ONLY", "run_dir": str(run_dir)}
            )
        )
        return 0
    if run_dir is None:
        raise ContractError(
            "common PEM auxiliary availability needs explicit run directory"
        )
    run_dir = run_dir.resolve()
    if (
        run_dir.parent != root
        or run_dir.name != f"aux_availability_{plan['receipt_digest']}"
        or sealed_json(run_dir / "plan.json") != plan
    ):
        raise ContractError("common PEM auxiliary availability run key changed")
    if stage == "run":
        if (run_dir / "failure.json").exists() or (run_dir / "summary.json").exists():
            raise ContractError("common PEM auxiliary availability already terminal")
        with legacy._single_controller(run_dir):
            try:
                connection = _connect(plan["nds_host"])
                for index, row in enumerate(plan["requirements"], start=1):
                    receipt = _check_one(connection, row)
                    path = _receipt_path(run_dir, row)
                    if path.exists():
                        if sealed_json(path) != receipt:
                            raise ContractError("common PEM auxiliary metadata changed")
                    else:
                        _atomic_json(path, receipt)
                    _atomic_json(
                        run_dir / "progress.json",
                        _seal(
                            {
                                "status": "CHECKING_AUX_METADATA_ONLY",
                                "completed": index,
                                "expected": len(plan["requirements"]),
                            }
                        ),
                    )
                _atomic_json(
                    run_dir / "summary.json",
                    _seal(
                        {
                            "status": "PASS_AUX_METADATA_COVERAGE_COMPLETE_ONLY",
                            "plan_digest": plan["receipt_digest"],
                            "receipt_count": len(plan["requirements"]),
                            "auxiliary_samples_verified": False,
                            "paired_pem_outcomes_opened": False,
                        }
                    ),
                )
            except Exception as exc:
                _atomic_json(
                    run_dir / "failure.json",
                    _seal(
                        {
                            "status": "FAILED_AUX_METADATA_REQUIRES_REVIEW",
                            "plan_digest": plan["receipt_digest"],
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    ),
                )
                raise
        print(json.dumps({"status": "PASS_AUX_METADATA_COVERAGE_COMPLETE_ONLY"}))
        return 0
    if stage == "verify":
        if (run_dir / "failure.json").exists() or (
            run_dir / "controller.lock"
        ).exists():
            raise ContractError("common PEM auxiliary availability active or failed")
        expected_summary = _seal(
            {
                "status": "PASS_AUX_METADATA_COVERAGE_COMPLETE_ONLY",
                "plan_digest": plan["receipt_digest"],
                "receipt_count": len(plan["requirements"]),
                "auxiliary_samples_verified": False,
                "paired_pem_outcomes_opened": False,
            }
        )
        if sealed_json(run_dir / "summary.json") != expected_summary:
            raise ContractError("common PEM auxiliary availability summary changed")
        paths = {_receipt_path(run_dir, row) for row in plan["requirements"]}
        if set((run_dir / "receipts").glob("*.json")) != paths:
            raise ContractError("common PEM auxiliary availability receipt set changed")
        connection = _connect(plan["nds_host"])
        for row in plan["requirements"]:
            if sealed_json(_receipt_path(run_dir, row)) != _check_one(connection, row):
                raise ContractError("common PEM auxiliary availability replay changed")
        if list(run_dir.rglob("*.partial")):
            raise ContractError("common PEM auxiliary availability has partial files")
        print(
            json.dumps(
                {
                    "status": "PASS_VERIFIED_AUX_METADATA_COVERAGE_ONLY",
                    "count": len(paths),
                }
            )
        )
        return 0
    raise ValueError(f"unsupported common PEM auxiliary stage: {stage}")


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
            root=_host_path(ROOT, args.external_root),
            run_dir=_host_path(ROOT, args.run_dir) if args.run_dir else None,
        )
    )
