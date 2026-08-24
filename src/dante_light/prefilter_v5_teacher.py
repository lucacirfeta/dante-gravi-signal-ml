"""Provenance-closed native-O4a teacher targets for DANTE-Light v5.

Only frozen training identities are accepted.  Development, confirmation and
O4b are rejected before strain preparation or exact-DANTE scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import (
    ContractError,
    FailClosedReason,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light.executor import DeferredWindow
from src.dante_light.prefilter_v5_protocol import (
    ROOT,
    load_protocol,
    repository_reference,
    sha256_path,
)
from src.dante_light.prefilter_v5_seal import validate_identity_manifest


SCHEMA_VERSION = 1
TARGET_NAME = "native_o4a_novelty_score"
TARGET_SCORE_KEY = "native"
ALLOWED_PARTITION = "training"
ALLOWED_ROLE = "background"
DEFAULT_PROTOCOL = ROOT / "config/dante_light_prefilter_protocol_v5.json"
DEFAULT_SPLIT = ROOT / "config/dante_light_prefilter_splits_v5.json"
DEFAULT_REFERENCE_MANIFEST = ROOT / "config/reference_artifacts.json"
DEFAULT_CONTRACT = ROOT / "config/dante_light_prefilter_v5_teacher_contract.json"


@dataclass(frozen=True, slots=True)
class PreparedTeacherInput:
    image: np.ndarray
    clean_strain: np.ndarray
    raw_strain_sha256: str
    clean_strain_sha256: str
    image_sha256: str
    timings: dict[str, float]


def _repository_digest_candidates(root: Path, path: Path) -> set[str]:
    candidates = {sha256_path(path)} if path.is_file() else set()
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        candidates.add(
            hashlib.sha256(
                subprocess.check_output(
                    ["git", "show", f"HEAD:{relative}"],
                    cwd=root,
                    stderr=subprocess.DEVNULL,
                )
            ).hexdigest()
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return candidates


def _validate_reference(root: Path, value: Mapping[str, Any], label: str) -> Path:
    if set(value) != {"path", "sha256"}:
        raise ContractError(f"v5 teacher {label} reference is malformed")
    path_text = str(value["path"])
    if not path_text or Path(path_text).is_absolute() or "\\" in path_text:
        raise ContractError(f"v5 teacher {label} reference is not portable")
    path = root / path_text
    if str(value["sha256"]) not in _repository_digest_candidates(root, path):
        raise ContractError(f"v5 teacher {label} reference hash mismatch")
    return path


def _load_complete_split(
    *, root: Path, split_path: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    header = json.loads(split_path.read_text(encoding="utf-8"))
    declared = header.get("manifest_digest")
    if declared != canonical_json_sha256(
        {key: value for key, value in header.items() if key != "manifest_digest"}
    ):
        raise ContractError("v5 teacher split header digest mismatch")
    entries_path = _validate_reference(root, header["entries_reference"], "split entries")
    rows = [
        json.loads(line)
        for line in entries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    complete = dict(header)
    complete.pop("entries_reference")
    complete["rows"] = rows
    complete["manifest_digest"] = canonical_json_sha256(
        {key: value for key, value in complete.items() if key != "manifest_digest"}
    )
    validate_identity_manifest(complete)
    return header, rows


def load_training_rows(
    *, root: Path = ROOT, split_path: Path = DEFAULT_SPLIT
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return only the authorized training background identities."""

    header, rows = _load_complete_split(root=root, split_path=split_path)
    training = [row for row in rows if row["partition"] == ALLOWED_PARTITION]
    if not training:
        raise ContractError("v5 teacher training partition is empty")
    if any(
        row["role"] != ALLOWED_ROLE
        or row["source"]["run"] != "O4A"
        or row["window"]["run"] != "O4A"
        for row in training
    ):
        raise ContractError("v5 teacher training partition is contaminated")
    training.sort(
        key=lambda row: (
            row["detector"],
            int(row["stratum"]["block_index"]),
            int(row["stratum"]["window_index"]),
            row["window"]["window_id"],
        )
    )
    if len({row["window"]["window_id"] for row in training}) != len(training):
        raise ContractError("v5 teacher training identities are duplicated")
    return header, training


