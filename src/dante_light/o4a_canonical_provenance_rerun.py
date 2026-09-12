"""Fail-closed control plane for the canonical O4a provenance rerun.

This module does not implement scientific computations.  It binds the ordered
remediation stages, validates the immutable baselines and canonical source, and
rejects contract transitions outside an explicit JSON-pointer allowlist.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
from typing import Any

from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_REL = Path("config/dante_o4a_canonical_provenance_rerun_v1.json")
SCHEMA_VERSION = 1
EXPECTED_PROTOCOL_DIGEST = (
    "a50e77424501e1bcb01475d840ae40f9ae3fa306ab259a01b5e3529f179a6a05"
)
EXPECTED_STAGES = (
    "COHORT",
    "INDEX",
    "NATIVE_CALIBRATION",
    "RESCORE",
    "THRESHOLDS",
    "CLASSIFY",
    "TAXONOMY",
    "COINCIDENCE",
    "PEM",
    "COMPARE",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_source_sha256(path: Path) -> str:
    text = path.read_bytes().decode("utf-8", errors="strict")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _inside_root(root: Path, relative: str, *, label: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise ContractError(f"{label} must be a repository-relative path")
    path = (root / Path(*pure.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"{label} escapes the repository: {relative}") from exc
    return path


def _require_file_reference(
    root: Path, reference: Mapping[str, Any], *, label: str
) -> Path:
    path = _inside_root(root, str(reference["path"]), label=label)
    if not path.is_file():
        raise ContractError(f"{label} is absent: {path}")
    if sha256_file(path) != str(reference["sha256"]):
        raise ContractError(f"{label} digest mismatch: {path}")
    return path


def _json_pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def json_leaf_differences(
    baseline: Any, candidate: Any, *, pointer: str = ""
) -> set[str]:
    """Return leaf-level RFC-6901-style pointers that differ."""

    if isinstance(baseline, Mapping) and isinstance(candidate, Mapping):
        differences: set[str] = set()
        keys = set(baseline) | set(candidate)
        for key in keys:
            child = f"{pointer}/{_json_pointer_escape(str(key))}"
            if key not in baseline or key not in candidate:
                differences.add(child)
            else:
                differences.update(
                    json_leaf_differences(baseline[key], candidate[key], pointer=child)
                )
        return differences
    if (
        isinstance(baseline, Sequence)
        and not isinstance(baseline, (str, bytes, bytearray))
        and isinstance(candidate, Sequence)
        and not isinstance(candidate, (str, bytes, bytearray))
    ):
        if len(baseline) != len(candidate):
            return {pointer or "/"}
        differences: set[str] = set()
        for index, (left, right) in enumerate(zip(baseline, candidate, strict=True)):
            differences.update(
                json_leaf_differences(left, right, pointer=f"{pointer}/{index}")
            )
        return differences
    return set() if baseline == candidate else {pointer or "/"}


def _pointer_allowed(pointer: str, allowed: Sequence[str]) -> bool:
    for rule in allowed:
        if rule.endswith("/**"):
            prefix = rule[:-3]
            if pointer == prefix or pointer.startswith(f"{prefix}/"):
                return True
        elif pointer == rule:
            return True
    return False


def contract_digest(payload: Mapping[str, Any]) -> str:
    value = copy.deepcopy(dict(payload))
    value.pop("contract_digest", None)
    return canonical_json_sha256(value)


def assert_allowed_contract_transition(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    allowed_changes: Sequence[str],
) -> set[str]:
    """Reject any baseline-to-rerun contract change outside the allowlist."""

    differences = json_leaf_differences(baseline, candidate)
    forbidden = sorted(
        pointer
        for pointer in differences
        if not _pointer_allowed(pointer, allowed_changes)
    )
    if forbidden:
        raise ContractError(
            "scientific contract transition is not allowed: " + ", ".join(forbidden)
        )
    declared = candidate.get("contract_digest")
    if declared != contract_digest(candidate):
        raise ContractError("candidate contract self-digest mismatch")
    return differences


def _validate_git_source(root: Path, source: Mapping[str, Any]) -> None:
    path = _inside_root(root, str(source["path"]), label="canonical source")
    if canonical_source_sha256(path) != source["canonical_sha256"]:
        raise ContractError("canonical source working-tree digest mismatch")
    try:
        blob = subprocess.check_output(
            ["git", "show", f"{source['git_commit']}:{source['path']}"], cwd=root
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractError("canonical source Git blob is unavailable") from exc
    text = blob.decode("utf-8", errors="strict")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if digest != source["canonical_sha256"]:
        raise ContractError("canonical source Git blob digest mismatch")


def validate_protocol(
    payload: Mapping[str, Any], *, root: Path = ROOT, verify_git: bool = True
) -> dict[str, Any]:
    root = root.resolve()
    value = json.loads(json.dumps(payload, allow_nan=False))
    declared = value.pop("protocol_digest", None)
    computed = canonical_json_sha256(value)
    if declared != EXPECTED_PROTOCOL_DIGEST or declared != computed:
        raise ContractError("canonical provenance rerun protocol digest mismatch")
    value["protocol_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported canonical provenance rerun schema")
    if value.get("status") != "FROZEN_BEFORE_RECOMPUTATION":
        raise ContractError("canonical provenance rerun is not frozen")
    if value.get("ordered_stages") != list(EXPECTED_STAGES):
        raise ContractError("canonical provenance rerun stage order changed")
    if value.get("mandatory_transparency_note") is not True:
        raise ContractError("mandatory provenance transparency note was disabled")
    expected_boundary = {
        "classification_changed": False,
        "cohort_population_changed": False,
        "coincidence_changed": False,
        "index_hyperparameters_changed": False,
        "pem_changed": False,
        "preprocessing_changed": False,
        "scoring_changed": False,
        "statistical_validation_changed": False,
        "taxonomy_changed": False,
        "thresholds_changed": False,
    }
    if value.get("scientific_boundary") != expected_boundary:
        raise ContractError("canonical provenance rerun scientific boundary changed")
    if value.get("unresolved_historical_source", {}).get("sha256") != (
        "2c20d4e89b48060986770127bf41c2d860d22efc4f98f430cb152cfb71f39dcf"
    ):
        raise ContractError("historical unresolved source identity changed")

    baseline_names: list[str] = []
    for stage in value["stages"]:
        name = str(stage["name"])
        baseline_names.append(name)
        _require_file_reference(
            root, stage["baseline_contract"], label=f"{name} baseline contract"
        )
        rules = stage.get("allowed_changes", [])
        if not rules or "/contract_digest" not in rules or "/contract_id" not in rules:
            raise ContractError(f"{name} contract allowlist is incomplete")
    if baseline_names != list(EXPECTED_STAGES):
        raise ContractError("canonical provenance rerun stage definitions changed")

    transparency = _inside_root(
        root,
        str(value["transparency_note_path"]),
        label="transparency note",
    )
    if transparency.suffix.lower() != ".md":
        raise ContractError("transparency note must be a Markdown document")

    historical = {
        str(item).casefold().rstrip("/\\")
        for item in value["paths"]["historical_external_roots"]
    }
    targets = {
        str(item).casefold().rstrip("/\\")
        for item in value["paths"]["remediation_external_roots"]
    }
    if len(targets) != len(value["paths"]["remediation_external_roots"]):
        raise ContractError("remediation external roots are duplicated")
    if historical & targets:
        raise ContractError("remediation output aliases historical evidence")
    prefix = str(value["paths"]["remediation_external_root"]).casefold().rstrip("/\\")
    if not all(item == prefix or item.startswith(prefix + "/") for item in targets):
        raise ContractError("remediation stage root escapes its namespace")

    if verify_git:
        _validate_git_source(root, value["canonical_source"])
    return value


def load_protocol(*, root: Path = ROOT, verify_git: bool = True) -> dict[str, Any]:
    path = root.resolve() / PROTOCOL_REL
    if not path.is_file():
        raise ContractError(f"canonical provenance rerun protocol is absent: {path}")
    return validate_protocol(
        json.loads(path.read_text(encoding="utf-8")),
        root=root,
        verify_git=verify_git,
    )


def stage_spec(protocol: Mapping[str, Any], stage_name: str) -> dict[str, Any]:
    name = str(stage_name).upper()
    for stage in protocol["stages"]:
        if stage["name"] == name:
            return dict(stage)
    raise ContractError(f"unknown canonical provenance rerun stage: {stage_name}")


def build_cohort_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Derive the COHORT contract without changing any scientific field."""

    protocol = load_protocol(root=root, verify_git=True)
    stage = stage_spec(protocol, "COHORT")
    baseline_path = root / stage["baseline_contract"]["path"]
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = copy.deepcopy(baseline)
    candidate["contract_id"] = "dante-o4a-canonical-provenance-rerun-cohort-v1"
    candidate["references"]["patch_producer"]["sha256"] = protocol[
        "canonical_source"
    ]["canonical_sha256"]
    implementation = root / candidate["references"]["native_implementation"]["path"]
    candidate["references"]["native_implementation"]["sha256"] = sha256_file(
        implementation
    )
    candidate["external_output"]["root"] = protocol["paths"][
        "remediation_external_roots"
    ][0]
    candidate["remediation"] = {
        "protocol_digest": protocol["protocol_digest"],
        "baseline_contract_sha256": stage["baseline_contract"]["sha256"],
        "historical_source_sha256": protocol["unresolved_historical_source"][
            "sha256"
        ],
        "canonical_source_sha256": protocol["canonical_source"][
            "canonical_sha256"
        ],
        "historical_outputs_immutable": True,
    }
    candidate["contract_digest"] = contract_digest(candidate)
    assert_allowed_contract_transition(
        baseline,
        candidate,
        allowed_changes=stage["allowed_changes"],
    )
    from src.dante_light.o4a_corrected_native import validate_native_contract

    return validate_native_contract(candidate, root=root.resolve())


