"""Run-generic, outcome-blind DANTE-Light shadow-manifest construction."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from src.dante_light.contracts import (
    ContractError,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)


def _encoded(payload: Any, *, compact: bool = False) -> bytes:
    if compact:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    else:
        text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    return (text + "\n").encode("utf-8")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _atomic_locked(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() == content:
            return
        raise ContractError(f"refusing to overwrite divergent locked artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _integer(value: Any, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool):
        raise ContractError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label} must be an integer") from exc
    if parsed != value or parsed < (1 if positive else 0):
        raise ContractError(f"{label} must be {'positive' if positive else 'non-negative'}")
    return parsed


def _interval(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ContractError(f"{label} must contain [start, end]")
    try:
        start, end = float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label} bounds must be numeric") from exc
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ContractError(f"{label} must be a finite positive interval")
    return start, end


def validate_plan(payload: Mapping[str, Any], *, locked: bool) -> dict[str, Any]:
    """Validate and normalize a draft or self-hashed locked selection plan."""
    plan = dict(payload)
    digest = plan.pop("plan_sha256", None)
    required_status = "locked_before_dq_fetch" if locked else "draft"
    if plan.get("schema_version") != 1 or plan.get("status") != required_status:
        raise ContractError(f"selection plan must be schema 1 with status {required_status}")
    if locked and digest != canonical_json_sha256(plan):
        raise ContractError("selection plan self-hash mismatch")
    if not locked and digest is not None:
        raise ContractError("draft selection plan must not contain plan_sha256")
    if plan.get("outcome_fields_used_for_selection") != []:
        raise ContractError("selection plan must declare no outcome-dependent fields")
    run = str(plan.get("run", "")).strip().upper()
    if not run or run != plan.get("run"):
        raise ContractError("selection plan run must be a non-empty uppercase identifier")
    purpose = str(plan.get("purpose", "")).strip()
    if not purpose:
        raise ContractError("selection plan purpose is missing")
    official_start, official_end = _interval(
        plan.get("official_run_bounds_gps"), "official run bounds"
    )
    source = plan.get("source")
    if not isinstance(source, dict) or source.get("provider") != "GWOSC":
        raise ContractError("selection plan source provider must be GWOSC")
    release_url = str(source.get("release_url", ""))
    if not release_url.startswith("https://"):
        raise ContractError("selection plan release URL must use HTTPS")
    selection = plan.get("selection")
    if not isinstance(selection, dict):
        raise ContractError("selection contract is missing")
    detectors = selection.get("detectors")
    if not isinstance(detectors, list) or not detectors or len(detectors) != len(set(detectors)):
        raise ContractError("selection detectors must be a non-empty unique list")
    detectors = [str(value) for value in detectors]
    if set(detectors) != {"H1", "L1"}:
        raise ContractError("DANTE-Light schema 1 currently requires H1 and L1")
    flags = source.get("flags")
    if not isinstance(flags, dict) or set(flags) != set(detectors):
        raise ContractError("GWOSC DQ flags must be specified for every detector")
    for detector in detectors:
        expected = f"{detector}_CBC_CAT1"
        if flags[detector] != expected:
            raise ContractError(f"unsupported CAT1 flag for {detector}: {flags[detector]}")
    window_s = _integer(selection.get("window_s"), "window duration", positive=True)
    pad_s = _integer(selection.get("whitening_pad_s"), "whitening pad", positive=True)
    if window_s != 32 or pad_s != 4:
        raise ContractError("DANTE-Light schema 1 requires 32 s windows and 4 s padding")
    per_block = _integer(
        selection.get("windows_per_detector_block"),
        "windows per detector block",
        positive=True,
    )
    selection_rule = str(selection.get("selection_rule", ""))
    if selection_rule not in {"uniform_cat1", "first_aligned"}:
        raise ContractError(
            "selection rule must be uniform_cat1 or first_aligned"
        )
    tuning = _interval(selection.get("tuning_interval_gps"), "tuning interval")
    raw_blocks = selection.get("evaluation_blocks_gps")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ContractError("at least one evaluation block is required")
    blocks = [_interval(value, f"evaluation block {index}") for index, value in enumerate(raw_blocks, 1)]
    if blocks != sorted(blocks) or any(left[1] > right[0] for left, right in zip(blocks, blocks[1:])):
        raise ContractError("evaluation blocks must be sorted and non-overlapping")
    if not official_start <= tuning[0] < tuning[1] <= official_end:
        raise ContractError("tuning interval lies outside official run bounds")
    if any(not official_start <= start < end <= official_end for start, end in blocks):
        raise ContractError("evaluation block lies outside official run bounds")
    if tuning[1] > blocks[0][0]:
        raise ContractError("tuning interval must end before held-out evaluation begins")
    return {
        **plan,
        "run": run,
        "purpose": purpose,
        "official_run_bounds_gps": [official_start, official_end],
        "source": {
            "provider": "GWOSC",
            "release_url": release_url,
            "flags": {detector: flags[detector] for detector in detectors},
        },
        "selection": {
            "detectors": detectors,
            "window_s": window_s,
            "whitening_pad_s": pad_s,
            "windows_per_detector_block": per_block,
            "selection_rule": selection_rule,
            "tuning_interval_gps": list(tuning),
            "evaluation_blocks_gps": [list(value) for value in blocks],
        },
        **({"plan_sha256": digest} if locked else {}),
    }


def lock_selection_plan(draft: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_plan(draft, locked=False)
    body = {**normalized, "status": "locked_before_dq_fetch"}
    return {**body, "plan_sha256": canonical_json_sha256(body)}


def load_locked_plan(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContractError(f"cannot read locked selection plan {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("locked selection plan must be a JSON object")
    return validate_plan(payload, locked=True)


def fetch_dq_snapshot(
    plan: Mapping[str, Any],
    *,
    segment_fetcher: Callable[[str, int, int], Any] | None = None,
) -> dict[str, Any]:
    normalized = validate_plan(plan, locked=True)
    if segment_fetcher is None:
        from gwosc.timeline import get_segments

        segment_fetcher = get_segments
    blocks = normalized["selection"]["evaluation_blocks_gps"]
    query_start = math.floor(min(block[0] for block in blocks))
    query_end = math.ceil(max(block[1] for block in blocks))
    segments: dict[str, list[list[float]]] = {}
    for detector in normalized["selection"]["detectors"]:
        flag = normalized["source"]["flags"][detector]
        values = segment_fetcher(flag, query_start, query_end)
        rows = [[float(left), float(right)] for left, right in values]
        if any(not math.isfinite(value) for row in rows for value in row):
            raise ContractError(f"non-finite DQ segment for {detector}")
        segments[detector] = rows
    body = {
        "schema_version": 1,
        "status": "frozen_dq_only",
        "run": normalized["run"],
        "selection_plan_sha256": normalized["plan_sha256"],
        "official_run_bounds_gps": normalized["official_run_bounds_gps"],
        "source": {
            **normalized["source"],
            "outcome_data_accessed": False,
        },
        "query_bounds_gps": [query_start, query_end],
        "segments": segments,
    }
    return {**body, "snapshot_sha256": canonical_json_sha256(body)}


def _load_snapshot(path: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContractError(f"cannot read DQ snapshot {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("DQ snapshot must be a JSON object")
    body = dict(payload)
    digest = body.pop("snapshot_sha256", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("DQ snapshot self-hash mismatch")
    if payload.get("schema_version") != 1 or payload.get("status") != "frozen_dq_only":
        raise ContractError("DQ snapshot is not frozen schema 1")
    if payload.get("selection_plan_sha256") != plan["plan_sha256"]:
        raise ContractError("DQ snapshot belongs to a different selection plan")
    if payload.get("run") != plan["run"] or payload.get("official_run_bounds_gps") != plan["official_run_bounds_gps"]:
        raise ContractError("DQ snapshot run contract differs from selection plan")
    snapshot_source = payload.get("source", {})
    if snapshot_source.get("outcome_data_accessed") is not False:
        raise ContractError("DQ snapshot is not outcome-blind")
    if {key: value for key, value in snapshot_source.items() if key != "outcome_data_accessed"} != plan["source"]:
        raise ContractError("DQ snapshot source contract differs from selection plan")
    blocks = plan["selection"]["evaluation_blocks_gps"]
    expected_query = [
        math.floor(min(block[0] for block in blocks)),
        math.ceil(max(block[1] for block in blocks)),
    ]
    if payload.get("query_bounds_gps") != expected_query:
        raise ContractError("DQ snapshot query bounds differ from selection plan")
    if set(payload.get("segments", {})) != set(plan["selection"]["detectors"]):
        raise ContractError("DQ snapshot detector coverage differs from selection plan")
    return payload


def select_padded_windows(
    segments: list[list[float]],
    block_start: float,
    block_end: float,
    *,
    count: int,
    window_s: int,
    pad_s: int,
    selection_rule: str,
) -> list[int]:
    eligible: set[int] = set()
    for raw in sorted(segments):
        if not isinstance(raw, list) or len(raw) != 2:
            raise ContractError("DQ segment must contain [start, end]")
        raw_left, raw_right = float(raw[0]), float(raw[1])
        if not math.isfinite(raw_left) or not math.isfinite(raw_right) or raw_right <= raw_left:
            raise ContractError("DQ segment is not a finite positive interval")
        left = max(raw_left, block_start) + pad_s
        right = min(raw_right, block_end) - pad_s
        current = int(math.ceil(left / window_s) * window_s)
        while current + window_s <= right:
            eligible.add(current)
            current += window_s
    ordered = sorted(eligible)
    if len(ordered) < count:
        raise ContractError(
            f"CAT1 block [{block_start}, {block_end}] provides only {len(ordered)}/{count} padded windows"
        )
    if selection_rule == "first_aligned":
        return ordered[:count]
    if selection_rule != "uniform_cat1":
        raise ContractError(f"unsupported selection rule: {selection_rule}")
    indices = [((2 * index + 1) * len(ordered)) // (2 * count) for index in range(count)]
    if len(set(indices)) != count:
        raise ContractError("uniform CAT1 selection produced duplicate indices")
    return [ordered[index] for index in indices]


def build_shadow_manifest(
    *,
    plan_path: str | Path,
    snapshot_path: str | Path,
    output_path: str | Path,
    reference_manifest_path: str | Path,
    root: str | Path = ".",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root_path = Path(root).resolve()
    plan_source = Path(plan_path).resolve()
    snapshot_source = Path(snapshot_path).resolve()
    output = Path(output_path).resolve()
    reference_source = Path(reference_manifest_path).resolve()
    for label, source in (
        ("selection plan", plan_source),
        ("DQ snapshot", snapshot_source),
        ("reference manifest", reference_source),
        ("output", output),
    ):
        try:
            source.relative_to(root_path)
        except ValueError as exc:
            raise ContractError(f"{label} must be inside the repository root") from exc
    plan = load_locked_plan(plan_source)
    snapshot = _load_snapshot(snapshot_source, plan)
    selection = plan["selection"]
    entries: list[dict[str, Any]] = []
    block_counts: dict[str, dict[str, int]] = {}
    for block_index, (block_start, block_end) in enumerate(selection["evaluation_blocks_gps"], 1):
        block_name = f"block_{block_index}"
        block_counts[block_name] = {}
        for detector in selection["detectors"]:
            starts = select_padded_windows(
                snapshot["segments"][detector],
                block_start,
                block_end,
                count=selection["windows_per_detector_block"],
                window_s=selection["window_s"],
                pad_s=selection["whitening_pad_s"],
                selection_rule=selection["selection_rule"],
            )
            block_counts[block_name][detector] = len(starts)
            for gps_start in starts:
                window = WindowIdentity(
                    plan["run"], detector, gps_start, selection["window_s"]
                )
                row: dict[str, Any] = {
                    "window": window.to_dict(),
                    "roles": ["shadow_evaluation", block_name],
                    "source_kind": "public_strain",
                    "expected": {},
                    "metadata": {
                        "selection_basis": "GWOSC CBC_CAT1 only",
                        "block_index": block_index,
                        "block_bounds_gps": [block_start, block_end],
                        "whitening_context_cat1": True,
                    },
                }
                row["case_id"] = f"dlc1-{canonical_json_sha256(row)[:24]}"
                entries.append(row)
    entries.sort(key=lambda row: row["case_id"])
    entries_bytes = b"".join(_encoded(row, compact=True) for row in entries)
    entries_path = output.with_suffix(".jsonl")
    representation = RepresentationContract.from_reference_manifest(reference_source)
    unique_windows = len({row["window"]["window_id"] for row in entries})
    if unique_windows != len(entries):
        raise ContractError("shadow selection produced duplicate detector/GPS windows")
    body: dict[str, Any] = {
        "schema_version": 1,
        "status": "locked_before_scoring",
        "purpose": plan["purpose"],
        "run": plan["run"],
        "official_run_bounds_gps": plan["official_run_bounds_gps"],
        "raw_strain_embedded": False,
        "outcome_fields_used_for_selection": [],
        "representation": representation.to_dict(),
        "reference_contract": {
            "path": reference_source.relative_to(root_path).as_posix(),
            "sha256": _sha256_file(reference_source),
        },
        "selection_contract": {
            **selection,
            "dq_flags": [plan["source"]["flags"][detector] for detector in selection["detectors"]],
            "rule": (
                f"{selection['selection_rule']}: "
                f"{selection['windows_per_detector_block']} aligned padded-CAT1 "
                "windows per detector and fixed block"
            ),
        },
        "selection_plan": {
            "path": plan_source.relative_to(root_path).as_posix(),
            "sha256": _sha256_file(plan_source),
            "plan_sha256": plan["plan_sha256"],
        },
        "dq_snapshot": {
            "path": snapshot_source.relative_to(root_path).as_posix(),
            "sha256": _sha256_file(snapshot_source),
            "snapshot_sha256": snapshot["snapshot_sha256"],
        },
        "counts": {
            "entries": len(entries),
            "unique_windows": unique_windows,
            "by_block_and_detector": block_counts,
        },
        "entries_path": entries_path.relative_to(root_path).as_posix(),
        "entries_file_sha256": _sha256_bytes(entries_bytes),
        "entries_sha256": canonical_json_sha256(entries),
    }
    manifest = {**body, "manifest_sha256": canonical_json_sha256(body)}
    return manifest, entries


def write_locked_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    _atomic_locked(Path(path), _encoded(payload))


def write_shadow_manifest(
    output_path: str | Path, manifest: Mapping[str, Any], entries: list[dict[str, Any]]
) -> None:
    output = Path(output_path)
    _atomic_locked(output, _encoded(manifest))
    _atomic_locked(
        output.with_suffix(".jsonl"),
        b"".join(_encoded(row, compact=True) for row in entries),
    )


def check_shadow_manifest(
    output_path: str | Path, manifest: Mapping[str, Any], entries: list[dict[str, Any]]
) -> None:
    output = Path(output_path)
    expected_manifest = _encoded(manifest)
    expected_entries = b"".join(_encoded(row, compact=True) for row in entries)
    if not output.is_file() or output.read_bytes() != expected_manifest:
        raise ContractError(f"stale or missing shadow manifest: {output}")
    entries_path = output.with_suffix(".jsonl")
    if not entries_path.is_file() or entries_path.read_bytes() != expected_entries:
        raise ContractError(f"stale or missing shadow entries: {entries_path}")
