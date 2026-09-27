#!/usr/bin/env python3
"""Read-only official-frame coverage preflight for paired PEM background nulls.

Uses already-verified historical null spans only to plan transport. The
productive run must independently recompute span choice and null statistics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError  # noqa: E402
from src.dante_light.contracts import canonical_json_sha256  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_contract import load_contract  # noqa: E402
from src.dante_light.o3a_o4a_common_pem_gate import (  # noqa: E402
    load_background_source_contract,
    parse_official_frame_manifest,
    plan_background_frames,
)
from src.dante_light.o3a_raw_acquisition import (  # noqa: E402
    load_source_inventory,
)
from src.dante_light.o3a_native_pem import preflight_inputs as o3a_inputs  # noqa: E402
from src.dante_light.o4a_corrected_native_pem import (  # noqa: E402
    _external_inputs as o4a_inputs,
    load_native_pem_contract as load_o4a_pem_contract,
)
from src.dante_light.o4a_pem_raw_replay import (  # noqa: E402
    _host_path,
)
from src.pipeline_v2_production.pem_null_calibration import (  # noqa: E402
    _pick_background_span,
)


def _load_targets(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _fetch_manifest(url: str, *, release: str, duration: int) -> tuple[dict, str]:
    with urlopen(url, timeout=60) as response:
        data = response.read()
    return (
        parse_official_frame_manifest(data, release=release, frame_duration_s=duration),
        hashlib.sha256(data).hexdigest(),
    )


def _full_exclusion(run: str) -> list[float]:
    if run == "O3a":
        _, _, exclusion = o3a_inputs(root=ROOT)
        return exclusion
    parent = load_o4a_pem_contract(root=ROOT)
    coincidence = json.loads(
        (ROOT / parent["references"]["native_coincidence"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    classification = json.loads(
        (ROOT / parent["references"]["native_classification"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    _, exclusion, _ = o4a_inputs(
        root=ROOT,
        contract=parent,
        coincidence_external_root=_host_path(
            coincidence["external_run"]["directory"]
        ).parent,
        classification_external_root=_host_path(
            classification["external_run"]["directory"]
        ).parent,
    )
    return exclusion


def main(*, verify_span_selection: bool = False) -> int:
    comparison = load_contract(root=ROOT)
    background = load_background_source_contract(root=ROOT)
    block = int(comparison["method"]["measurement"]["background_block_s"])
    minimum = int(comparison["method"]["measurement"]["minimum_clean_windows"])
    o3a_inventory = load_source_inventory(root=ROOT)
    sources = background["sources"]
    report: dict = {"status": "PASS_BACKGROUND_FRAME_COVERAGE_ONLY", "runs": {}}
    for run in ("O3a", "O4a"):
        spec = comparison["runs"][run]
        source = sources[run]
        duration = int(source["frame_duration_s"])
        manifest, manifest_sha = _fetch_manifest(
            source["manifest_url"], release=source["release"], duration=duration
        )
        if manifest_sha != source["manifest_sha256"]:
            raise ContractError(f"common PEM {run} official manifest changed")
        targets = _load_targets(_host_path(spec["targets"]["path"]))
        exclusion = _full_exclusion(run) if verify_span_selection else []
        if verify_span_selection and (
            len(exclusion) != spec["candidate_exclusion"]["expected_count"]
            or canonical_json_sha256(exclusion) != spec["candidate_exclusion"]["digest"]
        ):
            raise ContractError(f"common PEM {run} full exclusion identity changed")
        run_dir = _host_path(spec["pem_summary"]["path"]).parent
        unique_frames: set[tuple[str, int]] = set()
        uses = 0
        for target in targets:
            detector, gps = str(target["detector"]), int(target["gps_start"])
            null_path = run_dir / f"null_calibration_{detector}_{gps}.json"
            if not null_path.is_file():
                raise ContractError(
                    f"common PEM {run} historical background null absent"
                )
            null = json.loads(null_path.read_text(encoding="utf-8"))
            span = null["background_span"]
            if (
                null["run"] != run
                or null["detector"] != detector
                or int(null["event_gps"]) != gps
                or null["candidate_exclusion_digest"]
                != spec["candidate_exclusion"]["digest"]
                or null["candidate_exclusion_population"]
                != spec["candidate_exclusion"]["expected_count"]
                or len(span) != 2
                or span[1] - span[0] != block
                or null["n_windows"] < minimum
            ):
                raise ContractError(f"common PEM {run} historical span receipt changed")
            if verify_span_selection:
                replay_start, replay_end, windows = _pick_background_span(
                    detector,
                    float(gps),
                    float(block),
                    run,
                    min_clean_windows=minimum,
                    candidate_gps=np.asarray(exclusion, dtype=np.float64),
                )
                if [replay_start, replay_end] != span or len(windows) != null[
                    "n_windows"
                ]:
                    raise ContractError(
                        f"common PEM {run} background span replay changed"
                    )
            pieces = plan_background_frames(
                detector=detector,
                start=int(span[0]),
                end=int(span[1]),
                manifest=manifest,
                frame_duration_s=duration,
            )
            uses += len(pieces)
            unique_frames.update((detector, int(item["gps_start"])) for item in pieces)
            if run == "O3a":
                published_urls = set(o3a_inventory["urls_by_detector"][detector])
                for item in pieces:
                    expected = (
                        f"https://gwosc.org/archive/data/{source['release']}/"
                        + str(item["relative_path"]).split("/", 1)[1]
                    )
                    if expected not in published_urls:
                        raise ContractError(
                            "common PEM O3a background frame outside frozen inventory"
                        )
        report["runs"][run] = {
            "target_total": len(targets),
            "manifest_sha256": manifest_sha,
            "manifest_frame_total": len(manifest),
            "required_unique_frames": len(unique_frames),
            "frame_uses": uses,
            "span_selection_replayed": len(targets) if verify_span_selection else 0,
        }
        if (
            len(unique_frames) != source["required_unique_frames_preflight"]
            or len(targets) != source["historical_span_selection_replayed"]
        ):
            raise ContractError(f"common PEM {run} frozen coverage changed")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-span-selection", action="store_true")
    args = parser.parse_args()
    raise SystemExit(main(verify_span_selection=args.verify_span_selection))
