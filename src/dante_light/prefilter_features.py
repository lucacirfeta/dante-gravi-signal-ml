"""Build provenance-bound cheap-feature ledgers for exact Light shadow runs."""

from __future__ import annotations

from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.executor import WindowTask
from src.dante_light.prefilter_evaluation import FEATURE_SOURCE
from src.dante_light.preprocessing import PreparedPrefilterFeatures
from src.dante_light.sources.files import ReplayManifestSource


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _portable_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _load_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid record JSON at {path}:{line_number}") from exc
        body = dict(record)
        declared = body.pop("record_id", None)
        expected = f"dlr1-{canonical_json_sha256(body)[:24]}"
        if declared != expected:
            raise ContractError(f"record digest mismatch at {path}:{line_number}")
        window = WindowIdentity.from_dict(record["window"])
        if window.window_id in records:
            raise ContractError(f"duplicate exact record: {window.window_id}")
        if record.get("disposition") not in {"ESCALATE", "NOT_ESCALATED"}:
            raise ContractError(f"feature extraction requires a complete exact record: {window.window_id}")
        records[window.window_id] = record
    if not records:
        raise ContractError("exact record source is empty")
    return records


def _existing_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            window = WindowIdentity.from_dict(row["window"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"invalid partial feature row at {path}:{line_number}") from exc
        if window.window_id in rows:
            raise ContractError(f"duplicate partial feature row: {window.window_id}")
        rows[window.window_id] = row
    return rows


def build_shadow_feature_ledger(
    *,
    root: str | Path,
    manifest_path: str | Path,
    records_path: str | Path,
    output_dir: str | Path,
    prepare: Callable[[WindowTask], PreparedPrefilterFeatures],
    limit: int | None = None,
) -> dict[str, Any]:
    """Extract resumable features and finalize a deterministic shadow ledger."""

    root = Path(root).resolve()
    manifest_path = Path(manifest_path).resolve()
    records_path = Path(records_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = ReplayManifestSource(manifest_path, root=root)
    tasks = source.tasks(limit=limit)
    records = _load_records(records_path)
    expected_ids = {task.window.window_id for task in tasks}
    if not expected_ids.issubset(records):
        missing = sorted(expected_ids - records)
        raise ContractError(f"exact records missing {len(missing)} feature windows")
    representation_digests = {records[key]["representation_sha256"] for key in expected_ids}
    if len(representation_digests) != 1:
        raise ContractError("exact records use multiple representations")
    representation_sha256 = representation_digests.pop()
    manifest_sha256 = _sha256(manifest_path)

    partial_path = output_dir / "shadow_features_v1.partial.jsonl"
    existing = _existing_rows(partial_path)
    if not set(existing).issubset(expected_ids):
        raise ContractError("partial ledger contains rows outside the frozen manifest")
    with partial_path.open("a", encoding="utf-8", newline="\n") as stream:
        for task in tasks:
            window_id = task.window.window_id
            if window_id in existing:
                continue
            prepared = prepare(task)
            record = records[window_id]
            expected_strain = record.get("evidence", {}).get("strain_sha256")
            if prepared.strain_sha256 != expected_strain:
                raise ContractError(f"raw strain digest changed for {window_id}")
            row = {
                "schema_version": 1,
                "window": task.window.to_dict(),
                "roles": ["shadow"],
                "partition": "evaluation",
                "split_artifact_sha256_by_role": {"shadow": manifest_sha256},
                "detector": task.window.detector,
                "morphology": None,
                "exact_disposition": record["disposition"],
                "retention_target": record["disposition"] == "ESCALATE",
                "representation_sha256": representation_sha256,
                "strain_sha256": prepared.strain_sha256,
                "features": asdict(prepared.features),
                "timings": prepared.timings,
            }
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            existing[window_id] = row

    if set(existing) != expected_ids:
        raise ContractError("partial feature ledger did not reach frozen coverage")
    rows_path = output_dir / "shadow_features_v1.jsonl"
    ordered = [existing[task.window.window_id] for task in tasks]
    rows_path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in ordered),
        encoding="utf-8",
        newline="\n",
    )
    partial_path.unlink()
    ledger = {
        "schema_version": 1,
        "status": "complete" if limit is None else "smoke_only",
        "scientific_mode": "research_only_shadow_feature_extraction",
        "feature_source": FEATURE_SOURCE,
        "outcome_fields_used_for_feature_extraction": [],
        "representation_sha256": representation_sha256,
        "cohort_split_sha256_by_role": {"shadow": manifest_sha256},
        "row_count": len(ordered),
        "rows_path": rows_path.name,
        "rows_sha256": _sha256(rows_path),
        "source_manifest": {"path": _portable_path(manifest_path, root), "sha256": manifest_sha256},
        "source_records": {"path": _portable_path(records_path, root), "sha256": _sha256(records_path)},
        "selection_limit": limit,
    }
    ledger["ledger_digest"] = canonical_json_sha256(ledger)
    ledger_path = output_dir / "shadow_feature_ledger_v1.json"
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return ledger


