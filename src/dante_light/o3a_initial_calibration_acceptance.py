"""Block-atomic O3a initial-calibration raw acceptance and seed scoring.

This is the first O3a stage allowed to open strain samples.  It evaluates the
already frozen, outcome-blind rank-zero blocks only.  Score magnitude and
class never participate in acceptance, and this module does not fit a
threshold or inspect candidate outcomes.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import h5py
import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_initial_calibration import (
    CONTRACT_REL as SELECTOR_REL,
    PLAN_REL as CALIBRATION_PLAN_REL,
    load_initial_calibration_plan,
    load_selector_contract,
)
from src.dante_light.o3a_native_contract import (
    ROOT,
    RUNTIME_REL,
    load_runtime_contract,
    load_scope_contract,
)
from src.dante_light.o3a_raw_acquisition import (
    ACQUISITION_REL,
    SAMPLE_RATE_HZ,
    load_acquisition_plan,
)
from src.dante_light.o3a_scale_adequacy import (
    STAGE_CONTRACT_REL,
    load_stage_contract,
)


CONTRACT_REL = "config/dante_o3a_initial_calibration_acceptance_v1.json"
IMPLEMENTATION_REL = "src/dante_light/o3a_initial_calibration_acceptance.py"
FREEZE_ENTRYPOINT_REL = (
    "scripts/freeze_dante_o3a_initial_calibration_acceptance.py"
)
RUN_ENTRYPOINT_REL = "scripts/run_dante_o3a_initial_calibration_acceptance.py"
PARITY_METHOD_REL = "config/dante_light_o4a_v1_parity_contract.json"
REFERENCE_MANIFEST_REL = "config/reference_artifacts.json"
PREPROCESSOR_REL = "src/core/preprocessor.py"
PATCH_SCORER_REL = "src/core/patch_scorer.py"
MODEL_LOADER_REL = "src/core/model_loader.py"
ENCODER_REL = "src/core/encoder.py"
PIPELINE_CONFIG_REL = "config.yaml"
SCHEMA_VERSION = 1
DEFAULT_EXTERNAL_ROOT = Path(
    "/mnt/e/dante_cache/dante_light/o3a_native_v1"
)
DEFAULT_RAW_ROOT = Path("/mnt/e/o3a")
DEFAULT_WORKERS = 8
DEFAULT_ENCODER_BATCH_SIZE = 8
DEFAULT_MAX_PREPROCESS_IN_FLIGHT = 16


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _binding(root: Path, relative: str, **extra: Any) -> dict[str, Any]:
    return {
        "path": relative,
        "sha256": file_sha256(root / relative),
        **extra,
    }


def _implementation_sources(root: Path) -> dict[str, str]:
    relatives = (
        IMPLEMENTATION_REL,
        FREEZE_ENTRYPOINT_REL,
        RUN_ENTRYPOINT_REL,
        PREPROCESSOR_REL,
        PATCH_SCORER_REL,
        MODEL_LOADER_REL,
        ENCODER_REL,
        PIPELINE_CONFIG_REL,
    )
    return {relative: file_sha256(root / relative) for relative in relatives}


def build_acceptance_contract(
    *, root: Path = ROOT, raw_download_summary: Path
) -> dict[str, Any]:
    selector = load_selector_contract(root=root)
    plan = load_initial_calibration_plan(root=root)
    acquisition = load_acquisition_plan(root=root)
    stage = load_stage_contract(root=root)
    native = load_scope_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=False)
    summary = json.loads(raw_download_summary.read_text(encoding="utf-8"))
    summary_body = {
        key: value for key, value in summary.items() if key != "artifact_digest"
    }
    if (
        summary.get("status") != "PASS_VERIFIED_RAW_DOWNLOAD"
        or summary.get("artifact_digest") != canonical_json_sha256(summary_body)
        or int(summary.get("verified_file_count", -1)) != 726
        or int(summary.get("failure_count", -1)) != 0
    ):
        raise ContractError("O3a raw download summary is not verified complete")
    raw_manifest = Path(str(summary["raw_manifest"]["path"]))
    if not raw_manifest.is_file():
        raise ContractError("O3a verified raw manifest is absent")
    manifest_sha256 = file_sha256(raw_manifest)
    if manifest_sha256 != summary["raw_manifest"]["sha256"]:
        raise ContractError("O3a verified raw manifest hash mismatch")

    parity = json.loads((root / PARITY_METHOD_REL).read_text(encoding="utf-8"))
    representation = parity["representation"]
    primary = native["references"]["initial_source_representation"]
    import yaml

    preprocessing = yaml.safe_load(
        (root / PIPELINE_CONFIG_REL).read_text(encoding="utf-8")
    )["preprocessing"]
    if (
        representation["primary_index_sha256"] != primary["sha256"]
        or int(representation["sample_rate_hz"]) != SAMPLE_RATE_HZ
        or float(representation["analysis_duration_s"])
        != float(selector["selection"]["window_duration_s"])
        or float(representation["whitening_pad_s"])
        != float(selector["selection"]["complete_symmetric_context_s"])
        or list(representation["query_qrange"])
        != list(preprocessing["qrange"])
        or list(representation["frequency_range_hz"])
        != list(preprocessing["frange"])
        or list(representation["image_shape"][:2])
        != list(preprocessing["output_size"])
        or representation["colormap"] != preprocessing["colormap"]
    ):
        raise ContractError("O3a seed representation is not method-parity compatible")
    raw_manifest_relative = raw_manifest.relative_to(raw_manifest.parents[1])
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_O3A_INITIAL_CALIBRATION_RAW_ACCEPTANCE",
        "run": "O3A",
        "parents": {
            "stage_contract": _binding(
                root,
                STAGE_CONTRACT_REL,
                contract_digest=stage["contract_digest"],
            ),
            "selector_contract": _binding(
                root,
                SELECTOR_REL,
                contract_digest=selector["contract_digest"],
            ),
            "initial_calibration_plan": _binding(
                root,
                CALIBRATION_PLAN_REL,
                plan_digest=plan["plan_digest"],
            ),
            "raw_acquisition_plan": _binding(
                root,
                ACQUISITION_REL,
                acquisition_digest=acquisition["acquisition_digest"],
            ),
            "native_scope_contract": _binding(
                root,
                "config/dante_o3a_native_v1_contract.json",
                contract_digest=native["contract_digest"],
            ),
            "canonical_runtime": _binding(
                root,
                RUNTIME_REL,
                contract_digest=runtime["contract_digest"],
                environment_digest=runtime["runtime_environment"][
                    "environment_digest"
                ],
            ),
        },
        "verified_raw_input": {
            "download_run_key": summary["run_key"],
            "download_summary_path": str(raw_download_summary),
            "download_summary_sha256": file_sha256(raw_download_summary),
            "download_artifact_digest": summary["artifact_digest"],
            "manifest_relative_to_raw_root": raw_manifest_relative.as_posix(),
            "manifest_sha256": manifest_sha256,
            "verified_file_count": int(summary["verified_file_count"]),
        },
        "method_parity": {
            "source": _binding(
                root,
                PARITY_METHOD_REL,
                contract_digest=parity["contract_digest"],
            ),
            "sample_rate_hz": int(representation["sample_rate_hz"]),
            "analysis_duration_s": float(
                representation["analysis_duration_s"]
            ),
            "whitening_pad_s": float(representation["whitening_pad_s"]),
            "bandpass_hz": [
                float(preprocessing["f_low"]),
                float(preprocessing["f_high"]),
            ],
            "query_qrange": list(representation["query_qrange"]),
            "frequency_range_hz": list(
                representation["frequency_range_hz"]
            ),
            "image_shape": list(representation["image_shape"]),
            "colormap": representation["colormap"],
            "top_k": int(representation["top_k"]),
            "primary_index": {
                "artifact_id": primary["artifact_id"],
                "path": primary["path"],
                "sha256": primary["sha256"],
                "n_centroids": int(primary["n_centroids"]),
            },
        },
        "population": {
            "provisional_block_count": int(
                acquisition["summary"]["provisional_block_count"]
            ),
            "blocks_per_detector": 295,
            "candidate_rows_per_block": 17,
            "evaluated_rows_per_detector": 5_015,
            "point_estimate_rows_per_detector": 5_000,
            "bootstrap_rows_per_detector": 4_998,
            "point_only_tail_rows_per_detector": 2,
        },
        "acceptance": {
            **selector["raw_acceptance"],
            "executed_by_this_freeze": True,
            "fallback_raw_available": False,
            "provisional_failure_action": (
                "STOP_FALLBACK_ACQUISITION_EXTENSION_REQUIRED"
            ),
        },
        "execution": {
            "device": "cuda",
            "workers": DEFAULT_WORKERS,
            "encoder_batch_size": DEFAULT_ENCODER_BATCH_SIZE,
            "max_preprocess_in_flight": DEFAULT_MAX_PREPROCESS_IN_FLIGHT,
            "block_shards_atomic": True,
            "resume_requires_shard_verification": True,
        },
        "implementation_sources": _implementation_sources(root),
        "scientific_boundary": {
            "strain_access_allowed": True,
            "primary_seed_scoring_allowed": True,
            "score_magnitude_or_class_affects_acceptance": False,
            "threshold_fitting_allowed": False,
            "classification_allowed": False,
            "candidate_outcome_review_allowed": False,
            "native_index_selection_allowed": False,
        },
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_acceptance_contract(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("contract_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("O3a raw-acceptance contract self-digest mismatch")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status")
        != "FROZEN_O3A_INITIAL_CALIBRATION_RAW_ACCEPTANCE"
        or value.get("run") != "O3A"
        or value.get("implementation_sources") != _implementation_sources(root)
    ):
        raise ContractError("O3a raw-acceptance contract binding mismatch")
    selector = load_selector_contract(root=root)
    plan = load_initial_calibration_plan(root=root)
    acquisition = load_acquisition_plan(root=root)
    stage = load_stage_contract(root=root)
    native = load_scope_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=False)
    expected_parents = {
        "stage_contract": _binding(
            root,
            STAGE_CONTRACT_REL,
            contract_digest=stage["contract_digest"],
        ),
        "selector_contract": _binding(
            root,
            SELECTOR_REL,
            contract_digest=selector["contract_digest"],
        ),
        "initial_calibration_plan": _binding(
            root,
            CALIBRATION_PLAN_REL,
            plan_digest=plan["plan_digest"],
        ),
        "raw_acquisition_plan": _binding(
            root,
            ACQUISITION_REL,
            acquisition_digest=acquisition["acquisition_digest"],
        ),
        "native_scope_contract": _binding(
            root,
            "config/dante_o3a_native_v1_contract.json",
            contract_digest=native["contract_digest"],
        ),
        "canonical_runtime": _binding(
            root,
            RUNTIME_REL,
            contract_digest=runtime["contract_digest"],
            environment_digest=runtime["runtime_environment"][
                "environment_digest"
            ],
        ),
    }
    if value.get("parents") != expected_parents:
        raise ContractError("O3a raw-acceptance parent binding mismatch")
    parity = json.loads((root / PARITY_METHOD_REL).read_text(encoding="utf-8"))
    method = value.get("method_parity", {})
    if (
        method.get("source")
        != _binding(
            root,
            PARITY_METHOD_REL,
            contract_digest=parity["contract_digest"],
        )
        or method.get("top_k") != parity["representation"]["top_k"]
        or method.get("primary_index", {}).get("sha256")
        != native["references"]["initial_source_representation"]["sha256"]
        or value.get("scientific_boundary", {}).get("threshold_fitting_allowed")
        is not False
        or value.get("scientific_boundary", {}).get("classification_allowed")
        is not False
        or value.get("acceptance", {}).get(
            "score_value_or_class_may_affect_acceptance"
        )
        is not False
    ):
        raise ContractError("O3a raw-acceptance scientific boundary mismatch")
    raw = value.get("verified_raw_input", {})
    if (
        int(raw.get("verified_file_count", -1)) != 726
        or not str(raw.get("manifest_sha256", ""))
        or Path(str(raw.get("manifest_relative_to_raw_root", ""))).is_absolute()
        or ".."
        in Path(str(raw.get("manifest_relative_to_raw_root", ""))).parts
    ):
        raise ContractError("O3a raw-acceptance raw binding is invalid")
    return dict(value)


def load_acceptance_contract(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / CONTRACT_REL
    if not path.is_file():
        raise ContractError("O3a raw-acceptance contract is absent")
    return validate_acceptance_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def write_acceptance_contract(
    *, root: Path = ROOT, raw_download_summary: Path
) -> dict[str, Any]:
    value = build_acceptance_contract(
        root=root, raw_download_summary=raw_download_summary
    )
    _atomic_json(root / CONTRACT_REL, value)
    return value


class RawSliceReader:
    """Read exact manifest-bound slices without loading complete 4096 s frames."""

    def __init__(
        self,
        *,
        manifest_path: Path,
        raw_root: Path,
        detectors: Sequence[str] = ("H1", "L1"),
    ) -> None:
        from src.core.patch_producer import load_frozen_raw_manifest

        self.raw_root = raw_root.resolve()
        self.manifests = {
            detector: load_frozen_raw_manifest(
                manifest_path, raw_root=raw_root, detector=detector
            )
            for detector in detectors
        }

    def read(
        self, *, detector: str, start: float, end: float
    ) -> tuple[np.ndarray, list[dict[str, Any]]]:
        from src.core.patch_producer import (
            IncompleteContextError,
            RawBlockConflictError,
            _verified_sha256,
        )

        manifest = self.manifests[detector]
        blocks = []
        for block_start, block_end, path in manifest.entries:
            if block_end <= start or block_start >= end:
                continue
            resolved = Path(path).resolve()
            digest = _verified_sha256(
                resolved, manifest.expected_sha256.get(resolved)
            )
            blocks.append((float(block_start), float(block_end), resolved, digest))
        blocks.sort(key=lambda item: (item[0], item[1], str(item[2])))
        tolerance = 1.0 / SAMPLE_RATE_HZ
        cursor = float(start)
        selected = []
        while cursor < end - tolerance:
            candidates = [
                item
                for item in blocks
                if item[0] <= cursor + tolerance and item[1] > cursor + tolerance
            ]
            if not candidates:
                raise IncompleteContextError(
                    f"gap in O3a raw coverage at GPS {cursor}"
                )
            chosen = sorted(
                candidates, key=lambda item: (-item[1], item[0], str(item[2]))
            )[0]
            if selected and chosen[:2] == selected[-1][:2]:
                raise RawBlockConflictError("O3a raw slice selection did not advance")
            selected.append(chosen)
            cursor = min(float(end), chosen[1])

        pieces = []
        sources = []
        cursor = float(start)
        for block_start, block_end, path, digest in selected:
            used_start = cursor
            used_end = min(float(end), block_end)
            first = int(round((used_start - block_start) * SAMPLE_RATE_HZ))
            last = int(round((used_end - block_start) * SAMPLE_RATE_HZ))
            expected_shape = (
                int(round((block_end - block_start) * SAMPLE_RATE_HZ)),
            )
            with h5py.File(path, "r") as handle:
                if "strain/Strain" not in handle:
                    raise ContractError(f"O3a strain dataset is absent: {path}")
                dataset = handle["strain/Strain"]
                spacing = float(dataset.attrs.get("Xspacing", 0.0))
                if (
                    tuple(dataset.shape) != expected_shape
                    or abs(spacing - 1.0 / SAMPLE_RATE_HZ) > 1e-15
                ):
                    raise ContractError(f"O3a strain metadata mismatch: {path}")
                values = np.asarray(dataset[first:last], dtype=np.float64)
            if values.shape != (last - first,) or not np.isfinite(values).all():
                raise ContractError(f"O3a raw slice is short or non-finite: {path}")
            pieces.append(values)
            sources.append(
                {
                    "relative_path": path.relative_to(self.raw_root).as_posix(),
                    "sha256": digest,
                    "used_interval_gps": [used_start, used_end],
                }
            )
            cursor = used_end
        joined = np.ascontiguousarray(np.concatenate(pieces), dtype=np.float64)
        expected_samples = int(round((end - start) * SAMPLE_RATE_HZ))
        if joined.shape != (expected_samples,) or not np.isfinite(joined).all():
            raise IncompleteContextError("O3a complete raw context is invalid")
        return joined, sources


def preprocess_context(
    values: np.ndarray,
    *,
    context_start: float,
    detector: str,
    analysis_start: float,
    analysis_end: float,
    pad_s: float,
    qrange: tuple[int, int],
    frange: tuple[int, int],
    output_size: tuple[int, int],
    colormap: str,
) -> np.ndarray:
    """Apply the canonical representation with strict finite-stage checks."""

    import matplotlib.pyplot as plt
    from gwpy.timeseries import TimeSeries

    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )

    if values.ndim != 1 or not np.isfinite(values).all():
        raise ContractError("O3a raw context is non-finite")
    series = TimeSeries(
        values,
        t0=context_start,
        sample_rate=SAMPLE_RATE_HZ,
        name=f"{detector}:GWOSC-4KHZ_R1_STRAIN",
    )
    whitened, pad_info = whiten_context(
        series, analysis_start, analysis_end, pad=pad_s
    )
    tolerance = 1.0 / SAMPLE_RATE_HZ
    if (
        float(pad_info["effective_left"]) < pad_s - tolerance
        or float(pad_info["effective_right"]) < pad_s - tolerance
        or not np.isfinite(np.asarray(whitened.value)).all()
    ):
        raise ContractError("O3a canonical whitening output is invalid")
    clean = extract_clean_subwindow(whitened, analysis_start, analysis_end)
    if (
        len(clean) != int(round((analysis_end - analysis_start) * SAMPLE_RATE_HZ))
        or not np.isfinite(np.asarray(clean.value)).all()
    ):
        raise ContractError("O3a canonical analysis crop is invalid")
    spectrogram = generate_qtransform(
        clean,
        qrange=qrange,
        frange=frange,
        output_size=output_size,
        save_path=None,
        cmap=colormap,
    )
    if spectrogram.shape != output_size or not np.isfinite(spectrogram).all():
        raise ContractError("O3a canonical Q-transform image is invalid")
    rgb = plt.get_cmap(colormap)(spectrogram)[:, :, :3]
    if rgb.shape != (*output_size, 3) or not np.isfinite(rgb).all():
        raise ContractError("O3a canonical RGB image is invalid")
    return np.ascontiguousarray(rgb * 255, dtype=np.uint8)


def _preprocess_task(
    values: np.ndarray,
    context_start: float,
    detector: str,
    analysis_start: float,
    analysis_end: float,
    pad_s: float,
    qrange: tuple[int, int],
    frange: tuple[int, int],
    output_size: tuple[int, int],
    colormap: str,
) -> np.ndarray:
    return preprocess_context(
        values,
        context_start=context_start,
        detector=detector,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
        pad_s=pad_s,
        qrange=qrange,
        frange=frange,
        output_size=output_size,
        colormap=colormap,
    )


def _tokens_are_finite(tokens: Any) -> bool:
    if hasattr(tokens, "isfinite"):
        return bool(tokens.isfinite().all().item())
    return bool(np.isfinite(np.asarray(tokens)).all())


def score_prepared_rows(
    prepared: Sequence[Mapping[str, Any]],
    *,
    scorer: Any,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Score a complete prepared block; score magnitude cannot reject a row."""

    if len(prepared) != 17:
        raise ContractError("O3a block must contain exactly 17 prepared rows")
    output: list[dict[str, Any]] = []
    for offset in range(0, len(prepared), batch_size):
        batch = list(prepared[offset : offset + batch_size])
        images = [np.asarray(row["image"], dtype=np.uint8) for row in batch]
        tokens = scorer.encode_patch_tokens(images)
        if not _tokens_are_finite(tokens):
            raise ContractError("O3a DINOv2 patch tokens are non-finite")
        scored = scorer.score_patch_tokens(
            tokens, 1.0, output_mode="score_only"
        )
        if len(scored) != len(batch):
            raise ContractError("O3a seed scorer returned the wrong row count")
        for row, image, score_row in zip(batch, images, scored):
            score = float(score_row["novelty_score"])
            if not np.isfinite(score):
                raise ContractError("O3a seed score is non-finite")
            output.append(
                {
                    "detector": str(row["detector"]),
                    "analysis_gps_start": int(row["analysis_gps_start"]),
                    "context_interval_gps": list(row["context_interval_gps"]),
                    "raw_sources": list(row["raw_sources"]),
                    "image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                    "primary_score": score,
                    "primary_score_float32_hex": np.float32(score).tobytes().hex(),
                }
            )
    return output


