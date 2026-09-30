"""Plan/run/independently verify the frozen offline local L1 PEM screen."""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_dante_o3a_l1_local_samples as parent  # noqa: E402
from scripts.run_dante_o3a_o4a_common_pem_background_acquisition import (  # noqa: E402
    _single_controller,
)
from src.core.index_contract import sha256_file  # noqa: E402
from src.dante_light.contracts import ContractError, canonical_json_sha256  # noqa: E402
from src.dante_light.o3a_l1_local_followup import load_design  # noqa: E402
from src.dante_light.o3a_l1_local_measurement import (  # noqa: E402
    NativeContextReader,
    block_record,
    decision_and_bootstrap,
    measure_context,
)
from src.dante_light.o3a_o4a_common_pem_acquisition import _atomic_json, sealed_json  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_contract import _host_path  # noqa: E402

CONFIG_PATH = "config/dante_o3a_l1_local_measurement_v1.json"
NEW_SOURCES = (
    CONFIG_PATH,
    "src/dante_light/o3a_l1_local_measurement.py",
    "scripts/run_dante_o3a_l1_local_measurement.py",
    "tests/test_dante_o3a_l1_local_measurement.py",
)


def seal(body: dict) -> dict:
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def load_config() -> dict:
    config = json.loads((ROOT / CONFIG_PATH).read_text())
    if (
        config["contract_id"] != "dante-o3a-l1-local-measurement-v1"
        or config["status"] != "FROZEN_GATE_C_EXECUTION_METHOD_UNCHANGED"
        or config["execution"]
        != {
            "gate_c_enabled": True,
            "source_freeze_required": True,
            "download_allowed": False,
            "automatic_resume_allowed": False,
        }
        or config["sampling"]
        != {
            "boundary": "HALF_OPEN_RELATIVE_SAMPLE_TIMESTAMPS",
            "indices": "[ceil(relative_start_s * sample_rate_hz), ceil(relative_end_s * sample_rate_hz))",
            "absolute_gps_float_subtraction_allowed": False,
            "library_crop_rounding_allowed": False,
        }
        or not config["author_boundary_and_preprocessing_approval_date"]
        or config["preprocessing"]["auxiliary_highpass"] is not False
        or config["preprocessing"]["event_control_policy_identical"] is not True
        or config["preprocessing"]["order"]
        != "FULL_NATIVE_CONTEXT_STRAIN_HIGHPASS_THEN_ALL_STREAMS_ANTIALIAS_RESAMPLE_THEN_EXACT_LOCAL_CROP"
        or config["preprocessing"]["strain_highpass"]
        != "GWPY_TIMESERIES_HIGHPASS_PARENT_CUTOFF_UNCHANGED_DEFAULTS"
        or config["preprocessing"]["resample"]
        != "GWPY_TIMESERIES_RESAMPLE_UNCHANGED_FIR_HAMMING_DEFAULTS_SKIP_EQUAL_RATE"
        or config["preprocessing"]["context"]
        != "EACH_INDIVIDUAL_FROZEN_CONTEXT_NOT_MERGED_TRANSPORT_SPAN"
        or config["scientific_boundary"]
        != {
            "post_hoc_target_selection": True,
            "diagnostic_only": True,
            "formal_p_value_or_fwer": False,
            "global_significance_claim": False,
            "astrophysical_origin_claim": False,
            "a2_promotion": False,
            "negative_clears_untested_channels": False,
            "historical_outputs_immutable": True,
            "local_screen_comparable_to_existing_intra_or_cross_detector_thresholds": False,
        }
    ):
        raise ContractError("local execution boundary changed")
    for ref in [config["method"], *config["preprocessing"]["historical_sources"]]:
        if sha256_file(ROOT / ref["path"]) != ref["sha256"]:
            raise ContractError("local execution method/history bytes changed")
    return config


def runtime_receipt(config: dict) -> dict:
    versions = {
        name: importlib.import_module(name).__version__
        for name in config["runtime_versions"]
    }
    if versions != config["runtime_versions"]:
        raise ContractError("local measurement library versions changed")
    modules = (
        "gwpy.timeseries.timeseries",
        "gwpy.signal.filter_design",
        "scipy.signal._spectral_py",
        "scipy.signal._signaltools",
        "numpy.fft._pocketfft",
    )
    return {
        "versions": versions,
        "implementation_sha256": {
            name: sha256_file(Path(inspect.getfile(importlib.import_module(name))))
            for name in modules
        },
    }


def git_source_audit(commit: str, sources: dict) -> dict:
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args])

    resolved = git("rev-parse", f"{commit}^{{commit}}").decode().strip()
    subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", resolved, "HEAD"],
        check=True,
    )
    audit = {}
    for name in sources:
        historical = git("show", f"{resolved}:{name}")
        current = (ROOT / name).read_bytes()
        if historical == current:
            audit[name] = "GIT_BYTE_IDENTICAL"
        elif (
            name not in NEW_SOURCES
            and historical.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") == current
        ):
            audit[name] = "EXACT_GIT_LF_TO_CRLF_RECONSTRUCTION_QUALIFIED"
        else:
            raise ContractError(f"source freeze Git mismatch: {name}")
    return {"commit": resolved, "qualification": audit}


