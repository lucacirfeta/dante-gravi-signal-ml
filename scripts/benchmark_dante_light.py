#!/usr/bin/env python3
"""Benchmark the exact canonical DANTE path on the frozen Light corpus."""

from __future__ import annotations

import argparse
from collections import defaultdict
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.index_contract import sha256_file  # noqa: E402
from src.core.patch_scorer import PatchScorer  # noqa: E402
from src.dante_light.contracts import (  # noqa: E402
    FailClosedReason,
    RepresentationContract,
    WindowIdentity,
)


DEFAULT_MANIFEST = ROOT / "config" / "dante_light_replay_v1.json"
DEFAULT_OUTPUT = ROOT / "benchmarks" / "dante_light_l0_baseline.json"
PRIMARY_INDEX = ROOT / "data" / "reference" / "patch_compressed_index_o3b.npz"
NATIVE_INDEX = (
    ROOT / "data" / "reference" / "patch_compressed_index_o4a_q4-64_ex.npz"
)


def percentile_summary(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    if not len(array):
        return {"count": 0, "total_s": 0.0, "p50_s": 0.0, "p95_s": 0.0, "p99_s": 0.0}
    return {
        "count": int(len(array)),
        "total_s": float(array.sum()),
        "p50_s": float(np.quantile(array, 0.50)),
        "p95_s": float(np.quantile(array, 0.95)),
        "p99_s": float(np.quantile(array, 0.99)),
    }


def source_hashes() -> dict[str, str]:
    paths = (
        Path(__file__).resolve(),
        ROOT / "src/core/patch_scorer.py",
        ROOT / "src/core/data_loader.py",
        ROOT / "src/core/preprocessor.py",
        ROOT / "src/core/model_loader.py",
        ROOT / "src/dante_light/contracts.py",
    )
    return {
        path.relative_to(ROOT).as_posix(): sha256_file(path) for path in paths
    }


def git_state() -> dict[str, Any]:
    def command(*args: str) -> str | None:
        try:
            return subprocess.check_output(
                ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    status = command("status", "--porcelain", "--untracked-files=no")
    return {
        "commit": command("rev-parse", "HEAD"),
        "branch": command("branch", "--show-current"),
        "tracked_dirty": None if status is None else bool(status),
    }


def environment(device) -> dict[str, Any]:
    import torch

    gpu = None
    if device.type == "cuda":
        gpu = torch.cuda.get_device_name(device)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "ram_bytes": physical_memory_bytes(),
        "torch": torch.__version__,
        "device": str(device),
        "gpu": gpu,
    }


def physical_memory_bytes() -> int | None:
    try:
        if os.name == "nt":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total_physical)
            return None
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size)
    except (AttributeError, OSError, ValueError):
        return None


def process_rss_bytes() -> int:
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("page_fault_count", wintypes.DWORD),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counters.working_set_size)
    import resource

    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def render_window(identity: WindowIdentity, *, local_only: bool) -> tuple[np.ndarray, str, dict[str, float]]:
    import matplotlib.pyplot as plt

    from src.core.data_loader import fetch_strain_data
    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )

    stages: dict[str, float] = {}
    start = identity.gps_start
    end = start + identity.duration_s
    began = time.perf_counter()
    strain = fetch_strain_data(
        identity.detector,
        start - 4.0,
        end + 4.0,
        local_only=local_only,
    )
    stages["data_read_s"] = time.perf_counter() - began
    actual_start = float(strain.t0.value)
    actual_end = actual_start + float(strain.duration.value)
    tolerance = 1.0 / float(strain.sample_rate.value)
    if actual_start > start - 4.0 + tolerance or actual_end < end + 4.0 - tolerance:
        raise RuntimeError(
            f"{FailClosedReason.INCOMPLETE_DATA.value}: requested padded "
            f"[{start - 4.0}, {end + 4.0}], got [{actual_start}, {actual_end}]"
        )
    input_sha256 = hashlib.sha256(
        np.ascontiguousarray(strain.value).tobytes()
    ).hexdigest()

    began = time.perf_counter()
    whitened, padding = whiten_context(strain, start, end, pad=4.0)
    clean = extract_clean_subwindow(whitened, start, end)
    stages["whitening_s"] = time.perf_counter() - began
    if padding["left"] or padding["right"]:
        raise RuntimeError(
            f"{FailClosedReason.INCOMPLETE_DATA.value}: whitening padding {padding}"
        )
    if abs(float(clean.duration.value) - identity.duration_s) > tolerance:
        raise RuntimeError(
            f"{FailClosedReason.INCOMPLETE_DATA.value}: clean duration "
            f"{clean.duration.value} != {identity.duration_s}"
        )

    began = time.perf_counter()
    spectrogram = generate_qtransform(clean, save_path=None, cmap="cividis")
    stages["q_transform_s"] = time.perf_counter() - began
    began = time.perf_counter()
    rgba = plt.get_cmap("cividis")(spectrogram)
    image = (rgba[:, :, :3] * 255).astype(np.uint8)
    stages["rendering_s"] = time.perf_counter() - began
    if image.shape != (256, 256, 3) or not np.all(np.isfinite(image)):
        raise RuntimeError(
            f"{FailClosedReason.NONFINITE_INPUT.value}: rendered image {image.shape}"
        )
    return image, input_sha256, stages


