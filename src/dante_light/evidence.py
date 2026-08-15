"""Build release evidence only from complete, internally consistent Light runs."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from src.core.artifact_manager import verify_reference_bundle
from src.core.index_contract import sha256_file
from src.dante_light.contracts import (
    ContractError,
    WindowIdentity,
    canonical_json_sha256,
)


COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SCORE_ATOL = 2e-7
RUN_FILES = ("run_manifest.json", "records.jsonl", "summary.json", "attempts.jsonl")


@dataclass(frozen=True, slots=True)
class ValidatedRun:
    directory: Path
    manifest: dict[str, Any]
    summary: dict[str, Any]
    records: dict[str, dict[str, Any]]
    artifacts: tuple[dict[str, str], ...]


def _root_member(root: Path, path: str | Path) -> Path:
    root = root.resolve()
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ContractError(f"evidence path escapes project root: {path}")
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON evidence {path}: {exc}") from exc


def _artifact(root: Path, path: Path) -> dict[str, str]:
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    return {"path": relative, "sha256": sha256_file(path)}


def _load_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    identities: set[tuple[str, str, float, float]] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read Light records {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
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
        raw_window = record["window"]
        window = WindowIdentity(
            run=raw_window["run"],
            detector=raw_window["detector"],
            gps_start=raw_window["gps_start"],
            duration_s=raw_window["duration_s"],
            schema_version=raw_window["schema_version"],
        )
        if window.to_dict() != raw_window:
            raise ContractError(f"window identity mismatch at {path}:{line_number}")
        identity = (window.run, window.detector, window.gps_start, window.duration_s)
        if identity in identities or window.window_id in records:
            raise ContractError(f"duplicate scientific identity at {path}:{line_number}")
        identities.add(identity)
        records[window.window_id] = record
    return records


def validate_run_directory(
    directory: str | Path,
    *,
    root: str | Path,
    expected_engine: str,
    prospective: bool,
) -> ValidatedRun:
    root = Path(root).resolve()
    directory = _root_member(root, directory)
    manifest_path = directory / "run_manifest.json"
    records_path = directory / "records.jsonl"
    summary_path = directory / "summary.json"
    for required in (manifest_path, records_path, summary_path):
        if not required.is_file():
            raise ContractError(f"incomplete Light run; missing {required}")

    manifest = _read_json(manifest_path)
    declared_manifest = manifest.get("manifest_sha256")
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_sha256", None)
    if declared_manifest != canonical_json_sha256(manifest_body):
        raise ContractError(f"run manifest digest mismatch: {manifest_path}")
    if manifest.get("schema_version") != 1:
        raise ContractError("unsupported Light run manifest schema")
    if manifest.get("scientific_engine") != expected_engine:
        raise ContractError(
            f"expected {expected_engine} run, found {manifest.get('scientific_engine')}"
        )
    if manifest.get("prospective") is not prospective:
        raise ContractError("run prospective flag does not match evidence mode")
    if manifest.get("prefilter") != "none":
        raise ContractError("release evidence requires the exact no-prefilter path")
    code_state = manifest["runtime_provenance"]["code_state"]
    if code_state.get("tracked_dirty") is not False:
        raise ContractError("release evidence cannot use a dirty tracked checkout")
    if COMMIT_RE.fullmatch(str(code_state.get("commit", ""))) is None:
        raise ContractError("release evidence lacks a full Git commit identity")

    records = _load_records(records_path)
    summary = _read_json(summary_path)
    executor = summary["executor"]
    if executor["drops"] != 0 or executor["written"] != executor["submitted"]:
        raise ContractError("Light run has drops or incomplete writes")
    if int(summary["records_total"]) != len(records):
        raise ContractError("Light summary/record count mismatch")
    if len(records) != int(executor["written"]):
        raise ContractError("Light executor/record count mismatch")
    allowed_status = {"complete", "complete_with_defer"} if prospective else {"complete"}
    if summary.get("status") not in allowed_status:
        raise ContractError(f"Light run status is not releasable: {summary.get('status')}")

    artifacts = tuple(
        _artifact(root, directory / filename)
        for filename in RUN_FILES
        if (directory / filename).is_file()
    )
    return ValidatedRun(directory, manifest, summary, records, artifacts)


def compare_exact_runs(
    canonical_dir: str | Path,
    shared_dir: str | Path,
    *,
    root: str | Path,
    prospective: bool,
    score_atol: float = SCORE_ATOL,
) -> dict[str, Any]:
    if not math.isfinite(score_atol) or score_atol <= 0 or score_atol > SCORE_ATOL:
        raise ContractError("score tolerance exceeds the frozen DANTE-Light bound")
    canonical = validate_run_directory(
        canonical_dir,
        root=root,
        expected_engine="canonical",
        prospective=prospective,
    )
    shared = validate_run_directory(
        shared_dir,
        root=root,
        expected_engine="shared_encoder_score_only",
        prospective=prospective,
    )
    comparable_manifest_fields = (
        "mode",
        "prefilter",
        "prospective",
        "representation",
        "epochs",
        "replay_manifest_sha256",
        "replay_entries_file_sha256",
        "roles",
        "limit",
        "cat1_provenance",
        "local_only",
        "strain_source",
    )
    for field in comparable_manifest_fields:
        if canonical.manifest.get(field) != shared.manifest.get(field):
            raise ContractError(f"paired Light manifests differ at {field}")
    for field in ("commit", "tracked_dirty"):
        if (
            canonical.manifest["runtime_provenance"]["code_state"].get(field)
            != shared.manifest["runtime_provenance"]["code_state"].get(field)
        ):
            raise ContractError(f"paired Light code states differ at {field}")
    if canonical.manifest["runtime_provenance"]["source_sha256"] != shared.manifest[
        "runtime_provenance"
    ]["source_sha256"]:
        raise ContractError("paired Light source hashes differ")
    if set(canonical.records) != set(shared.records):
        raise ContractError("paired Light window identities differ")

    max_delta = 0.0
    disposition_mismatches = 0
    for window_id in sorted(canonical.records):
        left = canonical.records[window_id]
        right = shared.records[window_id]
        for field in (
            "window",
            "representation_sha256",
            "epoch_id",
            "disposition",
            "defer_reason",
        ):
            if left.get(field) != right.get(field):
                if field == "disposition":
                    disposition_mismatches += 1
                raise ContractError(f"paired Light records differ at {window_id}/{field}")
        left_evidence = left.get("evidence", {})
        right_evidence = right.get("evidence", {})
        for field in (
            "strain_sha256",
            "image_sha256",
            "primary_top_k_sha256",
            "primary_mil_vector_sha256",
        ):
            if left_evidence.get(field) != right_evidence.get(field):
                raise ContractError(f"paired Light evidence differs at {window_id}/{field}")
        left_scores = left.get("scores", {})
        right_scores = right.get("scores", {})
        if set(left_scores) != set(right_scores):
            raise ContractError(f"paired Light score keys differ at {window_id}")
        for score_name in left_scores:
            delta = abs(float(left_scores[score_name]) - float(right_scores[score_name]))
            if not math.isfinite(delta) or delta > score_atol:
                raise ContractError(
                    f"paired Light score tolerance failed at {window_id}/{score_name}"
                )
            max_delta = max(max_delta, delta)

    failures = []
    defers = 0
    for run in (canonical, shared):
        defers += int(run.summary["executor"].get("deferred", 0))
        failures.extend(
            failure
            for failure in run.summary["executor"].get("failures", [])
            if failure.get("exception_type") != "DeferredWindow"
        )
    duplicate_identities = (
        len(canonical.records) - len(set(canonical.records))
        + len(shared.records) - len(set(shared.records))
    )
    return {
        "canonical": canonical,
        "shared": shared,
        "windows": len(canonical.records),
        "max_abs_score_delta": max_delta,
        "disposition_mismatches": disposition_mismatches,
        "duplicate_identities": duplicate_identities,
        "defers_across_pair": defers,
        "failures": failures,
        "score_atol": score_atol,
    }


def git_checkout_provenance(root: str | Path) -> dict[str, Any]:
    root = Path(root).resolve()

    def git(*args: str) -> str:
        try:
            return subprocess.check_output(
                ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ContractError(f"cannot attest Git checkout: {' '.join(args)}") from exc

    status = git("status", "--porcelain", "--untracked-files=no")
    commit = git("rev-parse", "HEAD")
    origin = git("remote", "get-url", "origin")
    if status:
        raise ContractError("clean-clone evidence requires a tracked-clean checkout")
    if COMMIT_RE.fullmatch(commit) is None:
        raise ContractError("clean-clone evidence lacks a full commit identity")
    return {
        "clean_clone": True,
        "tracked_dirty": False,
        "commit": commit,
        "origin_url": origin,
    }


def atomic_json(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    if path.exists():
        if _read_json(path) != payload:
            raise ContractError(f"refusing to overwrite divergent evidence: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_public_replay_evidence(
    canonical_dir: str | Path,
    shared_dir: str | Path,
    *,
    bundle_path: str | Path,
    output_path: str | Path,
    root: str | Path,
    mode: str,
) -> dict[str, Any]:
    if mode not in {"prepublish", "public"}:
        raise ContractError(f"unsupported clean-clone evidence mode: {mode}")
    root = Path(root).resolve()
    pair = compare_exact_runs(
        canonical_dir, shared_dir, root=root, prospective=False
    )
    canonical = pair["canonical"]
    if canonical.manifest.get("strain_source") != "gwosc-only":
        raise ContractError("clean-clone evidence requires --strain-source gwosc-only")
    if canonical.manifest.get("cat1_provenance") != "GWOSC CBC_CAT1 whole-window containment":
        raise ContractError("clean-clone evidence requires GWOSC CAT1 provenance")
    if pair["defers_across_pair"] or pair["failures"]:
        raise ContractError("clean-clone evidence contains DEFERs or failures")
    bundle = verify_reference_bundle(bundle_path)
    reference = _read_json(root / "config/reference_artifacts.json")["reference_bundle"]
    checkout = git_checkout_provenance(root)
    if checkout["commit"] != canonical.manifest["runtime_provenance"]["code_state"]["commit"]:
        raise ContractError("run commit does not match the attested clean checkout")

    public = mode == "public"
    if public:
        if reference.get("publication_status") != "deposited":
            raise ContractError("public replay requires a deposited reference bundle")
        if bundle["sha256"] != reference.get("sha256"):
            raise ContractError("downloaded bundle SHA256 differs from public contract")
        if not str(reference.get("url", "")).startswith("https://"):
            raise ContractError("public bundle URL must use HTTPS")
        if not str(checkout["origin_url"]).startswith("https://"):
            raise ContractError("public replay checkout origin must use HTTPS")

    artifacts = list(pair["canonical"].artifacts + pair["shared"].artifacts)
    payload = {
        "schema_version": 1,
        "status": "complete",
        "mode": (
            "clean_clone_public_replay"
            if public
            else "clean_clone_prepublish_preflight"
        ),
        "public_sources_only": public,
        "strain_source": "gwosc-only",
        "reference_bundle_sha256": bundle["sha256"],
        "bundle_source": {
            "url": reference.get("url") if public else None,
            "download_verified": public,
            "publication_status": reference.get("publication_status"),
        },
        "checkout": checkout,
        "replay_manifest_sha256": canonical.manifest["replay_manifest_sha256"],
        "replay_entries_file_sha256": canonical.manifest[
            "replay_entries_file_sha256"
        ],
        "coverage": {
            "windows": pair["windows"],
            "drops": 0,
            "failures": [],
        },
        "exact_replay": {
            "score_atol": pair["score_atol"],
            "max_abs_score_delta": pair["max_abs_score_delta"],
            "disposition_mismatches": pair["disposition_mismatches"],
        },
        "artifacts": artifacts,
    }
    atomic_json(output_path, payload)
    return payload