def build_plan(commit: str) -> dict:
    config, design = load_config(), load_design(ROOT)
    input_root = _host_path(ROOT, config["matched_samples"]["root"])
    if (input_root / "controller.lock").exists() or (
        input_root / "failure.json"
    ).exists():
        raise ContractError("matched parent active/failed")
    saved = sealed_json(input_root / "plan.json")
    summary = sealed_json(input_root / "summary.json")
    ref = config["matched_samples"]
    if (
        saved != parent.build_plan()
        or saved["receipt_digest"] != ref["plan_digest"]
        or summary["receipt_digest"] != ref["summary_digest"]
        or sha256_file(input_root / "summary.json") != ref["summary_sha256"]
        or parent.verify_all(input_root, saved) != summary
    ):
        raise ContractError("matched native parent independent replay changed")
    metadata_config = parent.load_config()["input_metadata"]
    metadata_root = _host_path(ROOT, metadata_config["root"])
    metadata_plan = sealed_json(metadata_root / "plan.json")
    metadata_summary = sealed_json(metadata_root / "summary.json")
    if [
        {"detector": t["detector"], "gps_start": t["gps_start"]}
        for t in metadata_summary["targets"]
    ] != design["targets"]:
        raise ContractError("local two-target family identity changed")
    region = next(
        t
        for t in metadata_plan["feasibility"]["targets"]
        if t["gps_start"] == saved["target"]["gps_start"]
    )
    common = json.loads((ROOT / design["parents"]["common_method"]["path"]).read_text())
    names = tuple(
        dict.fromkeys(
            (
                *parent.SOURCES,
                *NEW_SOURCES,
                *(r["path"] for r in config["preprocessing"]["historical_sources"]),
            )
        )
    )
    sources = {name: sha256_file(ROOT / name) for name in names}
    return seal(
        {
            "status": "FROZEN_LOCAL_MEASUREMENT_PLAN_NO_OUTCOMES",
            "execution_contract": config,
            "method": design,
            "input_root": str(input_root),
            "input_plan_digest": saved["receipt_digest"],
            "input_summary_digest": summary["receipt_digest"],
            "target_region": region,
            "target_accounting": metadata_summary["targets"],
            "blocks": saved["target"]["blocks"],
            "channels": common["method"]["channels"]["L1"],
            "strain_highpass_hz": common["method"]["measurement"]["strain_highpass_hz"],
            "source_sha256": sources,
            "source_freeze": git_source_audit(commit, sources),
            "runtime": runtime_receipt(config),
            "network_access_allowed": False,
        }
    )


def result_summary(
    plan: dict, event: dict, blocks: list[dict], *, independent: bool
) -> dict:
    results = []
    for target in plan["target_accounting"]:
        if target["gps_start"] != plan["target_region"]["gps_start"]:
            if target["status"] != "INCONCLUSIVE":
                raise ContractError("unmeasured local target not metadata-inconclusive")
            results.append(target)
        else:
            results.append(
                {
                    "detector": target["detector"],
                    "gps_start": target["gps_start"],
                    "identity_digest": target["identity_digest"],
                    "event_value": event.get("value"),
                    "event_status": event["status"],
                    "metadata_eligible_blocks": sum(
                        b["eligible"] for b in plan["blocks"]
                    ),
                    "excluded_unavailable_blocks": sum(
                        b["status"] != "MEASURED" for b in blocks
                    ),
                    **decision_and_bootstrap(
                        event, blocks, plan["method"], independent=independent
                    ),
                }
            )
    return seal(
        {
            "status": "PASS_LOCAL_L1_MEASUREMENT_COMPLETE_DIAGNOSTIC_ONLY",
            "plan_digest": plan["receipt_digest"],
            "targets": results,
            "block_receipt_count": len(blocks),
            "context_count": sum(len(b["contexts"]) for b in blocks),
            "metadata_excluded_blocks": [
                b for b in plan["blocks"] if not b["eligible"]
            ],
            "scientific_boundary": plan["execution_contract"]["scientific_boundary"],
        }
    )


def run_measurement(run_dir: Path, plan: dict):
    parent_plan = sealed_json(Path(plan["input_root"]) / "plan.json")
    reader = NativeContextReader(
        Path(plan["input_root"]), parent_plan, plan["channels"]
    )
    event = measure_context(
        reader, plan["target_region"]["gps_start"], "event", plan, independent=False
    )
    _atomic_json(
        run_dir / "event.json", seal({"plan_digest": plan["receipt_digest"], **event})
    )
    blocks = []
    for block in plan["blocks"]:
        if not block["eligible"]:
            continue
        starts = block["context_starts_gps"]
        contexts = [
            measure_context(reader, start, "background", plan, independent=False)
            for start in starts
        ]
        record = block_record(contexts, starts, plan["method"])
        _atomic_json(
            run_dir / "blocks" / f"{starts[0]}.json",
            seal({"plan_digest": plan["receipt_digest"], **record}),
        )
        blocks.append(record)
        _atomic_json(
            run_dir / "progress.json",
            seal(
                {"plan_digest": plan["receipt_digest"], "accounted_blocks": len(blocks)}
            ),
        )
    # Catch input/source changes during measurement before sealing a terminal result.
    if build_plan(plan["source_freeze"]["commit"]) != plan:
        raise ContractError("local input/source changed during measurement")
    _atomic_json(
        run_dir / "summary.json", result_summary(plan, event, blocks, independent=False)
    )