def _block_identity(
    detector: str, block: Mapping[str, Any], stride: int
) -> dict[str, Any]:
    first = int(block["first_gps_start"])
    starts = [first + offset * stride for offset in range(17)]
    return {
        "detector": detector,
        "stratum_index": int(block["stratum_index"]),
        "candidate_rank_in_stratum": int(block["candidate_rank_in_stratum"]),
        "selection_priority_sha256": str(block["selection_priority_sha256"]),
        "analysis_gps_starts": starts,
        "output_row_count": int(block["output_row_count"]),
    }


def _shard_digest(value: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: item for key, item in value.items() if key != "shard_digest"}
    )


def validate_block_shard(
    value: Mapping[str, Any], *, run_key: str, identity: Mapping[str, Any]
) -> dict[str, Any]:
    if value.get("shard_digest") != _shard_digest(value):
        raise ContractError("O3a acceptance shard self-digest mismatch")
    if value.get("run_key") != run_key or value.get("block_identity") != identity:
        raise ContractError("O3a acceptance shard identity mismatch")
    status = value.get("status")
    if status == "PASS_BLOCK_ATOMIC_ACCEPTANCE":
        rows = value.get("rows", [])
        expected_starts = identity["analysis_gps_starts"]
        if (
            len(rows) != 17
            or [int(row["analysis_gps_start"]) for row in rows]
            != expected_starts
            or any(str(row["detector"]) != identity["detector"] for row in rows)
            or any(not np.isfinite(float(row["primary_score"])) for row in rows)
            or any(
                str(row["primary_score_float32_hex"])
                != np.float32(float(row["primary_score"])).tobytes().hex()
                for row in rows
            )
            or value.get("failures") != []
        ):
            raise ContractError("O3a accepted block shard is invalid")
    elif status == "FAILED_BLOCK_ATOMIC_ACCEPTANCE":
        if value.get("rows") != [] or not value.get("failures"):
            raise ContractError("O3a rejected block shard is invalid")
    else:
        raise ContractError("O3a acceptance shard status is invalid")
    return dict(value)


