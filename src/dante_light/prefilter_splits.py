"""Deterministically freeze development/evaluation cohorts for L4."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _priority(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()


def _partition(rows: list[dict[str, Any]], *, development_n: int, seed: int) -> None:
    if not 0 < development_n < len(rows):
        raise ContractError("invalid prefilter cohort split size")
    ordered = sorted(rows, key=lambda row: _priority(seed, row["cohort_id"]))
    for index, row in enumerate(ordered):
        row["partition"] = "development" if index < development_n else "evaluation"
        row["partition_priority"] = _priority(seed, row["cohort_id"])


def _robust_rows(root: Path, *, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    aggregate = root / "data/production/aggregated"
    cache = aggregate / (
        "dsd_index_stability_candidate_tokens_o4a_idxq4-64_queryq4-64_"
        "q4-64_n40_s42_1154059b80ca.npz"
    )
    taxonomy = aggregate / "Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"
    with np.load(cache, allow_pickle=False) as payload:
        keys = [str(value) for value in payload["candidate_keys"]]
    by_key: dict[str, dict[str, str]] = {}
    with taxonomy.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            key = f"{row['detector']}:{int(float(row['gps_start']))}"
            by_key[key] = row
    rows: list[dict[str, Any]] = []
    for key in keys:
        source = by_key.get(key)
        if source is None:
            raise ContractError(f"P5 candidate is missing from taxonomy: {key}")
        if source["robustness_class"] != "ROBUST":
            continue
        detector, gps = key.split(":")
        window = WindowIdentity("O4A", detector, float(gps) + 4.0)
        rows.append(
            {
                "cohort_id": f"robust:{key}",
                "role": "robust_candidate",
                "detector": detector,
                "morphology": "unknown",
                "retention_target": True,
                "window": window.to_dict(),
                "source_class": "ROBUST",
            }
        )
    for detector in ("H1", "L1"):
        selected = [row for row in rows if row["detector"] == detector]
        if len(selected) != 40:
            raise ContractError(f"expected 40 P5 robust rows for {detector}")
        _partition(selected, development_n=20, seed=seed)
    return rows, [
        {"path": cache.relative_to(root).as_posix(), "sha256": _sha256(cache)},
        {"path": taxonomy.relative_to(root).as_posix(), "sha256": _sha256(taxonomy)},
    ]


def _known_rows(root: Path, *, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    path = root / "data/production/aggregated/cqg_known_glitch_controls.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for detector, block in payload["detectors"].items():
        for event in block["manifest"]:
            morphology = str(event["label"]).replace("_", "")
            window = WindowIdentity("O3B", detector, float(event["event_time"]) - 16.0)
            rows.append(
                {
                    "cohort_id": f"known:{detector}:{event['gravityspy_id']}",
                    "role": "known_glitch",
                    "detector": detector,
                    "morphology": morphology,
                    "retention_target": True,
                    "window": window.to_dict(),
                    "gravityspy_id": event["gravityspy_id"],
                    "ml_confidence": float(event["ml_confidence"]),
                    "snr": float(event["snr"]),
                }
            )
    for detector in ("H1", "L1"):
        for morphology in ("Blip", "KoiFish", "ScatteredLight"):
            selected = [
                row for row in rows
                if row["detector"] == detector and row["morphology"] == morphology
            ]
            if len(selected) != 30:
                raise ContractError(f"expected 30 {detector}/{morphology} controls")
            _partition(selected, development_n=12, seed=seed)
    return rows, [{"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}]


def _injection_rows(root: Path, *, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    path = root / (
        "data/production/aggregated/"
        "astrophysical_injection_trials_o4a_idxq4-64_queryq4-64.csv"
    )
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as stream:
        for source in csv.DictReader(stream):
            for detector in ("H1", "L1"):
                system = source["system"]
                distance = float(source["distance_mpc"])
                trial = int(source["trial_index"])
                gps = float(source["gps"])
                window = WindowIdentity("O4A", detector, gps)
                rows.append(
                    {
                        "cohort_id": f"injection:{system}:{distance:g}:{trial}:{detector}",
                        "role": "injection",
                        "detector": detector,
                        "morphology": system,
                        "retention_target": True,
                        "window": window.to_dict(),
                        "distance_mpc": distance,
                        "trial_index": trial,
                        "ra": float(source["ra"]),
                        "dec": float(source["dec"]),
                        "psi": float(source["psi"]),
                        "inclination": float(source["inclination"]),
                    }
                )
    systems = ("BBH_30_30", "BBH_10_10", "NSBH_10_1.4")
    distances = (100.0, 200.0, 400.0, 800.0, 1600.0)
    for detector in ("H1", "L1"):
        for system in systems:
            for distance in distances:
                selected = [
                    row for row in rows
                    if row["detector"] == detector
                    and row["morphology"] == system
                    and row["distance_mpc"] == distance
                ]
                if len(selected) != 25:
                    raise ContractError(f"expected 25 {detector}/{system}/{distance:g} trials")
                _partition(selected, development_n=7, seed=seed)
    return rows, [{"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}]


def _background_rows(root: Path, *, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    del seed
    manifest_path = root / "config/dante_light_replay_v1.json"
    entries_path = root / "config/dante_light_replay_v1.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("entries_file_sha256") != _sha256(entries_path):
        raise ContractError("frozen replay entry-file SHA256 mismatch")
    rows: list[dict[str, Any]] = []
    for line in entries_path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if "background_stratified" not in entry["roles"]:
            continue
        window = WindowIdentity.from_dict(entry["window"])
        rows.append(
            {
                "cohort_id": f"background:{window.window_id}",
                "role": "background",
                "detector": window.detector,
                "morphology": "clean_background",
                "retention_target": False,
                "window": window.to_dict(),
                "partition": "development",
                "partition_priority": entry["case_id"],
            }
        )
    counts = {detector: sum(row["detector"] == detector for row in rows) for detector in ("H1", "L1")}
    if counts != {"H1": 274, "L1": 278}:
        raise ContractError(f"unexpected frozen background counts: {counts}")
    return rows, [
        {"path": manifest_path.relative_to(root).as_posix(), "sha256": _sha256(manifest_path)},
        {"path": entries_path.relative_to(root).as_posix(), "sha256": _sha256(entries_path)},
    ]


def build_prefilter_splits(*, root: str | Path, seed: int = 20260821) -> dict[str, Any]:
    root = Path(root).resolve()
    builders = {
        "background": _background_rows,
        "robust_candidate": _robust_rows,
        "known_glitch": _known_rows,
        "injection": _injection_rows,
    }
    cohorts = {}
    for role, builder in builders.items():
        rows, sources = builder(root, seed=seed)
        rows.sort(key=lambda row: row["cohort_id"])
        body = {"role": role, "seed": seed, "sources": sources, "rows": rows}
        cohorts[role] = {
            **body,
            "split_sha256": canonical_json_sha256(body),
            "counts": {
                "total": len(rows),
                "development": sum(row["partition"] == "development" for row in rows),
                "evaluation": sum(row["partition"] == "evaluation" for row in rows),
            },
        }
    result = {
        "schema_version": 1,
        "status": "locked_before_feature_extraction",
        "seed": seed,
        "outcome_fields_used_for_partition": [],
        "cohorts": cohorts,
    }
    result["artifact_digest"] = canonical_json_sha256(result)
    return result


def write_prefilter_splits(payload: dict[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries_path = destination.with_suffix(".jsonl")
    entries = [
        {"cohort_role": role, **row}
        for role, cohort in payload["cohorts"].items()
        for row in cohort["rows"]
    ]
    entries.sort(key=lambda row: (row["cohort_role"], row["cohort_id"]))
    entries_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in entries
        ),
        encoding="utf-8",
        newline="\n",
    )
    manifest = {
        key: value for key, value in payload.items() if key != "cohorts"
    }
    manifest["entries_path"] = entries_path.name
    manifest["entries_file_sha256"] = _sha256(entries_path)
    manifest["cohorts"] = {
        role: {key: value for key, value in cohort.items() if key != "rows"}
        for role, cohort in payload["cohorts"].items()
    }
    destination.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def load_prefilter_splits(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        entries_path = path.parent / manifest["entries_path"]
        if _sha256(entries_path) != manifest["entries_file_sha256"]:
            raise ContractError("L4 split entry-file SHA256 mismatch")
        entries = [
            json.loads(line)
            for line in entries_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise ContractError(f"invalid L4 split artifact: {exc}") from exc
    payload = {
        key: value
        for key, value in manifest.items()
        if key not in {"entries_path", "entries_file_sha256"}
    }
    for role, cohort in payload["cohorts"].items():
        cohort["rows"] = [
            {key: value for key, value in row.items() if key != "cohort_role"}
            for row in entries
            if row.get("cohort_role") == role
        ]
        if len(cohort["rows"]) != int(cohort["counts"]["total"]):
            raise ContractError(f"L4 split count mismatch for {role}")
        body = {
            "role": role,
            "seed": payload["seed"],
            "sources": cohort["sources"],
            "rows": cohort["rows"],
        }
        if canonical_json_sha256(body) != cohort["split_sha256"]:
            raise ContractError(f"L4 role split digest mismatch for {role}")
    return payload
