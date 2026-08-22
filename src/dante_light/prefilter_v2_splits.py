"""Outcome-blind availability-screened development augmentation for L4 v2."""

from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_splits import load_prefilter_splits
from src.dante_light.prefilter_v2_protocol import PrefilterProtocolV2


Preflight = Callable[[WindowIdentity], Mapping[str, Any]]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _priority(seed: int, role: str, detector: str, morphology: str, identity: str) -> str:
    value = f"{seed}:{role}:{detector}:{morphology}:{identity}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_morphology(label: str) -> str:
    return str(label).replace("_", "")


def _preflight_candidates(
    candidates: list[dict[str, Any]],
    *,
    quota: int,
    reserve: int,
    workers: int,
    preflight: Preflight,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    selected: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    def inspect(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, Exception | None]:
        window = WindowIdentity.from_dict(source["window"])
        try:
            evidence = dict(preflight(window))
            strain_sha256 = str(evidence.get("strain_sha256", ""))
            if len(strain_sha256) != 64:
                raise ContractError("availability preflight omitted strain SHA256")
        except Exception as exc:
            return source, None, exc
        return source, evidence, None

    pool = candidates[: quota + reserve]
    cursor = 0
    while len(selected) < quota and cursor < len(pool):
        batch_n = min(quota - len(selected), len(pool) - cursor)
        batch = pool[cursor : cursor + batch_n]
        cursor += batch_n
        if workers == 1:
            results = [inspect(source) for source in batch]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                results = list(executor.map(inspect, batch))
        for source, evidence, exc in results:
            window = WindowIdentity.from_dict(source["window"])
            if exc is not None:
                failures.append(
                    {
                        "cohort_id": source["cohort_id"],
                        "window_id": window.window_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                continue
            row = dict(source)
            row["partition"] = "development"
            row["availability_preflight"] = {
                key: value
                for key, value in evidence.items()
                if key not in {"feature", "features", "score", "exact_disposition"}
            }
            selected.append(row)
    if len(selected) != quota:
        raise ContractError(
            f"availability-screened development quota not filled: {len(selected)}/{quota}"
        )
    return selected, failures


def _base_rows(
    root: Path, protocol: PrefilterProtocolV2
) -> tuple[dict[str, Any], Path]:
    source = protocol.payload["cohort_augmentation"]["base_split"]
    path = root / str(source["path"])
    entries_path = path.with_suffix(".jsonl")
    if _sha256(path) != source["sha256"] or _sha256(entries_path) != source["entries_sha256"]:
        raise ContractError("prefilter v2 base split provenance mismatch")
    split = load_prefilter_splits(path)
    for cohort in split["cohorts"].values():
        for row in cohort["rows"]:
            if row["partition"] == "development" and row["window"]["run"] == "O4B":
                raise ContractError("O4b row leaked into prefilter v2 development")
    return split, path


def _augment_robust(
    root: Path,
    protocol: PrefilterProtocolV2,
    base_rows: list[dict[str, Any]],
    *,
    occupied_window_ids: set[str],
    preflight: Preflight,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, str]]:
    rules = protocol.payload["cohort_augmentation"]["robust_candidate"]
    path = root / str(rules["source_path"])
    if _sha256(path) != rules["source_sha256"]:
        raise ContractError("robust augmentation taxonomy SHA256 mismatch")
    seed = int(protocol.payload["cohort_split_seed"])
    quota = int(rules["additional_development_per_detector"])
    workers = int(protocol.payload["cohort_augmentation"]["availability_preflight"]["workers"])
    additions: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as stream:
        sources = list(csv.DictReader(stream))
    for detector in protocol.payload["required_detectors"]:
        candidates = []
        for source in sources:
            if source["detector"] != detector or source["robustness_class"] != rules["required_class"]:
                continue
            gps = int(float(source["gps_start"]))
            window = WindowIdentity("O4A", detector, float(gps) + 4.0)
            if window.window_id in occupied_window_ids:
                continue
            cohort_id = f"v2-robust:{detector}:{gps}"
            candidates.append(
                {
                    "cohort_id": cohort_id,
                    "role": "robust_candidate",
                    "detector": detector,
                    "morphology": "unknown",
                    "retention_target": True,
                    "window": window.to_dict(),
                    "source_class": str(source["robustness_class"]),
                    "partition_priority": _priority(seed, "robust_candidate", detector, "unknown", cohort_id),
                    "augmentation_source": "detector-aware O4a master taxonomy",
                }
            )
        candidates.sort(key=lambda row: (row["partition_priority"], row["cohort_id"]))
        chosen, rejected = _preflight_candidates(
            candidates,
            quota=quota,
            reserve=max(quota, 5),
            workers=workers,
            preflight=preflight,
        )
        additions.extend(chosen)
        failures.extend(rejected)
        occupied_window_ids.update(row["window"]["window_id"] for row in chosen)
    return [*base_rows, *additions], failures, {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": _sha256(path),
    }


def _known_exclusion_gps(root: Path) -> dict[str, np.ndarray]:
    path = root / "data/production/aggregated/cqg_known_glitch_controls.json"
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for detector in ("H1", "L1"):
        clean = payload["detectors"][detector]["clean_gps"]
        result[detector] = np.asarray([*clean["train"], *clean["held_out"]], dtype=float)
    return result


def _augment_known(
    root: Path,
    protocol: PrefilterProtocolV2,
    base_rows: list[dict[str, Any]],
    *,
    occupied_window_ids: set[str],
    preflight: Preflight,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    rules = protocol.payload["cohort_augmentation"]["known_glitch"]
    seed = int(protocol.payload["cohort_split_seed"])
    quota = int(rules["additional_development_per_stratum"])
    reserve = int(rules["availability_reserve_per_stratum"])
    workers = int(protocol.payload["cohort_augmentation"]["availability_preflight"]["workers"])
    excluded_ids = {
        str(row.get("gravityspy_id"))
        for row in base_rows
        if row.get("gravityspy_id") is not None
    }
    excluded_gps = _known_exclusion_gps(root)
    additions: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    sources: list[dict[str, str]] = []
    label_by_morphology = {
        "Blip": "Blip",
        "KoiFish": "Koi_Fish",
        "ScatteredLight": "Scattered_Light",
    }
    for detector in protocol.payload["required_detectors"]:
        path = root / str(rules["catalog_paths"][detector])
        if _sha256(path) != rules["catalog_sha256"][detector]:
            raise ContractError(f"known-glitch catalog SHA256 mismatch for {detector}")
        sources.append({"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": _sha256(path)})
        with path.open(newline="", encoding="utf-8") as stream:
            catalog = list(csv.DictReader(stream))
        for morphology in protocol.payload["required_morphologies_by_role"]["known_glitch"]:
            label = label_by_morphology[morphology]
            candidates = []
            for source in catalog:
                gravityspy_id = str(source["gravityspy_id"])
                if gravityspy_id in excluded_ids:
                    continue
                if source["ifo"] != detector or source["ml_label"] != label:
                    continue
                if float(source["ml_confidence"]) < float(rules["minimum_ml_confidence"]):
                    continue
                if float(source["snr"]) < float(rules["minimum_snr"]):
                    continue
                event_time = float(source["event_time"])
                if np.min(np.abs(excluded_gps[detector] - event_time)) < float(rules["separation_guard_s"]):
                    continue
                window = WindowIdentity("O3B", detector, event_time - 16.0)
                if window.window_id in occupied_window_ids:
                    continue
                cohort_id = f"v2-known:{detector}:{gravityspy_id}"
                candidates.append(
                    {
                        "cohort_id": cohort_id,
                        "role": "known_glitch",
                        "detector": detector,
                        "morphology": morphology,
                        "retention_target": True,
                        "window": window.to_dict(),
                        "gravityspy_id": gravityspy_id,
                        "ml_confidence": float(source["ml_confidence"]),
                        "snr": float(source["snr"]),
                        "partition_priority": _priority(seed, "known_glitch", detector, morphology, gravityspy_id),
                        "augmentation_source": "Gravity Spy O3b high-confidence catalog",
                    }
                )
            candidates.sort(key=lambda row: (row["partition_priority"], row["cohort_id"]))
            chosen, rejected = _preflight_candidates(
                candidates,
                quota=quota,
                reserve=reserve,
                workers=workers,
                preflight=preflight,
            )
            additions.extend(chosen)
            failures.extend(rejected)
            excluded_ids.update(row["gravityspy_id"] for row in chosen)
            occupied_window_ids.update(row["window"]["window_id"] for row in chosen)
    return [*base_rows, *additions], failures, sources


def build_prefilter_v2_splits(
    *,
    root: str | Path,
    protocol: PrefilterProtocolV2,
    preflight: Preflight,
) -> dict[str, Any]:
    root = Path(root).resolve()
    base, base_path = _base_rows(root, protocol)
    cohorts = deepcopy(base["cohorts"])
    occupied_window_ids = {
        row["window"]["window_id"]
        for cohort in cohorts.values()
        for row in cohort["rows"]
    }
    robust_rows, robust_failures, robust_source = _augment_robust(
        root,
        protocol,
        cohorts["robust_candidate"]["rows"],
        occupied_window_ids=occupied_window_ids,
        preflight=preflight,
    )
    known_rows, known_failures, known_sources = _augment_known(
        root,
        protocol,
        cohorts["known_glitch"]["rows"],
        occupied_window_ids=occupied_window_ids,
        preflight=preflight,
    )
    cohorts["robust_candidate"]["rows"] = robust_rows
    cohorts["known_glitch"]["rows"] = known_rows
    source_additions = {
        "robust_candidate": [robust_source],
        "known_glitch": known_sources,
    }
    for role, cohort in cohorts.items():
        rows = sorted(cohort["rows"], key=lambda row: row["cohort_id"])
        sources = [
            {
                "path": str(base_path.relative_to(root)).replace("\\", "/"),
                "sha256": _sha256(base_path),
                "role_split_sha256": base["cohorts"][role]["split_sha256"],
            },
            *source_additions.get(role, []),
        ]
        body = {
            "role": role,
            "seed": int(protocol.payload["cohort_split_seed"]),
            "sources": sources,
            "rows": rows,
        }
        cohorts[role] = {
            **body,
            "split_sha256": canonical_json_sha256(body),
            "counts": {
                "total": len(rows),
                "development": sum(row["partition"] == "development" for row in rows),
                "evaluation": sum(row["partition"] == "evaluation" for row in rows),
            },
        }
    detectors = tuple(protocol.payload["required_detectors"])
    morphologies = protocol.payload["required_morphologies_by_role"]
    development_rules = protocol.payload["development"]
    evaluation_rules = protocol.payload["evaluation"]
    for detector in detectors:
        background_n = sum(
            row["partition"] == "development" and row["detector"] == detector
            for row in cohorts["background"]["rows"]
        )
        if background_n < int(development_rules["minimum_background_per_detector"]):
            raise ContractError(f"underpowered v2 development background for {detector}: {background_n}")
        for partition, rules in (
            ("development", development_rules),
            ("evaluation", evaluation_rules),
        ):
            groups = [
                ("robust_candidate", "unknown"),
                *(("known_glitch", value) for value in morphologies["known_glitch"]),
                *(("injection", value) for value in morphologies["injection"]),
            ]
            for role, morphology in groups:
                count = sum(
                    row["partition"] == partition
                    and row["detector"] == detector
                    and row["morphology"] == morphology
                    for row in cohorts[role]["rows"]
                )
                minimum = int(rules["minimum_group_n_by_role"][role])
                if count < minimum:
                    raise ContractError(
                        f"underpowered v2 {partition} group "
                        f"{role}/{detector}/{morphology}: {count}/{minimum}"
                    )
    identities = [
        row["window"]["window_id"]
        for cohort in cohorts.values()
        for row in cohort["rows"]
    ]
    if len(identities) != len(set(identities)):
        raise ContractError("prefilter v2 cohorts overlap in window identity")
    result = {
        "schema_version": 2,
        "status": "availability_screened_before_feature_extraction",
        "seed": int(protocol.payload["cohort_split_seed"]),
        "protocol": protocol.reference,
        "outcome_fields_used_for_partition": [],
        "feature_values_used_for_partition": [],
        "exact_scores_used_for_partition": [],
        "availability_preflight": {
            "robust_candidate_failures": robust_failures,
            "known_glitch_failures": known_failures,
        },
        "cohorts": cohorts,
    }
    result["artifact_digest"] = canonical_json_sha256(result)
    return result