def _progress(run_dir: Path, *, total_blocks: int) -> dict[str, Any]:
    shards = list((run_dir / "shards").glob("*.json"))
    passed = 0
    failed = 0
    for path in shards:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("status") == "PASS_BLOCK_ATOMIC_ACCEPTANCE":
            passed += 1
        elif value.get("status") == "FAILED_BLOCK_ATOMIC_ACCEPTANCE":
            failed += 1
    complete = passed + failed
    value = {
        "status": "RUNNING" if complete < total_blocks else "COMPLETE",
        "total_blocks": total_blocks,
        "complete_blocks": complete,
        "passed_blocks": passed,
        "failed_blocks": failed,
        "fraction_complete": complete / total_blocks if total_blocks else 0.0,
    }
    _atomic_json(run_dir / "progress.json", value)
    return value


def _run_key(contract: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "stage": "o3a_initial_calibration_raw_acceptance",
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": contract["parents"][
                "canonical_runtime"
            ]["environment_digest"],
            "raw_manifest_sha256": contract["verified_raw_input"][
                "manifest_sha256"
            ],
            "execution": contract["execution"],
        }
    )


def _build_scorer(*, root: Path, contract: Mapping[str, Any], device: str) -> Any:
    from src.core.patch_scorer import PatchScorer

    primary = contract["method_parity"]["primary_index"]
    return PatchScorer(
        root / str(primary["path"]),
        device=device,
        k=int(contract["method_parity"]["top_k"]),
        expected_sha256=str(primary["sha256"]),
        artifact_manifest_path=root / REFERENCE_MANIFEST_REL,
        k_ablations=[],
        n_background=0,
    )