def verify_measurement(run_dir: Path, plan: dict):
    if (run_dir / "controller.lock").exists() or list(run_dir.rglob("*.partial")):
        raise ContractError("local measurement active/partial")
    eligible = [b for b in plan["blocks"] if b["eligible"]]
    expected = {
        run_dir / "blocks" / f"{b['context_starts_gps'][0]}.json" for b in eligible
    }
    if set((run_dir / "blocks").glob("*.json")) != expected:
        raise ContractError("local complete block receipt set changed")
    parent_plan = sealed_json(Path(plan["input_root"]) / "plan.json")
    reader = NativeContextReader(
        Path(plan["input_root"]), parent_plan, plan["channels"]
    )
    event = measure_context(
        reader, plan["target_region"]["gps_start"], "event", plan, independent=True
    )
    if sealed_json(run_dir / "event.json") != seal(
        {"plan_digest": plan["receipt_digest"], **event}
    ):
        raise ContractError("local event exact replay changed")
    blocks = []
    for block in eligible:
        starts = block["context_starts_gps"]
        contexts = [
            measure_context(reader, start, "background", plan, independent=True)
            for start in starts
        ]
        record = block_record(contexts, starts, plan["method"])
        if sealed_json(run_dir / "blocks" / f"{starts[0]}.json") != seal(
            {"plan_digest": plan["receipt_digest"], **record}
        ):
            raise ContractError("local block exact replay changed")
        blocks.append(record)
    summary = result_summary(plan, event, blocks, independent=True)
    if sealed_json(run_dir / "summary.json") != summary:
        raise ContractError("local independent decision/bootstrap/summary mismatch")
    if build_plan(plan["source_freeze"]["commit"]) != plan:
        raise ContractError("local input/source changed during verification")
    return seal(
        {
            "status": "PASS_VERIFIED_LOCAL_L1_DIAGNOSTIC_ONLY",
            "plan_digest": plan["receipt_digest"],
            "summary_digest": summary["receipt_digest"],
            "summary_sha256": sha256_file(run_dir / "summary.json"),
            "block_receipt_count": len(blocks),
            "target_count": len(summary["targets"]),
            "independent_fft_replay": True,
            "exact_producer_replay": True,
        }
    )


def main(stage: str, run_dir_arg: str | None, commit: str | None) -> int:
    if not commit:
        raise ContractError("explicit local source-freeze commit required")
    plan = build_plan(commit)
    run_dir = (
        _host_path(ROOT, plan["execution_contract"]["output_root"])
        / f"local_{plan['receipt_digest']}"
    )
    if run_dir_arg:
        supplied = (
            _host_path(ROOT, run_dir_arg)
            if not Path(run_dir_arg).is_absolute()
            else Path(run_dir_arg)
        )
        if supplied.resolve() != run_dir.resolve():
            raise ContractError("local measurement exact run key required")
    if stage == "plan":
        if (run_dir / "plan.json").exists():
            if sealed_json(run_dir / "plan.json") != plan:
                raise ContractError("local measurement existing plan changed")
        elif run_dir.exists() and any(run_dir.iterdir()):
            raise ContractError("local measurement plan directory nonempty")
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            _atomic_json(run_dir / "plan.json", plan)
        print(json.dumps({"status": plan["status"], "run_dir": str(run_dir)}))
        return 0
    if not run_dir_arg or sealed_json(run_dir / "plan.json") != plan:
        raise ContractError("local measurement explicit frozen plan needed")
    if (run_dir / "failure.json").exists():
        raise ContractError("local failed: preserve evidence, no automatic resume")
    if stage == "run":
        if (run_dir / "summary.json").exists():
            raise ContractError("local measurement already terminal")
        with _single_controller(run_dir):
            try:
                run_measurement(run_dir, plan)
            except Exception as exc:
                _atomic_json(
                    run_dir / "failure.json",
                    seal(
                        {
                            "status": "FAILED_LOCAL_MEASUREMENT_REQUIRES_REVIEW",
                            "plan_digest": plan["receipt_digest"],
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    ),
                )
                raise
        status = "PASS_LOCAL_L1_MEASUREMENT_COMPLETE_DIAGNOSTIC_ONLY"
    elif stage == "verify":
        receipt = verify_measurement(run_dir, plan)
        _atomic_json(run_dir / "verification.json", receipt)
        status = receipt["status"]
    else:
        raise ValueError(stage)
    print(json.dumps({"status": status, "run_dir": str(run_dir)}))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "run", "verify"), required=True)
    parser.add_argument("--run-dir")
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.stage, args.run_dir, args.source_commit))