def score_once(
    item: dict[str, Any],
    primary: PatchScorer,
    native: PatchScorer,
    *,
    local_only: bool,
    persist_stream,
) -> tuple[dict[str, Any], dict[str, float]]:
    identity = WindowIdentity.from_dict(item["window"])
    total_began = time.perf_counter()
    image, input_sha256, stages = render_window(identity, local_only=local_only)
    primary_timing: dict[str, float] = {}
    native_timing: dict[str, float] = {}
    primary_result = primary.score_spectrogram(
        [image], threshold=1.0, timings=primary_timing
    )[0]
    native_result = native.score_spectrogram(
        [image], threshold=1.0, timings=native_timing
    )[0]
    stages.update({f"primary_{key}": value for key, value in primary_timing.items()})
    stages.update({f"native_{key}": value for key, value in native_timing.items()})
    expected = item.get("expected", {}).get("native_score")
    result = {
        "case_id": item["case_id"],
        "window_id": identity.window_id,
        "input_sha256": input_sha256,
        "primary_score": float(primary_result["novelty_score"]),
        "native_score": float(native_result["novelty_score"]),
        "expected_native_score": expected,
        "expected_abs_delta": (
            None if expected is None else abs(float(native_result["novelty_score"]) - float(expected))
        ),
        "primary_top_k_sha256": hashlib.sha256(
            primary_result["top_k_indices"].tobytes()
        ).hexdigest(),
        "native_top_k_sha256": hashlib.sha256(
            native_result["top_k_indices"].tobytes()
        ).hexdigest(),
    }
    persist_began = time.perf_counter()
    persist_stream.write(json.dumps(result, sort_keys=True, allow_nan=False) + "\n")
    persist_stream.flush()
    os.fsync(persist_stream.fileno())
    stages["persistence_s"] = time.perf_counter() - persist_began
    stages["end_to_end_s"] = time.perf_counter() - total_began
    return result, stages