def execute_acceptance(
    *,
    root: Path = ROOT,
    raw_root: Path = DEFAULT_RAW_ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
    workers: int = DEFAULT_WORKERS,
    encoder_batch_size: int = DEFAULT_ENCODER_BATCH_SIZE,
    max_preprocess_in_flight: int = DEFAULT_MAX_PREPROCESS_IN_FLIGHT,
) -> dict[str, Any]:
    contract = load_acceptance_contract(root=root)
    expected_execution = contract["execution"]
    actual_execution = {
        "device": device,
        "workers": workers,
        "encoder_batch_size": encoder_batch_size,
        "max_preprocess_in_flight": max_preprocess_in_flight,
        "block_shards_atomic": True,
        "resume_requires_shard_verification": True,
    }
    if actual_execution != expected_execution:
        raise ContractError("O3a raw-acceptance execution parameters changed")
    load_runtime_contract(root=root, require_current=True, device=device)
    manifest_path = raw_root / str(
        contract["verified_raw_input"]["manifest_relative_to_raw_root"]
    )
    if (
        not manifest_path.is_file()
        or file_sha256(manifest_path)
        != contract["verified_raw_input"]["manifest_sha256"]
    ):
        raise ContractError("O3a raw manifest is absent or divergent")
    plan = load_initial_calibration_plan(root=root)
    run_key = _run_key(contract)
    run_dir = external_root / f"initial_calibration_acceptance_{run_key}"
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    reader = RawSliceReader(manifest_path=manifest_path, raw_root=raw_root)
    scorer = _build_scorer(root=root, contract=contract, device=device)
    stride = int(plan["selection"]["window_stride_s"])
    pad = float(contract["method_parity"]["whitening_pad_s"])
    duration = float(contract["method_parity"]["analysis_duration_s"])
    qrange = tuple(int(value) for value in contract["method_parity"]["query_qrange"])
    frange = tuple(
        int(value) for value in contract["method_parity"]["frequency_range_hz"]
    )
    output_size = tuple(
        int(value) for value in contract["method_parity"]["image_shape"][:2]
    )
    colormap = str(contract["method_parity"]["colormap"])
    total_blocks = sum(
        len(plan["detector_plans"][detector]["selected_blocks"])
        for detector in plan["detectors"]
    )
    _progress(run_dir, total_blocks=total_blocks)

    with ProcessPoolExecutor(max_workers=workers) as pool:
        for detector in plan["detectors"]:
            for block in plan["detector_plans"][detector]["selected_blocks"]:
                identity = _block_identity(detector, block, stride)
                shard_path = shard_dir / (
                    f"{detector}_stratum_{int(block['stratum_index']):03d}.json"
                )
                if shard_path.is_file():
                    validate_block_shard(
                        json.loads(shard_path.read_text(encoding="utf-8")),
                        run_key=run_key,
                        identity=identity,
                    )
                    continue
                prepared: dict[int, dict[str, Any]] = {}
                failures: list[dict[str, Any]] = []
                future_rows: dict[Any, dict[str, Any]] = {}

                def collect_one_preprocess_result() -> None:
                    future = next(as_completed(tuple(future_rows)))
                    row = future_rows.pop(future)
                    try:
                        image = future.result()
                        prepared[int(row["analysis_gps_start"])] = {
                            **row,
                            "image": image,
                        }
                    except Exception as exc:
                        failures.append(
                            {
                                "analysis_gps_start": int(
                                    row["analysis_gps_start"]
                                ),
                                "stage": "preprocessing",
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            }
                        )

                for gps in identity["analysis_gps_starts"]:
                    context_start = float(gps) - pad
                    context_end = float(gps) + duration + pad
                    try:
                        values, sources = reader.read(
                            detector=detector,
                            start=context_start,
                            end=context_end,
                        )
                        future = pool.submit(
                            _preprocess_task,
                            values,
                            context_start,
                            detector,
                            float(gps),
                            float(gps) + duration,
                            pad,
                            qrange,
                            frange,
                            output_size,
                            colormap,
                        )
                        future_rows[future] = {
                            "detector": detector,
                            "analysis_gps_start": gps,
                            "context_interval_gps": [context_start, context_end],
                            "raw_sources": sources,
                        }
                        if len(future_rows) >= max_preprocess_in_flight:
                            collect_one_preprocess_result()
                    except Exception as exc:
                        failures.append(
                            {
                                "analysis_gps_start": gps,
                                "stage": "raw_context",
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            }
                        )
                while future_rows:
                    collect_one_preprocess_result()
                scored_rows: list[dict[str, Any]] = []
                if not failures and len(prepared) == 17:
                    try:
                        scored_rows = score_prepared_rows(
                            [prepared[gps] for gps in identity["analysis_gps_starts"]],
                            scorer=scorer,
                            batch_size=encoder_batch_size,
                        )
                    except Exception as exc:
                        failures.append(
                            {
                                "analysis_gps_start": None,
                                "stage": "encoder_or_seed_scorer",
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            }
                        )
                status = (
                    "PASS_BLOCK_ATOMIC_ACCEPTANCE"
                    if not failures and len(scored_rows) == 17
                    else "FAILED_BLOCK_ATOMIC_ACCEPTANCE"
                )
                body = {
                    "schema_version": SCHEMA_VERSION,
                    "status": status,
                    "run_key": run_key,
                    "block_identity": identity,
                    "rows": scored_rows if status.startswith("PASS") else [],
                    "failures": sorted(
                        failures,
                        key=lambda row: (
                            -1
                            if row["analysis_gps_start"] is None
                            else int(row["analysis_gps_start"]),
                            row["stage"],
                        ),
                    ),
                    "score_value_or_class_used_for_acceptance": False,
                    "threshold_fitted": False,
                }
                shard = {**body, "shard_digest": canonical_json_sha256(body)}
                _atomic_json(shard_path, shard)
                _progress(run_dir, total_blocks=total_blocks)

    accepted_rows: list[dict[str, Any]] = []
    failures = []
    detector_counts = {detector: 0 for detector in plan["detectors"]}
    bootstrap_counts = {detector: 0 for detector in plan["detectors"]}
    for detector in plan["detectors"]:
        for block in plan["detector_plans"][detector]["selected_blocks"]:
            identity = _block_identity(detector, block, stride)
            shard_path = shard_dir / (
                f"{detector}_stratum_{int(block['stratum_index']):03d}.json"
            )
            shard = validate_block_shard(
                json.loads(shard_path.read_text(encoding="utf-8")),
                run_key=run_key,
                identity=identity,
            )
            if shard["status"] != "PASS_BLOCK_ATOMIC_ACCEPTANCE":
                failures.append(
                    {
                        "detector": detector,
                        "stratum_index": int(block["stratum_index"]),
                        "shard_path": str(shard_path),
                        "shard_digest": shard["shard_digest"],
                        "failures": shard["failures"],
                    }
                )
                continue
            output_count = int(identity["output_row_count"])
            for index, row in enumerate(shard["rows"][:output_count]):
                calibration_row = {
                    **row,
                    "stratum_index": int(block["stratum_index"]),
                    "block_selection_priority_sha256": identity[
                        "selection_priority_sha256"
                    ],
                    "bootstrap_eligible": (
                        int(block["stratum_index"]) < 294
                    ),
                    "point_only_tail": (
                        int(block["stratum_index"]) == 294 and index < 2
                    ),
                }
                accepted_rows.append(calibration_row)
                detector_counts[detector] += 1
                if calibration_row["bootstrap_eligible"]:
                    bootstrap_counts[detector] += 1

    ledger_path = run_dir / "initial_calibration_accepted.jsonl"
    if failures:
        if ledger_path.exists():
            raise ContractError(
                "refusing stale accepted ledger after O3a block failure"
            )
        status = "FAILED_FALLBACK_ACQUISITION_EXTENSION_REQUIRED"
        _atomic_json(
            run_dir / "failures.json",
            {"status": status, "failed_blocks": failures},
        )
        ledger_binding = None
    else:
        if detector_counts != {"H1": 5_000, "L1": 5_000}:
            raise ContractError("O3a accepted calibration row count mismatch")
        if bootstrap_counts != {"H1": 4_998, "L1": 4_998}:
            raise ContractError("O3a bootstrap calibration row count mismatch")
        _atomic_jsonl(ledger_path, accepted_rows)
        ledger_binding = {
            "path": str(ledger_path),
            "sha256": file_sha256(ledger_path),
        }
        status = "PASS_VERIFIED_O3A_INITIAL_CALIBRATION_ACCEPTANCE"
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "raw_manifest_sha256": contract["verified_raw_input"][
            "manifest_sha256"
        ],
        "total_blocks": total_blocks,
        "passed_blocks": total_blocks - len(failures),
        "failed_block_count": len(failures),
        "accepted_point_rows_by_detector": detector_counts,
        "accepted_bootstrap_rows_by_detector": bootstrap_counts,
        "accepted_ledger": ledger_binding,
        "threshold_fitted": False,
        "classification_executed": False,
        "candidate_outcomes_reviewed": False,
        "score_value_or_class_used_for_acceptance": False,
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "summary.json", summary)
    _progress(run_dir, total_blocks=total_blocks)
    if failures:
        raise ContractError(
            "O3a provisional calibration block failed; acquire the next "
            "same-stratum candidate under a versioned extension"
        )
    return summary


__all__ = [
    "CONTRACT_REL",
    "RawSliceReader",
    "build_acceptance_contract",
    "execute_acceptance",
    "load_acceptance_contract",
    "preprocess_context",
    "score_prepared_rows",
    "validate_acceptance_contract",
    "validate_block_shard",
    "write_acceptance_contract",
]
