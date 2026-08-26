"""Outcome-blind freeze for the DANTE-Light v7 selective-deferral study.

The v7 task is deliberately narrower than score distillation: predict only
whether a window is safe to omit from the expensive exact-DANTE path.  The
primary safety endpoint is therefore exact-teacher-positive retention, not a
conditional probability estimated on overwhelmingly teacher-negative
background traffic.
"""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.stats import qmc

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v5_power import (
    gate_pass_probability,
    minimum_passing_successes,
    worst_case_wilson_half_width,
)


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_ID = "dante-light-l4-prefilter-v7-selective-deferral"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
PARTITIONS = ("training", "threshold_search", "risk_calibration", "confirmation")
DETECTORS = ("H1", "L1")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def repository_reference(root: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve()
    relative = resolved.relative_to(root.resolve()).as_posix()
    digest = file_sha256(resolved)
    try:
        unchanged = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative],
            cwd=root,
            check=False,
        ).returncode == 0
        tracked = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{relative}"],
            cwd=root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        if unchanged and tracked:
            digest = hashlib.sha256(
                subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=root)
            ).hexdigest()
    except (OSError, subprocess.SubprocessError):
        pass
    return {"path": relative, "sha256": digest}


def _reference_matches(root: Path, reference: Mapping[str, Any]) -> bool:
    path = root / str(reference["path"])
    candidates = {file_sha256(path)} if path.is_file() else set()
    try:
        candidates.add(
            hashlib.sha256(
                subprocess.check_output(
                    ["git", "show", f"HEAD:{reference['path']}"],
                    cwd=root,
                    stderr=subprocess.DEVNULL,
                )
            ).hexdigest()
        )
    except (OSError, subprocess.SubprocessError):
        pass
    return str(reference["sha256"]) in candidates


def _priority(seed: str, purpose: str, *identity: object) -> str:
    return canonical_json_sha256(
        {"seed": seed, "purpose": purpose, "identity": list(identity)}
    )


def _window(run: str, detector: str, gps_start: float) -> dict[str, Any]:
    return WindowIdentity(run, detector, float(gps_start), 32.0).to_dict()