def build_teacher_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Build the author-approved training-only native-O4a teacher contract."""

    protocol = load_protocol(root / DEFAULT_PROTOCOL.relative_to(ROOT), root=root)
    split_path = root / DEFAULT_SPLIT.relative_to(ROOT)
    split, training = load_training_rows(root=root, split_path=split_path)
    representation = RepresentationContract.from_reference_manifest(
        root / DEFAULT_REFERENCE_MANIFEST.relative_to(ROOT)
    )
    replay_ids = []
    for detector in representation_detectors(protocol):
        replay_ids.append(
            next(row["window"]["window_id"] for row in training if row["detector"] == detector)
        )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_TRAINING_ONLY",
        "protocol_reference": repository_reference(
            root, root / DEFAULT_PROTOCOL.relative_to(ROOT)
        ),
        "split_header_reference": repository_reference(root, split_path),
        "split_entries_reference": dict(split["entries_reference"]),
        "reference_manifest_reference": repository_reference(
            root, root / DEFAULT_REFERENCE_MANIFEST.relative_to(ROOT)
        ),
        "representation": representation.to_dict(),
        "teacher": {
            "target_name": TARGET_NAME,
            "decision_score_key": TARGET_SCORE_KEY,
            "target_index_artifact_id": "o4a_native_q4_64_k1216",
            "target_index_sha256": representation.native_index_sha256,
            "encoder_index_artifact_id": "o3b_production_k275",
            "encoder_index_sha256": representation.primary_index_sha256,
            "engine": "shared_encoder_score_only",
            "output_mode": "score_only",
            "threshold_applied": False,
            "physical_truth_label": False,
            "primary_o3b_score_as_target": False,
            "standardization": "per_detector_mean_and_std_fit_on_training_only",
        },
        "access_boundary": {
            "allowed_partitions": [ALLOWED_PARTITION],
            "allowed_roles": [ALLOWED_ROLE],
            "development_rows_allowed": False,
            "confirmation_rows_allowed": False,
            "o4b_rows_allowed": False,
            "morphology_labels_used": False,
        },
        "training_identity_count": len(training),
        "training_identity_digest": canonical_json_sha256(
            [row["window"]["window_id"] for row in training]
        ),
        "replay_sample_window_ids": replay_ids,
        "cache": {
            "environment_alias": "DANTE_V5_CACHE_ROOT",
            "default_windows_location": "E:/dante_cache/dante_light/prefilter_l4_v5_training",
            "incompatible_run_reuse_allowed": False,
            "canonical_whitened_float32_cached": True,
            "large_ledgers_committed_to_git": False,
        },
        "scientific_boundary": {
            "distils_exact_runtime_routing_score": True,
            "does_not_establish_physical_truth": True,
            "does_not_authorize_development_confirmation_o4b_or_routing": True,
            "outcome_fields_accessed_at_freeze": [],
        },
    }
    return {**body, "teacher_contract_digest": canonical_json_sha256(body)}


def representation_detectors(protocol: Mapping[str, Any]) -> tuple[str, ...]:
    detectors = tuple(str(value) for value in protocol["approved_design"]["signal"]["detectors"])
    if detectors != ("H1", "L1"):
        raise ContractError("v5 teacher detector contract changed")
    return detectors


def validate_teacher_contract(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("teacher_contract_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("v5 teacher contract self-digest mismatch")
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("status") != "FROZEN_TRAINING_ONLY":
        raise ContractError("v5 teacher contract status/schema mismatch")
    protocol_path = _validate_reference(root, payload["protocol_reference"], "protocol")
    protocol = load_protocol(protocol_path, root=root)
    split_path = _validate_reference(root, payload["split_header_reference"], "split header")
    _validate_reference(root, payload["split_entries_reference"], "split entries")
    _validate_reference(root, payload["reference_manifest_reference"], "reference manifest")
    split, rows = load_training_rows(root=root, split_path=split_path)
    if payload["split_entries_reference"] != split["entries_reference"]:
        raise ContractError("v5 teacher split entries reference changed")
    representation = RepresentationContract.from_reference_manifest(
        root / payload["reference_manifest_reference"]["path"]
    )
    if payload["representation"] != representation.to_dict():
        raise ContractError("v5 teacher representation changed")
    teacher = payload["teacher"]
    if (
        teacher.get("target_name") != TARGET_NAME
        or teacher.get("decision_score_key") != TARGET_SCORE_KEY
        or teacher.get("target_index_sha256") != representation.native_index_sha256
        or teacher.get("engine") != "shared_encoder_score_only"
        or teacher.get("output_mode") != "score_only"
        or teacher.get("threshold_applied") is not False
        or teacher.get("primary_o3b_score_as_target") is not False
    ):
        raise ContractError("v5 teacher target is not the approved native O4a score")
    boundary = payload["access_boundary"]
    if (
        boundary.get("allowed_partitions") != [ALLOWED_PARTITION]
        or boundary.get("allowed_roles") != [ALLOWED_ROLE]
        or any(
            boundary.get(field) is not False
            for field in (
                "development_rows_allowed",
                "confirmation_rows_allowed",
                "o4b_rows_allowed",
                "morphology_labels_used",
            )
        )
    ):
        raise ContractError("v5 teacher access boundary was widened")
    if payload["training_identity_count"] != len(rows):
        raise ContractError("v5 teacher identity count changed")
    if payload["training_identity_digest"] != canonical_json_sha256(
        [row["window"]["window_id"] for row in rows]
    ):
        raise ContractError("v5 teacher identity digest changed")
    expected_replay = [
        next(row["window"]["window_id"] for row in rows if row["detector"] == detector)
        for detector in representation_detectors(protocol)
    ]
    if payload["replay_sample_window_ids"] != expected_replay:
        raise ContractError("v5 teacher replay identities changed")
    return dict(value)


def load_teacher_contract(
    path: Path = DEFAULT_CONTRACT, *, root: Path = ROOT
) -> dict[str, Any]:
    return validate_teacher_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def read_contiguous_teacher_span(
    entries: Sequence[tuple[float, float, Path]],
    *,
    gps_start: float,
    gps_end: float,
    sample_rate_hz: int,
) -> object | None:
    """Join a padded teacher request across contiguous immutable raw files."""

    from gwpy.timeseries import TimeSeries, TimeSeriesList

    overlapping = sorted(
        (
            (float(start), float(end), Path(path))
            for start, end, path in entries
            if float(end) > gps_start and float(start) < gps_end
        ),
        key=lambda item: (item[0], item[1], str(item[2])),
    )
    if len(overlapping) < 2:
        return None
    selected = []
    covered_until = gps_start
    tolerance = 1.0 / float(sample_rate_hz)
    for start, end, path in overlapping:
        if end <= covered_until + tolerance:
            continue
        if start > covered_until + tolerance:
            return None
        selected.append((start, end, path))
        covered_until = max(covered_until, end)
        if covered_until >= gps_end - tolerance:
            break
    if len(selected) < 2 or covered_until < gps_end - tolerance:
        return None
    pieces = TimeSeriesList()
    for start, end, path in selected:
        piece = TimeSeries.read(path).crop(max(start, gps_start), min(end, gps_end))
        if int(round(float(piece.sample_rate.value))) != sample_rate_hz:
            piece = piece.resample(sample_rate_hz)
        pieces.append(piece)
    try:
        joined = pieces.join(gap="raise").crop(gps_start, gps_end)
    except (ValueError, RuntimeError):
        return None
    actual_start = float(joined.t0.value)
    actual_end = actual_start + float(joined.duration.value)
    if actual_start > gps_start + tolerance or actual_end < gps_end - tolerance:
        return None
    return joined


def _fetch_teacher_strain(
    window: WindowIdentity,
    *,
    representation: RepresentationContract,
    local_only: bool,
) -> object:
    from src.core import data_loader

    start = window.gps_start - representation.whitening_pad_s
    end = window.gps_start + window.duration_s + representation.whitening_pad_s
    try:
        return data_loader.fetch_strain_data(
            window.detector,
            start,
            end,
            sample_rate=representation.sample_rate_hz,
            local_only=local_only,
            remote_only=False,
        )
    except RuntimeError as exc:
        if not local_only:
            raise
        for directory in data_loader._DATA_DIRECTORIES:
            if not directory.exists():
                continue
            stitched = read_contiguous_teacher_span(
                data_loader._local_block_index(directory, window.detector),
                gps_start=start,
                gps_end=end,
                sample_rate_hz=representation.sample_rate_hz,
            )
            if stitched is not None:
                return stitched
        raise DeferredWindow(FailClosedReason.DEPENDENCY_UNAVAILABLE) from exc


def prepare_teacher_input(
    window: WindowIdentity,
    *,
    representation: RepresentationContract,
    local_only: bool = True,
) -> PreparedTeacherInput:
    """Prepare the exact canonical image plus cached float32 student input."""

    import matplotlib.pyplot as plt

    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )

    timings: dict[str, float] = {}
    start = window.gps_start
    end = start + window.duration_s
    began = time.perf_counter()
    strain = _fetch_teacher_strain(
        window, representation=representation, local_only=local_only
    )
    timings["data_read_s"] = time.perf_counter() - began
    sample_rate_hz = float(strain.sample_rate.value)
    tolerance = 1.0 / sample_rate_hz
    actual_start = float(strain.t0.value)
    actual_end = actual_start + float(strain.duration.value)
    pad = representation.whitening_pad_s
    if (
        int(round(sample_rate_hz)) != representation.sample_rate_hz
        or actual_start > start - pad + tolerance
        or actual_end < end + pad - tolerance
        or not np.isfinite(strain.value).all()
    ):
        raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
    raw_values = np.ascontiguousarray(strain.value)
    raw_sha256 = hashlib.sha256(raw_values.tobytes()).hexdigest()
    began = time.perf_counter()
    whitened, padding = whiten_context(strain, start, end, pad=pad)
    clean = extract_clean_subwindow(whitened, start, end)
    timings["whitening_s"] = time.perf_counter() - began
    if (
        float(padding.get("effective_left", 0.0)) + tolerance < pad
        or float(padding.get("effective_right", 0.0)) + tolerance < pad
        or abs(float(clean.duration.value) - window.duration_s) > tolerance
    ):
        raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
    clean_values = np.ascontiguousarray(clean.value, dtype=np.float32)
    expected_samples = int(round(representation.sample_rate_hz * representation.analysis_duration_s))
    if clean_values.shape != (expected_samples,) or not np.isfinite(clean_values).all():
        raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
    began = time.perf_counter()
    spectrogram = generate_qtransform(
        clean,
        save_path=None,
        cmap=representation.colormap,
        qrange=representation.query_qrange,
        frange=representation.frequency_range_hz,
        output_size=representation.image_shape[:2],
    )
    timings["q_transform_s"] = time.perf_counter() - began
    began = time.perf_counter()
    rgba = plt.get_cmap(representation.colormap)(spectrogram)
    image = np.ascontiguousarray((rgba[:, :, :3] * 255).astype(np.uint8))
    timings["rendering_s"] = time.perf_counter() - began
    if image.shape != representation.image_shape or not np.isfinite(image).all():
        raise DeferredWindow(FailClosedReason.NONFINITE_INPUT)
    return PreparedTeacherInput(
        image=image,
        clean_strain=clean_values,
        raw_strain_sha256=raw_sha256,
        clean_strain_sha256=hashlib.sha256(clean_values.tobytes()).hexdigest(),
        image_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
        timings={key: float(value) for key, value in timings.items()},
    )


class ExactNativeTeacher:
    """Exact shared-encoder DANTE scorer with native O4a output only."""

    def __init__(
        self,
        *,
        root: Path = ROOT,
        representation: RepresentationContract,
        device: str | None = None,
    ) -> None:
        from src.core.patch_scorer import PatchScorer

        manifest_path = root / "config/reference_artifacts.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_root = (manifest_path.parent / str(manifest["artifact_root"])).resolve()
        primary_path = artifact_root / manifest["reference_indices"]["o3b_production_k275"]["path"]
        native_path = artifact_root / manifest["reference_indices"]["o4a_native_q4_64_k1216"]["path"]
        self.primary = PatchScorer(
            primary_path,
            device=device,
            k=representation.top_k,
            expected_sha256=representation.primary_index_sha256,
            artifact_manifest_path=manifest_path,
        )
        self.native = PatchScorer(
            native_path,
            device=device,
            k=representation.top_k,
            expected_sha256=representation.native_index_sha256,
            artifact_manifest_path=manifest_path,
            model=self.primary.model,
        )
        self.representation = representation

    def score(self, images: Sequence[np.ndarray]) -> tuple[list[float], dict[str, float]]:
        timings: dict[str, float] = {}
        result = self.primary.score_multi_index(
            list(images),
            {TARGET_SCORE_KEY: (self.native, 1.0)},
            output_modes={TARGET_SCORE_KEY: "score_only"},
            timings=timings,
        )
        scores = [float(row["novelty_score"]) for row in result[TARGET_SCORE_KEY]]
        if len(scores) != len(images) or not np.isfinite(scores).all():
            raise ContractError("v5 native teacher returned invalid scores")
        return scores, {key: float(value) for key, value in timings.items()}


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    temporary.replace(path)


def _atomic_npz(path: Path, **arrays: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        np.savez(stream, **arrays)
    temporary.replace(path)


def teacher_run_key(
    contract: Mapping[str, Any], *, code_references: Mapping[str, Mapping[str, str]]
) -> str:
    required = {
        "artifact_manifest",
        "core_preprocessor",
        "core_utils",
        "dante_preprocessing",
        "data_loader",
        "encoder",
        "ledger_builder",
        "model_loader",
        "patch_scorer",
        "runtime_config",
        "teacher_implementation",
    }
    if set(code_references) != required:
        raise ContractError("v5 teacher run key lacks exact-path code references")
    return canonical_json_sha256(
        {
            "teacher_contract_digest": contract["teacher_contract_digest"],
            "training_identity_digest": contract["training_identity_digest"],
            "representation_contract_sha256": contract["representation"]["contract_sha256"],
            "code_references": dict(code_references),
        }
    )


def _validate_cached_block(
    path: Path,
    *,
    run_key: str,
    expected_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    declared = payload.pop("block_digest", None)
    if declared != canonical_json_sha256(payload):
        raise ContractError(f"v5 teacher cached block digest mismatch: {path.name}")
    payload["block_digest"] = declared
    if payload.get("status") != "COMPLETE" or payload.get("run_key") != run_key:
        raise ContractError(f"v5 teacher cached block is stale: {path.name}")
    expected_ids = [row["window"]["window_id"] for row in expected_rows]
    actual_ids = [row["window"]["window_id"] for row in payload["rows"]]
    if actual_ids != expected_ids:
        raise ContractError(f"v5 teacher cached block identities changed: {path.name}")
    shard = path.parent / payload["strain_shard"]["path"]
    if not shard.is_file() or sha256_path(shard) != payload["strain_shard"]["sha256"]:
        raise ContractError(f"v5 teacher cached strain shard mismatch: {path.name}")
    with np.load(shard, allow_pickle=False) as data:
        strain = np.asarray(data["clean_strain"])
        window_ids = np.asarray(data["window_ids"]).astype(str).tolist()
    if strain.dtype != np.float32 or strain.shape[0] != len(expected_rows):
        raise ContractError(f"v5 teacher cached strain shard shape changed: {path.name}")
    if window_ids != expected_ids:
        raise ContractError(f"v5 teacher cached strain shard identity mismatch: {path.name}")
    for index, row in enumerate(payload["rows"]):
        clean_digest = hashlib.sha256(
            np.ascontiguousarray(strain[index], dtype=np.float32).tobytes()
        ).hexdigest()
        if clean_digest != row["clean_strain_sha256"]:
            raise ContractError(f"v5 teacher cached clean strain mismatch: {path.name}")
        score = float(row["teacher_target"][TARGET_NAME])
        score_hex = np.float32(score).tobytes().hex()
        if (
            not np.isfinite(score)
            or row["teacher_target"].get("score_key") != TARGET_SCORE_KEY
            or row["teacher_target"].get("name") != TARGET_NAME
            or row["teacher_target"].get("float32_hex") != score_hex
        ):
            raise ContractError(f"v5 teacher cached score invalid: {path.name}")
    return payload


def build_teacher_ledger(
    *,
    root: Path,
    contract: Mapping[str, Any],
    cache_root: Path,
    compact_artifact_path: Path,
    code_references: Mapping[str, Mapping[str, str]],
    prepare: Callable[[WindowIdentity], PreparedTeacherInput],
    score: Callable[[Sequence[np.ndarray]], tuple[list[float], dict[str, float]]],
    workers: int,
    limit_blocks: int | None = None,
) -> dict[str, Any]:
    """Build resumable block-atomic targets and cached whitened strain."""

    checked = validate_teacher_contract(contract, root=root)
    if workers < 1 or workers > 16:
        raise ContractError("v5 teacher workers must be in [1,16]")
    if limit_blocks is not None and limit_blocks <= 0:
        raise ContractError("v5 teacher smoke block limit must be positive")
    for label, reference in code_references.items():
        _validate_reference(root, reference, label)
    run_key = teacher_run_key(checked, code_references=code_references)
    run_dir = cache_root / f"teacher_{run_key}"
    block_dir = run_dir / "blocks"
    block_dir.mkdir(parents=True, exist_ok=True)
    header, rows = load_training_rows(root=root)
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["detector"]), int(row["stratum"]["block_index"]))
        grouped.setdefault(key, []).append(row)
    ordered_groups = sorted(grouped.items())
    expected_blocks = len(ordered_groups)
    if limit_blocks is not None:
        ordered_groups = ordered_groups[:limit_blocks]
    run_header = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "teacher_contract_digest": checked["teacher_contract_digest"],
        "training_identity_digest": checked["training_identity_digest"],
        "code_references": dict(code_references),
        "cache_root_semantics": "DANTE_V5_CACHE_ROOT/versioned_by_full_run_key",
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
    }
    run_header_path = run_dir / "run_identity.json"
    if run_header_path.exists():
        if json.loads(run_header_path.read_text(encoding="utf-8")) != run_header:
            raise ContractError("v5 teacher cache run identity collision")
    else:
        _atomic_json(run_header_path, run_header)

    block_payloads: list[dict[str, Any]] = []
    for (detector, block_index), block_rows in ordered_groups:
        block_rows.sort(
            key=lambda row: (
                int(row["stratum"]["window_index"]), row["window"]["window_id"]
            )
        )
        block_name = f"{detector}_{block_index}"
        block_path = block_dir / f"{block_name}.json"
        if block_path.exists():
            block_payloads.append(
                _validate_cached_block(
                    block_path, run_key=run_key, expected_rows=block_rows
                )
            )
            continue

        prepared_by_id: dict[str, PreparedTeacherInput] = {}
        failures = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(prepare, WindowIdentity.from_dict(row["window"])): row
                for row in block_rows
            }
            for future in as_completed(futures):
                row = futures[future]
                window_id = row["window"]["window_id"]
                try:
                    prepared_by_id[window_id] = future.result()
                except Exception as exc:
                    failures.append(
                        {
                            "window_id": window_id,
                            "exception_type": type(exc).__name__,
                            "reason": (
                                exc.reason.value
                                if isinstance(exc, DeferredWindow)
                                else str(exc)
                            ),
                        }
                    )
        if failures:
            failure = {
                "schema_version": SCHEMA_VERSION,
                "status": "NOT_READY_INCOMPLETE_TEACHER_INPUT",
                "run_key": run_key,
                "detector": detector,
                "block_index": block_index,
                "failures": sorted(failures, key=lambda row: row["window_id"]),
                "development_rows_accessed": [],
                "confirmation_rows_accessed": [],
                "o4b_rows_accessed": [],
            }
            _atomic_json(run_dir / "failure.json", failure)
            raise ContractError(
                f"v5 teacher input failed for {len(failures)} windows in {block_name}"
            )
        prepared = [prepared_by_id[row["window"]["window_id"]] for row in block_rows]
        scores, score_timings = score([item.image for item in prepared])
        if len(scores) != len(block_rows):
            raise ContractError("v5 teacher scorer changed block cardinality")
        strain = np.stack([item.clean_strain for item in prepared]).astype(
            np.float32, copy=False
        )
        window_ids = np.asarray(
            [row["window"]["window_id"] for row in block_rows], dtype="U32"
        )
        shard_path = block_dir / f"{block_name}_clean_strain.npz"
        _atomic_npz(shard_path, clean_strain=strain, window_ids=window_ids)
        result_rows = []
        for row, item, native_score in zip(block_rows, prepared, scores, strict=True):
            result_rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "window": row["window"],
                    "source_id": row["source"]["source_id"],
                    "block_index": block_index,
                    "raw_strain_sha256": item.raw_strain_sha256,
                    "clean_strain_sha256": item.clean_strain_sha256,
                    "image_sha256": item.image_sha256,
                    "teacher_target": {
                        "name": TARGET_NAME,
                        "score_key": TARGET_SCORE_KEY,
                        TARGET_NAME: float(native_score),
                        "float32_hex": np.float32(native_score).tobytes().hex(),
                    },
                    "preparation_timings_s": item.timings,
                }
            )
        block_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "COMPLETE",
            "run_key": run_key,
            "detector": detector,
            "block_index": block_index,
            "teacher_contract_digest": checked["teacher_contract_digest"],
            "strain_shard": {
                "path": shard_path.name,
                "sha256": sha256_path(shard_path),
                "dtype": "float32",
                "shape": list(strain.shape),
            },
            "score_timings_s": score_timings,
            "rows": result_rows,
            "development_rows_accessed": [],
            "confirmation_rows_accessed": [],
            "o4b_rows_accessed": [],
        }
        block_payload = {
            **block_body,
            "block_digest": canonical_json_sha256(block_body),
        }
        _atomic_json(block_path, block_payload)
        block_payloads.append(block_payload)

    smoke_only = limit_blocks is not None
    score_values: dict[str, list[float]] = {"H1": [], "L1": []}
    row_count = 0
    block_references = []
    for payload in block_payloads:
        row_count += len(payload["rows"])
        score_values[payload["detector"]].extend(
            float(row["teacher_target"][TARGET_NAME]) for row in payload["rows"]
        )
        block_path = block_dir / f"{payload['detector']}_{payload['block_index']}.json"
        block_references.append(
            {
                "path": block_path.relative_to(run_dir).as_posix(),
                "sha256": sha256_path(block_path),
            }
        )
    summary_body = {
        "schema_version": SCHEMA_VERSION,
        "status": "SMOKE_ONLY" if smoke_only else "COMPLETE",
        "run_key": run_key,
        "teacher_contract_digest": checked["teacher_contract_digest"],
        "training_identity_digest": checked["training_identity_digest"],
        "split_manifest_digest": header["manifest_digest"],
        "target_name": TARGET_NAME,
        "target_score_key": TARGET_SCORE_KEY,
        "target_index_sha256": checked["representation"]["native_index_sha256"],
        "row_count": row_count,
        "expected_full_row_count": checked["training_identity_count"],
        "block_count": len(block_payloads),
        "expected_full_block_count": expected_blocks,
        "score_descriptives_training_only": {
            detector: {
                "n": len(values),
                "mean": float(np.mean(values)) if values else None,
                "std_population": float(np.std(values, ddof=0)) if values else None,
                "minimum": float(np.min(values)) if values else None,
                "maximum": float(np.max(values)) if values else None,
            }
            for detector, values in score_values.items()
        },
        "block_references": block_references,
        "code_references": dict(code_references),
        "cache_location": {
            "environment_alias": "DANTE_V5_CACHE_ROOT",
            "run_subdirectory": run_dir.name,
        },
        "teacher_scores_used_for_training": False,
        "student_training_executed": False,
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
    }
    summary = {
        **summary_body,
        "artifact_digest": canonical_json_sha256(summary_body),
    }
    cache_summary_path = run_dir / "teacher_ledger_summary_v5.json"
    _atomic_json(cache_summary_path, summary)
    if not smoke_only:
        if row_count != checked["training_identity_count"] or len(block_payloads) != expected_blocks:
            raise ContractError("v5 teacher full ledger is incomplete")
        _atomic_json(compact_artifact_path, summary)
    return summary


def default_cache_root() -> Path:
    configured = os.environ.get("DANTE_V5_CACHE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path("E:/dante_cache/dante_light/prefilter_l4_v5_training").resolve()


def verify_teacher_ledger_summary(
    summary: Mapping[str, Any],
    *,
    root: Path,
    contract: Mapping[str, Any],
    cache_root: Path,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Recompute ledger identities, hashes and cached block contents."""

    checked = validate_teacher_contract(contract, root=root)
    payload = dict(summary)
    declared = payload.pop("artifact_digest", None)
    if declared != canonical_json_sha256(payload):
        raise ContractError("v5 teacher summary self-digest mismatch")
    payload["artifact_digest"] = declared
    allowed_status = {"COMPLETE"} if require_complete else {"COMPLETE", "SMOKE_ONLY"}
    if payload.get("status") not in allowed_status:
        raise ContractError("v5 teacher ledger is not complete")
    for label, reference in payload["code_references"].items():
        _validate_reference(root, reference, label)
    expected_run_key = teacher_run_key(
        checked, code_references=payload["code_references"]
    )
    if payload.get("run_key") != expected_run_key:
        raise ContractError("v5 teacher summary run key mismatch")
    if (
        payload.get("target_name") != TARGET_NAME
        or payload.get("target_score_key") != TARGET_SCORE_KEY
        or payload.get("target_index_sha256")
        != checked["representation"]["native_index_sha256"]
        or payload.get("teacher_contract_digest")
        != checked["teacher_contract_digest"]
        or payload.get("training_identity_digest")
        != checked["training_identity_digest"]
    ):
        raise ContractError("v5 teacher summary target/provenance mismatch")
    for field in (
        "development_rows_accessed",
        "confirmation_rows_accessed",
        "o4b_rows_accessed",
    ):
        if payload.get(field) != []:
            raise ContractError(f"v5 teacher ledger accessed forbidden {field}")
    if payload.get("teacher_scores_used_for_training") is not False or payload.get("student_training_executed") is not False:
        raise ContractError("v5 teacher ledger silently opened student training")
    run_subdirectory = str(payload["cache_location"]["run_subdirectory"])
    if run_subdirectory != f"teacher_{expected_run_key}" or Path(run_subdirectory).name != run_subdirectory:
        raise ContractError("v5 teacher cache subdirectory is not run-key bound")
    run_dir = (cache_root / run_subdirectory).resolve()
    if not run_dir.is_relative_to(cache_root.resolve()):
        raise ContractError("v5 teacher cache path escaped its declared root")
    _header, training_rows = load_training_rows(root=root)
    expected_by_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in training_rows:
        key = (str(row["detector"]), int(row["stratum"]["block_index"]))
        expected_by_key.setdefault(key, []).append(row)
    for rows in expected_by_key.values():
        rows.sort(
            key=lambda row: (
                int(row["stratum"]["window_index"]), row["window"]["window_id"]
            )
        )
    seen_ids: list[str] = []
    seen_keys: list[tuple[str, int]] = []
    for reference in payload["block_references"]:
        relative = str(reference["path"])
        block_path = (run_dir / relative).resolve()
        if (
            Path(relative).is_absolute()
            or "\\" in relative
            or not block_path.is_relative_to(run_dir)
            or sha256_path(block_path) != reference["sha256"]
        ):
            raise ContractError("v5 teacher block reference mismatch")
        raw = json.loads(block_path.read_text(encoding="utf-8"))
        key = (str(raw["detector"]), int(raw["block_index"]))
        if key not in expected_by_key or key in seen_keys:
            raise ContractError("v5 teacher block identity is unexpected or duplicated")
        block = _validate_cached_block(
            block_path, run_key=expected_run_key, expected_rows=expected_by_key[key]
        )
        seen_keys.append(key)
        seen_ids.extend(row["window"]["window_id"] for row in block["rows"])
    if payload["block_count"] != len(seen_keys) or payload["row_count"] != len(seen_ids):
        raise ContractError("v5 teacher summary counts do not match cached blocks")
    if len(seen_ids) != len(set(seen_ids)):
        raise ContractError("v5 teacher ledger repeats a training identity")
    if payload["status"] == "COMPLETE":
        expected_ids = [row["window"]["window_id"] for row in training_rows]
        if (
            payload["row_count"] != checked["training_identity_count"]
            or payload["block_count"] != len(expected_by_key)
            or seen_ids != expected_ids
        ):
            raise ContractError("v5 teacher complete ledger is incomplete or reordered")
    return {
        "status": "PASS_COMPLETE" if payload["status"] == "COMPLETE" else "PASS_SMOKE_ONLY",
        "run_key": expected_run_key,
        "row_count": len(seen_ids),
        "block_count": len(seen_keys),
        "target": TARGET_NAME,
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
    }
