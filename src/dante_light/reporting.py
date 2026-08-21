"""Deterministic, fail-closed reporting for DANTE-Light run evidence.

The machine-readable stage artifacts remain authoritative.  This module only
builds a human-readable view after checking their internal counts, cross-links
and recorded file hashes.  It never rescales scores or assigns an offline
physical class.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from src.dante_light.contracts import ContractError, canonical_json_sha256


_REQUIRED_FOLLOWUP_FILES = (
    "manifest_v1.json",
    "physical_v1.json",
    "gallery_v1.json",
)
_OPTIONAL_CATALOG_FILE = "catalog_v1.json"


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContractError(f"cannot read {label} JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError(f"{label} must be a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(body)
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
        relation = "positive" if positive else "non-negative"
        raise ContractError(f"{label} must be a {relation} integer")
    return parsed


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{label} must be numeric") from exc
    if not math.isfinite(parsed) or parsed < (0.0 if not positive else 1e-300):
        relation = "positive" if positive else "non-negative"
        raise ContractError(f"{label} must be finite and {relation}")
    return parsed


def _inside(root: Path, path: str | Path) -> Path:
    source = Path(path)
    resolved = source.resolve() if source.is_absolute() else (root / source).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ContractError(f"artifact escapes report root: {path}") from exc
    return resolved


def _from_root(root: Path, path: str | Path) -> Path:
    source = Path(path)
    return source.resolve() if source.is_absolute() else (root / source).resolve()


def _portable_path(root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        value = resolved.relative_to(root.resolve())
    except ValueError:
        value = resolved
    return str(value).replace("\\", "/")


def _verify_artifact_list(
    payload: Mapping[str, Any], root: Path, label: str
) -> None:
    artifacts = payload.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ContractError(f"{label} artifacts must be a list")
    seen: set[str] = set()
    for row in artifacts:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise ContractError(f"{label} artifact record is malformed")
        name = str(row["path"]).replace("\\", "/")
        if name in seen:
            raise ContractError(f"{label} contains duplicate artifact path: {name}")
        seen.add(name)
        source = _inside(root, name)
        if not source.is_file() or _sha256(source) != row["sha256"]:
            raise ContractError(f"{label} artifact hash mismatch: {name}")


def _validate_prospective(payload: Mapping[str, Any], root: Path) -> dict[str, Any]:
    if payload.get("schema_version") != 1:
        raise ContractError("prospective evidence schema must be 1")
    if payload.get("status") != "complete" or payload.get("mode") != "prospective_shadow":
        raise ContractError("prospective evidence is not complete operational shadow evidence")
    if payload.get("prefilter") != "none":
        raise ContractError("final report requires the exact no-prefilter path")
    if payload.get("strain_source") != "gwosc-only" or payload.get("public_sources_only") is not True:
        raise ContractError("final report requires public GWOSC-only prospective evidence")

    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        raise ContractError("prospective coverage is missing")
    windows = _integer(coverage.get("windows"), "coverage windows", positive=True)
    drops = _integer(coverage.get("drops"), "coverage drops")
    duplicates = _integer(
        coverage.get("duplicate_identities"), "coverage duplicate identities"
    )
    deferred = _integer(coverage.get("deferred_windows"), "coverage deferred windows")
    defer_rate = _number(coverage.get("defer_rate"), "coverage defer rate")
    failures = coverage.get("failures")
    if not isinstance(failures, list):
        raise ContractError("coverage failures must be a list")
    if defer_rate != deferred / windows:
        raise ContractError("coverage defer rate disagrees with deferred count")
    if drops or duplicates or deferred or failures:
        raise ContractError("prospective coverage contains drops, duplicates, DEFERs, or failures")

    detectors = payload.get("detectors")
    if not isinstance(detectors, dict) or not detectors:
        raise ContractError("prospective detector coverage is missing")
    detector_rows: dict[str, dict[str, Any]] = {}
    detector_total = 0
    for detector, row in sorted(detectors.items()):
        if not isinstance(row, dict):
            raise ContractError(f"detector evidence is malformed: {detector}")
        count = _integer(row.get("windows"), f"{detector} windows", positive=True)
        start = _number(row.get("evaluation_start_gps"), f"{detector} evaluation start")
        end = _number(row.get("evaluation_end_gps"), f"{detector} evaluation end")
        if end <= start:
            raise ContractError(f"{detector} evaluation interval is not positive")
        epoch_id = str(row.get("epoch_id", "")).strip()
        if not epoch_id:
            raise ContractError(f"{detector} epoch id is missing")
        detector_rows[str(detector)] = {
            "epoch_id": epoch_id,
            "evaluation_start_gps": start,
            "evaluation_end_gps": end,
            "windows": count,
        }
        detector_total += count
    if detector_total != windows:
        raise ContractError("detector window count does not equal total coverage")

    exact = payload.get("exact_replay")
    if not isinstance(exact, dict):
        raise ContractError("exact replay evidence is missing")
    mismatch = _integer(exact.get("disposition_mismatches"), "disposition mismatches")
    delta = _number(exact.get("max_abs_score_delta"), "maximum score delta")
    atol = _number(exact.get("score_atol"), "score tolerance", positive=True)
    if mismatch:
        raise ContractError("canonical/shared disposition mismatch is non-zero")
    if delta > atol:
        raise ContractError("canonical/shared score delta exceeds tolerance")

    run_commit = str(payload.get("run_commit", ""))
    if len(run_commit) != 40 or any(character not in "0123456789abcdef" for character in run_commit):
        raise ContractError("run commit is not a lowercase 40-character Git SHA")

    latency = payload.get("latency_s")
    if not isinstance(latency, dict):
        raise ContractError("latency evidence is missing")
    p50 = _number(latency.get("p50"), "latency p50")
    p95 = _number(latency.get("p95"), "latency p95")
    p99 = _number(latency.get("p99"), "latency p99")
    if not p50 <= p95 <= p99:
        raise ContractError("latency quantiles are not monotone")
    objective = _number(
        payload.get("pre_registered_latency_objective_s"),
        "pre-registered latency objective",
        positive=True,
    )
    if payload.get("latency_objective_met") is not (p99 <= objective):
        raise ContractError("latency objective flag disagrees with measured p99")
    if p99 > objective:
        raise ContractError("pre-registered latency objective was not met")

    _verify_artifact_list(payload, root, "prospective evidence")
    return {
        "windows": windows,
        "detectors": detector_rows,
        "latency_s": {"p50": p50, "p95": p95, "p99": p99},
        "latency_objective_s": objective,
        "score_atol": atol,
        "max_abs_score_delta": delta,
        "run_commit": run_commit,
    }


def _load_followup(directory: Path, prospective_windows: int) -> tuple[dict[str, Any], list[Path]]:
    paths = [directory / name for name in _REQUIRED_FOLLOWUP_FILES]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ContractError(f"follow-up directory is incomplete: {', '.join(missing)}")
    manifest, physical, gallery = (
        _read_object(path, path.stem) for path in paths
    )
    catalog_path = directory / _OPTIONAL_CATALOG_FILE
    catalog = _read_object(catalog_path, catalog_path.stem) if catalog_path.is_file() else None
    if catalog is not None:
        paths.insert(2, catalog_path)
    body = dict(manifest)
    digest = body.pop("manifest_sha256", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("follow-up manifest self-hash mismatch")
    if manifest.get("schema_version") != 1 or manifest.get("status") != "frozen":
        raise ContractError("follow-up manifest is not frozen schema 1")
    selection = manifest.get("selection")
    if not isinstance(selection, dict) or selection.get("disposition") != "ESCALATE":
        raise ContractError("follow-up selection is not the ESCALATE cohort")
    source_count = _integer(selection.get("n_source_windows"), "follow-up source windows", positive=True)
    candidates = _integer(selection.get("n_candidates"), "follow-up candidates", positive=True)
    if source_count != prospective_windows:
        raise ContractError("follow-up source count differs from prospective coverage")
    if not isinstance(manifest.get("candidates"), list) or len(manifest["candidates"]) != candidates:
        raise ContractError("follow-up candidate count mismatch")
    detector_counts = selection.get("detector_counts")
    if not isinstance(detector_counts, dict) or sum(
        _integer(value, f"follow-up {key} candidates")
        for key, value in detector_counts.items()
    ) != candidates:
        raise ContractError("follow-up detector counts do not equal candidate count")

    linked = [("physical", physical), ("gallery", gallery)]
    if catalog is not None:
        linked.append(("catalog", catalog))
    for label, payload in linked:
        if payload.get("schema_version") != 1 or payload.get("manifest_sha256") != digest:
            raise ContractError(f"{label} follow-up does not belong to the frozen manifest")
    if physical.get("status") not in {"complete", "complete_with_unavailable"}:
        raise ContractError("physical follow-up is incomplete")
    summary = physical.get("summary")
    if not isinstance(summary, dict):
        raise ContractError("physical follow-up summary is missing")
    accounted = _integer(summary.get("n_accounted"), "physical accounted candidates")
    failed = _integer(summary.get("n_failed"), "physical failed candidates")
    measured = _integer(summary.get("n_physical_measured"), "physical measured candidates")
    unavailable = _integer(summary.get("n_data_unavailable"), "physical unavailable candidates")
    if accounted != candidates or failed or measured + unavailable != candidates:
        raise ContractError("physical follow-up accounting is incomplete")
    if physical.get("failures") not in ([], None):
        raise ContractError("physical follow-up contains failures")
    catalog_matches = None
    if catalog is not None:
        if catalog.get("status") != "complete" or _integer(
            catalog.get("n_candidates"), "catalog candidates"
        ) != candidates:
            raise ContractError("catalog follow-up is incomplete")
        catalog_matches = _integer(
            catalog.get("n_candidates_with_catalog_match"), "catalog matches"
        )
        if catalog_matches > candidates:
            raise ContractError("catalog matches exceed candidate count")
    if gallery.get("status") != "complete" or _integer(
        gallery.get("n_candidates"), "gallery candidates"
    ) != candidates:
        raise ContractError("gallery follow-up is incomplete")
    if _integer(gallery.get("n_exact_image_hash"), "exact gallery images") != candidates:
        raise ContractError("gallery image hashes are incomplete")
    if _integer(gallery.get("n_exact_strain_hash"), "exact gallery strain") != candidates:
        raise ContractError("gallery strain hashes are incomplete")

    return (
        {
            "n_source_windows": source_count,
            "n_candidates": candidates,
            "detector_counts": dict(sorted(detector_counts.items())),
            "n_physical_measured": measured,
            "n_data_unavailable": unavailable,
            "n_catalog_matches": catalog_matches,
            "catalog_status": "COMPLETE" if catalog is not None else "NOT_SUPPLIED",
            "pooled_null_p99_diagnostic": summary.get("pooled_null_p99_diagnostic"),
        },
        paths,
    )


def _load_auxiliary(path: Path, expected_candidates: int | None, root: Path) -> dict[str, Any]:
    payload = _read_object(path, "auxiliary result")
    body = dict(payload)
    digest = body.pop("result_sha256", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("auxiliary result self-hash mismatch")
    if payload.get("schema_version") != 1 or payload.get("status") != "PASS":
        raise ContractError("auxiliary result is not a passing schema-1 artifact")
    if payload.get("scientific_status") != "DIAGNOSTIC_ONLY":
        raise ContractError("auxiliary result lacks the diagnostic-only boundary")
    n_events = _integer(payload.get("n_events"), "auxiliary events", positive=True)
    if expected_candidates is not None and n_events != expected_candidates:
        raise ContractError("auxiliary event count differs from follow-up cohort")
    events = payload.get("events")
    verdict_counts = payload.get("verdict_counts")
    if not isinstance(events, list) or len(events) != n_events or not isinstance(verdict_counts, dict):
        raise ContractError("auxiliary event accounting is malformed")
    reproduced: dict[str, int] = {}
    for event in events:
        verdict = str(event.get("diagnostic_verdict", ""))
        if not verdict:
            raise ContractError("auxiliary event verdict is missing")
        reproduced[verdict] = reproduced.get(verdict, 0) + 1
    normalized = {str(key): _integer(value, f"auxiliary verdict {key}") for key, value in verdict_counts.items()}
    if dict(sorted(reproduced.items())) != dict(sorted(normalized.items())):
        raise ContractError("auxiliary verdict counts do not reproduce event rows")
    detector_counts = payload.get("detector_counts")
    if not isinstance(detector_counts, dict) or sum(
        _integer(value, f"auxiliary {key} events")
        for key, value in detector_counts.items()
    ) != n_events:
        raise ContractError("auxiliary detector counts do not equal event count")

    for group in ("calibration_artifacts",):
        artifacts = payload.get(group, [])
        if not isinstance(artifacts, list):
            raise ContractError(f"auxiliary {group} must be a list")
        for row in artifacts:
            source = _inside(root, row["path"])
            if not source.is_file() or _sha256(source) != row["sha256"]:
                raise ContractError(f"auxiliary artifact hash mismatch: {row['path']}")
    for event in events:
        artifact_path = event.get("event_artifact_path")
        artifact_hash = event.get("event_artifact_sha256")
        if artifact_path is None and artifact_hash is None:
            continue
        source = _inside(root, artifact_path)
        if not source.is_file() or _sha256(source) != artifact_hash:
            raise ContractError(f"auxiliary event artifact hash mismatch: {artifact_path}")

    return {
        "n_events": n_events,
        "n_calibration_epochs": _integer(
            payload.get("n_calibration_epochs"), "auxiliary calibration epochs", positive=True
        ),
        "detector_counts": dict(sorted(detector_counts.items())),
        "verdict_counts": dict(sorted(normalized.items())),
    }


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _render_markdown(
    primary: Mapping[str, Any],
    followup: Mapping[str, Any] | None,
    auxiliary: Mapping[str, Any] | None,
    source_rows: list[dict[str, str]],
) -> str:
    latency = primary["latency_s"]
    lines = [
        "# DANTE-Light run report",
        "",
        "> Generated from validated machine-readable evidence. The source JSON files and their hashes remain authoritative.",
        "",
        "## Prospective shadow execution",
        "",
        f"- Status: **PASS** ({primary['windows']} durably accounted windows).",
        f"- Canonical/shared agreement: 0 disposition mismatches; maximum score delta {primary['max_abs_score_delta']:.3g} (tolerance {primary['score_atol']:.3g}).",
        f"- Durable-write latency: p50 {latency['p50']:.3f} s, p95 {latency['p95']:.3f} s, p99 {latency['p99']:.3f} s; pre-registered p99 objective {primary['latency_objective_s']:.3f} s.",
        f"- Run commit: `{_escape(primary['run_commit'])}`.",
        "",
        "| Detector | Windows | Evaluation GPS interval | Causal epoch |",
        "|---|---:|---|---|",
    ]
    for detector, row in primary["detectors"].items():
        lines.append(
            f"| {_escape(detector)} | {row['windows']} | {row['evaluation_start_gps']:.3f}--{row['evaluation_end_gps']:.3f} | `{_escape(row['epoch_id'])}` |"
        )
    lines.extend(["", "## Escalation follow-up", ""])
    if followup is None:
        lines.append(
            "Optional offline escalation follow-up was not supplied. This report therefore makes no statement about physical coincidence, catalog association, morphology, or auxiliary witnesses."
        )
    else:
        rate = 100.0 * followup["n_candidates"] / followup["n_source_windows"]
        lines.extend(
            [
                f"- ESCALATE cohort: {followup['n_candidates']}/{followup['n_source_windows']} ({rate:.3f}%).",
                f"- Physical measurements: {followup['n_physical_measured']}; explicitly data-unavailable: {followup['n_data_unavailable']}.",
                "- Every gallery strain and image digest reproduces the frozen cohort.",
                "",
                "`ESCALATE` is a routing decision, not a physical classification or a claim of novelty.",
            ]
        )
        if followup["catalog_status"] == "COMPLETE":
            lines.insert(
                lines.index("- Every gallery strain and image digest reproduces the frozen cohort."),
                f"- Catalog matches inside frozen windows: {followup['n_catalog_matches']}.",
            )
        else:
            lines.insert(
                lines.index("- Every gallery strain and image digest reproduces the frozen cohort."),
                "- Catalog follow-up: not supplied; no zero-match inference is made.",
            )
    lines.extend(["", "## Public auxiliary diagnostic", ""])
    if auxiliary is None:
        lines.append("Optional public auxiliary evidence was not supplied.")
    else:
        lines.append(
            f"Diagnostic-only coverage: {auxiliary['n_events']} events using {auxiliary['n_calibration_epochs']} calibration epochs."
        )
        lines.extend(["", "| Verdict | Count |", "|---|---:|"])
        for verdict, count in auxiliary["verdict_counts"].items():
            lines.append(f"| `{_escape(verdict)}` | {count} |")
        lines.extend(
            [
                "",
                "The limited public witness set cannot veto, confirm, or physically classify a candidate.",
            ]
        )
    lines.extend(
        [
            "",
            "## Scientific boundary",
            "",
            "`NOT_ESCALATED` is a triage outcome and is not the offline `BACKGROUND` class. DANTE-Light does not establish astrophysical origin, instrumental origin, or a novel glitch morphology; those conclusions require the full offline validation chain and appropriately powered physical evidence.",
            "",
            "## Source provenance",
            "",
            "| Artifact | SHA-256 |",
            "|---|---|",
        ]
    )
    for row in source_rows:
        lines.append(f"| `{_escape(row['path'])}` | `{row['sha256']}` |")
    return "\n".join(lines) + "\n"


def build_run_report(
    *,
    prospective_path: str | Path,
    output_path: str | Path,
    receipt_path: str | Path | None = None,
    followup_dir: str | Path | None = None,
    auxiliary_path: str | Path | None = None,
    root: str | Path = ".",
) -> dict[str, Any]:
    """Build a deterministic report only after all supplied evidence validates."""
    root_path = Path(root).resolve()
    prospective_source = _from_root(root_path, prospective_path)
    prospective_payload = _read_object(prospective_source, "prospective evidence")
    primary = _validate_prospective(prospective_payload, root_path)

    source_paths = [("prospective_evidence", prospective_source)]
    followup = None
    if followup_dir is not None:
        followup, followup_paths = _load_followup(
            _from_root(root_path, followup_dir), primary["windows"]
        )
        source_paths.extend(
            (f"followup_{path.stem.removesuffix('_v1')}", path)
            for path in followup_paths
        )
    auxiliary = None
    if auxiliary_path is not None:
        if followup is None:
            raise ContractError("auxiliary evidence requires a validated follow-up cohort")
        auxiliary_source = _from_root(root_path, auxiliary_path)
        auxiliary = _load_auxiliary(
            auxiliary_source,
            followup["n_candidates"] if followup is not None else None,
            root_path,
        )
        source_paths.append(("auxiliary_result", auxiliary_source))

    source_rows = [
        {
            "role": role,
            "path": _portable_path(root_path, path),
            "sha256": _sha256(path),
        }
        for role, path in source_paths
    ]
    markdown = _render_markdown(primary, followup, auxiliary, source_rows)
    output = _from_root(root_path, output_path)
    _atomic_bytes(output, markdown.encode("utf-8"))
    report_hash = _sha256(output)
    status = "COMPLETE" if followup is not None else "COMPLETE_WITHOUT_OPTIONAL_FOLLOWUP"
    body: dict[str, Any] = {
        "schema_version": 1,
        "status": status,
        "scientific_status": "TRIAGE_REPORT_ONLY",
        "report_path": _portable_path(root_path, output),
        "report_sha256": report_hash,
        "coverage": {"windows": primary["windows"], "detectors": primary["detectors"]},
        "exact_replay": {
            "max_abs_score_delta": primary["max_abs_score_delta"],
            "score_atol": primary["score_atol"],
            "disposition_mismatches": 0,
        },
        "latency_s": primary["latency_s"],
        "followup": followup,
        "auxiliary": auxiliary,
        "source_artifacts": source_rows,
    }
    receipt = {**body, "receipt_sha256": canonical_json_sha256(body)}
    receipt_output = (
        _from_root(root_path, receipt_path)
        if receipt_path is not None
        else output.with_suffix(output.suffix + ".json")
    )
    _atomic_bytes(
        receipt_output,
        (json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
    )
    return receipt


def verify_run_report(
    receipt_path: str | Path, *, root: str | Path = "."
) -> dict[str, Any]:
    """Verify the receipt, rendered report and every bound source byte."""
    root_path = Path(root).resolve()
    receipt_source = _from_root(root_path, receipt_path)
    receipt = _read_object(receipt_source, "DANTE-Light report receipt")
    body = dict(receipt)
    digest = body.pop("receipt_sha256", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("report receipt self-hash mismatch")
    if receipt.get("schema_version") != 1:
        raise ContractError("report receipt schema must be 1")
    if receipt.get("status") not in {"COMPLETE", "COMPLETE_WITHOUT_OPTIONAL_FOLLOWUP"}:
        raise ContractError("report receipt status is not complete")
    if receipt.get("scientific_status") != "TRIAGE_REPORT_ONLY":
        raise ContractError("report receipt scientific boundary mismatch")

    report = _inside(root_path, receipt.get("report_path", ""))
    if not report.is_file() or _sha256(report) != receipt.get("report_sha256"):
        raise ContractError("rendered report hash mismatch")
    artifacts = receipt.get("source_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractError("report receipt source artifacts are missing")
    roles: set[str] = set()
    paths: set[str] = set()
    for row in artifacts:
        if not isinstance(row, dict) or set(row) != {"role", "path", "sha256"}:
            raise ContractError("report source artifact record is malformed")
        role, name = str(row["role"]), str(row["path"])
        if role in roles or name in paths:
            raise ContractError("report source artifacts contain duplicate roles or paths")
        roles.add(role)
        paths.add(name)
        source = _inside(root_path, name)
        if not source.is_file() or _sha256(source) != row["sha256"]:
            raise ContractError(f"report source artifact hash mismatch: {name}")
    if "prospective_evidence" not in roles:
        raise ContractError("report receipt lacks prospective evidence")
    required_followup = {
        "followup_manifest",
        "followup_physical",
        "followup_gallery",
    }
    if receipt["status"] == "COMPLETE" and not required_followup.issubset(roles):
        raise ContractError("complete report receipt lacks full follow-up evidence")
    if "auxiliary_result" in roles and not required_followup.issubset(roles):
        raise ContractError("report auxiliary evidence is not linked to full follow-up")
    return receipt
