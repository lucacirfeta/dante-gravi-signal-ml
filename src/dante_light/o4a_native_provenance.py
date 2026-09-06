"""Fail-closed reconciliation for the historical native source-byte digest.

The frozen native contracts recorded a raw-byte digest for ``patch_producer``
while Git enforced LF-normalized Python sources.  The original byte stream is
not retained, so this module does not rewrite history or pretend that it is.
It validates a separately versioned reconciliation record and permits only the
explicit historical-to-canonical source mappings recorded there.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
RECONCILIATION_REL = Path(
    "artifacts/dante_light/o4a_v1_parity/"
    "native_patch_producer_provenance_reconciliation_v1.json"
)
SCHEMA_VERSION = 1
SOURCE_HASH_SEMANTICS = "utf8_lf_v1"
RECONCILIATION_DIGEST = (
    "c1430f4c5cf23345e91d022d152d8fd82265264f987d3a19f5f1700e65c2827d"
)
GIT_ATTRIBUTES_ALLOWED_ADDITIONS = frozenset(
    {
        "config/dante_o4a_final_impact_attribution_v1.json text eol=lf",
        "config/dante_workflow_public_smoke_v1.json text eol=lf",
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_source_sha256(path: Path) -> str:
    """Hash strict UTF-8 source after CRLF/lone-CR normalization to LF."""

    text = path.read_bytes().decode("utf-8", errors="strict")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _canonical_blob_sha256(blob: bytes) -> str:
    text = blob.decode("utf-8", errors="strict")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _require_reference(root: Path, reference: Mapping[str, Any], label: str) -> Path:
    path = (root / str(reference["path"])).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"native provenance {label} escapes the repository") from exc
    if not path.is_file() or sha256_file(path) != str(reference["sha256"]):
        raise ContractError(f"native provenance {label} digest mismatch: {path}")
    return path


def _policy_rules(blob: bytes) -> set[str]:
    try:
        text = blob.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContractError("native provenance git attributes are not UTF-8") from exc
    return {
        line.strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip() and not line.lstrip().startswith("#")
    }


def _require_git_attributes_policy(
    root: Path, reference: Mapping[str, Any]
) -> Path:
    """Accept the frozen policy bytes or the exact approved additive extension."""

    path = (root / str(reference["path"])).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ContractError("native provenance git attributes escapes repository") from exc
    if not path.is_file():
        raise ContractError(f"native provenance git attributes is absent: {path}")
    current = path.read_bytes()
    expected_sha256 = str(reference["sha256"])
    if hashlib.sha256(current).hexdigest() == expected_sha256:
        return path

    try:
        commits = subprocess.check_output(
            ["git", "log", "--format=%H", "--", relative],
            cwd=root,
            text=True,
            encoding="utf-8",
        ).splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractError(
            "native provenance historical git attributes are unavailable"
        ) from exc
    historical: bytes | None = None
    for commit in commits:
        try:
            candidate = subprocess.check_output(
                ["git", "show", f"{commit}:{relative}"], cwd=root
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ContractError(
                "native provenance historical git attributes are unavailable"
            ) from exc
        if hashlib.sha256(candidate).hexdigest() == expected_sha256:
            historical = candidate
            break
    if historical is None:
        raise ContractError(
            "native provenance frozen git attributes bytes are not retained"
        )

    historical_rules = _policy_rules(historical)
    current_rules = _policy_rules(current)
    additions = current_rules - historical_rules
    if not historical_rules.issubset(current_rules) or not additions.issubset(
        GIT_ATTRIBUTES_ALLOWED_ADDITIONS
    ):
        raise ContractError(
            "native provenance git attributes change is not an approved additive extension"
        )
    return path


def validate_reconciliation(
    payload: Mapping[str, Any], *, root: Path = ROOT, verify_git: bool = False
) -> dict[str, Any]:
    """Validate the immutable reconciliation record and every local binding."""

    root = root.resolve()
    value = json.loads(json.dumps(payload, allow_nan=False))
    declared = value.pop("record_digest", None)
    if declared != RECONCILIATION_DIGEST or declared != canonical_json_sha256(value):
        raise ContractError("native provenance reconciliation self-digest mismatch")
    value["record_digest"] = declared
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "PASS_PROVENANCE_RECONCILED"
        or value.get("source_hash_semantics") != SOURCE_HASH_SEMANTICS
        or value.get("conclusion")
        != "BYTE_REPRESENTATION_NOT_RETAINED_CANONICAL_SOURCE_RECOVERED"
    ):
        raise ContractError("native provenance reconciliation schema changed")

    boundary = value.get("scientific_boundary", {})
    expected_boundary = {
        "classes_changed": False,
        "cohort_changed": False,
        "index_changed": False,
        "populations_changed": False,
        "rerun_required": False,
        "scores_changed": False,
        "thresholds_changed": False,
    }
    if boundary != expected_boundary:
        raise ContractError("native provenance reconciliation scientific boundary changed")

    attributes_path = _require_git_attributes_policy(root, value["git_attributes"])
    if "src/**/*.py text eol=lf" not in attributes_path.read_text(encoding="utf-8"):
        raise ContractError("native provenance LF policy is absent")

    for label, reference in value["historical_contracts"].items():
        path = _require_reference(root, reference, f"historical contract {label}")
        contract = json.loads(path.read_text(encoding="utf-8"))
        if contract.get("contract_digest") != reference["contract_digest"]:
            raise ContractError(f"native provenance contract digest changed: {label}")
        patch_references = [
            item
            for item in contract.get("references", {}).values()
            if item.get("path") == "src/core/patch_producer.py"
        ]
        if len(patch_references) != 1 or patch_references[0].get("sha256") != value[
            "unretained_raw_source"
        ]["sha256"]:
            raise ContractError(f"native provenance historical source link changed: {label}")

    _require_reference(root, value["canonical_runtime"], "canonical runtime")
    runtime = json.loads(
        (root / value["canonical_runtime"]["path"]).read_text(encoding="utf-8")
    )
    if runtime.get("contract_digest") != value["canonical_runtime"]["contract_digest"]:
        raise ContractError("native provenance runtime contract digest changed")

    _require_reference(root, value["raw_manifest"], "raw manifest")
    cohort_artifact_path = _require_reference(
        root, value["native_cohort"]["compact_artifact"], "native cohort artifact"
    )
    cohort_artifact = json.loads(cohort_artifact_path.read_text(encoding="utf-8"))
    if (
        cohort_artifact.get("row_total") != value["native_cohort"]["row_total"]
        or cohort_artifact.get("ledger", {}).get("sha256")
        != value["native_cohort"]["ledger_sha256"]
        or Path(cohort_artifact.get("external_run", {}).get("directory", "")).name
        != value["native_cohort"]["run_directory"]
    ):
        raise ContractError("native provenance cohort identity changed")

    canonical = value["canonical_source"]
    canonical_path = (root / canonical["path"]).resolve()
    if canonical_source_sha256(canonical_path) != canonical["sha256"]:
        raise ContractError("native provenance canonical patch producer changed")

    exceptions = value.get("reference_exceptions", [])
    keys: set[tuple[str, str]] = set()
    for exception in exceptions:
        key = (str(exception["path"]), str(exception["historical_raw_sha256"]))
        if key in keys:
            raise ContractError("native provenance reference exception is duplicated")
        keys.add(key)
        current_path = (root / key[0]).resolve()
        if canonical_source_sha256(current_path) != exception["current_canonical_sha256"]:
            raise ContractError(f"native provenance reconciled source changed: {key[0]}")
        if exception.get("reason") not in {
            "line_ending_reconciliation",
            "provenance_validator_only",
        }:
            raise ContractError("native provenance exception reason changed")

    replay = value.get("canonical_replay", {})
    rows = replay.get("rows", [])
    identities = {(row.get("detector"), row.get("gps_start")) for row in rows}
    counts = {
        detector: sum(row.get("detector") == detector for row in rows)
        for detector in ("H1", "L1")
    }
    stitched = {
        detector: sum(
            row.get("detector") == detector and row.get("stitched") is True
            for row in rows
        )
        for detector in ("H1", "L1")
    }
    if (
        replay.get("runtime") != "canonical_wsl_preprocessing_subset_v1"
        or replay.get("runtime_scope")
        != {
            "excluded_as_noncomputational": [
                "cuda_device",
                "environment_digest",
                "torch",
            ],
            "required_exact": [
                "operating_system.system",
                "operating_system.machine",
                "operating_system.wsl",
                "python",
                "packages.astropy",
                "packages.gwpy",
                "packages.h5py",
                "packages.numpy",
                "packages.scipy",
                "numpy_version",
            ],
        }
        or len(rows) != 12
        or len(identities) != 12
        or counts != {"H1": 6, "L1": 6}
        or stitched != {"H1": 2, "L1": 2}
        or any(row.get("quality_disposition") != "PASS_CLEAN" for row in rows)
    ):
        raise ContractError("native provenance canonical replay evidence changed")

    if verify_git:
        commit = canonical["git_commit"]
        git_path = canonical["path"]
        try:
            blob = subprocess.check_output(
                ["git", "show", f"{commit}:{git_path}"], cwd=root
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ContractError("native provenance Git source is unavailable") from exc
        if _canonical_blob_sha256(blob) != canonical["sha256"]:
            raise ContractError("native provenance Git source digest changed")

    return value


def load_reconciliation(
    *, root: Path = ROOT, verify_git: bool = False
) -> dict[str, Any]:
    path = root.resolve() / RECONCILIATION_REL
    if not path.is_file():
        raise ContractError("native provenance reconciliation record is absent")
    return validate_reconciliation(
        json.loads(path.read_text(encoding="utf-8")),
        root=root,
        verify_git=verify_git,
    )


def verify_reference_with_reconciliation(
    *,
    root: Path,
    path: Path,
    expected_sha256: str,
    raw_hasher: Callable[[Path], str] = sha256_file,
) -> None:
    """Verify a reference exactly, or through one frozen reconciliation pair."""

    root = root.resolve()
    path = path.resolve()
    if path.is_file() and raw_hasher(path) == expected_sha256:
        return
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ContractError(f"native provenance reference escapes repository: {path}") from exc
    record = load_reconciliation(root=root)
    match = next(
        (
            item
            for item in record["reference_exceptions"]
            if item["path"] == relative
            and item["historical_raw_sha256"] == expected_sha256
        ),
        None,
    )
    if match is None or not path.is_file():
        raise ContractError(f"native provenance reference mismatch: {path}")
    if canonical_source_sha256(path) != match["current_canonical_sha256"]:
        raise ContractError(f"native provenance canonical reference mismatch: {path}")


def replay_reconciliation_sample(
    *,
    root: Path = ROOT,
    raw_root: Path,
    native_external_root: Path,
) -> dict[str, Any]:
    """Replay the frozen 12-window sample in the canonical WSL environment."""

    from src.dante_light.o4a_corrected_native import (
        _initialize_quality_worker,
        _quality_check_proposal,
    )
    from src.dante_light.o4a_corrected_runtime import (
        capture_runtime_environment,
        load_canonical_runtime_contract,
    )

    root = root.resolve()
    record = load_reconciliation(root=root, verify_git=True)
    frozen_runtime = load_canonical_runtime_contract(root=root, require_current=False)[
        "runtime_environment"
    ]
    current_runtime = capture_runtime_environment()
    frozen_projection = {
        "operating_system": {
            key: frozen_runtime["operating_system"][key]
            for key in ("system", "machine", "wsl")
        },
        "python": frozen_runtime["python"],
        "packages": {
            key: frozen_runtime["packages"][key]
            for key in ("astropy", "gwpy", "h5py", "numpy", "scipy")
        },
        "numpy_version": frozen_runtime["numpy_version"],
    }
    current_projection = {
        "operating_system": {
            key: current_runtime["operating_system"][key]
            for key in ("system", "machine", "wsl")
        },
        "python": current_runtime["python"],
        "packages": {
            key: current_runtime["packages"][key]
            for key in ("astropy", "gwpy", "h5py", "numpy", "scipy")
        },
        "numpy_version": current_runtime["numpy_version"],
    }
    if current_projection != frozen_projection:
        raise ContractError(
            "STOP_ENVIRONMENT_MISMATCH: native provenance replay requires the "
            "frozen WSL preprocessing runtime"
        )
    cohort = record["native_cohort"]
    ledger_path = (
        native_external_root.resolve()
        / cohort["run_directory"]
        / cohort["ledger_filename"]
    )
    if not ledger_path.is_file() or sha256_file(ledger_path) != cohort["ledger_sha256"]:
        raise ContractError("native provenance external cohort ledger mismatch")
    ledger_rows = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_identity = {
        (str(row["detector"]), float(row["gps_start"])): row for row in ledger_rows
    }
    if len(by_identity) != 1294:
        raise ContractError("native provenance external cohort identity count changed")

    manifest = root / record["raw_manifest"]["path"]
    _initialize_quality_worker(str(manifest), str(raw_root.resolve()), 4096, 4.0)
    checked: list[dict[str, Any]] = []
    for expected in record["canonical_replay"]["rows"]:
        identity = (str(expected["detector"]), float(expected["gps_start"]))
        frozen = by_identity.get(identity)
        if frozen is None:
            raise ContractError(f"native provenance replay identity absent: {identity}")
        for field in (
            "clean_window_sha256",
            "context_sources_digest",
            "quality_disposition",
        ):
            if frozen.get(field) != expected[field]:
                raise ContractError(
                    f"native provenance frozen replay evidence changed: {identity} {field}"
                )
        actual = _quality_check_proposal(
            {
                "detector": identity[0],
                "gps_start": identity[1],
                "priority": frozen["priority"],
            }
        )
        for field in (
            "clean_window_sha256",
            "context_sources_digest",
            "quality_disposition",
        ):
            if actual[field] != expected[field]:
                raise ContractError(
                    f"native provenance canonical replay mismatch: {identity} {field}"
                )
        actual_stitched = len(actual["context_sources"]) > 1
        if actual_stitched is not expected["stitched"]:
            raise ContractError(
                f"native provenance canonical stitching mismatch: {identity}"
            )
        checked.append(
            {
                "detector": identity[0],
                "gps_start": identity[1],
                "stitched": actual_stitched,
            }
        )
    return {
        "status": "PASS_CANONICAL_REPLAY",
        "row_total": len(checked),
        "counts_by_detector": {
            detector: sum(row["detector"] == detector for row in checked)
            for detector in ("H1", "L1")
        },
        "stitched_by_detector": {
            detector: sum(
                row["detector"] == detector and row["stitched"] for row in checked
            )
            for detector in ("H1", "L1")
        },
        "scientific_outputs_written": False,
    }


__all__ = [
    "RECONCILIATION_REL",
    "canonical_source_sha256",
    "load_reconciliation",
    "replay_reconciliation_sample",
    "validate_reconciliation",
    "verify_reference_with_reconciliation",
]
