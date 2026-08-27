"""Fail-closed teacher-stability amendment for DANTE-Light v7.

The amendment is built exclusively from the already-opened v7 training
partition.  It freezes the complete exact-teacher fingerprint and a small,
deterministically selected training canary.  No threshold-search,
risk-calibration, confirmation, or O4b identity is read by the runtime canary.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
from typing import Any, Mapping, Sequence

import numpy as np
import torch

from src.core.artifact_manager import verify_reference_indices
from src.dante_light.contracts import (
    ContractError,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light.prefilter_v5_teacher import (
    ExactNativeTeacher,
    TARGET_NAME,
    prepare_teacher_input,
)
from src.dante_light.prefilter_v7_training import (
    DEFAULT_CACHE,
    DEFAULT_LEDGER_SUMMARY,
    DEFAULT_TARGETS,
)
from src.dante_light.prefilter_v7_training_freeze import (
    ROOT,
    file_sha256,
    repository_reference,
)


SCHEMA_VERSION = 1
CANARIES_PER_CELL = 2
CANARY_PURPOSE = "dante-light-v7-teacher-stability-canary-v1"
PROTECTED_PARTITIONS = ("threshold_search", "risk_calibration", "confirmation")
FORBIDDEN_PARTITIONS = ("threshold_search", "risk_calibration", "confirmation", "o4b")
DEFAULT_CONTRACT = ROOT / "config/dante_light_prefilter_v7_teacher_stability.json"
DEFAULT_BASELINE = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_stability/teacher_stability_baseline_v7.json"
)
DEFAULT_IDENTITIES = ROOT / "config/dante_light_prefilter_v7_identities.jsonl"
DEFAULT_TEACHER_CONTRACT = ROOT / "config/dante_light_prefilter_v5_teacher_contract.json"
DEFAULT_TRAINING_SUMMARY = (
    ROOT / "artifacts/dante_light/prefilter_l4_v7_training/student_training_summary_v7.json"
)
DEFAULT_CONFIRMATION_SEAL = ROOT / "config/dante_light_prefilter_v7_confirmation_seal.json"


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
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ContractError(f"required teacher dependency is absent: {name}") from exc


def runtime_environment(device: str) -> dict[str, Any]:
    if device not in {"cpu", "cuda"}:
        raise ContractError("teacher stability device must be cpu or cuda")
    if device == "cuda" and not torch.cuda.is_available():
        raise ContractError("frozen teacher stability device cuda is unavailable")
    result: dict[str, Any] = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "torch": torch.__version__,
        "scipy": _package_version("scipy"),
        "gwpy": _package_version("gwpy"),
        "matplotlib": _package_version("matplotlib"),
        "pillow": _package_version("pillow"),
        "device": device,
        "dtype": "float32",
        "deterministic_algorithms_required": True,
    }
    if device == "cuda":
        result.update(
            {
                "cuda_runtime": torch.version.cuda,
                "cuda_device_name": torch.cuda.get_device_name(0),
                "cuda_device_capability": list(torch.cuda.get_device_capability(0)),
            }
        )
    return result


def _verify_digest(payload: Mapping[str, Any], field: str, label: str) -> None:
    body = dict(payload)
    declared = body.pop(field, None)
    if declared != canonical_json_sha256(body):
        raise ContractError(f"{label} digest mismatch")


def _require_reference(root: Path, reference: Mapping[str, Any], label: str) -> Path:
    if set(reference) != {"path", "sha256"}:
        raise ContractError(f"teacher stability reference is malformed: {label}")
    relative = Path(str(reference["path"]))
    if relative.is_absolute() or ".." in relative.parts or "\\" in str(reference["path"]):
        raise ContractError(f"teacher stability reference is not portable: {label}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ContractError(f"teacher stability reference is absent: {label}")
    if file_sha256(path) != str(reference["sha256"]):
        raise ContractError(f"teacher stability reference hash mismatch: {label}")
    return path


def _canary_priority(identity_id: str) -> str:
    return hashlib.sha256(f"{CANARY_PURPOSE}:{identity_id}".encode("utf-8")).hexdigest()


def _load_training_sources(
    root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    ledger_path = root / DEFAULT_LEDGER_SUMMARY.relative_to(ROOT)
    targets_path = root / DEFAULT_TARGETS.relative_to(ROOT)
    identities_path = root / DEFAULT_IDENTITIES.relative_to(ROOT)
    ledger = _read_json(ledger_path)
    _verify_digest(ledger, "artifact_digest", "v7 teacher ledger")
    if ledger.get("status") != "COMPLETE_TRAINING_ONLY" or ledger.get("row_count") != 600:
        raise ContractError("v7 teacher ledger is not complete training-only evidence")
    if any(ledger["accessed"].get(name) for name in FORBIDDEN_PARTITIONS):
        raise ContractError("protected v7 data was accessed before stability freeze")
    if ledger.get("compact_targets", {}).get("sha256") != file_sha256(targets_path):
        raise ContractError("v7 compact teacher targets changed")
    targets = _read_jsonl(targets_path)
    identities = {row["identity_id"]: row for row in _read_jsonl(identities_path)}
    if len(targets) != 600 or len({row["identity_id"] for row in targets}) != 600:
        raise ContractError("v7 compact targets are incomplete or duplicated")
    if any(identities[row["identity_id"]]["partition"] != "training" for row in targets):
        raise ContractError("teacher canary source crossed the training partition")
    return ledger, targets, identities


def _select_canaries(
    targets: Sequence[Mapping[str, Any]], identities: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    cells: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in targets:
        cells.setdefault((str(row["detector"]), str(row["sampling_role"])), []).append(row)
    expected_cells = {
        (detector, role)
        for detector in ("H1", "L1")
        for role in ("background", "teacher_positive")
    }
    if set(cells) != expected_cells:
        raise ContractError("v7 training canary cells are incomplete")
    selected: list[dict[str, Any]] = []
    for cell in sorted(expected_cells):
        candidates = sorted(cells[cell], key=lambda row: _canary_priority(str(row["identity_id"])))
        for target in candidates[:CANARIES_PER_CELL]:
            identity = identities[str(target["identity_id"])]
            selected.append(
                {
                    "identity_id": str(target["identity_id"]),
                    "detector": str(target["detector"]),
                    "sampling_role": str(target["sampling_role"]),
                    "selection_priority": _canary_priority(str(target["identity_id"])),
                    "window": dict(identity["window"]),
                    "expected": {
                        "raw_strain_sha256": str(target["raw_strain_sha256"]),
                        "clean_strain_sha256": str(target["clean_strain_sha256"]),
                        "image_sha256": str(target["image_sha256"]),
                        "teacher_score_float32_hex": str(target["teacher_target"]["float32_hex"]),
                        "teacher_score": float(target["teacher_target"][TARGET_NAME]),
                    },
                }
            )
    return selected


def _teacher_fingerprint(root: Path, ledger: Mapping[str, Any], device: str) -> dict[str, Any]:
    teacher_contract_path = root / DEFAULT_TEACHER_CONTRACT.relative_to(ROOT)
    teacher_contract = _read_json(teacher_contract_path)
    _verify_digest(teacher_contract, "teacher_contract_digest", "v5 teacher contract")
    representation = RepresentationContract.from_reference_manifest(
        root / "config/reference_artifacts.json"
    )
    if representation.to_dict() != teacher_contract["representation"]:
        raise ContractError("current representation disagrees with the frozen teacher contract")
    verified_indices = verify_reference_indices(
        manifest_path=root / "config/reference_artifacts.json"
    )
    by_id = {row["artifact_id"]: row for row in verified_indices}
    native = by_id.get("o4a_native_q4_64_k1216")
    primary = by_id.get("o3b_production_k275")
    if (
        native is None
        or primary is None
        or native["sha256"] != representation.native_index_sha256
        or primary["sha256"] != representation.primary_index_sha256
    ):
        raise ContractError("installed teacher indexes disagree with the frozen representation")
    code_names = (
        "core_preprocessor",
        "data_loader",
        "exact_teacher",
        "patch_scorer",
        "reference_artifacts",
    )
    code_references = {name: dict(ledger["code_references"][name]) for name in code_names}
    for name, reference in code_references.items():
        _require_reference(root, reference, f"teacher_code/{name}")
    manifest = _read_json(root / "config/reference_artifacts.json")
    model = manifest["models"]["dinov2_vits14_reg"]
    body = {
        "representation": representation.to_dict(),
        "model": {
            "artifact_id": "dinov2_vits14_reg",
            "repository": model["repository"],
            "revision": model["revision"],
            "source_python_tree_sha256": model["source_python_tree_sha256"],
            "weights_sha256": model["weights_sha256"],
            "weights_bytes": int(model["weights_bytes"]),
        },
        "indices": {
            "native": {
                "artifact_id": native["artifact_id"],
                "sha256": native["sha256"],
                "shape": list(native["shape"]),
            },
            "primary_encoder": {
                "artifact_id": primary["artifact_id"],
                "sha256": primary["sha256"],
                "shape": list(primary["shape"]),
            },
        },
        "code_references": code_references,
        "teacher_contract_reference": repository_reference(root, teacher_contract_path),
        "runtime_environment": runtime_environment(device),
    }
    return {**body, "fingerprint_digest": canonical_json_sha256(body)}


def build_stability_contract(
    *, root: Path = ROOT, device: str = "cuda", write: bool = True
) -> dict[str, Any]:
    ledger, targets, identities = _load_training_sources(root)
    confirmation_seal_path = root / DEFAULT_CONFIRMATION_SEAL.relative_to(ROOT)
    confirmation_seal = _read_json(confirmation_seal_path)
    if (
        confirmation_seal.get("status") != "SEALED_NOT_OPENED"
        or confirmation_seal.get("access_entries_at_freeze") != 0
        or confirmation_seal.get("confirmation_student_outputs_accessed") != []
        or confirmation_seal.get("o4b_accessed") != []
    ):
        raise ContractError("v7 confirmation is not sealed before stability amendment")
    canaries = _select_canaries(targets, identities)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_PRE_THRESHOLD_SEARCH",
        "authorization": {
            "actor": "Luca Cirfeta",
            "decision": "confirm_teacher_stability_amendment",
            "date": "2026-08-27",
        },
        "teacher_fingerprint": _teacher_fingerprint(root, ledger, device),
        "canary_contract": {
            "source_partition": "training",
            "protected_partition_rows_used": 0,
            "selection": f"two_smallest_sha256_{CANARY_PURPOSE}_per_detector_sampling_role",
            "canaries_per_cell": CANARIES_PER_CELL,
            "total_canaries": len(canaries),
            "comparison": {
                "raw_strain_sha256": "exact",
                "clean_strain_sha256": "exact",
                "image_sha256": "exact",
                "teacher_score_float32_hex": "exact",
            },
            "rows": canaries,
        },
        "stage_precondition": {
            "required_before_first_partition_row_read": list(PROTECTED_PARTITIONS),
            "failure_action": "STOP_NO_ACCESS_NO_RETUNE",
            "partition_data_may_not_be_used_for_canary": True,
            "fingerprint_must_equal_training": True,
            "canary_must_equal_training": True,
            "receipt_chain_required_for_confirmation_unlock": list(PROTECTED_PARTITIONS),
        },
        "supplemental_seal": {
            "parent_confirmation_seal_digest": confirmation_seal["seal_digest"],
            "parent_status": "SEALED_NOT_OPENED",
            "additional_unlock_bindings": [
                "teacher_stability_contract_digest",
                "threshold_search_stability_receipt_digest",
                "risk_calibration_stability_receipt_digest",
                "confirmation_stability_receipt_digest",
            ],
        },
        "source_references": {
            "teacher_ledger": repository_reference(
                root, root / DEFAULT_LEDGER_SUMMARY.relative_to(ROOT)
            ),
            "teacher_targets": repository_reference(
                root, root / DEFAULT_TARGETS.relative_to(ROOT)
            ),
            "identity_manifest": repository_reference(
                root, root / DEFAULT_IDENTITIES.relative_to(ROOT)
            ),
            "training_summary": repository_reference(
                root, root / DEFAULT_TRAINING_SUMMARY.relative_to(ROOT)
            ),
            "confirmation_seal": repository_reference(root, confirmation_seal_path),
            "stability_implementation": repository_reference(root, Path(__file__)),
            "stability_builder": repository_reference(
                root, root / "scripts/freeze_dante_light_prefilter_v7_teacher_stability.py"
            ),
            "stability_verifier": repository_reference(
                root, root / "scripts/verify_dante_light_prefilter_v7_teacher_stability.py"
            ),
        },
        "accessed": {name: [] for name in FORBIDDEN_PARTITIONS},
    }
    contract = {**body, "stability_contract_digest": canonical_json_sha256(body)}
    if write:
        _write_json(root / DEFAULT_CONTRACT.relative_to(ROOT), contract)
    return contract


def verify_stability_contract(
    path: Path = DEFAULT_CONTRACT, *, root: Path = ROOT
) -> dict[str, Any]:
    contract_path = root / path.relative_to(ROOT) if path.is_absolute() else root / path
    payload = _read_json(contract_path)
    _verify_digest(payload, "stability_contract_digest", "v7 teacher stability contract")
    if payload.get("status") != "FROZEN_PRE_THRESHOLD_SEARCH":
        raise ContractError("teacher stability contract status changed")
    if any(payload.get("accessed", {}).get(name) for name in FORBIDDEN_PARTITIONS):
        raise ContractError("teacher stability freeze crossed a protected boundary")
    if payload.get("stage_precondition") != {
        "required_before_first_partition_row_read": list(PROTECTED_PARTITIONS),
        "failure_action": "STOP_NO_ACCESS_NO_RETUNE",
        "partition_data_may_not_be_used_for_canary": True,
        "fingerprint_must_equal_training": True,
        "canary_must_equal_training": True,
        "receipt_chain_required_for_confirmation_unlock": list(PROTECTED_PARTITIONS),
    }:
        raise ContractError("teacher stability stage precondition changed")
    for label, reference in payload["source_references"].items():
        _require_reference(root, reference, label)
    ledger, targets, identities = _load_training_sources(root)
    expected_canaries = _select_canaries(targets, identities)
    canary_contract = payload["canary_contract"]
    if {
        "source_partition": canary_contract.get("source_partition"),
        "protected_partition_rows_used": canary_contract.get(
            "protected_partition_rows_used"
        ),
        "selection": canary_contract.get("selection"),
        "canaries_per_cell": canary_contract.get("canaries_per_cell"),
        "total_canaries": canary_contract.get("total_canaries"),
        "comparison": canary_contract.get("comparison"),
    } != {
        "source_partition": "training",
        "protected_partition_rows_used": 0,
        "selection": f"two_smallest_sha256_{CANARY_PURPOSE}_per_detector_sampling_role",
        "canaries_per_cell": CANARIES_PER_CELL,
        "total_canaries": len(expected_canaries),
        "comparison": {
            "raw_strain_sha256": "exact",
            "clean_strain_sha256": "exact",
            "image_sha256": "exact",
            "teacher_score_float32_hex": "exact",
        },
    }:
        raise ContractError("teacher stability canary contract changed")
    if canary_contract.get("rows") != expected_canaries:
        raise ContractError("teacher stability canary selection or expectations changed")
    device = str(payload["teacher_fingerprint"]["runtime_environment"]["device"])
    current_fingerprint = _teacher_fingerprint(root, ledger, device)
    if current_fingerprint != payload["teacher_fingerprint"]:
        raise ContractError("STOP_NO_ACCESS_NO_RETUNE: exact teacher fingerprint changed")
    return payload


def _teacher_run_dir(root: Path, cache_root: Path) -> Path:
    ledger = _read_json(root / DEFAULT_LEDGER_SUMMARY.relative_to(ROOT))
    return cache_root.resolve() / str(ledger["cache_location"]["run_subdirectory"])


def _require_canary_observation(
    canary: Mapping[str, Any],
    *,
    raw_strain_sha256: str,
    clean_strain_sha256: str,
    image_sha256: str,
    teacher_score_float32_hex: str,
) -> None:
    expected = canary["expected"]
    observed = {
        "raw_strain_sha256": raw_strain_sha256,
        "clean_strain_sha256": clean_strain_sha256,
        "image_sha256": image_sha256,
        "teacher_score_float32_hex": teacher_score_float32_hex,
    }
    for name, value in observed.items():
        if value != expected[name]:
            raise ContractError(
                f"STOP_NO_ACCESS_NO_RETUNE: canary {name} changed for {canary['identity_id']}"
            )


def run_training_canary(
    *,
    requested_partition: str,
    root: Path = ROOT,
    cache_root: Path = DEFAULT_CACHE,
    contract_path: Path = DEFAULT_CONTRACT,
    device: str | None = None,
    prior_partition_access_entries: int = 0,
    write_path: Path | None = None,
) -> dict[str, Any]:
    if requested_partition not in {"baseline", *PROTECTED_PARTITIONS}:
        raise ContractError("unknown teacher stability stage")
    if prior_partition_access_entries != 0:
        raise ContractError("STOP_NO_ACCESS_NO_RETUNE: partition was accessed before teacher check")
    contract = verify_stability_contract(contract_path, root=root)
    frozen_device = str(contract["teacher_fingerprint"]["runtime_environment"]["device"])
    if device is not None and device != frozen_device:
        raise ContractError("STOP_NO_ACCESS_NO_RETUNE: teacher device changed")
    actual_device = frozen_device

    run_dir = _teacher_run_dir(root, cache_root)
    raw_manifest_path = run_dir / "raw_manifest_v7.jsonl"
    ledger = _read_json(root / DEFAULT_LEDGER_SUMMARY.relative_to(ROOT))
    if (
        not raw_manifest_path.is_file()
        or file_sha256(raw_manifest_path) != ledger["raw_manifest"]["sha256"]
    ):
        raise ContractError("STOP_NO_ACCESS_NO_RETUNE: training raw manifest changed")
    raw_records = {row["identity_id"]: row for row in _read_jsonl(raw_manifest_path)}
    raw_dir = run_dir / "raw"
    for canary in contract["canary_contract"]["rows"]:
        record = raw_records.get(canary["identity_id"])
        if record is None:
            raise ContractError("STOP_NO_ACCESS_NO_RETUNE: canary raw record is absent")
        source_name = Path(str(record["relative_path"])).name
        raw_path = raw_dir / canary["detector"] / str(record["block_index"]) / source_name
        if not raw_path.is_file() or file_sha256(raw_path) != record["file_sha256"]:
            raise ContractError("STOP_NO_ACCESS_NO_RETUNE: canary raw file changed")

    torch.use_deterministic_algorithms(True)
    if actual_device == "cuda":
        torch.cuda.manual_seed_all(0)
    np.random.seed(0)
    representation = RepresentationContract.from_reference_manifest(
        root / "config/reference_artifacts.json"
    )
    # Constructing the teacher verifies the pinned DINOv2 source/weights and
    # both reference-index hashes before any canary strain is read.
    teacher = ExactNativeTeacher(
        root=root, representation=representation, device=actual_device
    )
    from src.core import data_loader

    if raw_dir not in data_loader._DATA_DIRECTORIES:
        data_loader._DATA_DIRECTORIES.insert(0, raw_dir)
    prepared = []
    for canary in contract["canary_contract"]["rows"]:
        item = prepare_teacher_input(
            WindowIdentity.from_dict(canary["window"]),
            representation=representation,
            local_only=True,
        )
        _require_canary_observation(
            canary,
            raw_strain_sha256=item.raw_strain_sha256,
            clean_strain_sha256=item.clean_strain_sha256,
            image_sha256=item.image_sha256,
            teacher_score_float32_hex=canary["expected"]["teacher_score_float32_hex"],
        )
        prepared.append(item)
    scores, _ = teacher.score([item.image for item in prepared])
    observations = []
    for canary, item, score in zip(contract["canary_contract"]["rows"], prepared, scores):
        score_hex = np.float32(score).tobytes().hex()
        _require_canary_observation(
            canary,
            raw_strain_sha256=item.raw_strain_sha256,
            clean_strain_sha256=item.clean_strain_sha256,
            image_sha256=item.image_sha256,
            teacher_score_float32_hex=score_hex,
        )
        observations.append(
            {
                "identity_id": canary["identity_id"],
                "raw_strain_sha256": item.raw_strain_sha256,
                "clean_strain_sha256": item.clean_strain_sha256,
                "image_sha256": item.image_sha256,
                "teacher_score": float(score),
                "teacher_score_float32_hex": score_hex,
            }
        )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_TRAINING_CANARY_NO_PROTECTED_ACCESS",
        "requested_partition": requested_partition,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "stability_contract_digest": contract["stability_contract_digest"],
        "teacher_fingerprint_digest": contract["teacher_fingerprint"]["fingerprint_digest"],
        "canary_count": len(observations),
        "observations": observations,
        "partition_rows_accessed_before_check": 0,
        "accessed": {name: [] for name in FORBIDDEN_PARTITIONS},
        "failure_action": "STOP_NO_ACCESS_NO_RETUNE",
    }
    receipt = {**body, "stability_receipt_digest": canonical_json_sha256(body)}
    if write_path is not None:
        _write_json(write_path, receipt)
    return receipt


def verify_stability_receipt(
    receipt: Mapping[str, Any], *, contract: Mapping[str, Any]
) -> None:
    _verify_digest(receipt, "stability_receipt_digest", "teacher stability receipt")
    requested_partition = receipt.get("requested_partition")
    if (
        receipt.get("status") != "PASS_TRAINING_CANARY_NO_PROTECTED_ACCESS"
        or requested_partition not in {"baseline", *PROTECTED_PARTITIONS}
        or receipt.get("stability_contract_digest") != contract["stability_contract_digest"]
        or receipt.get("teacher_fingerprint_digest")
        != contract["teacher_fingerprint"]["fingerprint_digest"]
        or receipt.get("partition_rows_accessed_before_check") != 0
        or receipt.get("accessed") != {name: [] for name in FORBIDDEN_PARTITIONS}
        or receipt.get("failure_action") != "STOP_NO_ACCESS_NO_RETUNE"
    ):
        raise ContractError("teacher stability receipt is not a clean pre-access PASS")
    expected_rows = contract["canary_contract"]["rows"]
    observations = receipt.get("observations", [])
    if receipt.get("canary_count") != len(expected_rows) or len(observations) != len(expected_rows):
        raise ContractError("teacher stability receipt canary count changed")
    for canary, observed in zip(expected_rows, observations):
        if observed.get("identity_id") != canary["identity_id"]:
            raise ContractError("teacher stability receipt canary order changed")
        _require_canary_observation(
            canary,
            raw_strain_sha256=str(observed.get("raw_strain_sha256")),
            clean_strain_sha256=str(observed.get("clean_strain_sha256")),
            image_sha256=str(observed.get("image_sha256")),
            teacher_score_float32_hex=str(observed.get("teacher_score_float32_hex")),
        )