def build_split_feature_ledger(
    *,
    root: str | Path,
    split_path: str | Path,
    role: str,
    output_dir: str | Path,
    prepare: Callable[[WindowTask], PreparedPrefilterFeatures],
    limit: int | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Extract a resumable role ledger from a frozen L4 split artifact."""

    root = Path(root).resolve()
    split_path = Path(split_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    from src.dante_light.prefilter_splits import load_prefilter_splits

    split = load_prefilter_splits(split_path)
    try:
        cohort = split["cohorts"][role]
    except KeyError as exc:
        raise ContractError(f"role is absent from L4 split artifact: {role}") from exc
    if split.get("status") != "locked_before_feature_extraction":
        raise ContractError("L4 split artifact is not locked")
    if role not in {"background", "robust_candidate", "known_glitch", "injection"}:
        raise ContractError(f"unsupported L4 feature role: {role}")
    if not 1 <= int(workers) <= 8:
        raise ContractError("L4 feature workers must be between 1 and 8")
    split_sha256 = str(cohort["split_sha256"])
    rows = list(cohort["rows"])
    if limit is not None:
        if limit <= 0:
            raise ContractError("feature limit must be positive")
        rows = rows[:limit]
    tasks = [
        WindowTask(WindowIdentity.from_dict(row["window"]), payload=row)
        for row in rows
    ]
    expected_ids = {task.window.window_id for task in tasks}
    if len(expected_ids) != len(tasks):
        raise ContractError(f"duplicate window identities in {role} split")
    from src.dante_light.contracts import RepresentationContract

    representation_sha256 = RepresentationContract.from_reference_manifest(
        root / "config/reference_artifacts.json"
    ).contract_sha256
    partial_path = output_dir / f"{role}_features_v1.partial.jsonl"
    existing = _existing_rows(partial_path)
    if not set(existing).issubset(expected_ids):
        raise ContractError("partial cohort ledger contains rows outside its frozen split")

    def prepare_row(task: WindowTask) -> tuple[str, dict[str, Any]]:
        prepared = prepare(task)
        source = task.payload
        return task.window.window_id, {
            "schema_version": 1,
            "window": task.window.to_dict(),
            "roles": [role],
            "partition": source["partition"],
            "split_artifact_sha256_by_role": {role: split_sha256},
            "detector": task.window.detector,
            "morphology": source["morphology"],
            "retention_target": bool(source["retention_target"]),
            "exact_disposition": "NOT_APPLICABLE",
            "representation_sha256": representation_sha256,
            "strain_sha256": prepared.strain_sha256,
            "features": asdict(prepared.features),
            "timings": prepared.timings,
            "preparation_metadata": prepared.metadata,
            "cohort_id": source["cohort_id"],
        }

    pending = [task for task in tasks if task.window.window_id not in existing]
    with partial_path.open("a", encoding="utf-8", newline="\n") as stream:
        if workers == 1:
            results = (prepare_row(task) for task in pending)
            for window_id, row in results:
                stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                existing[window_id] = row
        else:
            with ThreadPoolExecutor(max_workers=int(workers)) as pool:
                futures = {pool.submit(prepare_row, task): task for task in pending}
                for future in as_completed(futures):
                    window_id, row = future.result()
                    if window_id in existing:
                        raise ContractError(f"duplicate concurrent feature result: {window_id}")
                    stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                    stream.flush()
                    existing[window_id] = row
    if set(existing) != expected_ids:
        raise ContractError("partial cohort feature ledger did not reach frozen coverage")
    rows_path = output_dir / f"{role}_features_v1.jsonl"
    ordered = [existing[task.window.window_id] for task in tasks]
    rows_path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in ordered),
        encoding="utf-8",
        newline="\n",
    )
    partial_path.unlink()
    ledger = {
        "schema_version": 1,
        "status": "complete" if limit is None else "smoke_only",
        "scientific_mode": "research_only_split_feature_extraction",
        "feature_source": FEATURE_SOURCE,
        "outcome_fields_used_for_feature_extraction": [],
        "role": role,
        "representation_sha256": representation_sha256,
        "cohort_split_sha256_by_role": {role: split_sha256},
        "row_count": len(ordered),
        "rows_path": rows_path.name,
        "rows_sha256": _sha256(rows_path),
        "source_split": {
            "path": _portable_path(split_path, root),
            "sha256": _sha256(split_path),
            "role_split_sha256": split_sha256,
        },
        "selection_limit": limit,
        "extraction_workers": int(workers),
    }
    ledger["ledger_digest"] = canonical_json_sha256(ledger)
    ledger_path = output_dir / f"{role}_feature_ledger_v1.json"
    ledger_path.write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return ledger
