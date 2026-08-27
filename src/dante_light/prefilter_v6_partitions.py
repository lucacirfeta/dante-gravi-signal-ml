"""Outcome-blind deterministic partition freeze for DANTE-Light v6."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_phase_b_planning import file_sha256, load_jsonl
from src.dante_light.prefilter_v6_pre_phase_b import (
    maximum_disjoint_starts,
    merged_intervals,
    valid_starts_for_block,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "dante_light_prefilter_v6_partition_freeze.json"


def _priority(contract_digest: str, purpose: str, *identity: object) -> str:
    return canonical_json_sha256(
        {
            "contract_digest": contract_digest,
            "purpose": purpose,
            "identity": list(identity),
        }
    )


def _covered(
    intervals: Sequence[Sequence[int]], *, start: float, duration_s: int, pad_s: int
) -> bool:
    left = float(start) - pad_s
    right = float(start) + duration_s + pad_s
    return any(float(a) <= left and right <= float(b) for a, b in intervals)


def _interleave_strata(
    rows: Sequence[Mapping[str, Any]], *, strata: int, purpose: str, contract_digest: str
) -> list[dict[str, Any]]:
    buckets: list[list[dict[str, Any]]] = []
    for stratum in range(strata):
        bucket = [dict(row) for row in rows if int(row["span_stratum"]) == stratum]
        bucket.sort(
            key=lambda row: (
                _priority(contract_digest, purpose, row["detector"], row["block_index"]),
                int(row["block_index"]),
            )
        )
        buckets.append(bucket)
    ordered: list[dict[str, Any]] = []
    for index in range(max(map(len, buckets), default=0)):
        for bucket in buckets:
            if index < len(bucket):
                ordered.append(bucket[index])
    if len(ordered) != len(rows):
        raise ContractError("stratified interleave lost a block")
    return ordered


def _spread_starts(starts: Sequence[float], *, count: int) -> list[float]:
    values = sorted(float(value) for value in starts)
    if len(values) < count or count <= 0:
        raise ContractError("insufficient disjoint starts for spread selection")
    if count == 1:
        return [values[len(values) // 2]]
    denominator = count - 1
    indices = [
        (index * (len(values) - 1) + denominator // 2) // denominator
        for index in range(count)
    ]
    if len(set(indices)) != count:
        raise ContractError("spread start selection produced duplicate indices")
    return [values[index] for index in indices]


def _hash_start(
    starts: Sequence[float], *, contract_digest: str, purpose: str, block_key: str
) -> float:
    values = [float(value) for value in starts]
    if not values:
        raise ContractError("cannot select a start from an empty block")
    return min(
        values,
        key=lambda value: (
            _priority(contract_digest, purpose, block_key, value),
            value,
        ),
    )


def load_partition_contract(
    path: str | Path = DEFAULT_CONTRACT, *, root: Path = ROOT
) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 partition-freeze contract digest mismatch")
    if payload.get("status") != "FROZEN_OUTCOME_BLIND_PARTITION_CONTRACT":
        raise ContractError("v6 partition contract is not frozen")
    if any(payload["outcome_access"].values()):
        raise ContractError("v6 partition freeze accessed an outcome")
    if payload["selection_contract"].get("local_availability_used_for_selection") is not False:
        raise ContractError("local availability cannot select v6 identities")
    for name, reference in payload["source_references"].items():
        relative = Path(reference["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError(f"non-portable v6 partition reference: {name}")
        candidate = root / relative
        if not candidate.is_file() or file_sha256(candidate) != reference["sha256"]:
            raise ContractError(f"v6 partition source mismatch: {name}")
    return payload


def official_eligible_blocks(
    *,
    contract: Mapping[str, Any],
    flags: Mapping[str, Any],
    identity_audit: Mapping[str, Any],
    v5_rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    signal = contract["signal"]
    duration = int(signal["window_duration_s"])
    pad = int(signal["whitening_pad_each_side_s"])
    step = int(signal["candidate_start_step_s"])
    required = int(contract["partition_contract"]["windows_per_block"]["phase_b"])
    block_duration = int(signal["block_duration_s"])
    prior = set(identity_audit["prior_usage"]["union_o4a_block_keys"])
    used_v5 = {
        f"{row['detector']}:{int(row['stratum']['block_index'])}"
        for row in v5_rows
        if "block_index" in row.get("stratum", {})
    }
    result: dict[str, list[dict[str, Any]]] = {}
    strata = int(contract["selection_contract"]["span_strata"])
    for detector in signal["detectors"]:
        cat1 = flags[f"{detector}_O4A_CBC_CAT1"]["segments"]
        excluded = [
            segment
            for suffix in ("HW_INJ", "CBC_INJ", "BURST_INJ")
            for segment in flags[f"{detector}_O4A_{suffix}"]["segments"]
        ]
        block_indices = {
            block
            for start, end in cat1
            for block in range(
                int(start) // block_duration,
                (int(end) - 1) // block_duration + 1,
            )
        }
        eligible: list[dict[str, Any]] = []
        for block in sorted(block_indices):
            key = f"{detector}:{block}"
            if key in prior or key in used_v5:
                continue
            official_starts = valid_starts_for_block(
                block=block,
                local_intervals=cat1,
                cat1_intervals=cat1,
                excluded_intervals=excluded,
                duration_s=duration,
                pad_s=pad,
                step_s=step,
            )
            disjoint = maximum_disjoint_starts(
                official_starts, duration_s=duration, pad_s=pad
            )
            if len(disjoint) < required:
                continue
            eligible.append(
                {
                    "detector": detector,
                    "block_index": int(block),
                    "block_key": key,
                    "block_gps_start": int(block * block_duration),
                    "block_gps_end": int((block + 1) * block_duration),
                    "available_start_span_s": float(max(official_starts) - min(official_starts)),
                    "maximum_disjoint_window_count": len(disjoint),
                    "official_disjoint_starts": disjoint,
                }
            )
        ranked = sorted(
            eligible,
            key=lambda row: (
                float(row["available_start_span_s"]),
                int(row["block_index"]),
            ),
        )
        for rank, row in enumerate(ranked):
            row["span_stratum"] = min(strata - 1, rank * strata // len(ranked))
        result[detector] = ranked
    return result


def build_partition_freeze(
    *, contract: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    refs = contract["source_references"]
    flags = json.loads((root / refs["gwosc_segment_snapshot"]["path"]).read_text(encoding="utf-8"))["flags"]
    identity = json.loads((root / refs["v5_identity_audit"]["path"]).read_text(encoding="utf-8"))
    v5_rows = load_jsonl(root / refs["v5_split_entries"]["path"])
    raw_rows = load_jsonl(root / refs["raw_manifest"]["path"])
    planning = json.loads(
        (root / refs["phase_b_planning_audit"]["path"]).read_text(encoding="utf-8")
    )
    local = merged_intervals(raw_rows)
    eligible = official_eligible_blocks(
        contract=contract, flags=flags, identity_audit=identity, v5_rows=v5_rows
    )
    for detector in contract["signal"]["detectors"]:
        pool_digest = canonical_json_sha256(
            sorted(row["block_key"] for row in eligible[detector])
        )
        if pool_digest != planning["capacity"][detector]["official_eligible_block_keys_digest"]:
            raise ContractError(f"v6 eligible pool differs from planning audit: {detector}")
    digest = str(contract["contract_digest"])
    selection = contract["selection_contract"]
    partitions = contract["partition_contract"]["blocks_per_detector"]
    strata = int(selection["span_strata"])
    rows: list[dict[str, Any]] = []
    download_rows: list[dict[str, Any]] = []
    partition_order = list(selection["partition_assignment_order"])
    for detector in contract["signal"]["detectors"]:
        ordered = _interleave_strata(
            eligible[detector],
            strata=strata,
            purpose="v6_partition_order",
            contract_digest=digest,
        )
        cursor = 0
        selected: list[dict[str, Any]] = []
        for partition in partition_order:
            count = int(partitions[partition])
            group = ordered[cursor : cursor + count]
            if len(group) != count:
                raise ContractError(f"insufficient v6 blocks for {detector}/{partition}")
            cursor += count
            for row in group:
                item = dict(row)
                item["partition"] = partition
                selected.append(item)
        phase_b = [row for row in selected if row["partition"] == "phase_b"]
        phase_b_order = _interleave_strata(
            phase_b,
            strata=strata,
            purpose="v6_phase_b_internal_split",
            contract_digest=digest,
        )
        fit_count = int(contract["partition_contract"]["phase_b_internal_split"]["fit"])
        phase_b_subset = {
            row["block_key"]: ("fit" if index < fit_count else "internal_validation")
            for index, row in enumerate(phase_b_order)
        }
        for item in selected:
            partition = str(item["partition"])
            disjoint = item.pop("official_disjoint_starts")
            window_count = int(contract["partition_contract"]["windows_per_block"][partition])
            if partition == "phase_b":
                starts = _spread_starts(disjoint, count=window_count)
                subset = phase_b_subset[item["block_key"]]
            else:
                starts = [
                    _hash_start(
                        disjoint,
                        contract_digest=digest,
                        purpose=f"v6_{partition}_window",
                        block_key=item["block_key"],
                    )
                ]
                subset = "sealed" if partition in {"phase_c", "phase_d_confirmation"} else "reserved"
            missing_starts = [
                start
                for start in starts
                if not _covered(
                    local[detector],
                    start=start,
                    duration_s=int(contract["signal"]["window_duration_s"]),
                    pad_s=int(contract["signal"]["whitening_pad_each_side_s"]),
                )
            ]
            local_windows = not missing_starts
            item.update(
                {
                    "subset": subset,
                    "selected_window_starts": starts,
                    "selected_windows_digest": canonical_json_sha256(starts),
                    "selected_windows_currently_local": local_windows,
                    "selection_priority": _priority(
                        digest, "v6_partition_order", detector, item["block_index"]
                    ),
                }
            )
            rows.append(item)
            if not local_windows:
                download_rows.append(
                    {
                        "detector": detector,
                        "block_index": int(item["block_index"]),
                        "block_key": item["block_key"],
                        "gps_start": int(item["block_gps_start"]),
                        "gps_end": int(item["block_gps_end"]),
                        "missing_selected_window_starts": missing_starts,
                        "fetch_intervals": [
                            {
                                "gps_start": float(start) - int(contract["signal"]["whitening_pad_each_side_s"]),
                                "gps_end": float(start)
                                + int(contract["signal"]["window_duration_s"])
                                + int(contract["signal"]["whitening_pad_each_side_s"]),
                            }
                            for start in missing_starts
                        ],
                        "missing_padded_window_count": len(missing_starts),
                        "reason": "frozen_selected_window_not_covered_by_current_raw_manifest",
                        "partitions": [partition],
                    }
                )
    rows.sort(key=lambda row: (row["detector"], row["partition"], row["block_index"]))
    download_rows.sort(key=lambda row: (row["detector"], row["block_index"]))
    counts = Counter((row["detector"], row["partition"]) for row in rows)
    strata_counts = Counter(
        (row["detector"], row["partition"], int(row["span_stratum"])) for row in rows
    )
    summary = {
        detector: {
            partition: {
                "blocks": counts[(detector, partition)],
                "span_strata": {
                    str(stratum): strata_counts[(detector, partition, stratum)]
                    for stratum in range(strata)
                },
            }
            for partition in partition_order
        }
        for detector in contract["signal"]["detectors"]
    }
    body = {
        "schema_version": 1,
        "status": "FROZEN_OUTCOME_BLIND_PARTITIONS",
        "contract_digest": digest,
        "rows": rows,
        "download_rows": download_rows,
        "summary": summary,
        "download_summary": {
            detector: {
                "blocks": sum(row["detector"] == detector for row in download_rows),
                "padded_windows": sum(
                    int(row["missing_padded_window_count"])
                    for row in download_rows
                    if row["detector"] == detector
                ),
                "padded_seconds": sum(
                    float(interval["gps_end"]) - float(interval["gps_start"])
                    for row in download_rows
                    if row["detector"] == detector
                    for interval in row["fetch_intervals"]
                ),
            }
            for detector in contract["signal"]["detectors"]
        },
        "eligible_pool_digest": {
            detector: canonical_json_sha256(
                sorted(row["block_key"] for row in eligible[detector])
            )
            for detector in contract["signal"]["detectors"]
        },
        "outcomes_accessed": [],
        "scientific_boundary": contract["scientific_boundary"],
    }
    validate_partition_freeze(body, contract=contract)
    return {**body, "manifest_digest": canonical_json_sha256(body)}


def validate_partition_freeze(
    payload: Mapping[str, Any], *, contract: Mapping[str, Any]
) -> None:
    if payload.get("status") != "FROZEN_OUTCOME_BLIND_PARTITIONS":
        raise ContractError("v6 partition payload has the wrong status")
    if payload.get("outcomes_accessed") != []:
        raise ContractError("v6 partition payload contains outcome access")
    rows = list(payload["rows"])
    keys = [row["block_key"] for row in rows]
    if len(keys) != len(set(keys)):
        raise ContractError("v6 detector/block identity crosses partitions")
    expected = contract["partition_contract"]["blocks_per_detector"]
    windows = contract["partition_contract"]["windows_per_block"]
    for detector in contract["signal"]["detectors"]:
        for partition, count in expected.items():
            selected = [
                row for row in rows
                if row["detector"] == detector and row["partition"] == partition
            ]
            if len(selected) != int(count):
                raise ContractError(f"v6 partition count mismatch: {detector}/{partition}")
            if any(len(row["selected_window_starts"]) != int(windows[partition]) for row in selected):
                raise ContractError(f"v6 window count mismatch: {detector}/{partition}")
            stratum_counts = Counter(int(row["span_stratum"]) for row in selected)
            if max(stratum_counts.values()) - min(stratum_counts.values()) > 1:
                raise ContractError(f"v6 span strata are imbalanced: {detector}/{partition}")
        phase_b = [row for row in rows if row["detector"] == detector and row["partition"] == "phase_b"]
        subsets = Counter(row["subset"] for row in phase_b)
        if subsets != Counter(contract["partition_contract"]["phase_b_internal_split"]):
            raise ContractError(f"v6 Phase-B internal split mismatch: {detector}")
        for subset, expected_count in contract["partition_contract"]["phase_b_internal_split"].items():
            subset_rows = [row for row in phase_b if row["subset"] == subset]
            if len(subset_rows) != int(expected_count):
                raise ContractError(f"v6 Phase-B subset count mismatch: {detector}/{subset}")
            subset_strata = Counter(int(row["span_stratum"]) for row in subset_rows)
            if max(subset_strata.values()) - min(subset_strata.values()) > 1:
                raise ContractError(f"v6 Phase-B subset strata are imbalanced: {detector}/{subset}")
    download_keys = {row["block_key"] for row in payload["download_rows"]}
    expected_download = {
        row["block_key"] for row in rows if not row["selected_windows_currently_local"]
    }
    if download_keys != expected_download:
        raise ContractError("v6 download manifest differs from frozen missing identities")
    for row in payload["download_rows"]:
        if int(row["missing_padded_window_count"]) != len(row["fetch_intervals"]):
            raise ContractError("v6 download interval count mismatch")
        if int(row["missing_padded_window_count"]) != len(row["missing_selected_window_starts"]):
            raise ContractError("v6 missing-window count mismatch")
    if any(
        row["selected_windows_digest"] != canonical_json_sha256(row["selected_window_starts"])
        for row in rows
    ):
        raise ContractError("v6 selected-window digest mismatch")
