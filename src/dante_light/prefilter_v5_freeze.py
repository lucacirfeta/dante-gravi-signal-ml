"""Outcome-blind construction of the DANTE-Light v5 protocol and identities."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.stats import qmc

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v5_protocol import (
    PROTOCOL_ID, derive_seed, protocol_digest, repository_reference, validate_protocol,
)
from src.dante_light.prefilter_v5_seal import build_confirmation_seal, build_identity_manifest


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for row in rows), encoding="utf-8", newline="\n")


def _priority(seed: int, *parts: object) -> str:
    return hashlib.sha256(json.dumps([seed, *parts], separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _reference(root: Path, relative: str) -> dict[str, str]:
    return repository_reference(root, root / relative)


def _contained(segments: Sequence[Sequence[int]], start: float, end: float) -> bool:
    return any(float(left) <= start and end <= float(right) for left, right in segments)


def _hardware_clear(flags: Mapping[str, Any], detector: str, start: float, end: float) -> bool:
    return all(not (float(left) < end and start < float(right)) for suffix in ("HW_INJ", "CBC_INJ", "BURST_INJ") for left, right in flags[f"{detector}_O4A_{suffix}"]["segments"])


def _valid_starts(flags: Mapping[str, Any], detector: str, block: int, *, duration: float, pad: float) -> list[float]:
    left = block * 4096
    right = left + 4096
    cat1 = [
        (float(start), float(end))
        for start, end in flags[f"{detector}_O4A_CBC_CAT1"]["segments"]
        if float(start) < right and left < float(end)
    ]
    excluded = [
        (float(start), float(end))
        for suffix in ("HW_INJ", "CBC_INJ", "BURST_INJ")
        for start, end in flags[f"{detector}_O4A_{suffix}"]["segments"]
        if float(start) < right and left < float(end)
    ]
    result = []
    for offset in range(int(pad), 4096 - int(duration + pad) + 1, 4):
        start = float(left + offset); padded_left = start - pad; padded_right = start + duration + pad
        if any(a <= padded_left and padded_right <= b for a, b in cat1) and all(not (a < padded_right and padded_left < b) for a, b in excluded):
            result.append(start)
    return result


def _choose_starts(candidates: Sequence[float], count: int, *, seed: int, identity: str, forbidden: Sequence[tuple[float, float]] = ()) -> list[float]:
    chosen: list[float] = []
    occupied = list(forbidden)
    for start in sorted(candidates, key=lambda value: (_priority(seed, identity, value), value)):
        interval = (start - 4.0, start + 36.0)
        if any(left < interval[1] and interval[0] < right for left, right in occupied):
            continue
        chosen.append(start); occupied.append(interval)
        if len(chosen) == count:
            return chosen
    raise ContractError(f"insufficient disjoint valid windows for {identity}: {len(chosen)}/{count}")


def _identity(*, role: str, detector: str, morphology: str, partition: str, gps: float, priority: str, source_kind: str, run: str, source_id: str, stratum: Mapping[str, Any]) -> dict[str, Any]:
    window = WindowIdentity(run, detector, float(gps), 32.0)
    return {
        "schema_version": 1,
        "cohort_id": f"v5-{partition}-{role}:{detector}:{source_id}",
        "role": role,
        "detector": detector,
        "morphology": morphology,
        "partition": partition,
        "partition_priority": priority,
        "retention_target": role != "background",
        "source": {"kind": source_kind, "run": run, "source_id": source_id},
        "stratum": dict(stratum),
        "window": window.to_dict(),
    }


def _load_prior_o3b(root: Path) -> tuple[set[str], set[str]]:
    blocks: set[str] = set(); source_ids: set[str] = set()
    for version in ("v1", "v2", "v4"):
        path = root / f"config/dante_light_prefilter_splits_{version}.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("role") != "known_glitch":
                continue
            window = row["window"]
            blocks.add(f"{window['detector']}:{math.floor(float(window['gps_start']) / 4096)}")
            source_ids.add(str(row.get("gravityspy_id") or row.get("source", {}).get("source_id")))
    return blocks, source_ids


def _robust_candidates(root: Path, fresh: set[str], flags: Mapping[str, Any], seed: int) -> dict[str, list[dict[str, Any]]]:
    result = {"H1": [], "L1": []}; seen = set()
    path = root / "data/production/aggregated/Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            detector = str(row["detector"])
            if detector not in result or row["robustness_class"] != "ROBUST":
                continue
            event = float(row["gps_start"]); gps = event + 4.0; block = math.floor(gps / 4096); key = f"{detector}:{block}"
            padded = (gps - 4.0, gps + 36.0)
            if key not in fresh or key in seen or not _contained(flags[f"{detector}_O4A_CBC_CAT1"]["segments"], *padded) or not _hardware_clear(flags, detector, *padded):
                continue
            source_id = f"taxonomy:{detector}:{event:.6f}"
            result[detector].append({"block": block, "gps": gps, "source_id": source_id, "family": str(row["global_family_id"]), "priority": _priority(seed, detector, source_id)})
            seen.add(key)
    for detector in result:
        result[detector].sort(key=lambda row: (row["priority"], row["source_id"]))
    return result


def _select_o4a_partitions(design: Mapping[str, Any], fresh: set[str], flags: Mapping[str, Any], robust: Mapping[str, Sequence[Mapping[str, Any]]], seed: int) -> tuple[dict[tuple[str, str], list[int]], dict[tuple[str, int], Mapping[str, Any]], dict[tuple[str, int], list[float]]]:
    counts = design["partition_contract"]["blocks_per_detector"]
    robust_n = design["partition_contract"]["protected_per_detector_stratum"]["robust_candidate"]
    selected: dict[tuple[str, str], list[int]] = {}; robust_by_block = {}; valid = {}
    for detector in design["signal"]["detectors"]:
        eligible = []
        for key in sorted(fresh):
            name, raw_block = key.split(":")
            if name != detector:
                continue
            block = int(raw_block); starts = _valid_starts(flags, detector, block, duration=float(design["signal"]["window_duration_s"]), pad=float(design["signal"]["whitening_context_pad_s"]))
            try:
                _choose_starts(starts, int(design["partition_contract"]["background_windows_per_block"]["training"]), seed=seed, identity=f"capacity:{detector}:{block}")
            except ContractError:
                continue
            eligible.append(block); valid[(detector, block)] = starts
        required_robust = int(robust_n["development"]) + int(robust_n["confirmation"])
        robust_pool = [row for row in robust[detector] if row["block"] in set(eligible)]
        if len(robust_pool) < required_robust:
            raise ContractError(f"insufficient fresh ROBUST blocks for {detector}: {len(robust_pool)}/{required_robust}")
        cursor = 0; used = set()
        for partition in ("development", "confirmation"):
            n = int(robust_n[partition]); rows = robust_pool[cursor:cursor+n]; cursor += n
            blocks = [int(row["block"]) for row in rows]; used.update(blocks)
            selected[(detector, partition)] = blocks
            for row in rows: robust_by_block[(detector, int(row["block"]))] = row
        remaining = sorted((block for block in eligible if block not in used), key=lambda block: (_priority(seed, "fill", detector, block), block))
        for partition in ("development", "confirmation"):
            needed = int(counts[partition]) - len(selected[(detector, partition)])
            selected[(detector, partition)].extend(remaining[:needed]); remaining = remaining[needed:]
        training_n = int(counts["training"])
        if len(remaining) < training_n:
            raise ContractError(f"insufficient eligible v5 blocks for {detector}: {len(remaining)}/{training_n}")
        selected[(detector, "training")] = remaining[:training_n]
    return selected, robust_by_block, valid


def _background_and_robust_rows(design: Mapping[str, Any], selected: Mapping[tuple[str, str], Sequence[int]], robust_by_block: Mapping[tuple[str, int], Mapping[str, Any]], valid: Mapping[tuple[str, int], Sequence[float]], seeds: Mapping[str, int]) -> tuple[list[dict[str, Any]], dict[tuple[str, int], list[tuple[float, float]]]]:
    rows = []; occupied: dict[tuple[str, int], list[tuple[float, float]]] = {}
    for (detector, partition), blocks in sorted(selected.items()):
        count = int(design["partition_contract"]["background_windows_per_block"][partition])
        for block in blocks:
            forbidden = []
            robust = robust_by_block.get((detector, block))
            if robust and partition != "training":
                forbidden.append((float(robust["gps"]) - 4.0, float(robust["gps"]) + 36.0))
            starts = _choose_starts(valid[(detector, block)], count, seed=seeds["background_windows"], identity=f"background:{detector}:{partition}:{block}", forbidden=forbidden)
            occupied[(detector, block)] = [*forbidden, *((start - 4.0, start + 36.0) for start in starts)]
            for index, gps in enumerate(starts):
                source_id = f"raw-block:{detector}:{block}:window:{index}"
                rows.append(_identity(role="background", detector=detector, morphology="o4a_shadow_traffic", partition=partition, gps=gps, priority=_priority(seeds["background_windows"], source_id), source_kind="o4a_raw_mirror_cbc_cat1", run="O4A", source_id=source_id, stratum={"block_index": block, "window_index": index}))
            if robust and partition != "training":
                rows.append(_identity(role="robust_candidate", detector=detector, morphology="DANTE_ROBUST", partition=partition, gps=float(robust["gps"]), priority=str(robust["priority"]), source_kind="detector_aware_taxonomy_identity", run="O4A", source_id=str(robust["source_id"]), stratum={"robustness_class": "ROBUST", "taxonomy_family": str(robust["family"])}))
    return rows, occupied


def _known_rows(root: Path, design: Mapping[str, Any], seed: int) -> list[dict[str, Any]]:
    prior_blocks, prior_ids = _load_prior_o3b(root); used_blocks = set(prior_blocks); result = []
    candidates = [json.loads(line) for line in (root / "config/dante_light_prefilter_v4_known_source_snapshot.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    n_by_partition = design["partition_contract"]["protected_per_detector_stratum"]["known_glitch"]
    for detector in design["signal"]["detectors"]:
        for morphology in design["partition_contract"]["known_glitch_morphologies"]:
            pool = []
            for row in candidates:
                source_id = str(row["gravityspy_id"]); gps = float(row["event_time"]) - 16.0; block = f"{detector}:{math.floor(gps/4096)}"
                if row["detector"] == detector and row["morphology"] == morphology and source_id not in prior_ids and block not in used_blocks:
                    pool.append({"gps": gps, "block": block, "source_id": source_id, "priority": _priority(seed, detector, morphology, source_id)})
            pool.sort(key=lambda row: (row["priority"], row["source_id"]))
            cursor = 0
            for partition in ("development", "confirmation"):
                needed = int(n_by_partition[partition]); chosen = []
                while cursor < len(pool) and len(chosen) < needed:
                    item = pool[cursor]; cursor += 1
                    if item["block"] in used_blocks: continue
                    chosen.append(item); used_blocks.add(item["block"])
                if len(chosen) != needed:
                    raise ContractError(f"insufficient fresh known glitches for {detector}/{morphology}/{partition}")
                for item in chosen:
                    result.append(_identity(role="known_glitch", detector=detector, morphology=morphology, partition=partition, gps=item["gps"], priority=item["priority"], source_kind="gravity_spy_o3b", run="O3B", source_id=item["source_id"], stratum={"gravityspy_label": morphology}))
    return result


def _lhs(seed: int, dimensions: int, count: int) -> np.ndarray:
    return qmc.LatinHypercube(d=dimensions, strength=1, optimization=None, seed=seed).random(count)


def _injection_rows(design: Mapping[str, Any], selected: Mapping[tuple[str, str], Sequence[int]], valid: Mapping[tuple[str, int], Sequence[float]], occupied: dict[tuple[str, int], list[tuple[float, float]]], seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    identities = []; trials = []; distances = [float(value) for value in design["waveforms"]["distance_mpc"]]
    per_distance = int(design["waveforms"]["trials_per_distance_detector_partition"])
    legacy = design["waveforms"]["legacy_comparability"]; stress = design["waveforms"]["aligned_tidal_nsbh_stress"]
    systems = [(name, "legacy_comparability", values) for name, values in legacy["systems"].items()] + [(stress["system"], "aligned_tidal_nsbh_stress", stress)]
    for detector in design["signal"]["detectors"]:
        for partition in ("development", "confirmation"):
            blocks = list(selected[(detector, partition)])
            for system_index, (system, population, system_cfg) in enumerate(systems):
                ordered_blocks = sorted(blocks, key=lambda block: (_priority(seed, "injection-block", detector, partition, system, block), block))[:len(distances)*per_distance]
                if len(ordered_blocks) != len(distances)*per_distance:
                    raise ContractError("insufficient v5 injection blocks")
                cell_cursor = 0
                for distance in distances:
                    cell_seed = int(_priority(seed, detector, partition, system, distance)[:16], 16)
                    samples = _lhs(cell_seed, 7, per_distance)
                    for local_index in range(per_distance):
                        block = ordered_blocks[cell_cursor]; cell_cursor += 1
                        gps = _choose_starts(valid[(detector, block)], 1, seed=seed, identity=f"injection:{detector}:{partition}:{system}:{distance}:{local_index}", forbidden=occupied[(detector, block)])[0]
                        occupied[(detector, block)].append((gps - 4.0, gps + 36.0))
                        u = samples[local_index]; trial_index = distances.index(distance) * per_distance + local_index
                        source_id = f"v5inj:{detector}:{partition}:{system}:{trial_index}"
                        trial = {
                            "schema_version": 1, "source_id": source_id, "detector": detector, "partition": partition,
                            "population": population, "system": system, "approximant": legacy["approximant"] if population == "legacy_comparability" else stress["approximant"],
                            "distance_mpc": distance, "trial_index": trial_index, "gps_start": gps,
                            "inclination_rad": float(np.arccos(2*u[0]-1)), "ra_rad": float(2*np.pi*u[1]), "dec_rad": float(np.arcsin(2*u[2]-1)), "psi_rad": float(np.pi*u[3]),
                            "outcome_fields_present": [],
                        }
                        if population == "legacy_comparability":
                            trial.update(system_cfg)
                        else:
                            trial.update({
                                "mass_1_msun": float(stress["black_hole_mass_msun"][0] + u[4] * (stress["black_hole_mass_msun"][1] - stress["black_hole_mass_msun"][0])),
                                "mass_2_msun": float(stress["neutron_star_mass_msun"][0] + u[5] * (stress["neutron_star_mass_msun"][1] - stress["neutron_star_mass_msun"][0])),
                                "spin_1z": float(stress["black_hole_aligned_spin"][0] + u[6] * (stress["black_hole_aligned_spin"][1] - stress["black_hole_aligned_spin"][0])),
                                "spin_2z": float(stress["neutron_star_aligned_spin"]),
                                "lambda_2": float(stress["neutron_star_tidal_lambda"][0] + ((u[4]+u[5]) % 1.0) * (stress["neutron_star_tidal_lambda"][1] - stress["neutron_star_tidal_lambda"][0])),
                                "f_low_hz": float(stress["f_low_hz"]),
                            })
                        trial["trial_digest"] = canonical_json_sha256(trial); trials.append(trial)
                        identities.append(_identity(role="injection", detector=detector, morphology=system, partition=partition, gps=gps, priority=_priority(seed, source_id), source_kind="software_injection", run="O4A", source_id=source_id, stratum={"population": population, "system": system, "distance_mpc": distance, "trial_index": trial_index}))
    return identities, trials


def build_protocol(root: Path, design: Mapping[str, Any], power_reference: Mapping[str, str]) -> dict[str, Any]:
    sources = {
        "identity_audit": _reference(root, "artifacts/dante_light/prefilter_l4_v5_design/identity_audit_v5.json"),
        "raw_manifest": _reference(root, "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl"),
        "segment_snapshot": _reference(root, "config/dante_light_prefilter_v4_segments.json"),
        "taxonomy": _reference(root, "data/production/aggregated/Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"),
        "known_source_snapshot": _reference(root, "config/dante_light_prefilter_v4_known_source_snapshot.jsonl"),
        "student_architectures": _reference(root, "src/dante_light/prefilter_v4_student.py"),
        "preprocessing": _reference(root, "src/dante_light/preprocessing.py"),
        "exact_dante_runner": _reference(root, "src/dante_light/runner.py"),
        "scattering_negative_feasibility": _reference(root, "artifacts/dante_light/prefilter_l4_v5_design/scattering_feasibility_v5.json"),
    }
    parent_digests = sorted([power_reference["sha256"], *[reference["sha256"] for reference in sources.values()]])
    seeds = {purpose: derive_seed(PROTOCOL_ID, purpose, parent_digests) for purpose in design["seed_derivation"]["purposes"]}
    body = {
        "schema_version": 5, "status": "FROZEN_OUTCOME_BLIND", "protocol_id": PROTOCOL_ID,
        "design_reference": _reference(root, "config/dante_light_prefilter_v5_design.json"),
        "power_artifact_reference": dict(power_reference), "approved_design": dict(design), "source_references": sources,
        "seed_derivation": {"method": design["seed_derivation"]["method"], "parent_digests": parent_digests, "seeds": seeds},
        "training_replicate_seeds": [seeds[f"training_replicate_{index}"] for index in range(int(design["students"]["replicate_count"]))],
        "outcome_access_at_freeze": {"teacher_scores": [], "student_outputs": [], "development": [], "confirmation": [], "o4b": []},
    }
    return {**body, "protocol_digest": canonical_json_sha256(body)}


def build_freeze(root: Path, *, freeze_commit: str) -> dict[str, Any]:
    design = json.loads((root / "config/dante_light_prefilter_v5_design.json").read_text(encoding="utf-8"))
    power_path = root / "artifacts/dante_light/prefilter_l4_v5_design/confirmation_power_analysis_v5.json"
    if not power_path.is_file():
        raise ContractError("v5 power artifact must be generated before the freeze")
    protocol = build_protocol(root, design, repository_reference(root, power_path)); protocol_path = root / "config/dante_light_prefilter_protocol_v5.json"; _write_json(protocol_path, protocol); validate_protocol(protocol, root=root)
    identity_audit = json.loads((root / "artifacts/dante_light/prefilter_l4_v5_design/identity_audit_v5.json").read_text(encoding="utf-8"))
    fresh = set(identity_audit["capacity"]["fresh_fully_covered_block_keys"]); prior = set(identity_audit["prior_usage"]["union_o4a_block_keys"])
    segments = json.loads((root / "config/dante_light_prefilter_v4_segments.json").read_text(encoding="utf-8"))["flags"]
    seeds = protocol["seed_derivation"]["seeds"]
    robust = _robust_candidates(root, fresh, segments, seeds["robust_selection"])
    selected, robust_by_block, valid = _select_o4a_partitions(design, fresh, segments, robust, seeds["partition"])
    rows, occupied = _background_and_robust_rows(design, selected, robust_by_block, valid, seeds)
    rows.extend(_known_rows(root, design, seeds["known_selection"]))
    injection_rows, trials = _injection_rows(design, selected, valid, occupied, seeds["injection_trials"]); rows.extend(injection_rows)
    trial_path = root / "config/dante_light_prefilter_v5_injection_trials.jsonl"; _write_jsonl(trial_path, trials)
    sources = [protocol["source_references"][name] for name in sorted(protocol["source_references"])] + [repository_reference(root, trial_path)]
    manifest = build_identity_manifest(rows, protocol_reference=repository_reference(root, protocol_path), source_references=sources, selection_code_reference=_reference(root, "src/dante_light/prefilter_v5_freeze.py"), seed_derivation=protocol["seed_derivation"], prior_block_keys=prior)
    complete = dict(manifest); public_rows = complete.pop("rows")
    entries_path = root / "config/dante_light_prefilter_splits_v5.jsonl"; _write_jsonl(entries_path, public_rows)
    complete["entries_reference"] = repository_reference(root, entries_path); complete["manifest_digest"] = canonical_json_sha256({key: value for key, value in complete.items() if key != "manifest_digest"})
    split_path = root / "config/dante_light_prefilter_splits_v5.json"; _write_json(split_path, complete)
    seal = build_confirmation_seal(manifest, freeze_commit=freeze_commit, code_references={
        "split_builder": _reference(root, "src/dante_light/prefilter_v5_freeze.py"),
        "protocol_validator": _reference(root, "src/dante_light/prefilter_v5_protocol.py"),
        "seal_verifier": _reference(root, "src/dante_light/prefilter_v5_seal.py"),
        "preprocessing": protocol["source_references"]["preprocessing"],
        "exact_dante_runner": protocol["source_references"]["exact_dante_runner"],
    }, declared_storage_roots=[
        {"root_id": "repository", "kind": "repository_relative", "location": "."},
        {"root_id": "raw_strain", "kind": "environment_alias", "location": "DANTE_RAW_STRAIN_ROOT"},
        {"root_id": "v5_cache", "kind": "environment_alias", "location": "DANTE_V5_CACHE_ROOT"},
    ], protected_endpoints=design["confirmation"]["protected_endpoints"])
    seal["public_split_header_reference"] = repository_reference(root, split_path); seal["public_split_entries_reference"] = repository_reference(root, entries_path); seal["injection_trials_reference"] = repository_reference(root, trial_path)
    seal["seal_digest"] = canonical_json_sha256({key: value for key, value in seal.items() if key != "seal_digest"})
    seal_path = root / "config/dante_light_prefilter_v5_confirmation_seal.json"; _write_json(seal_path, seal)
    counts = {}
    for row in public_rows:
        key = "/".join((row["partition"], row["role"], row["detector"], row["morphology"])); counts[key] = counts.get(key, 0) + 1
    return {"protocol": protocol, "manifest_header": complete, "rows": public_rows, "trials": trials, "seal": seal, "counts": counts}
