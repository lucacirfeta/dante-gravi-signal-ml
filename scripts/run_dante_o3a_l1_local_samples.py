"""Acquire and independently replay matched L1 samples; no local PEM outcomes."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import preflight_dante_o3a_l1_local_inputs as parent  # noqa: E402
from scripts.run_dante_o3a_o4a_common_pem_background_acquisition import (  # noqa: E402
    _single_controller,
)
from src.core.index_contract import sha256_file  # noqa: E402
from src.dante_light.contracts import ContractError, canonical_json_sha256  # noqa: E402
from src.dante_light.o3a_l1_local_followup import load_design  # noqa: E402
from src.dante_light.o3a_l1_local_samples import auxiliary_specs, transport_intervals  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_acquisition import _atomic_json, sealed_json  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_acquisition_v2 import (  # noqa: E402
    acquire_frame_v2,
    required_frames_with_probes,
    verify_frame_v2,
)
from src.dante_light.o3a_o4a_common_pem_aux_samples import (  # noqa: E402
    InfrastructureError,
    acquire_series,
    data_path,
    verify_series,
)
from src.dante_light.o3a_o4a_common_pem_background import verify_background_receipt  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_contract import _host_path  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_gate import parse_official_frame_manifest  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_span_replay import produce_span_receipt  # noqa: E402

CONFIG_PATH = "config/dante_o3a_l1_local_samples_v1.json"
SOURCES = (
    *parent.SOURCES,
    CONFIG_PATH,
    "src/dante_light/o3a_l1_local_samples.py",
    "scripts/run_dante_o3a_l1_local_samples.py",
    "src/dante_light/o3a_o4a_common_pem_acquisition_v2.py",
    "src/dante_light/o3a_o4a_common_pem_aux_samples.py",
    "src/dante_light/o3a_o4a_common_pem_background.py",
    "src/dante_light/o3a_o4a_common_pem_gate.py",
    "src/dante_light/o3a_o4a_common_pem_span_replay.py",
)


def seal(body: dict) -> dict:
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def load_config() -> dict:
    config = json.loads((ROOT / CONFIG_PATH).read_text())
    if (
        config["schema_version"] != 1
        or config["contract_id"] != "dante-o3a-l1-local-matched-samples-v1"
        or config["strain_source"]["run"] != "O3a"
        or config["transport"]
        != {
            "grouping": "MERGE_ONLY_EXACTLY_ADJACENT_ACCEPTED_CONTEXTS_NO_GAP_FILLING",
            "native_rates_and_nds_policy": "INHERIT_HASH_BOUND_AUXILIARY_NATIVE_RATES_CONTRACT",
            "event_auxiliary_policy": "VERIFY_AND_REFERENCE_EXISTING_EXACT_NATIVE_EVENT_FILES_NO_REFETCH",
            "strain_policy": "OFFICIAL_MD5_AND_METADATA_THEN_ALL_USED_SAMPLES_INDEPENDENT_LOCAL_REPLAY",
            "probe_policy": "INHERIT_V2_EARLIEST_USED_ONE_SECOND_PROBE",
            "sample_cast_resample_filter_allowed": False,
            "resume_on_failure_automatic": False,
            "partial_acquisition_interpretable": False,
        }
    ):
        raise ContractError("matched samples transport policy changed")
    if config["status"] != "FROZEN_TRANSPORT_ONLY_NO_LOCAL_PEM_MEASUREMENT" or config[
        "scientific_boundary"
    ] != {
        "transport_only": True,
        "local_coherence_opened": False,
        "local_reference_tail_opened": False,
        "sensor_veto_safety_established": False,
        "global_significance_claim": False,
        "historical_artifacts_modified": False,
    }:
        raise ContractError("matched samples scientific boundary changed")
    for ref in (config["method"], config["strain_source"]):
        if sha256_file(_host_path(ROOT, ref["path"])) != ref["sha256"]:
            raise ContractError("matched samples parent file changed")
    return config


def build_plan() -> dict:
    config = load_config()
    design = load_design(ROOT)
    metadata_dir = _host_path(ROOT, config["input_metadata"]["root"])
    metadata_plan = sealed_json(metadata_dir / "plan.json")
    metadata = sealed_json(metadata_dir / "summary.json")
    ref = config["input_metadata"]
    if (
        metadata_plan != parent.plan()
        or metadata_plan["receipt_digest"] != ref["plan_digest"]
        or metadata["receipt_digest"] != ref["summary_digest"]
        or sha256_file(metadata_dir / "summary.json") != ref["summary_sha256"]
    ):
        raise ContractError("matched sample metadata parent changed")
    # Offline metadata replay, no NDS2 query or sample read.
    parent.main("verify", str(metadata_dir))
    usable = [
        t for t in metadata["targets"] if t["status"] == "PASS_DQ_AUX_METADATA_ONLY"
    ]
    expected = config["expected"]
    if len(usable) != expected["measured_target_count"]:
        raise ContractError("matched sample target population changed")
    target = usable[0]
    duration = design["controls"]["context_duration_s"]
    intervals = transport_intervals(target["blocks"], duration)
    if (
        target["eligible_reference_blocks"] != expected["eligible_blocks"]
        or sum(b["eligible"] for b in target["blocks"]) != expected["eligible_blocks"]
        or sum(end - start for start, end in intervals) // duration
        != expected["control_contexts"]
        or len(intervals) != expected["control_transport_intervals"]
    ):
        raise ContractError("matched sample block/context accounting changed")
    common = json.loads((ROOT / design["parents"]["common_method"]["path"]).read_text())
    inputs = json.loads((ROOT / design["parents"]["common_inputs"]["path"]).read_text())
    native = json.loads((ROOT / design["parents"]["native_pem"]["path"]).read_text())
    rates = json.loads(
        (ROOT / design["parents"]["auxiliary_native_rates"]["path"]).read_text()
    )
    channels = common["method"]["channels"]["L1"]
    specs = auxiliary_specs(
        intervals,
        channels=channels,
        rates=rates["sample_rate_hz"]["L1"],
        target_gps=target["gps_start"],
    )
    if (
        len(specs) != expected["control_auxiliary_series"]
        or sum(s["sample_count"] * 4 for s in specs)
        != expected["control_auxiliary_sample_bytes"]
    ):
        raise ContractError("matched native sample exposure changed")
    aux_root = _host_path(ROOT, inputs["input_roots"]["auxiliary_samples"])
    aux_plan, aux_summary = (
        sealed_json(aux_root / "plan.json"),
        sealed_json(aux_root / "summary.json"),
    )
    if (
        (aux_root / "controller.lock").exists()
        or (aux_root / "failure.json").exists()
        or aux_plan["receipt_digest"] != aux_root.name.removeprefix("aux_samples_")
        or aux_summary["status"] != "PASS_AUX_NATIVE_SAMPLES_COMPLETE_ONLY"
        or aux_summary["plan_digest"] != aux_plan["receipt_digest"]
    ):
        raise ContractError("borrowed native event parent active/failed/changed")
    event_interval = [target["gps_start"], target["gps_start"] + duration]
    event_specs = [
        s
        for s in aux_plan["series"]
        if s["run"] == "O3a"
        and s["detector"] == "L1"
        and s["interval_gps"] == event_interval
        and s["channel"] in channels
        and {"target_gps": target["gps_start"], "role": "event"} in s["uses"]
    ]
    if (
        len(event_specs) != expected["borrowed_event_auxiliary_series"]
        or {s["channel"] for s in event_specs} != set(channels)
        or any(
            s["sample_rate_hz"] != rates["sample_rate_hz"]["L1"][s["channel"]]
            or s["sample_count"] != duration * s["sample_rate_hz"]
            for s in event_specs
        )
    ):
        raise ContractError("borrowed native event exact channel/interval missing")
    background = json.loads((ROOT / config["strain_source"]["path"]).read_text())
    source = background["sources"][config["strain_source"]["run"]]
    manifest_path = (
        _host_path(ROOT, inputs["input_roots"]["background_acquisition"])
        / "O3a_strain_hdf_md5.txt"
    )
    if sha256_file(manifest_path) != source["manifest_sha256"]:
        raise ContractError("matched strain official manifest changed")
    manifest = parse_official_frame_manifest(
        manifest_path.read_bytes(),
        release=source["release"],
        frame_duration_s=source["frame_duration_s"],
    )
    spans = [
        {"detector": "L1", "interval_gps": interval, "role": "background"}
        for interval in intervals
    ]
    spans.append({"detector": "L1", "interval_gps": event_interval, "role": "event"})
    frames = required_frames_with_probes(
        spans, manifest=manifest, frame_duration_s=source["frame_duration_s"]
    )
    return seal(
        {
            "status": "FROZEN_MATCHED_NATIVE_SAMPLE_PLAN_NO_OUTCOMES",
            "contract_digest": canonical_json_sha256(config),
            "source_sha256": {f: sha256_file(ROOT / f) for f in SOURCES},
            "metadata_plan_digest": metadata_plan["receipt_digest"],
            "metadata_summary_digest": metadata["receipt_digest"],
            "target": target,
            "spans": spans,
            "frames": frames,
            "strain_source": source,
            "manifest_path": str(manifest_path),
            "manifest_sha256": source["manifest_sha256"],
            "auxiliary_series": specs,
            "event_auxiliary_specs": event_specs,
            "event_auxiliary_parent_root": str(aux_root),
            "event_auxiliary_parent_digest": aux_plan["receipt_digest"],
            "nds_host": native["execution"]["nds_host"],
            "execution": rates["execution"],
            "expected": expected,
        }
    )


def manifest_for(plan: dict) -> dict:
    path = Path(plan["manifest_path"])
    if sha256_file(path) != plan["manifest_sha256"]:
        raise ContractError("matched samples saved manifest changed")
    return parse_official_frame_manifest(
        path.read_bytes(),
        release=plan["strain_source"]["release"],
        frame_duration_s=plan["strain_source"]["frame_duration_s"],
    )


def span_path(run_dir: Path, span: dict) -> Path:
    return (
        run_dir
        / "strain_receipts"
        / f"{span['role']}_{span['interval_gps'][0]}_{span['interval_gps'][1]}.json"
    )


def event_aux_receipts(plan: dict) -> list[dict]:
    root = Path(plan["event_auxiliary_parent_root"])
    result = []
    for spec in plan["event_auxiliary_specs"]:
        path = root / "receipts" / f"{spec['key']}.json"
        receipt = sealed_json(path)
        if receipt["nds_host"] != plan["nds_host"]:
            raise ContractError("borrowed event native source changed")
        verify_series(
            spec,
            receipt,
            run_dir=root,
            chunk_seconds=plan["execution"]["chunk_seconds"],
        )
        result.append(
            {
                "spec": spec,
                "receipt_path": str(path),
                "receipt_sha256": sha256_file(path),
                "file_sha256": receipt["file_sha256"],
                "samples_sha256": receipt["samples_sha256"],
            }
        )
    return result


def fetch_aux(channel: str, *, start: int, end: int, host: str):
    from gwpy.timeseries import TimeSeries

    return TimeSeries.fetch(channel, start, end, host=host)


def verify_all(run_dir: Path, plan: dict) -> dict:
    manifest = manifest_for(plan)
    expected_frames = {
        run_dir / "frame_acquisition" / "receipts" / f"{f['filename']}.json"
        for f in plan["frames"]
    }
    expected_files = {
        run_dir / "frame_acquisition" / "frames" / f["filename"] for f in plan["frames"]
    }
    expected_aux = {
        run_dir / "auxiliary" / "receipts" / f"{s['key']}.json"
        for s in plan["auxiliary_series"]
    }
    if (
        set((run_dir / "frame_acquisition" / "receipts").glob("*.json"))
        != expected_frames
        or set((run_dir / "frame_acquisition" / "frames").glob("*.hdf5"))
        != expected_files
        or set((run_dir / "auxiliary" / "receipts").glob("*.json")) != expected_aux
        or set((run_dir / "auxiliary" / "data").glob("*.npy"))
        != {data_path(run_dir / "auxiliary", s) for s in plan["auxiliary_series"]}
        or set((run_dir / "strain_receipts").glob("*.json"))
        != {span_path(run_dir, s) for s in plan["spans"]}
        or list(run_dir.rglob("*.partial"))
        or list(run_dir.rglob("*.partial.npy"))
    ):
        raise ContractError("matched sample complete file/receipt set changed")
    for frame in plan["frames"]:
        verify_frame_v2(
            frame,
            source=plan["strain_source"],
            manifest=manifest,
            run_dir=run_dir / "frame_acquisition",
        )
    for span in plan["spans"]:
        receipt = sealed_json(span_path(run_dir, span))
        if (
            receipt["plan_digest"] != plan["receipt_digest"]
            or receipt["identity"] != span
        ):
            raise ContractError("matched strain receipt identity changed")
        verify_background_receipt(
            receipt["strain"],
            source=plan["strain_source"],
            manifest=manifest,
            cache_dir=run_dir / "frame_acquisition" / "frames",
        )
    for spec in plan["auxiliary_series"]:
        receipt = sealed_json(
            run_dir / "auxiliary" / "receipts" / f"{spec['key']}.json"
        )
        if receipt["nds_host"] != plan["nds_host"]:
            raise ContractError("matched auxiliary source host changed")
        verify_series(
            spec,
            receipt,
            run_dir=run_dir / "auxiliary",
            chunk_seconds=plan["execution"]["chunk_seconds"],
        )
    event = event_aux_receipts(plan)
    if sealed_json(run_dir / "event_auxiliary_references.json") != seal(
        {"plan_digest": plan["receipt_digest"], "references": event}
    ):
        raise ContractError("matched borrowed event reference changed")
    return seal(
        {
            "status": "PASS_MATCHED_NATIVE_SAMPLES_COMPLETE_ONLY",
            "plan_digest": plan["receipt_digest"],
            "frame_count": len(plan["frames"]),
            "strain_span_count": len(plan["spans"]),
            "control_auxiliary_series_count": len(plan["auxiliary_series"]),
            "borrowed_event_auxiliary_count": len(event),
            "eligible_block_count": plan["expected"]["eligible_blocks"],
            "control_context_count": plan["expected"]["control_contexts"],
            "local_pem_outcomes_opened": False,
            "source_reacquisition_independent": False,
        }
    )


def main(stage: str, run_dir_arg: str | None) -> int:
    config = load_config()
    plan = build_plan()
    root = _host_path(ROOT, config["output_root"])
    run_dir = root / f"samples_{plan['receipt_digest']}"
    if run_dir_arg:
        supplied = Path(run_dir_arg)
        if not supplied.is_absolute():
            supplied = _host_path(ROOT, run_dir_arg)
        if supplied.resolve() != run_dir.resolve():
            raise ContractError("matched samples run key changed")
    if stage == "plan":
        if (run_dir / "plan.json").exists():
            if sealed_json(run_dir / "plan.json") != plan:
                raise ContractError("matched samples existing plan changed")
        elif run_dir.exists() and any(run_dir.iterdir()):
            raise ContractError("matched samples existing directory nonempty")
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            _atomic_json(run_dir / "plan.json", plan)
        print(
            json.dumps(
                {
                    "status": plan["status"],
                    "run_dir": str(run_dir),
                    "frame_count": len(plan["frames"]),
                    "auxiliary_series_count": len(plan["auxiliary_series"]),
                    "strain_span_count": len(plan["spans"]),
                }
            )
        )
        return 0
    if not run_dir_arg or sealed_json(run_dir / "plan.json") != plan:
        raise ContractError("matched samples explicit frozen run needed")
    if (run_dir / "failure.json").exists():
        raise ContractError(
            "matched samples failed: preserve evidence, no automatic resume"
        )
    if stage == "run":
        if (run_dir / "summary.json").exists():
            raise ContractError("matched samples already terminal")
        with _single_controller(run_dir):
            try:
                required_bytes = (
                    plan["expected"]["control_auxiliary_sample_bytes"]
                    + len(plan["frames"])
                    * plan["strain_source"]["frame_duration_s"]
                    * plan["strain_source"]["sample_rate_hz"]
                    * 8
                )
                if (
                    shutil.disk_usage(run_dir).free
                    < required_bytes
                    * plan["execution"]["minimum_free_space_multiplier"]
                ):
                    raise InfrastructureError(
                        "matched sample disk headroom insufficient"
                    )
                refs = event_aux_receipts(plan)
                _atomic_json(
                    run_dir / "event_auxiliary_references.json",
                    seal({"plan_digest": plan["receipt_digest"], "references": refs}),
                )
                manifest = manifest_for(plan)
                for i, frame in enumerate(plan["frames"], start=1):
                    acquire_frame_v2(
                        frame,
                        source=plan["strain_source"],
                        manifest=manifest,
                        run_dir=run_dir / "frame_acquisition",
                    )
                    _atomic_json(
                        run_dir / "progress.json",
                        seal(
                            {
                                "stage": "OFFICIAL_STRAIN_FRAMES",
                                "completed": i,
                                "expected": len(plan["frames"]),
                            }
                        ),
                    )
                for i, span in enumerate(plan["spans"], start=1):
                    value = produce_span_receipt(
                        detector=span["detector"],
                        start=span["interval_gps"][0],
                        end=span["interval_gps"][1],
                        source=plan["strain_source"],
                        manifest=manifest,
                        cache_dir=run_dir / "frame_acquisition" / "frames",
                    )
                    _atomic_json(
                        span_path(run_dir, span),
                        seal(
                            {
                                "plan_digest": plan["receipt_digest"],
                                "identity": span,
                                "strain": value,
                            }
                        ),
                    )
                    _atomic_json(
                        run_dir / "progress.json",
                        seal(
                            {
                                "stage": "STRAIN_FULL_SPANS",
                                "completed": i,
                                "expected": len(plan["spans"]),
                            }
                        ),
                    )
                for i, spec in enumerate(plan["auxiliary_series"], start=1):
                    value = acquire_series(
                        spec,
                        run_dir=run_dir / "auxiliary",
                        nds_host=plan["nds_host"],
                        chunk_seconds=plan["execution"]["chunk_seconds"],
                        retries=plan["execution"]["fetch_retries"],
                        backoff_base_s=plan["execution"]["backoff_base_s"],
                        fetch=fetch_aux,
                    )
                    _atomic_json(
                        run_dir / "auxiliary" / "receipts" / f"{spec['key']}.json",
                        seal(value),
                    )
                    _atomic_json(
                        run_dir / "progress.json",
                        seal(
                            {
                                "stage": "NATIVE_AUXILIARY_SERIES",
                                "completed": i,
                                "expected": len(plan["auxiliary_series"]),
                            }
                        ),
                    )
                summary = verify_all(run_dir, plan)
                _atomic_json(run_dir / "summary.json", summary)
            except Exception as exc:
                _atomic_json(
                    run_dir / "failure.json",
                    seal(
                        {
                            "status": "FAILED_INFRASTRUCTURE"
                            if isinstance(
                                exc,
                                (
                                    InfrastructureError,
                                    URLError,
                                    TimeoutError,
                                    ConnectionError,
                                ),
                            )
                            else "FAILED_STRUCTURAL_OR_PROVENANCE_REQUIRES_REVIEW",
                            "plan_digest": plan["receipt_digest"],
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    ),
                )
                raise
    elif stage == "verify":
        if (run_dir / "controller.lock").exists():
            raise ContractError("matched sample controller still active")
        if sealed_json(run_dir / "summary.json") != verify_all(run_dir, plan):
            raise ContractError("matched sample summary replay changed")
    else:
        raise ValueError(stage)
    print(
        json.dumps(
            {
                "status": "PASS_VERIFIED_MATCHED_NATIVE_SAMPLES_ONLY"
                if stage == "verify"
                else "PASS_MATCHED_NATIVE_SAMPLES_COMPLETE_ONLY",
                "control_contexts": plan["expected"]["control_contexts"],
                "eligible_blocks": plan["expected"]["eligible_blocks"],
                "local_pem_outcomes_opened": False,
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