def _row(
    *,
    partition: str,
    role: str,
    detector: str,
    morphology: str,
    run: str,
    gps_start: float,
    source_kind: str,
    source_id: str,
    seed: str,
    stratum: Mapping[str, Any],
    transfer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    window = _window(run, detector, gps_start)
    block = math.floor(float(gps_start) / 4096.0)
    body = {
        "schema_version": 1,
        "partition": partition,
        "role": role,
        "detector": detector,
        "morphology": morphology,
        "block_key": f"{run}:{detector}:{block}",
        "window": window,
        "source": {"kind": source_kind, "source_id": source_id, "run": run},
        "stratum": dict(stratum),
        "selection_priority": _priority(seed, "identity", partition, role, detector, source_id),
        "transfer": dict(transfer) if transfer is not None else None,
    }
    body["identity_id"] = f"dlv7-{canonical_json_sha256(body)[:24]}"
    return body


def _validate_upstream_unopened(root: Path) -> dict[str, Any]:
    v5_seal = _read_json(root / "config/dante_light_prefilter_v5_confirmation_seal.json")
    if v5_seal.get("status") != "SEALED_NOT_OPENED" or v5_seal.get("access_entries_at_freeze") != 0:
        raise ContractError("v5 confirmation is not sealed and unopened")
    v6_summary = _read_json(
        root
        / "artifacts/dante_light/prefilter_l4_v6_training/phase_b_screening_summary_v6.json"
    )
    for field in ("phase_c_rows_accessed", "phase_d_rows_accessed", "o4b_rows_accessed"):
        if v6_summary.get(field) != []:
            raise ContractError(f"v6 protected boundary violated: {field}")
    selection = v6_summary.get("selection", {})
    if (
        v6_summary.get("status") != "PHASE_B_SCREENING_COMPLETE"
        or selection.get("phase_c_unlock_allowed") is not False
        or float(selection.get("selected", {}).get("worst_cell_spearman", 1.0)) >= 0.9
    ):
        raise ContractError("v6 Phase B failure boundary is not explicit")
    return {
        "v5_confirmation_seal_digest": v5_seal["seal_digest"],
        "v6_phase_b_status": v6_summary["status"],
        "v6_phase_c_unlock_allowed": False,
        "v6_selected_worst_cell_spearman": float(
            selection["selected"]["worst_cell_spearman"]
        ),
        "v6_phase_c_rows_accessed": [],
        "v6_phase_d_rows_accessed": [],
        "o4b_rows_accessed": [],
    }


def _background_prevalence_audit(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Recompute the historical v6 natural-traffic teacher prevalence.

    The detailed v6 teacher blocks remain in the E-drive cache.  This creates a
    compact, repository-portable row ledger so the design premise can be
    checked without silently relying on a remembered count.
    """

    source_path = (
        root
        / "artifacts/dante_light/prefilter_l4_v6_training/teacher_ledger_summary_v6.json"
    )
    source = _read_json(source_path)
    cache_root = Path(
        os.environ.get(
            "DANTE_V6_TRAINING_CACHE_ROOT",
            "E:/dante_cache/dante_light/prefilter_l4_v6_training",
        )
    )
    run_root = cache_root / source["cache_location"]["run_subdirectory"]
    epochs = _read_json(root / "config/dante_light_epochs_v1.json")
    rows: list[dict[str, Any]] = []
    for reference in source["block_references"]:
        path = run_root / reference["path"]
        if not path.is_file() or file_sha256(path) != reference["sha256"]:
            raise ContractError(f"v6 teacher block provenance mismatch: {reference['path']}")
        block = _read_json(path)
        for item in block["rows"]:
            detector = str(block["detector"])
            score = float(item["teacher_target"]["native_o4a_novelty_score"])
            threshold = float(epochs["epochs"][detector]["threshold"])
            rows.append(
                {
                    "schema_version": 1,
                    "detector": detector,
                    "block_index": int(block["block_index"]),
                    "window_id": str(item["window"]["window_id"]),
                    "gps_start": float(item["window"]["gps_start"]),
                    "native_o4a_novelty_score": score,
                    "historical_threshold": threshold,
                    "exact_dante_retains": bool(score > threshold),
                }
            )
    rows.sort(key=lambda row: (row["detector"], row["block_index"], row["gps_start"]))
    counts = {}
    for detector in DETECTORS:
        selected = [row for row in rows if row["detector"] == detector]
        positives = sum(row["exact_dante_retains"] for row in selected)
        counts[detector] = {
            "n": len(selected),
            "exact_dante_retained": int(positives),
            "fraction": positives / len(selected),
            "threshold": float(epochs["epochs"][detector]["threshold"]),
        }
    body = {
        "schema_version": 1,
        "status": "RETROSPECTIVE_DESIGN_EVIDENCE_VERIFIED",
        "source_teacher_ledger_reference": repository_reference(root, source_path),
        "source_block_reference_count": len(source["block_references"]),
        "threshold_reference": repository_reference(root, root / "config/dante_light_epochs_v1.json"),
        "decision_rule": "native_o4a_novelty_score_strictly_greater_than_historical_detector_threshold",
        "counts": counts,
        "rows_digest": canonical_json_sha256(rows),
        "interpretation": {
            "rare_not_empty": True,
            "zero_of_1440_claim_rejected": True,
            "calibration_expected_positive_count_is_too_small_for_primary_safety_inference": True,
            "supports_case_control_teacher_positive_retention_endpoint": True,
        },
        "protected_v6_phase_c_or_phase_d_accessed": [],
        "o4b_accessed": [],
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}, rows


def _used_o4a_blocks(root: Path) -> dict[str, set[int]]:
    used = {detector: set() for detector in DETECTORS}
    for row in _read_jsonl(root / "config/dante_light_prefilter_splits_v5.jsonl"):
        if row["window"]["run"] == "O4A":
            used[row["detector"]].add(math.floor(float(row["window"]["gps_start"]) / 4096.0))
    for row in _read_jsonl(root / "config/dante_light_prefilter_v6_partitions.jsonl"):
        used[row["detector"]].add(int(row["block_index"]))
    return used


def _select_teacher_positive_rows(
    root: Path,
    *,
    seed: str,
    counts: Mapping[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    epochs = _read_json(root / "config/dante_light_epochs_v1.json")
    used = _used_o4a_blocks(root)
    pools: dict[str, list[dict[str, Any]]] = {detector: [] for detector in DETECTORS}
    taxonomy_path = root / "data/production/aggregated/Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"
    with taxonomy_path.open(newline="", encoding="utf-8") as stream:
        for raw in csv.DictReader(stream):
            detector = str(raw["detector"])
            if detector not in pools:
                continue
            score = float(raw["native_score_idxq4_64_queryq4_64"])
            threshold = float(epochs["epochs"][detector]["threshold"])
            if score <= threshold:
                continue
            event_gps = float(raw["gps_start"])
            window_gps = event_gps + 4.0
            block = math.floor(window_gps / 4096.0)
            if block in used[detector]:
                continue
            pools[detector].append(
                {
                    "detector": detector,
                    "event_gps": event_gps,
                    "window_gps": window_gps,
                    "block": block,
                    "score": score,
                    "threshold": threshold,
                    "class": str(raw["robustness_class_idxq4_64_queryq4_64"]),
                    "family": str(raw["global_family_id"]),
                }
            )
    output: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}
    remaining_by_detector: dict[str, list[dict[str, Any]]] = {}
    for detector in DETECTORS:
        # One case per detector/GPS block.  Keep the highest-score event in a
        # block, then interleave score quartiles so the cohort is not only the
        # most extreme tail of the historical exact-DANTE positives.
        by_block: dict[int, dict[str, Any]] = {}
        for item in pools[detector]:
            current = by_block.get(item["block"])
            if current is None or (item["score"], -item["event_gps"]) > (
                current["score"],
                -current["event_gps"],
            ):
                by_block[item["block"]] = item
        ranked = sorted(by_block.values(), key=lambda item: (item["score"], item["event_gps"]))
        for index, item in enumerate(ranked):
            item["score_quantile_stratum"] = min(3, index * 4 // len(ranked))
        buckets = []
        for stratum in range(4):
            bucket = [item for item in ranked if item["score_quantile_stratum"] == stratum]
            bucket.sort(
                key=lambda item: (
                    _priority(seed, "teacher-positive", detector, item["block"]),
                    item["block"],
                )
            )
            buckets.append(bucket)
        ordered = [
            bucket[index]
            for index in range(max(map(len, buckets), default=0))
            for bucket in buckets
            if index < len(bucket)
        ]
        required = sum(int(value) for value in counts.values())
        if len(ordered) < required + 60:
            raise ContractError(f"insufficient fresh teacher-positive blocks for {detector}")
        cursor = 0
        for partition in PARTITIONS:
            n = int(counts[partition])
            for item in ordered[cursor : cursor + n]:
                source_id = f"taxonomy:{detector}:{item['event_gps']:.6f}"
                output.append(
                    _row(
                        partition=partition,
                        role="teacher_positive",
                        detector=detector,
                        morphology="exact_DANTE_positive",
                        run="O4A",
                        gps_start=item["window_gps"],
                        source_kind="historical_exact_dante_positive",
                        source_id=source_id,
                        seed=seed,
                        stratum={
                            "score_quantile_stratum": item["score_quantile_stratum"],
                            "historical_taxonomy_class": item["class"],
                            "historical_taxonomy_family": item["family"],
                        },
                    )
                )
            cursor += n
        remaining_by_detector[detector] = ordered[cursor:]
        diagnostics[detector] = {
            "exact_threshold": float(epochs["epochs"][detector]["threshold"]),
            "fresh_unique_positive_blocks": len(ordered),
            "selected_primary_blocks": required,
            "remaining_after_primary": len(ordered) - required,
            "family_counts_selected": dict(
                Counter(
                    row["stratum"]["historical_taxonomy_family"]
                    for row in output
                    if row["detector"] == detector and row["role"] == "teacher_positive"
                )
            ),
            "class_counts_selected": dict(
                Counter(
                    row["stratum"]["historical_taxonomy_class"]
                    for row in output
                    if row["detector"] == detector and row["role"] == "teacher_positive"
                )
            ),
        }
    return output, diagnostics, remaining_by_detector


def _transfer_background_rows(root: Path, *, seed: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    mapping = {
        "phase_d_development": "training",
        "phase_c": "threshold_search",
        "phase_d_confirmation": "risk_calibration",
    }
    for source in _read_jsonl(root / "config/dante_light_prefilter_v6_partitions.jsonl"):
        if source["partition"] not in mapping:
            continue
        partition = mapping[source["partition"]]
        starts = source["selected_window_starts"]
        if len(starts) != 1:
            raise ContractError("reserved v6 transfer must contain one frozen window")
        result.append(
            _row(
                partition=partition,
                role="background",
                detector=source["detector"],
                morphology="o4a_shadow_traffic",
                run="O4A",
                gps_start=float(starts[0]),
                source_kind="transferred_frozen_o4a_background",
                source_id=f"v6:{source['partition']}:{source['block_key']}",
                seed=seed,
                stratum={"block_index": int(source["block_index"]), "window_index": 0},
                transfer={
                    "source_protocol": "v6",
                    "source_partition": source["partition"],
                    "source_subset": source["subset"],
                    "source_block_key": source["block_key"],
                    "source_outcomes_accessed": False,
                },
            )
        )
    for source in _read_jsonl(root / "config/dante_light_prefilter_splits_v5.jsonl"):
        if source["partition"] != "confirmation" or source["role"] != "background":
            continue
        result.append(
            _row(
                partition="confirmation",
                role="background",
                detector=source["detector"],
                morphology=source["morphology"],
                run=source["window"]["run"],
                gps_start=float(source["window"]["gps_start"]),
                source_kind="transferred_v5_confirmation_identity",
                source_id=source["cohort_id"],
                seed=seed,
                stratum=source["stratum"],
                transfer={
                    "source_protocol": "v5",
                    "source_partition": "confirmation",
                    "source_identity": source["cohort_id"],
                    "source_outcomes_accessed": False,
                },
            )
        )
    return result


def _calibration_robust_rows(
    remaining: Mapping[str, Sequence[Mapping[str, Any]]], *, seed: str, count: int
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for detector in DETECTORS:
        pool = [item for item in remaining[detector] if item["class"] == "ROBUST"]
        pool.sort(key=lambda item: (_priority(seed, "robust", detector, item["block"]), item["block"]))
        if len(pool) < count:
            raise ContractError(f"insufficient fresh ROBUST calibration blocks for {detector}")
        for item in pool[:count]:
            result.append(
                _row(
                    partition="risk_calibration",
                    role="robust_candidate",
                    detector=detector,
                    morphology="DANTE_ROBUST",
                    run="O4A",
                    gps_start=float(item["window_gps"]),
                    source_kind="detector_aware_taxonomy_identity",
                    source_id=f"taxonomy:{detector}:{item['event_gps']:.6f}",
                    seed=seed,
                    stratum={
                        "robustness_class": "ROBUST",
                        "taxonomy_family": item["family"],
                    },
                )
            )
    return result


def _prior_known_blocks_and_ids(root: Path) -> tuple[set[str], set[str]]:
    blocks: set[str] = set()
    source_ids: set[str] = set()
    for version in ("v1", "v2", "v4", "v5"):
        path = root / f"config/dante_light_prefilter_splits_{version}.jsonl"
        if not path.is_file():
            continue
        for row in _read_jsonl(path):
            if row.get("role") != "known_glitch":
                continue
            window = row["window"]
            blocks.add(
                f"{window['run']}:{window['detector']}:{math.floor(float(window['gps_start']) / 4096.0)}"
            )
            source_ids.add(str(row.get("gravityspy_id") or row["source"]["source_id"]))
    return blocks, source_ids


def _calibration_known_rows(root: Path, *, seed: str, count: int) -> list[dict[str, Any]]:
    prior_blocks, prior_ids = _prior_known_blocks_and_ids(root)
    candidates = _read_jsonl(root / "config/dante_light_prefilter_v4_known_source_snapshot.jsonl")
    result: list[dict[str, Any]] = []
    used_blocks = set(prior_blocks)
    for detector in DETECTORS:
        for morphology in ("Blip", "KoiFish", "ScatteredLight"):
            pool = []
            for source in candidates:
                if source["detector"] != detector or source["morphology"] != morphology:
                    continue
                source_id = str(source["gravityspy_id"])
                gps = float(source["event_time"]) - 16.0
                block_key = f"O3B:{detector}:{math.floor(gps / 4096.0)}"
                if source_id in prior_ids or block_key in used_blocks:
                    continue
                pool.append((source_id, gps, block_key))
            pool.sort(key=lambda item: (_priority(seed, "known", detector, morphology, item[0]), item[0]))
            chosen = []
            for item in pool:
                if item[2] in used_blocks:
                    continue
                chosen.append(item)
                used_blocks.add(item[2])
                if len(chosen) == count:
                    break
            if len(chosen) != count:
                raise ContractError(f"insufficient known-glitch calibration rows: {detector}/{morphology}")
            for source_id, gps, _ in chosen:
                result.append(
                    _row(
                        partition="risk_calibration",
                        role="known_glitch",
                        detector=detector,
                        morphology=morphology,
                        run="O3B",
                        gps_start=gps,
                        source_kind="gravity_spy_o3b",
                        source_id=source_id,
                        seed=seed,
                        stratum={"gravityspy_label": morphology},
                    )
                )
    return result


def _transfer_confirmation_protected(root: Path, *, seed: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    source_trials = {
        row["source_id"]: row
        for row in _read_jsonl(root / "config/dante_light_prefilter_v5_injection_trials.jsonl")
    }
    trials: list[dict[str, Any]] = []
    for source in _read_jsonl(root / "config/dante_light_prefilter_splits_v5.jsonl"):
        if source["partition"] != "confirmation" or source["role"] == "background":
            continue
        source_id = source["source"]["source_id"]
        rows.append(
            _row(
                partition="confirmation",
                role=source["role"],
                detector=source["detector"],
                morphology=source["morphology"],
                run=source["window"]["run"],
                gps_start=float(source["window"]["gps_start"]),
                source_kind="transferred_v5_confirmation_identity",
                source_id=source["cohort_id"],
                seed=seed,
                stratum=source["stratum"],
                transfer={
                    "source_protocol": "v5",
                    "source_partition": "confirmation",
                    "source_identity": source["cohort_id"],
                    "source_outcomes_accessed": False,
                },
            )
        )
        if source["role"] == "injection":
            trial = dict(source_trials[source_id])
            trial["v7_partition"] = "confirmation"
            trial["transfer_source"] = "v5_confirmation"
            trials.append(trial)
    return rows, trials


def _calibration_injections(
    background_rows: Sequence[Mapping[str, Any]],
    *,
    design: Mapping[str, Any],
    seed: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    backgrounds = {
        detector: [
            row
            for row in background_rows
            if row["partition"] == "risk_calibration" and row["detector"] == detector
        ]
        for detector in DETECTORS
    }
    waveforms = design["waveforms"]
    distances = [float(value) for value in waveforms["distance_mpc"]]
    per_distance = int(waveforms["trials_per_distance_detector_partition"])
    systems = [
        (name, "legacy_comparability", values)
        for name, values in waveforms["legacy_comparability"]["systems"].items()
    ]
    stress = waveforms["aligned_tidal_nsbh_stress"]
    systems.append((stress["system"], "aligned_tidal_nsbh_stress", stress))
    identities: list[dict[str, Any]] = []
    trials: list[dict[str, Any]] = []
    for detector in DETECTORS:
        for system, population, system_cfg in systems:
            ordered = sorted(
                backgrounds[detector],
                key=lambda row: (
                    _priority(seed, "injection-block", detector, system, row["block_key"]),
                    row["block_key"],
                ),
            )[: len(distances) * per_distance]
            if len(ordered) != len(distances) * per_distance:
                raise ContractError(f"insufficient calibration blocks for injections: {detector}/{system}")
            cell = 0
            for distance in distances:
                lhs_seed = int(_priority(seed, "lhs", detector, system, distance)[:16], 16)
                samples = qmc.LatinHypercube(d=8, strength=1, optimization=None, seed=lhs_seed).random(per_distance)
                for local_index in range(per_distance):
                    base = ordered[cell]
                    cell += 1
                    u = samples[local_index]
                    trial_index = distances.index(distance) * per_distance + local_index
                    source_id = f"v7cal:{detector}:{system}:{trial_index}"
                    trial: dict[str, Any] = {
                        "schema_version": 1,
                        "source_id": source_id,
                        "detector": detector,
                        "partition": "risk_calibration",
                        "population": population,
                        "system": system,
                        "distance_mpc": distance,
                        "trial_index": trial_index,
                        "gps_start": float(base["window"]["gps_start"]),
                        "inclination_rad": float(np.arccos(2 * u[0] - 1)),
                        "ra_rad": float(2 * np.pi * u[1]),
                        "dec_rad": float(np.arcsin(2 * u[2] - 1)),
                        "psi_rad": float(np.pi * u[3]),
                        "outcome_fields_present": [],
                    }
                    if population == "legacy_comparability":
                        trial["approximant"] = waveforms["legacy_comparability"]["approximant"]
                        trial.update(system_cfg)
                    else:
                        trial.update(
                            {
                                "approximant": stress["approximant"],
                                "mass_1_msun": float(stress["black_hole_mass_msun"][0] + u[4] * (stress["black_hole_mass_msun"][1] - stress["black_hole_mass_msun"][0])),
                                "mass_2_msun": float(stress["neutron_star_mass_msun"][0] + u[5] * (stress["neutron_star_mass_msun"][1] - stress["neutron_star_mass_msun"][0])),
                                "spin_1z": float(stress["black_hole_aligned_spin"][0] + u[6] * (stress["black_hole_aligned_spin"][1] - stress["black_hole_aligned_spin"][0])),
                                "spin_2z": float(stress["neutron_star_aligned_spin"]),
                                "lambda_2": float(stress["neutron_star_tidal_lambda"][0] + u[7] * (stress["neutron_star_tidal_lambda"][1] - stress["neutron_star_tidal_lambda"][0])),
                                "f_low_hz": float(stress["f_low_hz"]),
                            }
                        )
                    trial["trial_digest"] = canonical_json_sha256(trial)
                    trials.append(trial)
                    identities.append(
                        _row(
                            partition="risk_calibration",
                            role="injection",
                            detector=detector,
                            morphology=system,
                            run="O4A",
                            gps_start=float(base["window"]["gps_start"]),
                            source_kind="software_injection",
                            source_id=source_id,
                            seed=seed,
                            stratum={
                                "population": population,
                                "system": system,
                                "distance_mpc": distance,
                                "trial_index": trial_index,
                                "base_block_key": base["block_key"],
                            },
                        )
                    )
    return identities, trials


def _validate_manifest(rows: Sequence[Mapping[str, Any]], design: Mapping[str, Any]) -> None:
    if not rows:
        raise ContractError("v7 identity manifest is empty")
    ids = [str(row["identity_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ContractError("duplicate v7 identity_id")
    for row in rows:
        if row["partition"] not in PARTITIONS or row["detector"] not in DETECTORS:
            raise ContractError("invalid v7 partition or detector")
        WindowIdentity.from_dict(row["window"])
    for detector in DETECTORS:
        for partition, expected in design["identity_counts"]["background_per_detector"].items():
            actual = sum(
                row["detector"] == detector
                and row["partition"] == partition
                and row["role"] == "background"
                for row in rows
            )
            if actual != int(expected):
                raise ContractError(f"background count mismatch: {detector}/{partition}")
        for partition, expected in design["identity_counts"]["teacher_positive_per_detector"].items():
            actual = sum(
                row["detector"] == detector
                and row["partition"] == partition
                and row["role"] == "teacher_positive"
                for row in rows
            )
            if actual != int(expected):
                raise ContractError(f"teacher-positive count mismatch: {detector}/{partition}")
    # Primary teacher-positive identities use one O4a case per 4096 s block
    # and are disjoint from all background identities in all v7 partitions.
    primary = [row for row in rows if row["role"] == "teacher_positive"]
    primary_blocks = [row["block_key"] for row in primary]
    if len(primary_blocks) != len(set(primary_blocks)):
        raise ContractError("teacher-positive block reused across v7 partitions")
    background_blocks = {row["block_key"] for row in rows if row["role"] == "background"}
    if set(primary_blocks) & background_blocks:
        raise ContractError("teacher-positive/background block overlap")
    for role in ("teacher_positive", "robust_candidate", "known_glitch"):
        for detector in DETECTORS:
            for partition in ("risk_calibration", "confirmation"):
                blocks = [
                    row["block_key"]
                    for row in rows
                    if row["role"] == role
                    and row["detector"] == detector
                    and row["partition"] == partition
                ]
                if len(blocks) != len(set(blocks)):
                    raise ContractError(f"non-independent blocks in {role}/{detector}/{partition}")
    for detector in DETECTORS:
        for partition in ("risk_calibration", "confirmation"):
            morphologies = {
                row["morphology"]
                for row in rows
                if row["role"] == "injection"
                and row["detector"] == detector
                and row["partition"] == partition
            }
            for morphology in morphologies:
                blocks = [
                    row["block_key"]
                    for row in rows
                    if row["role"] == "injection"
                    and row["detector"] == detector
                    and row["partition"] == partition
                    and row["morphology"] == morphology
                ]
                if len(blocks) != len(set(blocks)):
                    raise ContractError(
                        f"non-independent injection blocks in {detector}/{partition}/{morphology}"
                    )
    for detector in DETECTORS:
        for partition in PARTITIONS:
            pblocks = {
                row["block_key"]
                for row in primary
                if row["detector"] == detector and row["partition"] == partition
            }
            for other in PARTITIONS:
                if other == partition:
                    continue
                oblocks = {
                    row["block_key"]
                    for row in primary
                    if row["detector"] == detector and row["partition"] == other
                }
                if pblocks & oblocks:
                    raise ContractError("primary positive partitions overlap")


def _power_artifact(design: Mapping[str, Any]) -> dict[str, Any]:
    gate = design["gates"]["retention"]
    true_retention = float(design["power"]["true_retention_alternative"])
    rows = []
    for n in (18, 20, 25, 39, 45, 60, 90, 150, 300):
        minimum = minimum_passing_successes(
            n,
            minimum_retention=float(gate["minimum_point_retention"]),
            minimum_wilson_lower=float(gate["minimum_wilson_lower"]),
            confidence=float(gate["wilson_confidence"]),
        )
        rows.append(
            {
                "n": n,
                "minimum_retained": minimum,
                "minimum_observed_retention": minimum / n,
                "pass_probability_at_true_retention": gate_pass_probability(
                    n,
                    true_retention=true_retention,
                    minimum_retention=float(gate["minimum_point_retention"]),
                    minimum_wilson_lower=float(gate["minimum_wilson_lower"]),
                    confidence=float(gate["wilson_confidence"]),
                ),
            }
        )
    body = {
        "schema_version": 1,
        "status": "FROZEN_POWER_ANALYSIS",
        "primary_endpoint": "P(Light_defers|exact_DANTE_retains)",
        "retention_gate": gate,
        "true_retention_alternative": true_retention,
        "minimum_pass_probability": float(design["power"]["minimum_pass_probability"]),
        "candidate_results": rows,
        "frozen_primary_n_per_detector": {
            "threshold_search": int(design["identity_counts"]["teacher_positive_per_detector"]["threshold_search"]),
            "risk_calibration": int(design["identity_counts"]["teacher_positive_per_detector"]["risk_calibration"]),
            "confirmation": int(design["identity_counts"]["teacher_positive_per_detector"]["confirmation"]),
        },
        "protected_n_per_detector_morphology": {
            "robust_candidate": 60,
            "known_glitch": 60,
            "injection": 90,
        },
        "background_precision": {
            partition: {
                "n_per_detector": int(n),
                "worst_case_wilson_half_width": worst_case_wilson_half_width(
                    int(n), confidence=float(gate["wilson_confidence"])
                )
                if int(n) % 2 == 0
                else None,
            }
            for partition, n in design["identity_counts"]["background_per_detector"].items()
        },
        "selection_adjustment": {
            "method": "independent_fixed_holdout",
            "threshold_selected_once_on": "threshold_search",
            "threshold_frozen_before": "risk_calibration",
            "risk_bound_evaluated_once_on": "risk_calibration",
            "retuning_after_calibration_allowed": False,
            "confirmation_opened_only_after_all_calibration_gates_pass": True,
            "same_sample_SGR_or_pointwise_post_selection_interval_used": False,
        },
        "block_independence": "one_case_per_detector_4096s_block_within_each_gated_stratum",
        "net_saving_power_claimed": False,
        "outcomes_accessed": [],
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def default_design(prevalence: Mapping[str, Any]) -> dict[str, Any]:
    v5 = _read_json(ROOT / "config/dante_light_prefilter_v5_design.json")
    return {
        "schema_version": 1,
        "status": "APPROVED_OUTCOME_BLIND_FREEZE_INPUT",
        "protocol_id": PROTOCOL_ID,
        "task": {
            "type": "selective_deferral_binary_safety_triage",
            "population_scope": "frozen_retrospective_O4a_candidate_catalog_plus_natural_shadow_traffic",
            "student_score": "estimated_probability_of_defer_label",
            "routing_rule": "defer_if_score_greater_than_or_equal_to_detector_threshold_else_discard",
            "safe_discard_label": "historical_exact_DANTE_at_or_below_detector_threshold",
            "defer_label": "historical_exact_DANTE_strictly_above_detector_threshold",
            "physical_truth_label": False,
            "spearman_role": "diagnostic_only_not_a_gate",
        },
        "identity_counts": {
            "background_per_detector": {
                "training": 150,
                "threshold_search": 60,
                "risk_calibration": 150,
                "confirmation": 300,
            },
            "teacher_positive_per_detector": {
                "training": 150,
                "threshold_search": 60,
                "risk_calibration": 60,
                "confirmation": 60,
            },
            "protected_per_detector_morphology": {
                "risk_calibration": {"robust_candidate": 60, "known_glitch": 60, "injection": 90},
                "confirmation": {"robust_candidate": 60, "known_glitch": 60, "injection": 90},
            },
        },
        "threshold_selection": {
            "objective": "maximum_natural_background_discard_fraction",
            "constraint": "teacher_positive_retention_gate_passes_separately_for_H1_and_L1",
            "selection_partition": "threshold_search",
            "ties": "lowest_numeric_discard_threshold_then_lexicographic_model_identity",
            "tie_interpretation": "lower_defer_probability_threshold_is_the_more_conservative_rule",
            "freeze_before_risk_calibration": True,
            "calibration_failure_action": "STOP_NO_RETUNE_NO_FALLBACK",
        },
        "gates": {
            "retention": dict(v5["gates"]["protected_retention"]),
            "primary_teacher_positive": {
                "endpoint": "P(Light_defers|exact_DANTE_retains, frozen_O4a_candidate_catalog)",
                "separate_by_detector": True,
                "same_numeric_rule_as_protected_retention": True,
            },
            "protected_morphology": {
                "separate_by_detector_and_morphology": True,
                "aggregation_across_morphologies_allowed": False,
                "same_numeric_rule_as_protected_retention": True,
            },
            "operational": dict(v5["gates"]["operational"]),
            "uncertainty": dict(v5["gates"]["uncertainty"]),
        },
        "power": dict(v5["power"]),
        "waveforms": dict(v5["waveforms"]),
        "scientific_boundary": {
            "historical_exact_DANTE_positive_is_teacher_behavior_not_physical_truth": True,
            "primary_teacher_positive_population_is_catalog_conditioned_not_continuous_traffic": True,
            "primary_gate_kept_because_it_covers_teacher_positive_cases_outside_enumerated_protected_roles": True,
            "observed_o4a_teacher_positive_population_is_overwhelmingly_Family_01": True,
            "primary_gate_does_not_establish_broad_unseen_morphology_coverage": True,
            "false_omission_risk_on_natural_background": "secondary_only_if_enough_teacher_positives_exist",
            "o4b_access_allowed": False,
            "routing_enabled": False,
            "does_not_establish": [
                "independent_physical_or_astrophysical_classification",
                "global_exact_DANTE_score_fidelity",
                "unseen_morphology_safety",
                "O4b_or_operational_routing_readiness",
            ],
        },
        "retrospective_prevalence_evidence": {
            "H1": dict(prevalence["counts"]["H1"]),
            "L1": dict(prevalence["counts"]["L1"]),
            "zero_of_1440_claim_rejected": True,
            "role": "design_diagnosis_only_not_v7_confirmation",
        },
    }


def build_freeze(root: Path = ROOT, *, freeze_basis_commit: str) -> dict[str, Any]:
    upstream = _validate_upstream_unopened(root)
    prevalence, prevalence_rows = _background_prevalence_audit(root)
    prevalence_rows_path = root / "artifacts/dante_light/prefilter_l4_v7_design/background_teacher_prevalence_rows_v7.jsonl"
    _write_jsonl(prevalence_rows_path, prevalence_rows)
    prevalence_path = root / "artifacts/dante_light/prefilter_l4_v7_design/background_teacher_prevalence_audit_v7.json"
    prevalence["rows_reference"] = repository_reference(root, prevalence_rows_path)
    prevalence["artifact_digest"] = canonical_json_sha256(
        {key: value for key, value in prevalence.items() if key != "artifact_digest"}
    )
    _write_json(prevalence_path, prevalence)
    design = default_design(prevalence)
    design_body = dict(design)
    design["contract_digest"] = canonical_json_sha256(design_body)
    design_path = root / "config/dante_light_prefilter_v7_outcome_blind_contract.json"
    _write_json(design_path, design)
    seed = design["contract_digest"]

    backgrounds = _transfer_background_rows(root, seed=seed)
    positives, positive_diagnostics, remaining = _select_teacher_positive_rows(
        root,
        seed=seed,
        counts=design["identity_counts"]["teacher_positive_per_detector"],
    )
    robust = _calibration_robust_rows(remaining, seed=seed, count=60)
    known = _calibration_known_rows(root, seed=seed, count=60)
    confirmation_protected, transferred_trials = _transfer_confirmation_protected(root, seed=seed)
    calibration_injections, calibration_trials = _calibration_injections(
        backgrounds, design=design, seed=seed
    )
    rows = sorted(
        [*backgrounds, *positives, *robust, *known, *confirmation_protected, *calibration_injections],
        key=lambda row: (
            PARTITIONS.index(row["partition"]),
            row["detector"],
            row["role"],
            row["morphology"],
            row["identity_id"],
        ),
    )
    _validate_manifest(rows, design)
    manifest_path = root / "config/dante_light_prefilter_v7_identities.jsonl"
    _write_jsonl(manifest_path, rows)
    trials_path = root / "config/dante_light_prefilter_v7_injection_trials.jsonl"
    trials = sorted(
        [*calibration_trials, *transferred_trials],
        key=lambda row: (str(row.get("v7_partition", row.get("partition"))), row["detector"], row["system"], int(row["trial_index"])),
    )
    _write_jsonl(trials_path, trials)

    power = _power_artifact(design)
    power_path = root / "artifacts/dante_light/prefilter_l4_v7_design/selective_deferral_power_v7.json"
    _write_json(power_path, power)
    counts = Counter(
        (row["partition"], row["role"], row["detector"], row["morphology"])
        for row in rows
    )
    transfer_contract_body = {
        "schema_version": 1,
        "status": "TRANSFERRED_IDENTITIES_RETIRED_FROM_PRIOR_RESERVED_USE",
        "upstream_boundary": upstream,
        "source_references": {
            "v5_confirmation_seal": repository_reference(root, root / "config/dante_light_prefilter_v5_confirmation_seal.json"),
            "v5_identities": repository_reference(root, root / "config/dante_light_prefilter_splits_v5.jsonl"),
            "v6_partitions": repository_reference(root, root / "config/dante_light_prefilter_v6_partitions.jsonl"),
            "v6_phase_b_result": repository_reference(root, root / "artifacts/dante_light/prefilter_l4_v6_training/phase_b_screening_summary_v6.json"),
        },
        "mapping": {
            "v6.phase_d_development": "v7.training.background",
            "v6.phase_c": "v7.threshold_search.background",
            "v6.phase_d_confirmation": "v7.risk_calibration.background",
            "v5.confirmation": "v7.confirmation.background_and_protected",
        },
        "source_outcomes_accessed_for_transferred_rows": [],
        "future_use_under_prior_protocols": "RETIRED",
    }
    transfer_contract = {
        **transfer_contract_body,
        "transfer_digest": canonical_json_sha256(transfer_contract_body),
    }
    transfer_path = root / "config/dante_light_prefilter_v7_identity_transfer.json"
    _write_json(transfer_path, transfer_contract)

    header_body = {
        "schema_version": 1,
        "status": "FROZEN_IDENTITY_ONLY_NOT_OPENED",
        "protocol_reference": repository_reference(root, design_path),
        "manifest_reference": repository_reference(root, manifest_path),
        "injection_trials_reference": repository_reference(root, trials_path),
        "power_reference": repository_reference(root, power_path),
        "transfer_reference": repository_reference(root, transfer_path),
        "source_references": {
            "historical_thresholds": repository_reference(root, root / "config/dante_light_epochs_v1.json"),
            "exact_dante_runner": repository_reference(root, root / "src/dante_light/runner.py"),
            "taxonomy": repository_reference(root, root / "data/production/aggregated/Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"),
            "known_glitch_snapshot": repository_reference(root, root / "config/dante_light_prefilter_v4_known_source_snapshot.jsonl"),
            "selection_code": repository_reference(root, Path(__file__)),
            "background_teacher_prevalence_audit": repository_reference(root, prevalence_path),
        },
        "freeze_basis_commit": freeze_basis_commit,
        "counts": {"/".join(key): value for key, value in sorted(counts.items())},
        "teacher_positive_diagnostics": positive_diagnostics,
        "outcome_access_at_freeze": {
            "v7_student_outputs": [],
            "threshold_search_student_outputs": [],
            "risk_calibration_student_outputs": [],
            "confirmation_student_outputs": [],
            "o4b": [],
        },
        "historical_design_evidence_used": {
            "teacher_threshold_and_taxonomy_labels": True,
            "v6_background_prevalence_audit": {
                detector: dict(prevalence["counts"][detector]) for detector in DETECTORS
            },
            "role": "design_diagnosis_and_case_control_identity_selection_only",
        },
    }
    header = {**header_body, "manifest_digest": canonical_json_sha256(header_body)}
    header_path = root / "config/dante_light_prefilter_v7_identities.json"
    _write_json(header_path, header)

    confirmation_rows = [row for row in rows if row["partition"] == "confirmation"]
    confirmation_identity_digest = canonical_json_sha256(
        [
            {"identity_id": row["identity_id"], "window_id": row["window"]["window_id"], "source_id": row["source"]["source_id"]}
            for row in confirmation_rows
        ]
    )
    seal_body = {
        "schema_version": 1,
        "status": "SEALED_NOT_OPENED",
        "freeze_basis_commit": freeze_basis_commit,
        "protocol_reference": repository_reference(root, design_path),
        "identity_header_reference": repository_reference(root, header_path),
        "identity_manifest_reference": repository_reference(root, manifest_path),
        "confirmation_identity_digest": confirmation_identity_digest,
        "protected_endpoints": [
            "teacher_positive_retention_by_detector",
            "protected_retention_by_detector_and_morphology",
            "natural_background_discard_fraction_by_detector",
            "paired_block_bootstrap_mean_net_saving",
            "paired_prefilter_and_exact_path_costs",
        ],
        "threshold_binding_required_before_unlock": [
            "model_digest",
            "training_digest",
            "threshold_search_result_digest",
            "frozen_threshold_digest",
            "risk_calibration_result_digest",
            "verifier_digest",
        ],
        "unlock_rule": "all_risk_calibration_gates_pass_once_no_retune",
        "declared_storage_roots": [
            {"root_id": "repository", "kind": "repository_relative", "location": "."},
            {"root_id": "raw_strain", "kind": "environment_alias", "location": "DANTE_RAW_STRAIN_ROOT"},
            {"root_id": "v7_cache", "kind": "environment_alias", "location": "DANTE_V7_CACHE_ROOT"},
        ],
        "initial_access_log_sha256": EMPTY_SHA256,
        "access_entries_at_freeze": 0,
        "confirmation_student_outputs_accessed": [],
        "o4b_accessed": [],
    }
    seal = {**seal_body, "seal_digest": canonical_json_sha256(seal_body)}
    seal_path = root / "config/dante_light_prefilter_v7_confirmation_seal.json"
    _write_json(seal_path, seal)
    return {
        "design": design,
        "header": header,
        "rows": rows,
        "trials": trials,
        "power": power,
        "transfer": transfer_contract,
        "seal": seal,
    }


def verify_freeze(root: Path = ROOT) -> dict[str, Any]:
    design_path = root / "config/dante_light_prefilter_v7_outcome_blind_contract.json"
    design = _read_json(design_path)
    body = dict(design)
    declared = body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v7 design digest mismatch")
    rows = _read_jsonl(root / "config/dante_light_prefilter_v7_identities.jsonl")
    _validate_manifest(rows, design)
    header = _read_json(root / "config/dante_light_prefilter_v7_identities.json")
    header_body = dict(header)
    header_digest = header_body.pop("manifest_digest", None)
    if header_digest != canonical_json_sha256(header_body):
        raise ContractError("v7 identity header digest mismatch")
    for reference in [
        header["protocol_reference"],
        header["manifest_reference"],
        header["injection_trials_reference"],
        header["power_reference"],
        header["transfer_reference"],
        *header["source_references"].values(),
    ]:
        path = root / reference["path"]
        if not path.is_file() or not _reference_matches(root, reference):
            raise ContractError(f"v7 reference mismatch: {reference['path']}")
    if any(header["outcome_access_at_freeze"].values()):
        raise ContractError("v7 outcome boundary violated")
    prevalence_reference = header["source_references"]["background_teacher_prevalence_audit"]
    prevalence = _read_json(root / prevalence_reference["path"])
    prevalence_body = dict(prevalence)
    prevalence_digest = prevalence_body.pop("artifact_digest", None)
    if prevalence_digest != canonical_json_sha256(prevalence_body):
        raise ContractError("v7 prevalence artifact digest mismatch")
    prevalence_rows_reference = prevalence["rows_reference"]
    prevalence_rows_path = root / prevalence_rows_reference["path"]
    if (
        not prevalence_rows_path.is_file()
        or not _reference_matches(root, prevalence_rows_reference)
    ):
        raise ContractError("v7 prevalence row-ledger reference mismatch")
    prevalence_rows = _read_jsonl(prevalence_rows_path)
    if canonical_json_sha256(prevalence_rows) != prevalence["rows_digest"]:
        raise ContractError("v7 prevalence row-ledger digest mismatch")
    for detector in DETECTORS:
        selected = [row for row in prevalence_rows if row["detector"] == detector]
        retained = sum(bool(row["exact_dante_retains"]) for row in selected)
        expected = prevalence["counts"][detector]
        if len(selected) != int(expected["n"]) or retained != int(expected["exact_dante_retained"]):
            raise ContractError(f"v7 prevalence count mismatch: {detector}")
    transfer = _read_json(root / "config/dante_light_prefilter_v7_identity_transfer.json")
    transfer_body = dict(transfer)
    transfer_digest = transfer_body.pop("transfer_digest", None)
    if transfer_digest != canonical_json_sha256(transfer_body):
        raise ContractError("v7 transfer digest mismatch")
    if transfer["source_outcomes_accessed_for_transferred_rows"] != []:
        raise ContractError("v7 transfer opened a protected source")
    power = _read_json(root / "artifacts/dante_light/prefilter_l4_v7_design/selective_deferral_power_v7.json")
    power_body = dict(power)
    power_digest = power_body.pop("artifact_digest", None)
    if power_digest != canonical_json_sha256(power_body) or power_body != {
        key: value for key, value in _power_artifact(design).items() if key != "artifact_digest"
    }:
        raise ContractError("v7 power artifact mismatch")
    seal = _read_json(root / "config/dante_light_prefilter_v7_confirmation_seal.json")
    seal_body = dict(seal)
    seal_digest = seal_body.pop("seal_digest", None)
    if seal_digest != canonical_json_sha256(seal_body) or seal["status"] != "SEALED_NOT_OPENED":
        raise ContractError("v7 confirmation seal mismatch")
    confirmation_rows = [row for row in rows if row["partition"] == "confirmation"]
    expected_confirmation = canonical_json_sha256(
        [
            {"identity_id": row["identity_id"], "window_id": row["window"]["window_id"], "source_id": row["source"]["source_id"]}
            for row in confirmation_rows
        ]
    )
    if seal["confirmation_identity_digest"] != expected_confirmation:
        raise ContractError("v7 confirmation identity digest mismatch")
    if seal["access_entries_at_freeze"] != 0 or seal["initial_access_log_sha256"] != EMPTY_SHA256:
        raise ContractError("v7 confirmation access log is not empty at freeze")
    return {
        "status": "PASS",
        "protocol_id": design["protocol_id"],
        "contract_digest": design["contract_digest"],
        "manifest_digest": header["manifest_digest"],
        "seal_digest": seal["seal_digest"],
        "identity_count": len(rows),
        "confirmation_identity_count": len(confirmation_rows),
        "outcome_access_at_freeze": header["outcome_access_at_freeze"],
    }
