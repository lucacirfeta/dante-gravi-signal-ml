#!/usr/bin/env python3
"""Build the immutable, manifest-only DANTE-Light L0 replay corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import (  # noqa: E402
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)


AGG = ROOT / "data" / "production" / "aggregated"
DEFAULT_OUTPUT = ROOT / "config" / "dante_light_replay_v1.json"
TAXONOMY = AGG / "Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"
THRESHOLDS = AGG / "dsd_thresholds_o4a_idxq4-64_queryq4-64.json"
KNOWN = AGG / "cqg_known_glitch_controls.json"
CBC = AGG / "catalog_cross_match_events_circular_shift_v2_idxq4-64_queryq4-64_o4a.csv"
INJECTIONS = AGG / "astrophysical_injection_trials_o4a_idxq4-64_queryq4-64.csv"
FORUM = AGG / "candidate_case_L1_1382955228_idxq4-64_queryq4-64.json"
BACKGROUND_LEDGERS = {
    "H1": AGG
    / "background_scores_native_H1_O4a_idxq4-64_queryq4-64_pad4_n5000_bgv3_0241b2a1_0e17e39a_eb941186_ledger.csv",
    "L1": AGG
    / "background_scores_native_L1_O4a_idxq4-64_queryq4-64_pad4_n5000_bgv3_0241b2a1_6d254973_eb941186_ledger.csv",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def finite_or_none(value: Any) -> float | str | int | bool | None:
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    return str(value)


def case(
    *,
    run: str,
    detector: str,
    gps_start: float,
    roles: list[str],
    source_kind: str,
    expected: dict[str, Any],
    metadata: dict[str, Any],
    duration_s: float = 32.0,
) -> dict[str, Any]:
    window = WindowIdentity(run, detector, gps_start, duration_s)
    value = {
        "window": window.to_dict(),
        "roles": sorted(set(roles)),
        "source_kind": source_kind,
        "expected": expected,
        "metadata": metadata,
    }
    value["case_id"] = f"dlc1-{canonical_json_sha256(value)[:24]}"
    return value


def candidate_cases(thresholds: dict) -> list[dict[str, Any]]:
    frame = pd.read_csv(TAXONOMY)
    class_col = "robustness_class_idxq4_64_queryq4_64"
    score_col = "native_score_idxq4_64_queryq4_64"
    non_background = frame[frame[class_col] != "BACKGROUND"].copy()
    if len(non_background) != 7640:
        raise RuntimeError(f"expected 7,640 non-background candidates, got {len(non_background)}")
    if non_background.duplicated(["detector", "gps_start"]).any():
        raise RuntimeError("detector+GPS is not unique in the candidate corpus")

    boundary_keys: set[tuple[str, float]] = set()
    for detector, group in frame.groupby("detector", sort=True):
        limits = thresholds["thresholds"][detector]
        distance = pd.concat(
            [
                (group[score_col] - float(limits["ci_lower"])).abs(),
                (group[score_col] - float(limits["ci_upper"])).abs(),
            ],
            axis=1,
        ).min(axis=1)
        for index in distance.nsmallest(30).index:
            boundary_keys.add((detector, float(frame.loc[index, "gps_start"])))

    output: list[dict[str, Any]] = []
    emitted_keys: set[tuple[str, float]] = set()
    for row in non_background.sort_values(["detector", "gps_start"]).to_dict("records"):
        catalog_gps = float(row["gps_start"])
        detector = str(row["detector"])
        roles = ["candidate_non_background"]
        if (detector, catalog_gps) in boundary_keys:
            roles.append("threshold_boundary")
        if detector == "L1" and catalog_gps == 1382955228.0:
            roles.append("forum_candidate")
        output.append(
            case(
                run="O4A",
                detector=detector,
                gps_start=catalog_gps + 4.0,
                roles=roles,
                source_kind="public_or_local_strain",
                expected={
                    "offline_class": str(row[class_col]),
                    "native_score": float(row[score_col]),
                },
                metadata={
                    "catalog_gps": catalog_gps,
                    "catalog_to_analysis_offset_s": 4.0,
                    "session_id": int(row["session_id"]),
                    "origin_table": str(row["origin_table"]),
                    "global_family_id": str(row["global_family_id"]),
                },
            )
        )
        emitted_keys.add((detector, catalog_gps))

    # Preserve the background-side neighbours of both threshold boundaries as
    # explicit cases; otherwise a regression could move the boundary while all
    # non-background rows still happened to agree.
    boundary_background = frame[
        frame.apply(
            lambda row: (str(row["detector"]), float(row["gps_start"]))
            in boundary_keys
            and (str(row["detector"]), float(row["gps_start"]))
            not in emitted_keys,
            axis=1,
        )
    ]
    for row in boundary_background.sort_values(["detector", "gps_start"]).to_dict(
        "records"
    ):
        catalog_gps = float(row["gps_start"])
        output.append(
            case(
                run="O4A",
                detector=str(row["detector"]),
                gps_start=catalog_gps + 4.0,
                roles=["threshold_boundary"],
                source_kind="public_or_local_strain",
                expected={
                    "offline_class": str(row[class_col]),
                    "native_score": float(row[score_col]),
                },
                metadata={
                    "catalog_gps": catalog_gps,
                    "catalog_to_analysis_offset_s": 4.0,
                    "session_id": int(row["session_id"]),
                    "origin_table": str(row["origin_table"]),
                    "global_family_id": str(row["global_family_id"]),
                },
            )
        )
    return output


def background_cases() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for detector, path in BACKGROUND_LEDGERS.items():
        frame = pd.read_csv(path).sort_values(["source_start", "gps_start"])
        if len(frame) != 5000:
            raise RuntimeError(f"{detector}: expected 5,000 background rows")
        # One deterministic central window per detector/session.  This covers
        # every available session and therefore time without storing E: paths.
        for source_start, group in frame.groupby("source_start", sort=True):
            row = group.iloc[len(group) // 2]
            output.append(
                case(
                    run="O4A",
                    detector=detector,
                    gps_start=float(row["gps_start"]),
                    roles=["background_stratified"],
                    source_kind="public_or_local_strain",
                    expected={
                        "offline_class": "BACKGROUND_CALIBRATION",
                        "native_score": float(row["calibration_score"]),
                    },
                    metadata={
                        "source_session_start": float(source_start),
                        "bootstrap_block_index": int(row["bootstrap_block_index"]),
                    },
                )
            )
    return output


def known_glitch_cases() -> list[dict[str, Any]]:
    payload = json.loads(KNOWN.read_text(encoding="utf-8"))
    output: list[dict[str, Any]] = []
    for detector, record in sorted(payload["detectors"].items()):
        manifest = record["manifest"]
        scores = record["raw_scores"]["query_dante"]
        if len(manifest) != len(scores):
            raise RuntimeError(f"{detector}: known-glitch manifest/score mismatch")
        for event, score in zip(manifest, scores):
            event_time = float(event["event_time"])
            output.append(
                case(
                    run="O3B",
                    detector=detector,
                    gps_start=event_time - 16.0,
                    roles=["known_glitch"],
                    source_kind="public_strain",
                    expected={
                        "known_label": str(event["label"]),
                        "dante_score": float(score),
                    },
                    metadata={
                        "event_time": event_time,
                        "gravityspy_id": str(event["gravityspy_id"]),
                        "ml_confidence": float(event["ml_confidence"]),
                        "snr": float(event["snr"]),
                    },
                )
            )
    return output


def cbc_control_cases() -> list[dict[str, Any]]:
    frame = pd.read_csv(CBC)
    output: list[dict[str, Any]] = []
    for row in frame.sort_values("gps").to_dict("records"):
        for detector in ("H1", "L1"):
            if not bool(row[f"cov_{detector}"]):
                continue
            output.append(
                case(
                    run="O4A",
                    detector=detector,
                    gps_start=float(row["gps"]) - 16.0,
                    roles=["cbc_control"],
                    source_kind="public_strain",
                    expected={
                        "offline_class": finite_or_none(row[f"class_{detector}"]),
                        "native_score": finite_or_none(row[f"score_{detector}"]),
                    },
                    metadata={
                        "event_name": str(row["name"]),
                        "event_gps": float(row["gps"]),
                        "catalog_snr": finite_or_none(row["snr"]),
                    },
                )
            )
    return output


def injection_cases() -> list[dict[str, Any]]:
    frame = pd.read_csv(INJECTIONS)
    output: list[dict[str, Any]] = []
    for row in frame.sort_values(["system", "distance_mpc", "trial_index"]).to_dict(
        "records"
    ):
        for detector in ("H1", "L1"):
            output.append(
                case(
                    run="O4A",
                    detector=detector,
                    gps_start=float(row["gps"]) - 16.0,
                    roles=["cbc_injection"],
                    source_kind="synthetic_injection",
                    expected={
                        "offline_class": str(row[f"dsd_class_{detector}"]),
                        "native_score": float(row[f"score_{detector}_native"]),
                        "primary_flag": bool(row[f"flag_{detector}"]),
                    },
                    metadata={
                        "injection_gps": float(row["gps"]),
                        "system": str(row["system"]),
                        "distance_mpc": float(row["distance_mpc"]),
                        "trial_index": int(row["trial_index"]),
                        "seed": int(row["seed"]),
                    },
                )
            )
    return output


def build(output_path: Path = DEFAULT_OUTPUT) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sources = [
        TAXONOMY,
        THRESHOLDS,
        KNOWN,
        CBC,
        INJECTIONS,
        FORUM,
        *BACKGROUND_LEDGERS.values(),
    ]
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(source)
    threshold_payload = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    entries = (
        candidate_cases(threshold_payload)
        + background_cases()
        + known_glitch_cases()
        + cbc_control_cases()
        + injection_cases()
    )
    entries.sort(key=lambda item: item["case_id"])
    case_ids = [item["case_id"] for item in entries]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("duplicate replay case_id")

    role_counts: dict[str, int] = {}
    for item in entries:
        for role in item["roles"]:
            role_counts[role] = role_counts.get(role, 0) + 1
    entries_path = output_path.with_suffix(".jsonl")
    entries_bytes = "".join(
        json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
        for item in entries
    ).encode("utf-8")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "frozen",
        "purpose": "DANTE-Light L0 exact-replay and non-regression corpus",
        "raw_strain_embedded": False,
        "representation": RepresentationContract.from_reference_manifest(
            ROOT / "config" / "reference_artifacts.json"
        ).to_dict(),
        "selection_contract": {
            "candidate": "all O4a detector-aware ROBUST or AMBIGUOUS rows; analysis_start=catalog_gps+4s",
            "boundary": "30 smallest distances to either BGV3 CI edge per detector, tagged within candidate rows",
            "background": "central calibration-ledger row per detector and source session",
            "known_glitch": "all quality-screened CQG held-out Gravity Spy controls",
            "cbc_control": "all O4a catalog events for every detector with processed coverage",
            "cbc_injection": "all fixed trial-level injections for both detectors; reconstruction recipe retained",
            "forum_candidate": "L1 catalog GPS 1382955228 / analysis GPS 1382955232",
        },
        "source_artifacts": [
            {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size}
            for path in sources
        ],
        "counts": {
            "entries": len(entries),
            "unique_windows": len(
                {item["window"]["window_id"] for item in entries}
            ),
            "roles": dict(sorted(role_counts.items())),
        },
        "entries_path": entries_path.relative_to(ROOT).as_posix(),
        "entries_file_sha256": hashlib.sha256(entries_bytes).hexdigest(),
        "entries_sha256": canonical_json_sha256(entries),
    }
    payload["manifest_sha256"] = canonical_json_sha256(payload)
    return payload, entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    payload, entries = build(args.output)
    entries_path = args.output.with_suffix(".jsonl")
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    entries_encoded = "".join(
        json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
        for item in entries
    )
    if args.check:
        if (
            not args.output.is_file()
            or args.output.read_bytes() != encoded.encode("utf-8")
            or not entries_path.is_file()
            or entries_path.read_bytes() != entries_encoded.encode("utf-8")
        ):
            raise RuntimeError(f"stale replay manifest: {args.output}")
        print(f"PASS {args.output} {payload['manifest_sha256']}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Byte writes make the corpus digest independent of the host newline mode.
    args.output.write_bytes(encoded.encode("utf-8"))
    entries_path.write_bytes(entries_encoded.encode("utf-8"))
    print(json.dumps(payload["counts"], indent=2, sort_keys=True))
    print(f"WROTE {args.output} SHA256={sha256(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
