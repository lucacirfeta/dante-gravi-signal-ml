"""Exact native rescoring for frozen calibration and primary-candidate ledgers."""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_execution import verify_primary_scan
from src.dante_light.o4a_corrected_native_index import verify_native_index
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.dante_light.prefilter_v5_protocol import sha256_path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_native_rescore_v1.json")
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_native_rescore_v1"
)
SCHEMA_VERSION = 1
_WORKER_MANIFESTS: dict[str, Any] = {}
_WORKER_RAW_ROOT: Path | None = None


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
        for row in rows
    ).encode("utf-8")


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(_jsonl_bytes(rows))
    temporary.replace(path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_native_rescore_contract(
    contract: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(contract))
    digest = value.pop("contract_digest", None)
    if digest != canonical_json_sha256(value):
        raise ContractError("corrected native-rescore contract digest mismatch")
    if int(value.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ContractError("corrected native-rescore schema changed")
    scoring = value.get("scoring", {})
    expected = value.get("gates", {})
    if (
        int(scoring.get("top_k", -1)) != 68
        or scoring.get("output_mode") != "score_only"
        or int(expected.get("calibration_rows_by_detector", {}).get("H1", -1))
        != 5000
        or int(expected.get("calibration_rows_by_detector", {}).get("L1", -1))
        != 5000
        or int(expected.get("candidate_rows_by_detector", {}).get("H1", -1))
        != 4720
        or int(expected.get("candidate_rows_by_detector", {}).get("L1", -1))
        != 6222
        or expected.get("fail_closed") is not True
    ):
        raise ContractError("corrected native-rescore scientific boundary changed")
    for reference in value.get("references", {}).values():
        path = (root / str(reference["path"])).resolve()
        if not path.is_file() or sha256_path(path) != reference["sha256"]:
            raise ContractError(f"corrected native-rescore reference changed: {path}")
    return {"contract_digest": digest, **value}


def load_native_rescore_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_native_rescore_contract(
        json.loads((root / CONTRACT_REL).read_text(encoding="utf-8")), root
    )


def _calibration_rows(
    *, root: Path, contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for detector in ("H1", "L1"):
        reference = contract["references"][f"native_calibration_{detector}"]
        path = root / str(reference["path"])
        with path.open("r", encoding="utf-8", newline="") as stream:
            source = list(csv.DictReader(stream))
        expected = int(contract["gates"]["calibration_rows_by_detector"][detector])
        if len(source) != expected:
            raise ContractError("corrected native calibration cardinality changed")
        for row_number, row in enumerate(source):
            if str(row["detector"]) != detector:
                raise ContractError("corrected native calibration detector changed")
            gps = float(row["gps_start"])
            if float(row["gps_end"]) != gps + 32.0:
                raise ContractError("corrected native calibration geometry changed")
            rows.append(
                {
                    "input_index": len(rows),
                    "population": "native_calibration",
                    "detector": detector,
                    "gps_start": gps,
                    "ledger_row_number": row_number,
                    "bootstrap_block_index": int(row["bootstrap_block_index"]),
                    "source_path": str(row["source_path"]),
                    "source_interval": [
                        float(row["source_start"]),
                        float(row["source_end"]),
                    ],
                    "expected_image_sha256": None,
                    "identity_digest": canonical_json_sha256(
                        {
                            "detector": detector,
                            "gps_start": gps,
                            "population": "native_calibration",
                        }
                    ),
                }
            )
    return rows


def _candidate_rows(database_path: Path, *, offset: int) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        source = connection.execute(
            "SELECT detector,gps_start,identity_digest,image_sha256 FROM windows "
            "WHERE is_candidate=1 ORDER BY detector,gps_start"
        ).fetchall()
    finally:
        connection.close()
    rows = []
    for index, (detector, gps, identity_digest, image_sha256) in enumerate(source):
        rows.append(
            {
                "input_index": offset + index,
                "population": "primary_candidate",
                "detector": str(detector),
                "gps_start": float(gps),
                "expected_image_sha256": str(image_sha256),
                "identity_digest": str(identity_digest),
            }
        )
    return rows


def _validate_input_rows(
    rows: Sequence[Mapping[str, Any]], *, contract: Mapping[str, Any]
) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    identities: set[tuple[str, float]] = set()
    for expected_index, row in enumerate(rows):
        if int(row["input_index"]) != expected_index:
            raise ContractError("corrected native-rescore input order changed")
        detector = str(row["detector"])
        gps = float(row["gps_start"])
        identity = (detector, gps)
        if detector not in {"H1", "L1"} or identity in identities:
            raise ContractError("corrected native-rescore identity is invalid")
        identities.add(identity)
        counts[str(row["population"])][detector] += 1
    expected_calibration = contract["gates"]["calibration_rows_by_detector"]
    expected_candidates = contract["gates"]["candidate_rows_by_detector"]
    if any(
        counts["native_calibration"][detector] != int(expected_calibration[detector])
        or counts["primary_candidate"][detector] != int(expected_candidates[detector])
        for detector in ("H1", "L1")
    ):
        raise ContractError("corrected native-rescore input cardinality changed")
    return {
        population: {detector: int(counter[detector]) for detector in ("H1", "L1")}
        for population, counter in counts.items()
    }


def _initialize_worker(manifest_path: str, raw_root: str) -> None:
    from src.core.patch_producer import load_frozen_raw_manifest

    global _WORKER_MANIFESTS, _WORKER_RAW_ROOT
    _WORKER_RAW_ROOT = Path(raw_root).resolve()
    _WORKER_MANIFESTS = {
        detector: load_frozen_raw_manifest(
            Path(manifest_path), raw_root=_WORKER_RAW_ROOT, detector=detector
        )
        for detector in ("H1", "L1")
    }


def _read_manifest_slice(*, detector: str, start: float, end: float):
    import h5py
    from gwpy.timeseries import TimeSeries
    from src.core.patch_producer import (
        CompleteContext,
        ContextSource,
        IncompleteContextError,
        RawBlockConflictError,
        _verified_sha256,
    )

    manifest = _WORKER_MANIFESTS[detector]
    grouped: dict[tuple[float, float], list[Path]] = defaultdict(list)
    for block_start, block_end, path in manifest.entries:
        if block_end > start and block_start < end:
            grouped[(float(block_start), float(block_end))].append(Path(path).resolve())
    if not grouped:
        raise IncompleteContextError(f"no frozen raw source overlaps [{start}, {end}]")
    blocks: list[tuple[float, float, Path, str]] = []
    for (block_start, block_end), paths in grouped.items():
        verified = [
            (path, _verified_sha256(path, manifest.expected_sha256.get(path)))
            for path in sorted(set(paths), key=str)
        ]
        if len({digest for _path, digest in verified}) != 1:
            raise RawBlockConflictError(
                f"conflicting frozen copies for [{block_start}, {block_end}]"
            )
        path, digest = verified[0]
        blocks.append((block_start, block_end, path, digest))
    blocks.sort(key=lambda item: (item[0], item[1], str(item[2])))
    tolerance = 1.0 / 4096.0
    cursor = start
    selected: list[tuple[float, float, Path, str]] = []
    while cursor < end - tolerance:
        candidates = [
            item
            for item in blocks
            if item[0] <= cursor + tolerance and item[1] > cursor + tolerance
        ]
        if not candidates:
            raise IncompleteContextError(f"gap in frozen raw coverage at GPS {cursor}")
        chosen = sorted(candidates, key=lambda item: (-item[1], item[0], str(item[2])))[0]
        selected.append(chosen)
        cursor = min(end, chosen[1])
    pieces = []
    sources = []
    cursor = start
    for block_start, block_end, path, digest in selected:
        used_start = cursor
        used_end = min(end, block_end)
        first = int(round((used_start - block_start) * 4096))
        last = int(round((used_end - block_start) * 4096))
        with h5py.File(path, "r") as handle:
            expected_shape = (int(round((block_end - block_start) * 4096)),)
            if "Strain" not in handle or tuple(handle["Strain"].shape) != expected_shape:
                raise ContractError(f"corrected native-rescore HDF5 shape mismatch: {path}")
            values = np.asarray(handle["Strain"][first:last])
        if values.shape != (last - first,):
            raise ContractError("corrected native-rescore HDF5 slice is short")
        pieces.append(values)
        sources.append(
            ContextSource(
                path=path,
                block_start=block_start,
                block_end=block_end,
                used_start=used_start,
                used_end=used_end,
                sha256=digest,
            )
        )
        cursor = used_end
    values = np.ascontiguousarray(np.concatenate(pieces))
    if values.shape != (int(round((end - start) * 4096)),):
        raise IncompleteContextError("corrected native-rescore context is incomplete")
    series = TimeSeries(
        values,
        t0=start,
        sample_rate=4096,
        name=f"{detector}:GWOSC-16KHZ_R1_STRAIN",
    )
    return CompleteContext(series=series, sources=tuple(sources)), values


def _prepare_row(arguments: tuple[Mapping[str, Any], float, str]):
    import matplotlib.pyplot as plt
    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )

    row, pad_s, colormap = arguments
    detector = str(row["detector"])
    gps = float(row["gps_start"])
    context, raw_values = _read_manifest_slice(
        detector=detector, start=gps - pad_s, end=gps + 32.0 + pad_s
    )
    whitened, pad_info = whiten_context(context.series, gps, gps + 32.0, pad=pad_s)
    tolerance = 1.0 / 4096.0
    if (
        float(pad_info["effective_left"]) < pad_s - tolerance
        or float(pad_info["effective_right"]) < pad_s - tolerance
    ):
        raise ContractError("corrected native-rescore whitening context is incomplete")
    clean = extract_clean_subwindow(whitened, gps, gps + 32.0)
    clean_values = np.ascontiguousarray(clean.value)
    if clean_values.shape != (32 * 4096,) or np.any(~np.isfinite(clean_values)):
        raise ContractError("corrected native-rescore clean window is invalid")
    spectrogram = generate_qtransform(clean, save_path=None, cmap=colormap)
    cmap = plt.get_cmap(colormap)
    image = np.ascontiguousarray((cmap(spectrogram)[:, :, :3] * 255).astype(np.uint8))
    if image.shape != (256, 256, 3):
        raise ContractError("corrected native-rescore image shape changed")
    image_digest = hashlib.sha256(image.tobytes()).hexdigest()
    expected_image = row.get("expected_image_sha256")
    if expected_image is not None and image_digest != expected_image:
        raise ContractError("corrected native-rescore candidate image hash mismatch")
    assert _WORKER_RAW_ROOT is not None
    source_rows = [
        {
            "relative_path": str(source.path.relative_to(_WORKER_RAW_ROOT)),
            "block_interval": [source.block_start, source.block_end],
            "used_interval": [source.used_start, source.used_end],
            "sha256": source.sha256,
        }
        for source in context.sources
    ]
    replay = {
        key: value
        for key, value in row.items()
        if key not in {"expected_image_sha256"}
    }
    replay.update(
        {
            "context_sources": source_rows,
            "context_sources_digest": canonical_json_sha256(source_rows),
            "raw_context_sha256": hashlib.sha256(raw_values.tobytes()).hexdigest(),
            "clean_window_sha256": hashlib.sha256(clean_values.tobytes()).hexdigest(),
            "clean_window_dtype": str(clean_values.dtype),
            "clean_window_shape": list(clean_values.shape),
            "image_sha256": image_digest,
        }
    )
    return image, replay


def _float32_hex(value: float) -> str:
    scalar = np.asarray([value], dtype=np.float32)
    if not np.isfinite(scalar).all():
        raise ContractError("corrected native-rescore score is non-finite")
    return scalar.tobytes().hex()


def _run_key(
    contract: Mapping[str, Any],
    *,
    index_summary: Mapping[str, Any],
    scan_summary: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> str:
    return canonical_json_sha256(
        {
            "stage": "native_calibration_and_candidate_full_rescore",
            "contract_digest": contract["contract_digest"],
            "index_artifact_digest": index_summary["artifact_digest"],
            "primary_scan_artifact_digest": scan_summary["artifact_digest"],
            "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        }
    )


def _scorer_manifest(path: Path, *, index_path: Path, index_sha256: str) -> None:
    _atomic_json(
        path,
        {
            "schema_version": 1,
            "artifact_root": str(index_path.parent),
            "reference_indices": {
                "o4a_corrected_detector_aware_v1": {
                    "path": index_path.name,
                    "sha256": index_sha256,
                    "embedding_dim": 384,
                    "n_centroids": 1216,
                    "qrange": [4, 64],
                    "role": "corrected detector-aware native rescore",
                }
            },
        },
    )


def run_native_rescore(
    *,
    root: Path = ROOT,
    raw_root: Path,
    primary_external_root: Path,
    cohort_external_root: Path,
    index_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
    workers: int = 8,
    batch_size: int = 32,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    raw_root = raw_root.resolve()
    contract = load_native_rescore_contract(root)
    execution = contract["execution"]
    if workers != int(execution["workers"]) or batch_size != int(execution["batch_size"]):
        raise ContractError("corrected native-rescore execution parameters changed")
    index_summary, index_run_dir = verify_native_index(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        cohort_external_root=cohort_external_root.resolve(),
        external_root=index_external_root.resolve(),
        device=device,
    )
    scan_summary, scan_run_dir = verify_primary_scan(
        root=root, external_root=primary_external_root.resolve()
    )
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    run_key = _run_key(
        contract, index_summary=index_summary, scan_summary=scan_summary, runtime=runtime
    )
    run_dir = external_root.resolve() / f"native_rescore_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "native_rescore_summary.json"
    failure_path = run_dir / "failure.json"
    outputs = {
        "native_calibration_H1": run_dir / "native_calibration_H1.jsonl",
        "native_calibration_L1": run_dir / "native_calibration_L1.jsonl",
        "primary_candidate": run_dir / "native_candidates.jsonl",
    }
    if summary_path.is_file() or any(path.is_file() for path in outputs.values()):
        return verify_native_rescore(
            root=root,
            primary_external_root=primary_external_root,
            cohort_external_root=cohort_external_root,
            index_external_root=index_external_root,
            external_root=external_root,
            device=device,
        )
    identity = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "index_artifact_digest": index_summary["artifact_digest"],
        "primary_scan_artifact_digest": scan_summary["artifact_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "workers": workers,
        "batch_size": batch_size,
        "device": device,
    }
    _atomic_json(run_dir / "run_identity.json", identity)
    try:
        calibration = _calibration_rows(root=root, contract=contract)
        candidates = _candidate_rows(
            scan_run_dir / "primary_scan.sqlite", offset=len(calibration)
        )
        rows = calibration + candidates
        counts = _validate_input_rows(rows, contract=contract)
        index_path = index_run_dir / str(index_summary["index"]["filename"])
        if sha256_file(index_path) != index_summary["index"]["sha256"]:
            raise ContractError("corrected native-rescore index hash changed")
        manifest_path = run_dir / "scorer_artifact_manifest.json"
        _scorer_manifest(
            manifest_path,
            index_path=index_path,
            index_sha256=index_summary["index"]["sha256"],
        )
        from src.core.patch_scorer import PatchScorer

        scorer = PatchScorer(
            index_path,
            device=device,
            k=int(contract["scoring"]["top_k"]),
            expected_sha256=index_summary["index"]["sha256"],
            artifact_manifest_path=manifest_path,
            k_ablations=[],
            n_background=0,
        )
        result_rows: list[dict[str, Any]] = []
        manifest_path_raw = root / str(contract["references"]["raw_manifest"]["path"])
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_initialize_worker,
            initargs=(str(manifest_path_raw), str(raw_root)),
        ) as executor:
            for start in range(0, len(rows), batch_size):
                batch_rows = rows[start : start + batch_size]
                prepared = list(
                    executor.map(
                        _prepare_row,
                        [
                            (
                                row,
                                float(contract["preprocessing"]["whitening_pad_s"]),
                                str(contract["preprocessing"]["colormap"]),
                            )
                            for row in batch_rows
                        ],
                    )
                )
                images = [item[0] for item in prepared]
                tokens = scorer.encode_patch_tokens(images)
                scored = scorer.score_patch_tokens(
                    tokens, 1.0, output_mode=str(contract["scoring"]["output_mode"])
                )
                if len(scored) != len(batch_rows):
                    raise ContractError("corrected native-rescore scorer batch is incomplete")
                for (_image, replay), score_row in zip(prepared, scored, strict=True):
                    score = float(score_row["novelty_score"])
                    replay["native_score"] = score
                    replay["score_float32_hex"] = _float32_hex(score)
                    result_rows.append(replay)
        if len(result_rows) != len(rows):
            raise ContractError("corrected native-rescore output is incomplete")
        grouped_rows = {
            "native_calibration_H1": [
                row
                for row in result_rows
                if row["population"] == "native_calibration" and row["detector"] == "H1"
            ],
            "native_calibration_L1": [
                row
                for row in result_rows
                if row["population"] == "native_calibration" and row["detector"] == "L1"
            ],
            "primary_candidate": [
                row for row in result_rows if row["population"] == "primary_candidate"
            ],
        }
        for name, path in outputs.items():
            _atomic_jsonl(path, grouped_rows[name])
        output_summary = {
            name: {
                "filename": path.name,
                "row_total": len(grouped_rows[name]),
                "sha256": sha256_file(path),
                "row_digest": canonical_json_sha256(grouped_rows[name]),
            }
            for name, path in outputs.items()
        }
        body = {
            **identity,
            "status": "PASS_COMPLETE_NATIVE_RESCORE",
            "input_counts": counts,
            "row_total": len(result_rows),
            "outputs": output_summary,
            "gates": {
                "candidate_image_hash_mismatches": 0,
                "context_failures": 0,
                "nonfinite_scores": 0,
                "old_native_scores_read": False,
                "old_native_thresholds_read": False,
            },
        }
        body["artifact_digest"] = canonical_json_sha256(body)
        _atomic_json(summary_path, body)
        failure_path.unlink(missing_ok=True)
        return verify_native_rescore(
            root=root,
            primary_external_root=primary_external_root,
            cohort_external_root=cohort_external_root,
            index_external_root=index_external_root,
            external_root=external_root,
            device=device,
        )
    except BaseException as exc:
        failure = {
            **identity,
            "status": "FAILED_NATIVE_RESCORE",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        raise


def verify_native_rescore(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    cohort_external_root: Path,
    index_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_rescore_contract(root)
    index_summary, _index_run_dir = verify_native_index(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        cohort_external_root=cohort_external_root.resolve(),
        external_root=index_external_root.resolve(),
        device=device,
    )
    scan_summary, _scan_run_dir = verify_primary_scan(
        root=root, external_root=primary_external_root.resolve()
    )
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    run_key = _run_key(
        contract, index_summary=index_summary, scan_summary=scan_summary, runtime=runtime
    )
    run_dir = external_root.resolve() / f"native_rescore_{run_key}"
    summary_path = run_dir / "native_rescore_summary.json"
    if (run_dir / "failure.json").is_file():
        raise ContractError("corrected native-rescore failure artifact is present")
    if not summary_path.is_file():
        raise ContractError("corrected native-rescore summary is missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    digest = body.pop("artifact_digest", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("corrected native-rescore summary digest mismatch")
    if (
        summary.get("status") != "PASS_COMPLETE_NATIVE_RESCORE"
        or summary.get("run_key") != run_key
        or summary.get("contract_digest") != contract["contract_digest"]
        or int(summary.get("row_total", -1)) != 20942
        or summary.get("gates")
        != {
            "candidate_image_hash_mismatches": 0,
            "context_failures": 0,
            "nonfinite_scores": 0,
            "old_native_scores_read": False,
            "old_native_thresholds_read": False,
        }
    ):
        raise ContractError("corrected native-rescore summary boundary changed")
    seen: set[tuple[str, float]] = set()
    expected_outputs = {
        "native_calibration_H1": 5000,
        "native_calibration_L1": 5000,
        "primary_candidate": 10942,
    }
    for name, expected_count in expected_outputs.items():
        metadata = summary["outputs"][name]
        path = run_dir / str(metadata["filename"])
        if not path.is_file() or sha256_file(path) != metadata["sha256"]:
            raise ContractError("corrected native-rescore output hash changed")
        rows = _load_jsonl(path)
        if (
            len(rows) != expected_count
            or canonical_json_sha256(rows) != metadata["row_digest"]
        ):
            raise ContractError("corrected native-rescore output cardinality changed")
        for row in rows:
            identity = (str(row["detector"]), float(row["gps_start"]))
            if identity in seen or not np.isfinite(float(row["native_score"])):
                raise ContractError("corrected native-rescore output identity changed")
            if _float32_hex(float(row["native_score"])) != row["score_float32_hex"]:
                raise ContractError("corrected native-rescore score bytes changed")
            seen.add(identity)
    if len(seen) != 20942:
        raise ContractError("corrected native-rescore verification is incomplete")
    return summary, run_dir