def write_frozen_cohort_contract(*, root: Path = ROOT) -> Path:
    protocol = load_protocol(root=root, verify_git=True)
    stage = stage_spec(protocol, "COHORT")
    target = _inside_root(
        root, stage["remediation_contract"], label="COHORT remediation contract"
    )
    candidate = build_cohort_contract(root=root)
    serialized = json.dumps(candidate, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if target.is_file():
        if target.read_text(encoding="utf-8") != serialized:
            raise ContractError(f"refusing divergent frozen COHORT contract: {target}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    temporary.replace(target)
    return target


@contextmanager
def use_stage_contract(module: Any, contract_rel: str):
    """Temporarily route an existing stage module to a remediation contract."""

    previous = module.CONTRACT_REL
    module.CONTRACT_REL = Path(contract_rel)
    try:
        yield
    finally:
        module.CONTRACT_REL = previous


def run_cohort(
    *,
    root: Path = ROOT,
    workers: int = 8,
    quality_batch_size: int = 128,
    verify_only: bool = False,
) -> tuple[dict[str, Any], Path]:
    """Run or verify COHORT in its isolated remediation namespace."""

    protocol = load_protocol(root=root, verify_git=True)
    stage = stage_spec(protocol, "COHORT")
    contract_path = _inside_root(
        root, stage["remediation_contract"], label="COHORT remediation contract"
    )
    if not contract_path.is_file():
        raise ContractError("COHORT remediation contract is not frozen")
    baseline = json.loads(
        (root / stage["baseline_contract"]["path"]).read_text(encoding="utf-8")
    )
    candidate = json.loads(contract_path.read_text(encoding="utf-8"))
    assert_allowed_contract_transition(
        baseline, candidate, allowed_changes=stage["allowed_changes"]
    )

    from src.dante_light import o4a_corrected_native as cohort_module

    common = {
        "root": root.resolve(),
        "primary_external_root": Path(
            protocol["paths"]["primary_external_root_wsl"]
        ),
        "external_root": Path(protocol["paths"]["remediation_external_roots"][0]),
    }
    with use_stage_contract(cohort_module, stage["remediation_contract"]):
        if verify_only:
            return cohort_module.verify_native_cohort(**common)
        return cohort_module.freeze_native_cohort(
            raw_root=Path(protocol["paths"]["raw_root_wsl"]),
            workers=workers,
            quality_batch_size=quality_batch_size,
            **common,
        )


def require_tracked_clean(root: Path = ROOT) -> None:
    try:
        status = subprocess.check_output(
            [
                "git",
                "-c",
                "core.autocrlf=true",
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
            ],
            cwd=root,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractError("tracked-clean Git status is unavailable") from exc
    if status.strip():
        raise ContractError("canonical provenance rerun requires a tracked-clean checkout")


def is_wsl() -> bool:
    release = platform.release().casefold()
    return "microsoft" in release or "wsl" in release


def preflight(*, root: Path = ROOT, require_cuda: bool = True) -> dict[str, Any]:
    protocol = load_protocol(root=root, verify_git=True)
    require_tracked_clean(root)
    if not is_wsl():
        raise ContractError("canonical provenance rerun must execute inside WSL")
    if require_cuda:
        try:
            import torch
        except ImportError as exc:
            raise ContractError("canonical CUDA runtime is unavailable") from exc
        if not torch.cuda.is_available():
            raise ContractError("canonical CUDA device is unavailable")

    raw_root = Path(protocol["paths"]["raw_root_wsl"])
    output_root = Path(protocol["paths"]["remediation_external_root"])
    if not raw_root.is_dir():
        raise ContractError(f"canonical raw root is absent: {raw_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(output_root.parent).free
    minimum = int(protocol["gates"]["minimum_free_bytes"])
    if free_bytes < minimum:
        raise ContractError(
            f"insufficient remediation storage: {free_bytes} < {minimum} bytes"
        )
    return {
        "status": "PASS_PREFLIGHT",
        "protocol_digest": protocol["protocol_digest"],
        "tracked_clean": True,
        "wsl": True,
        "cuda_required": require_cuda,
        "raw_root": os.fspath(raw_root),
        "external_root": os.fspath(output_root),
        "free_bytes": free_bytes,
    }


__all__ = [
    "EXPECTED_STAGES",
    "PROTOCOL_REL",
    "ROOT",
    "assert_allowed_contract_transition",
    "build_cohort_contract",
    "canonical_source_sha256",
    "contract_digest",
    "json_leaf_differences",
    "load_protocol",
    "preflight",
    "require_tracked_clean",
    "run_cohort",
    "sha256_file",
    "stage_spec",
    "use_stage_contract",
    "validate_protocol",
    "write_frozen_cohort_contract",
]