def select_cases(manifest: dict, roles: set[str], limit: int) -> list[dict]:
    selected = [
        item
        for item in manifest["entries"]
        if item["source_kind"] != "synthetic_injection"
        and roles.intersection(item["roles"])
    ]
    # Interleave detectors deterministically instead of allowing case-id order
    # to produce a single-detector microbenchmark.
    selected.sort(
        key=lambda item: (
            item["window"]["gps_start"],
            item["window"]["detector"],
            item["case_id"],
        )
    )
    by_detector = {
        detector: [item for item in selected if item["window"]["detector"] == detector]
        for detector in sorted({item["window"]["detector"] for item in selected})
    }
    interleaved: list[dict] = []
    index = 0
    while len(interleaved) < min(limit, len(selected)):
        progressed = False
        for detector in sorted(by_detector):
            if index < len(by_detector[detector]):
                interleaved.append(by_detector[detector][index])
                progressed = True
                if len(interleaved) == limit:
                    break
        if not progressed:
            break
        index += 1
    return interleaved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--role", action="append", default=["background_stratified"])
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--device", default=None)
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()
    if args.limit <= 0 or args.repeat < 2 or args.warmup < 0:
        parser.error("limit must be positive, repeat >= 2, warmup >= 0")
    args.manifest = args.manifest.resolve()
    args.output = args.output.resolve()

    import torch

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries_path = ROOT / manifest["entries_path"]
    manifest["entries"] = [
        json.loads(line)
        for line in entries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if sha256_file(entries_path) != manifest["entries_file_sha256"]:
        raise RuntimeError("replay entry-file SHA256 mismatch")
    contract = RepresentationContract.from_reference_manifest(
        ROOT / "config/reference_artifacts.json"
    )
    selected = select_cases(manifest, set(args.role), args.limit)
    if not selected:
        raise RuntimeError("no replay cases match the requested roles")

    primary = PatchScorer(PRIMARY_INDEX, device=args.device, k=68)
    native = PatchScorer(NATIVE_INDEX, device=args.device, k=68)
    if primary.reference_sha256 != contract.primary_index_sha256:
        raise RuntimeError(f"{FailClosedReason.STALE_INDEX.value}: primary")
    if native.reference_sha256 != contract.native_index_sha256:
        raise RuntimeError(f"{FailClosedReason.STALE_INDEX.value}: native")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    results_path = args.output.with_suffix(".jsonl")
    stage_values: dict[str, list[float]] = defaultdict(list)
    failures: list[dict[str, Any]] = []
    warmup_results: list[dict[str, Any]] = []
    repeat_results: list[list[dict[str, Any]]] = []
    peak_rss = process_rss_bytes()
    peak_vram = 0
    with tempfile.NamedTemporaryFile(
        mode="w+", encoding="utf-8", delete=False, dir=args.output.parent
    ) as persisted:
        temporary_results = Path(persisted.name)
        for item in selected[: args.warmup]:
            try:
                result, _ = score_once(
                    item,
                    primary,
                    native,
                    local_only=args.local_only,
                    persist_stream=persisted,
                )
                warmup_results.append(result)
            except Exception as exc:
                failures.append(
                    {
                        "phase": "warmup",
                        "case_id": item["case_id"],
                        "disposition": "DEFER",
                        "reason": repr(exc),
                        "scores": {},
                    }
                )
        for repeat_index in range(args.repeat):
            current: list[dict[str, Any]] = []
            for item in selected:
                try:
                    result, timings = score_once(
                        item,
                        primary,
                        native,
                        local_only=args.local_only,
                        persist_stream=persisted,
                    )
                    result["repeat"] = repeat_index
                    current.append(result)
                    for name, value in timings.items():
                        stage_values[name].append(value)
                    peak_rss = max(peak_rss, process_rss_bytes())
                    if primary.device.type == "cuda":
                        peak_vram = max(peak_vram, torch.cuda.max_memory_allocated())
                except Exception as exc:
                    failures.append(
                        {
                            "phase": f"repeat_{repeat_index}",
                            "case_id": item["case_id"],
                            "disposition": "DEFER",
                            "reason": repr(exc),
                            "scores": {},
                        }
                    )
            repeat_results.append(current)
    temporary_results.replace(results_path)

    if failures:
        raise RuntimeError(
            f"benchmark has {len(failures)} fail-closed windows; first={failures[0]}"
        )
    expected_ids = [item["case_id"] for item in selected]
    for repeat in repeat_results:
        if [item["case_id"] for item in repeat] != expected_ids:
            raise RuntimeError("repeat coverage/order mismatch")
    numerical_max_delta = 0.0
    for index in range(len(selected)):
        primary_values = [repeat[index]["primary_score"] for repeat in repeat_results]
        native_values = [repeat[index]["native_score"] for repeat in repeat_results]
        numerical_max_delta = max(
            numerical_max_delta,
            max(primary_values) - min(primary_values),
            max(native_values) - min(native_values),
        )
    if numerical_max_delta > 1e-7:
        raise RuntimeError(
            f"repeat numerical mismatch: max score delta {numerical_max_delta}"
        )

    summaries = {name: percentile_summary(values) for name, values in stage_values.items()}
    end_to_end_total = summaries["end_to_end_s"]["total_s"]
    for summary in summaries.values():
        summary["fraction_of_end_to_end"] = (
            0.0 if end_to_end_total == 0 else summary["total_s"] / end_to_end_total
        )
    measured_windows = sum(len(value) for value in repeat_results)
    report = {
        "schema_version": 1,
        "status": "complete",
        "benchmark": "dante_light_l0_canonical_dual_index",
        "scientific_mode": "historical_exact_replay",
        "prefilter": "none",
        "warmup_excluded_from_summary": True,
        "manifest": {
            "path": args.manifest.relative_to(ROOT).as_posix(),
            "file_sha256": sha256_file(args.manifest),
            "entries_path": entries_path.relative_to(ROOT).as_posix(),
            "entries_file_sha256": sha256_file(entries_path),
            "manifest_sha256": manifest["manifest_sha256"],
            "entries_sha256": manifest["entries_sha256"],
        },
        "representation": contract.to_dict(),
        "source_sha256": source_hashes(),
        "code_state": git_state(),
        "environment": environment(primary.device),
        "selection": {
            "roles": sorted(set(args.role)),
            "requested_limit": args.limit,
            "selected_case_ids": expected_ids,
            "repeat_count": args.repeat,
            "warmup_count": len(warmup_results),
            "local_only": args.local_only,
        },
        "coverage": {
            "measured_windows": measured_windows,
            "failures": failures,
            "drops": 0,
            "queue_depth": 0,
        },
        "resources": {"peak_rss_bytes": peak_rss, "peak_vram_bytes": peak_vram},
        "numerical_repeat_max_abs_delta": numerical_max_delta,
        "throughput_windows_per_s": measured_windows / end_to_end_total,
        "stage_timings": summaries,
        "results_jsonl": {
            "path": results_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(results_path),
            "rows": measured_windows + len(warmup_results),
        },
        "results": repeat_results,
    }
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "windows": measured_windows,
        "throughput_windows_per_s": report["throughput_windows_per_s"],
        "repeat_max_abs_delta": numerical_max_delta,
        "peak_rss_bytes": peak_rss,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
