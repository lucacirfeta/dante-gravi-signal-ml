"""Freeze and replay outcome-blind DQ/NDS2 metadata for local L1 controls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_dante_o3a_o4a_common_pem_background_acquisition import (  # noqa: E402
    _single_controller,
)
from src.core.index_contract import sha256_file  # noqa: E402
from src.dante_light.contracts import ContractError, canonical_json_sha256  # noqa: E402
from src.dante_light.o3a_l1_local_followup import (  # noqa: E402
    CONFIG_PATH,
    load_design,
    metadata_preflight,
)
from src.dante_light.o3a_l1_local_inputs import (  # noqa: E402
    assess_inputs,
    auxiliary_metadata,
    normalize_segments,
)
from src.dante_light.o3a_o4a_common_pem_acquisition import (  # noqa: E402
    _atomic_json,
    sealed_json,
)
from src.dante_light.o3a_o4a_common_pem_contract import _host_path  # noqa: E402

SOURCES = (
    CONFIG_PATH,
    "src/dante_light/o3a_l1_local_followup.py",
    "src/dante_light/o3a_l1_local_inputs.py",
    "scripts/preflight_dante_o3a_l1_local_inputs.py",
    "scripts/run_dante_o3a_o4a_common_pem_background_acquisition.py",
    "src/dante_light/o3a_o4a_common_pem_acquisition.py",
    "src/dante_light/o3a_o4a_common_pem_contract.py",
    "src/dante_light/contracts.py",
    "src/core/index_contract.py",
)


def seal(body: dict) -> dict:
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def plan() -> dict:
    design = load_design(ROOT)
    return seal(
        {
            "status": "FROZEN_LOCAL_INPUT_METADATA_PLAN_ONLY",
            "design_digest": canonical_json_sha256(design),
            "source_sha256": {name: sha256_file(ROOT / name) for name in SOURCES},
            "feasibility": metadata_preflight(ROOT),
        }
    )


def replay(plan_value: dict, snapshots: list[dict], design: dict) -> list[dict]:
    expected = [
        t for t in plan_value["feasibility"]["targets"] if t["tail_resolution_possible"]
    ]
    if [s["gps_start"] for s in snapshots] != [t["gps_start"] for t in expected]:
        raise ContractError("input metadata snapshot identity/accounting changed")
    common = json.loads((ROOT / design["parents"]["common_method"]["path"]).read_text())
    channels = common["method"]["channels"]["L1"]
    results = []
    for target in plan_value["feasibility"]["targets"]:
        if not target["tail_resolution_possible"]:
            results.append(
                {
                    "gps_start": target["gps_start"],
                    "detector": target["detector"],
                    "status": "INCONCLUSIVE",
                    "reason": "REFERENCE_TAIL_UNRESOLVED",
                    "candidate_clean_block_upper_bound": target[
                        "candidate_clean_blocks_before_cat2_cat3"
                    ],
                    "new_local_outcome_computed": False,
                }
            )
            continue
        snapshot = next(s for s in snapshots if s["gps_start"] == target["gps_start"])
        if snapshot["query_bounds_gps"] != target["same_cat1_segment_gps"]:
            raise ContractError("input metadata query segment changed")
        for value in snapshot["auxiliary"].values():
            reconstructed = normalize_segments(
                [[r["gps_start"], r["gps_end"]] for r in value["source_segments"]],
                snapshot["query_bounds_gps"],
            )
            if reconstructed != value["coverage_segments"]:
                raise ContractError("input NDS2 metadata coverage changed")
        results.append(
            assess_inputs(
                target,
                design=design,
                channels=channels,
                quality=snapshot["quality"],
                auxiliary=snapshot["auxiliary"],
            )
        )
    return results


def main(stage: str, run_dir_arg: str | None) -> int:
    design = load_design(ROOT)
    frozen = plan()
    root = _host_path(ROOT, design["input_preflight"]["output_root"])
    run_dir = root / f"inputs_{frozen['receipt_digest']}"
    if run_dir_arg:
        supplied = Path(run_dir_arg)
        if not supplied.is_absolute():
            supplied = _host_path(ROOT, run_dir_arg)
        if supplied.resolve() != run_dir.resolve():
            raise ContractError("input metadata run key changed")
    if stage == "plan":
        if (run_dir / "plan.json").exists():
            if sealed_json(run_dir / "plan.json") != frozen:
                raise ContractError("input metadata existing plan changed")
        else:
            if run_dir.exists() and any(run_dir.iterdir()):
                raise ContractError("input metadata run directory nonempty")
            run_dir.mkdir(parents=True, exist_ok=True)
            _atomic_json(run_dir / "plan.json", frozen)
        print(json.dumps({"status": frozen["status"], "run_dir": str(run_dir)}))
        return 0
    if not run_dir_arg or sealed_json(run_dir / "plan.json") != frozen:
        raise ContractError("input metadata needs exact frozen plan/run directory")
    if (run_dir / "failure.json").exists():
        raise ContractError("input metadata failed; preserve evidence for review")
    if stage == "run":
        if (run_dir / "summary.json").exists():
            raise ContractError("input metadata already terminal")
        with _single_controller(run_dir):
            try:
                import nds2
                from gwosc.timeline import get_segments

                native = json.loads(
                    (ROOT / design["parents"]["native_pem"]["path"]).read_text()
                )
                common = json.loads(
                    (ROOT / design["parents"]["common_method"]["path"]).read_text()
                )
                channels = common["method"]["channels"]["L1"]
                connection = nds2.connection(
                    native["execution"]["nds_host"],
                    design["input_preflight"]["nds_port"],
                )
                snapshots = []
                for target in frozen["feasibility"]["targets"]:
                    if not target["tail_resolution_possible"]:
                        continue
                    start, end = target["same_cat1_segment_gps"]
                    quality = {
                        flag: [list(s) for s in get_segments(flag, start, end)]
                        for flag in design["input_preflight"]["quality_flags"]
                    }
                    if not connection.set_epoch(start, end):
                        raise ContractError("input metadata NDS2 epoch unavailable")
                    snapshot = {
                        "gps_start": target["gps_start"],
                        "query_bounds_gps": [start, end],
                        "quality": quality,
                        "nds_host": native["execution"]["nds_host"],
                        "auxiliary": auxiliary_metadata(
                            connection.get_availability(channels),
                            channels,
                            [start, end],
                        ),
                    }
                    snapshots.append(snapshot)
                _atomic_json(
                    run_dir / "source_snapshot.json",
                    seal(
                        {
                            "plan_digest": frozen["receipt_digest"],
                            "snapshots": snapshots,
                        }
                    ),
                )
                results = replay(frozen, snapshots, design)
                _atomic_json(
                    run_dir / "summary.json",
                    seal(
                        {
                            "status": "PASS_LOCAL_INPUT_METADATA_ACCOUNTING_ONLY",
                            "plan_digest": frozen["receipt_digest"],
                            "snapshot_sha256": sha256_file(
                                run_dir / "source_snapshot.json"
                            ),
                            "targets": results,
                            "sample_arrays_opened": False,
                            "gate_c_enabled": False,
                        }
                    ),
                )
            except Exception as exc:
                _atomic_json(
                    run_dir / "failure.json",
                    seal(
                        {
                            "status": "FAILED_INPUT_METADATA_REQUIRES_REVIEW",
                            "plan_digest": frozen["receipt_digest"],
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    ),
                )
                raise
    elif stage == "verify":
        if (run_dir / "controller.lock").exists() or list(run_dir.rglob("*.partial")):
            raise ContractError("input metadata active or partial")
        snapshot = sealed_json(run_dir / "source_snapshot.json")
        if snapshot["plan_digest"] != frozen["receipt_digest"]:
            raise ContractError("input metadata parent plan changed")
        results = replay(frozen, snapshot["snapshots"], design)
        expected = seal(
            {
                "status": "PASS_LOCAL_INPUT_METADATA_ACCOUNTING_ONLY",
                "plan_digest": frozen["receipt_digest"],
                "snapshot_sha256": sha256_file(run_dir / "source_snapshot.json"),
                "targets": results,
                "sample_arrays_opened": False,
                "gate_c_enabled": False,
            }
        )
        if sealed_json(run_dir / "summary.json") != expected:
            raise ContractError("input metadata summary replay changed")
    else:
        raise ValueError(stage)
    print(
        json.dumps(
            {
                "status": "PASS_VERIFIED_LOCAL_INPUT_METADATA_ONLY"
                if stage == "verify"
                else "PASS_LOCAL_INPUT_METADATA_ACCOUNTING_ONLY",
                "targets": [
                    {
                        k: v
                        for k, v in t.items()
                        if k not in {"blocks", "identity_digest"}
                    }
                    for t in results
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "run", "verify"), required=True)
    parser.add_argument("--run-dir")
    args = parser.parse_args()
    raise SystemExit(main(args.stage, args.run_dir))
