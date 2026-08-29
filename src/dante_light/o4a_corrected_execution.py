"""Input acquisition and resumable execution support for corrected O4a."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from collections import defaultdict
import bisect
import concurrent.futures
import multiprocessing as mp
import sqlite3
import subprocess
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_protocol import (
    OUTPUT_REL as PROTOCOL_REL,
    ROOT,
    iter_calibration_identities,
    iter_scan_identities,
    validate_corrected_protocol,
)
from src.dante_light.prefilter_v5_protocol import repository_reference, sha256_path
from src.dante_light.evidence import SCORE_ATOL


SCHEMA_VERSION = 1
DEFAULT_EXTERNAL_ROOT = Path("E:/dante_cache/dante_light/o4a_corrected_v2")
COMPACT_ACQUISITION_REL = "artifacts/dante_light/o4a_v1_parity/corrected_input_acquisition.json"
IMPLEMENTATION_REL = "src/dante_light/o4a_corrected_execution.py"
ACQUISITION_IMPLEMENTATION_COMMIT = "9bc42ed8165adb34e4c26355b975310cab766aa9"
ACQUISITION_IMPLEMENTATION_SHA256 = "e0aeb817c043f8db135406befdd2b91b63179f80cc15310341be48de6961bf28"
COMPACT_CALIBRATION_REL = "artifacts/dante_light/o4a_v1_parity/corrected_primary_calibration.json"
COMPACT_SCAN_REL = "artifacts/dante_light/o4a_v1_parity/corrected_primary_scan.json"


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _strain_record(path: Path, *, detector: str, start: float, end: float) -> dict[str, Any]:
    from gwpy.timeseries import TimeSeries

    series = TimeSeries.read(path)
    if int(round(float(series.sample_rate.value))) != 4096:
        raise ContractError(f"acquired corrected input has wrong sample rate: {path}")
    tolerance = 1.0 / 4096.0
    actual_start = float(series.t0.value)
    actual_end = actual_start + float(series.duration.value)
    if abs(actual_start - start) > tolerance or abs(actual_end - end) > tolerance:
        raise ContractError(f"acquired corrected input has wrong interval: {path}")
    values = np.ascontiguousarray(series.value)
    if values.shape != (int(round((end - start) * 4096)),) or not np.isfinite(values).all():
        raise ContractError(f"acquired corrected input is incomplete/nonfinite: {path}")
    return {
        "detector": detector,
        "gps_start": start,
        "gps_end": end,
        "sample_rate_hz": 4096,
        "sample_count": int(values.size),
        "file_sha256": sha256_path(path),
        "strain_values_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _missing_intervals(root: Path) -> list[dict[str, Any]]:
    rows = [
        row
        for row in iter_calibration_identities(root)
        if row["coverage_in_frozen_raw_manifest"]
        == "not_complete_in_frozen_local_manifest"
    ]
    result = []
    seen = set()
    for row in rows:
        key = (
            row["detector"],
            float(row["required_padded_interval"][0]),
            float(row["required_padded_interval"][1]),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "detector": key[0],
                "gps_start": key[1],
                "gps_end": key[2],
            }
        )
    result.sort(key=lambda row: (row["detector"], row["gps_start"]))
    if len(result) != 15:
        raise ContractError("corrected O4a missing calibration interval count changed")
    return result


def _default_fetcher(detector: str, start: int, end: int):
    from src.core.data_loader import fetch_strain_data

    return fetch_strain_data(
        detector,
        start,
        end,
        sample_rate=4096,
        cache_raw=False,
        remote_only=True,
        edge_tolerance=0.0,
    )


def acquire_missing_calibration_inputs(
    *,
    root: Path = ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    fetcher: Callable[[str, int, int], Any] = _default_fetcher,
    compact_path: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    """Fetch only frozen missing intervals and bind their exact bytes."""

    root = root.resolve()
    external_root = external_root.resolve()
    protocol_path = root / PROTOCOL_REL
    protocol = validate_corrected_protocol(
        json.loads(protocol_path.read_text(encoding="utf-8")), root
    )
    run_dir = external_root / f"inputs_{protocol['protocol_digest']}"
    data_dir = run_dir / "missing_calibration"
    manifest_path = run_dir / "acquisition_manifest.json"
    compact_path = root / COMPACT_ACQUISITION_REL if compact_path is None else compact_path
    if manifest_path.is_file():
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_acquisition_manifest(saved, run_dir=run_dir, protocol=protocol)
        _atomic_json(compact_path, compact_acquisition_summary(saved, root=root))
        return saved, run_dir

    data_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for identity in _missing_intervals(root):
        detector = str(identity["detector"])
        start = int(identity["gps_start"])
        end = int(identity["gps_end"])
        prefix = f"{detector}_{start}_{end}_"
        existing = sorted(data_dir.glob(prefix + "*.hdf5"))
        if len(existing) > 1:
            raise ContractError(f"multiple acquired inputs for {detector} [{start}, {end}]")
        if existing:
            path = existing[0]
            record = _strain_record(path, detector=detector, start=start, end=end)
            if path.stem != prefix + record["file_sha256"]:
                raise ContractError(f"acquired input filename/hash mismatch: {path}")
        else:
            series = fetcher(detector, start, end)
            temporary = data_dir / f".{detector}_{start}_{end}.tmp.hdf5"
            if temporary.exists():
                temporary.unlink()
            series.write(temporary, format="hdf5")
            record = _strain_record(
                temporary, detector=detector, start=start, end=end
            )
            path = data_dir / f"{prefix}{record['file_sha256']}.hdf5"
            temporary.replace(path)
        records.append(
            {
                **identity,
                **record,
                "relative_path": path.relative_to(run_dir).as_posix(),
                "source": "GWOSC_OPEN_DATA_VIA_GWPY_FETCH_OPEN_DATA",
            }
        )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_CONTENT_ADDRESSED_INPUTS",
        "protocol_digest": protocol["protocol_digest"],
        "protocol_reference": repository_reference(root, protocol_path),
        "record_count": len(records),
        "records": records,
        "record_digest": canonical_json_sha256(records),
        "network_fetch_was_outcome_blind": True,
        "scores_or_labels_accessed_during_fetch": [],
    }
    manifest = {**body, "manifest_digest": canonical_json_sha256(body)}
    _atomic_json(manifest_path, manifest)
    validate_acquisition_manifest(manifest, run_dir=run_dir, protocol=protocol)
    _atomic_json(compact_path, compact_acquisition_summary(manifest, root=root))
    return manifest, run_dir


def validate_acquisition_manifest(
    value: Mapping[str, Any], *, run_dir: Path, protocol: Mapping[str, Any]
) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("manifest_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("corrected O4a acquisition manifest self-digest mismatch")
    if (
        payload.get("status") != "COMPLETE_CONTENT_ADDRESSED_INPUTS"
        or payload.get("protocol_digest") != protocol["protocol_digest"]
        or payload.get("record_count") != 15
        or payload.get("record_digest") != canonical_json_sha256(payload["records"])
    ):
        raise ContractError("corrected O4a acquisition manifest contract mismatch")
    expected = _missing_intervals(ROOT)
    actual = [
        {
            "detector": row["detector"],
            "gps_start": row["gps_start"],
            "gps_end": row["gps_end"],
        }
        for row in payload["records"]
    ]
    if actual != expected:
        raise ContractError("corrected O4a acquired identities changed")
    for row in payload["records"]:
        relative = Path(str(row["relative_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError("corrected O4a acquired path is not portable")
        path = run_dir / relative
        measured = _strain_record(
            path,
            detector=str(row["detector"]),
            start=float(row["gps_start"]),
            end=float(row["gps_end"]),
        )
        for key, measured_value in measured.items():
            if row.get(key) != measured_value:
                raise ContractError(f"corrected O4a acquired input mismatch: {path}")
    return dict(value)


def compact_acquisition_summary(
    manifest: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    try:
        acquisition_blob = subprocess.check_output(
            [
                "git",
                "show",
                f"{ACQUISITION_IMPLEMENTATION_COMMIT}:{IMPLEMENTATION_REL}",
            ],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError("cannot resolve corrected O4a acquisition code snapshot") from exc
    if hashlib.sha256(acquisition_blob).hexdigest() != ACQUISITION_IMPLEMENTATION_SHA256:
        raise ContractError("corrected O4a acquisition code snapshot hash mismatch")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": manifest["status"],
        "protocol_digest": manifest["protocol_digest"],
        "external_manifest_digest": manifest["manifest_digest"],
        "record_count": manifest["record_count"],
        "record_digest": manifest["record_digest"],
        "detector_counts": {
            detector: sum(row["detector"] == detector for row in manifest["records"])
            for detector in ("H1", "L1")
        },
        "total_samples": sum(int(row["sample_count"]) for row in manifest["records"]),
        "acquisition_execution_snapshot": {
            "commit": ACQUISITION_IMPLEMENTATION_COMMIT,
            "path": IMPLEMENTATION_REL,
            "sha256": ACQUISITION_IMPLEMENTATION_SHA256,
        },
        "verification_implementation_reference": repository_reference(
            root, root / IMPLEMENTATION_REL
        ),
        "scientific_boundary": {
            "input_acquisition_only": True,
            "scoring_executed": False,
            "thresholds_changed": False,
            "publication_authorized": False,
        },
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def _load_protocol(root: Path) -> dict[str, Any]:
    return validate_corrected_protocol(
        json.loads((root / PROTOCOL_REL).read_text(encoding="utf-8")), root
    )


def _load_acquisition(
    *, root: Path, external_root: Path, protocol: Mapping[str, Any]
) -> tuple[dict[str, Any], Path]:
    run_dir = external_root / f"inputs_{protocol['protocol_digest']}"
    path = run_dir / "acquisition_manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    return validate_acquisition_manifest(value, run_dir=run_dir, protocol=protocol), run_dir


def _execution_references(root: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "protocol": PROTOCOL_REL,
        "acquisition_summary": COMPACT_ACQUISITION_REL,
        "execution_implementation": IMPLEMENTATION_REL,
        "raw_manifest": "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl",
        "reference_artifacts": "config/reference_artifacts.json",
        "patch_producer": "src/core/patch_producer.py",
        "preprocessor": "src/core/preprocessor.py",
        "patch_scorer": "src/core/patch_scorer.py",
        "model_loader": "src/core/model_loader.py",
        "encoder": "src/core/encoder.py",
    }
    return {
        name: repository_reference(root, root / relative)
        for name, relative in paths.items()
    }


def _calibration_run_key(
    *, protocol: Mapping[str, Any], acquisition: Mapping[str, Any], references: Mapping[str, Any]
) -> str:
    return canonical_json_sha256(
        {
            "protocol_digest": protocol["protocol_digest"],
            "acquisition_manifest_digest": acquisition["manifest_digest"],
            "references": dict(references),
            "stage": "primary_session_calibration_full_rescore",
        }
    )


class _CorrectedContextReader:
    def __init__(
        self,
        *,
        root: Path,
        raw_root: Path,
        acquisition: Mapping[str, Any],
        acquisition_run_dir: Path,
    ) -> None:
        from src.core.patch_producer import load_frozen_raw_manifest

        manifest_path = root / "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl"
        self.base = {
            detector: load_frozen_raw_manifest(
                manifest_path, raw_root=raw_root, detector=detector
            )
            for detector in ("H1", "L1")
        }
        self.gaps = {
            (str(row["detector"]), float(row["gps_start"]), float(row["gps_end"])): (
                acquisition_run_dir / str(row["relative_path"]),
                dict(row),
            )
            for row in acquisition["records"]
        }

    def read(self, *, detector: str, start: float, end: float):
        from gwpy.timeseries import TimeSeries
        from src.core.patch_producer import IncompleteContextError, read_complete_context

        manifest = self.base[detector]
        try:
            return read_complete_context(
                manifest.entries,
                gps_start=start,
                gps_end=end,
                sample_rate_hz=4096,
                expected_sha256=manifest.expected_sha256,
            )
        except IncompleteContextError:
            key = (detector, start, end)
            if key not in self.gaps:
                raise
            path, record = self.gaps[key]
            if sha256_path(path) != record["file_sha256"]:
                raise ContractError(f"corrected O4a gap input hash changed: {path}")
            series = TimeSeries.read(path)
            return type("AcquiredContext", (), {"series": series, "sources": ()})()


def _context_provenance(context: Any, *, acquired_record: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    if acquired_record is not None:
        return [
            {
                "path": acquired_record["relative_path"],
                "sha256": acquired_record["file_sha256"],
                "used_interval": [acquired_record["gps_start"], acquired_record["gps_end"]],
                "source_kind": "content_addressed_GWOSC_gap",
            }
        ]
    return [
        {
            "path": str(source.path),
            "sha256": source.sha256,
            "used_interval": [source.used_start, source.used_end],
            "source_kind": "frozen_raw_manifest",
        }
        for source in context.sources
    ]


def _score_only(scorer: Any, images: Sequence[np.ndarray]) -> list[float]:
    tokens = scorer.encode_patch_tokens(list(images))
    rows = scorer.score_patch_tokens(tokens, 1.0, output_mode="score_only")
    values = [float(row["novelty_score"]) for row in rows]
    if len(values) != len(images) or not np.isfinite(values).all():
        raise ContractError("corrected O4a primary scorer returned invalid values")
    return values


def _primary_scorer(*, root: Path, protocol: Mapping[str, Any], device: str):
    from src.core.patch_scorer import PatchScorer

    manifest_path = root / "config/reference_artifacts.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_root = (manifest_path.parent / str(manifest["artifact_root"])).resolve()
    spec = manifest["reference_indices"]["o3b_production_k275"]
    return PatchScorer(
        artifact_root / spec["path"],
        device=device,
        k=int(protocol["representation"]["top_k"]),
        expected_sha256=protocol["representation"]["primary_index_sha256"],
        artifact_manifest_path=manifest_path,
        k_ablations=[],
        n_background=0,
    )


def _validate_calibration_shard(
    value: Mapping[str, Any], *, expected_rows: Sequence[Mapping[str, Any]], run_key: str
) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("shard_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("corrected O4a calibration shard self-digest mismatch")
    expected_ids = [
        (int(row["session_id"]), str(row["detector"]), float(row["catalog_gps_start"]))
        for row in expected_rows
    ]
    actual_ids = [
        (int(row["session_id"]), str(row["detector"]), float(row["catalog_gps_start"]))
        for row in payload.get("rows", [])
    ]
    if (
        payload.get("status") != "COMPLETE"
        or payload.get("run_key") != run_key
        or actual_ids != expected_ids
    ):
        raise ContractError("corrected O4a calibration shard identity mismatch")
    for row in payload["rows"]:
        score = float(row["corrected_primary_score"])
        if not np.isfinite(score) or row["corrected_score_float32_hex"] != np.float32(score).tobytes().hex():
            raise ContractError("corrected O4a calibration shard score is invalid")
    scores = np.asarray([row["corrected_primary_score"] for row in payload["rows"]])
    threshold = float(np.percentile(scores, 99.0))
    if payload["empirical_p99"] != threshold:
        raise ContractError("corrected O4a calibration p99 mismatch")
    return dict(value)


def run_primary_calibration(
    *,
    root: Path = ROOT,
    raw_root: Path = Path("E:/o4a"),
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
    workers: int = 2,
    batch_size: int = 8,
) -> tuple[dict[str, Any], Path]:
    """Fully rescore all 39,971 frozen primary calibration identities."""

    if workers < 1 or batch_size < 1:
        raise ValueError("workers and batch_size must be positive")
    root = root.resolve()
    external_root = external_root.resolve()
    protocol = _load_protocol(root)
    acquisition, acquisition_run_dir = _load_acquisition(
        root=root, external_root=external_root, protocol=protocol
    )
    references = _execution_references(root)
    run_key = _calibration_run_key(
        protocol=protocol, acquisition=acquisition, references=references
    )
    run_dir = external_root / f"calibration_{run_key}"
    shard_dir = run_dir / "sessions"
    shard_dir.mkdir(parents=True, exist_ok=True)
    identity = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "protocol_digest": protocol["protocol_digest"],
        "acquisition_manifest_digest": acquisition["manifest_digest"],
        "references": references,
        "device_request": device,
        "workers": workers,
        "batch_size": batch_size,
    }
    identity_path = run_dir / "run_identity.json"
    if identity_path.is_file():
        if json.loads(identity_path.read_text(encoding="utf-8")) != identity:
            raise ContractError("corrected O4a calibration run-key collision")
    else:
        _atomic_json(identity_path, identity)
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in iter_calibration_identities(root):
        grouped[(int(row["session_id"]), str(row["detector"]))].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: float(row["catalog_gps_start"]))
    reader = _CorrectedContextReader(
        root=root,
        raw_root=raw_root.resolve(),
        acquisition=acquisition,
        acquisition_run_dir=acquisition_run_dir,
    )
    scorer = _primary_scorer(root=root, protocol=protocol, device=device)
    from src.core.patch_producer import _worker_preprocess

    ctx = mp.get_context("spawn")
    shard_values = []
    for (session_id, detector), rows in sorted(grouped.items()):
        shard_path = shard_dir / f"{session_id}_{detector}.json"
        if shard_path.is_file():
            shard_values.append(
                _validate_calibration_shard(
                    json.loads(shard_path.read_text(encoding="utf-8")),
                    expected_rows=rows,
                    run_key=run_key,
                )
            )
            continue
        output_rows = []
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=workers, mp_context=ctx
        ) as pool:
            for batch_start in range(0, len(rows), batch_size):
                batch = rows[batch_start : batch_start + batch_size]
                prepared = []
                futures = []
                for row in batch:
                    detector_value = str(row["detector"])
                    context_start, context_end = (
                        float(row["required_padded_interval"][0]),
                        float(row["required_padded_interval"][1]),
                    )
                    context = reader.read(
                        detector=detector_value,
                        start=context_start,
                        end=context_end,
                    )
                    values = np.ascontiguousarray(context.series.value)
                    if values.shape != (40 * 4096,) or not np.isfinite(values).all():
                        raise ContractError("corrected O4a calibration context is invalid")
                    gap = reader.gaps.get((detector_value, context_start, context_end))
                    provenance = _context_provenance(
                        context,
                        acquired_record=None if gap is None else gap[1],
                    )
                    futures.append(
                        pool.submit(
                            _worker_preprocess,
                            values,
                            float(context.series.t0.value),
                            float(context.series.dt.value),
                            str(context.series.name),
                            float(row["analysis_gps_start"]),
                            float(row["analysis_gps_start"]) + 32.0,
                            True,
                        )
                    )
                    prepared.append(
                        {
                            "row": row,
                            "raw_strain_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                            "sources": provenance,
                        }
                    )
                images = []
                for future in futures:
                    _gps, image = future.result()
                    if image is None or image.shape != (256, 256, 3):
                        raise ContractError("corrected O4a calibration preprocessing failed")
                    images.append(image)
                scores = _score_only(scorer, images)
                for item, image, score in zip(prepared, images, scores, strict=True):
                    row = item["row"]
                    historical = np.frombuffer(
                        bytes.fromhex(row["historical_score_float32_hex"]), dtype=np.float32
                    )[0]
                    output_rows.append(
                        {
                            "session_id": session_id,
                            "detector": detector,
                            "catalog_gps_start": float(row["catalog_gps_start"]),
                            "analysis_gps_start": float(row["analysis_gps_start"]),
                            "coverage_in_frozen_raw_manifest": row[
                                "coverage_in_frozen_raw_manifest"
                            ],
                            "historical_primary_score": float(historical),
                            "corrected_primary_score": float(score),
                            "corrected_score_float32_hex": np.float32(score).tobytes().hex(),
                            "absolute_historical_delta": abs(float(score) - float(historical)),
                            "raw_strain_sha256": item["raw_strain_sha256"],
                            "image_sha256": hashlib.sha256(
                                np.ascontiguousarray(image).tobytes()
                            ).hexdigest(),
                            "sources": item["sources"],
                        }
                    )
        scores = np.asarray(
            [row["corrected_primary_score"] for row in output_rows], dtype=np.float64
        )
        single_deltas = [
            float(row["absolute_historical_delta"])
            for row in output_rows
            if row["coverage_in_frozen_raw_manifest"] == "complete_single_file"
        ]
        if single_deltas and max(single_deltas) > SCORE_ATOL:
            failure = {
                "schema_version": SCHEMA_VERSION,
                "status": "FAILED_COMPLETE_SINGLE_REPLAY",
                "run_key": run_key,
                "session_id": session_id,
                "detector": detector,
                "score_atol": SCORE_ATOL,
                "max_abs_delta": max(single_deltas),
                "rows_scored": len(output_rows),
            }
            _atomic_json(run_dir / "failure.json", failure)
            raise ContractError(
                "corrected O4a complete-single calibration scores do not "
                f"reproduce in {session_id}_{detector}: "
                f"{max(single_deltas)} > {SCORE_ATOL}"
            )
        shard_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "COMPLETE",
            "run_key": run_key,
            "session_id": session_id,
            "detector": detector,
            "row_count": len(output_rows),
            "empirical_p99": float(np.percentile(scores, 99.0)),
            "threshold_rule": "numpy.percentile(scores, 99.0)",
            "rows": output_rows,
        }
        shard = {**shard_body, "shard_digest": canonical_json_sha256(shard_body)}
        _atomic_json(shard_path, shard)
        shard_values.append(
            _validate_calibration_shard(shard, expected_rows=rows, run_key=run_key)
        )
    summary = _calibration_summary(
        protocol=protocol,
        acquisition=acquisition,
        references=references,
        run_key=run_key,
        run_dir=run_dir,
        shards=shard_values,
    )
    _atomic_json(run_dir / "primary_calibration_summary.json", summary)
    _atomic_json(root / COMPACT_CALIBRATION_REL, summary)
    return summary, run_dir


def _calibration_summary(
    *,
    protocol: Mapping[str, Any],
    acquisition: Mapping[str, Any],
    references: Mapping[str, Any],
    run_key: str,
    run_dir: Path,
    shards: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [row for shard in shards for row in shard["rows"]]
    complete_single = [
        float(row["absolute_historical_delta"])
        for row in rows
        if row["coverage_in_frozen_raw_manifest"] == "complete_single_file"
    ]
    max_single_delta = max(complete_single)
    if max_single_delta > SCORE_ATOL:
        raise ContractError(
            "corrected O4a complete-single calibration scores do not reproduce "
            f"historical values: {max_single_delta} > {SCORE_ATOL}"
        )
    threshold_rows = [
        {
            "session_id": int(shard["session_id"]),
            "detector": str(shard["detector"]),
            "n": int(shard["row_count"]),
            "empirical_p99": float(shard["empirical_p99"]),
            "shard": f"sessions/{shard['session_id']}_{shard['detector']}.json",
            "shard_digest": shard["shard_digest"],
        }
        for shard in sorted(shards, key=lambda item: (item["session_id"], item["detector"]))
    ]
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_COMPLETE_PRIMARY_CALIBRATION",
        "run_key": run_key,
        "protocol_digest": protocol["protocol_digest"],
        "acquisition_manifest_digest": acquisition["manifest_digest"],
        "row_count": len(rows),
        "session_detector_count": len(shards),
        "thresholds": threshold_rows,
        "threshold_digest": canonical_json_sha256(threshold_rows),
        "complete_single_replay": {
            "n": len(complete_single),
            "score_atol": SCORE_ATOL,
            "max_abs_delta": max_single_delta,
            "pass": True,
        },
        "changed_context_counts": {
            kind: sum(row["coverage_in_frozen_raw_manifest"] == kind for row in rows)
            for kind in (
                "complete_only_by_stitch",
                "not_complete_in_frozen_local_manifest",
            )
        },
        "external_run_directory": run_dir.name,
        "references": dict(references),
        "scientific_boundary": {
            "same_frozen_identities_fully_rescored": True,
            "historical_scores_reused": False,
            "post_hoc_threshold_tuning": False,
            "candidate_scan_executed": False,
            "publication_authorized": False,
        },
    }
    if len(rows) != 39_971 or len(shards) != 84:
        raise ContractError("corrected O4a calibration output is incomplete")
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def verify_primary_calibration(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    external_root = external_root.resolve()
    protocol = _load_protocol(root)
    acquisition, _ = _load_acquisition(
        root=root, external_root=external_root, protocol=protocol
    )
    references = _execution_references(root)
    run_key = _calibration_run_key(
        protocol=protocol, acquisition=acquisition, references=references
    )
    run_dir = external_root / f"calibration_{run_key}"
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in iter_calibration_identities(root):
        grouped[(int(row["session_id"]), str(row["detector"]))].append(row)
    shards = []
    for (session_id, detector), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: float(row["catalog_gps_start"]))
        path = run_dir / "sessions" / f"{session_id}_{detector}.json"
        shards.append(
            _validate_calibration_shard(
                json.loads(path.read_text(encoding="utf-8")),
                expected_rows=rows,
                run_key=run_key,
            )
        )
    rebuilt = _calibration_summary(
        protocol=protocol,
        acquisition=acquisition,
        references=references,
        run_key=run_key,
        run_dir=run_dir,
        shards=shards,
    )
    saved = json.loads((run_dir / "primary_calibration_summary.json").read_text(encoding="utf-8"))
    if saved != rebuilt:
        raise ContractError("corrected O4a primary calibration summary is stale")
    return saved, run_dir


class _ScanIdentityLookup:
    """Low-memory detector+GPS lookup matching the frozen identity iterator."""

    def __init__(self, *, root: Path) -> None:
        from src.dante_light.o4a_corrected_protocol import _components, _raw_rows, _session_ids

        self._session_ids = _session_ids
        rows = _raw_rows(root)
        self.rows = {
            detector: [row for row in rows if row["detector"] == detector]
            for detector in ("H1", "L1")
        }
        self.starts = {
            detector: [float(row["gps_start"]) for row in self.rows[detector]]
            for detector in ("H1", "L1")
        }
        self.max_duration = {
            detector: max(float(row["gps_end"]) - float(row["gps_start"]) for row in self.rows[detector])
            for detector in ("H1", "L1")
        }
        self.components = _components(rows)
        self.component_starts = {
            detector: [start for start, _ in self.components[detector]]
            for detector in ("H1", "L1")
        }

    def lookup(self, detector: str, gps: float) -> dict[str, Any]:
        starts = self.starts[detector]
        rows = self.rows[detector]
        right = bisect.bisect_right(starts, gps)
        left = bisect.bisect_left(starts, gps - self.max_duration[detector])
        sources = [
            row
            for row in rows[left:right]
            if float(row["gps_start"]) <= gps
            and gps + 32.0 <= float(row["gps_end"])
            and abs((gps - float(row["gps_start"])) % 32.0) < 1.0e-9
        ]
        if not sources:
            raise ContractError(f"scan output is outside frozen identity set: {detector} {gps}")
        component_index = bisect.bisect_right(self.component_starts[detector], gps) - 1
        component_start, component_end = self.components[detector][component_index]
        required = (gps - 4.0, gps + 36.0)
        complete = component_start <= required[0] and required[1] <= component_end
        sessions = sorted(
            {session for row in sources for session in self._session_ids(row)}
        )
        sources.sort(
            key=lambda row: (
                float(row["gps_end"]) - float(row["gps_start"]),
                float(row["gps_start"]),
                float(row["gps_end"]),
                str(row["sha256"]),
            )
        )
        chosen = sources[0]
        return {
            "detector": detector,
            "analysis_gps_start": gps,
            "duration_s": 32.0,
            "historical_session_ids": sessions,
            "source_span": [float(chosen["gps_start"]), float(chosen["gps_end"])],
            "source_sha256": str(chosen["sha256"]),
            "overlapping_source_count": len(sources),
            "overlapping_source_digest": canonical_json_sha256(
                [
                    {
                        "interval": [float(row["gps_start"]), float(row["gps_end"])],
                        "sha256": str(row["sha256"]),
                    }
                    for row in sources
                ]
            ),
            "required_padded_interval": list(required),
            "context_disposition": (
                "COMPLETE_SYMMETRIC_4S" if complete else "EXCLUDED_COMPONENT_EDGE"
            ),
        }


def _scan_references(root: Path) -> dict[str, dict[str, Any]]:
    references = _execution_references(root)
    references["primary_calibration_summary"] = repository_reference(
        root, root / COMPACT_CALIBRATION_REL
    )
    return references


def _scan_run_key(
    *, protocol: Mapping[str, Any], calibration: Mapping[str, Any], references: Mapping[str, Any]
) -> str:
    return canonical_json_sha256(
        {
            "protocol_digest": protocol["protocol_digest"],
            "calibration_artifact_digest": calibration["artifact_digest"],
            "references": dict(references),
            "stage": "complete_primary_candidate_scan",
        }
    )


def _open_scan_database(path: Path, *, identity: Mapping[str, Any]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS windows (
          detector TEXT NOT NULL,
          gps_start REAL NOT NULL,
          primary_score REAL NOT NULL,
          score_float32_hex TEXT NOT NULL,
          session_ids_json TEXT NOT NULL,
          passing_session INTEGER,
          is_candidate INTEGER NOT NULL,
          identity_digest TEXT NOT NULL,
          image_sha256 TEXT NOT NULL,
          mil_vector BLOB,
          top_k_indices BLOB,
          patch_anomaly_scores BLOB,
          PRIMARY KEY(detector, gps_start)
        ) WITHOUT ROWID
        """
    )
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
    existing = connection.execute("SELECT value FROM metadata WHERE key='run_identity'").fetchone()
    if existing is None:
        connection.execute("INSERT INTO metadata(key,value) VALUES('run_identity',?)", (encoded,))
        connection.commit()
    elif existing[0] != encoded:
        connection.close()
        raise ContractError("corrected O4a scan database run-key collision")
    return connection


def _threshold_map(calibration: Mapping[str, Any]) -> dict[tuple[int, str], float]:
    result = {
        (int(row["session_id"]), str(row["detector"])): float(row["empirical_p99"])
        for row in calibration["thresholds"]
    }
    if len(result) != 84:
        raise ContractError("corrected O4a scan lacks all session thresholds")
    return result


def run_primary_scan(
    *,
    root: Path = ROOT,
    raw_root: Path = Path("E:/o4a"),
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
    workers: int = 2,
    batch_size: int = 16,
) -> tuple[dict[str, Any], Path]:
    """Run the frozen unique-window primary scan with transactional output."""

    from src.core.patch_producer import PatchProducer

    root = root.resolve()
    raw_root = raw_root.resolve()
    external_root = external_root.resolve()
    protocol = _load_protocol(root)
    calibration, _ = verify_primary_calibration(root=root, external_root=external_root)
    references = _scan_references(root)
    run_key = _scan_run_key(
        protocol=protocol, calibration=calibration, references=references
    )
    run_dir = external_root / f"primary_scan_{run_key}"
    identity = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "protocol_digest": protocol["protocol_digest"],
        "calibration_artifact_digest": calibration["artifact_digest"],
        "references": references,
        "device_request": device,
        "workers": workers,
        "batch_size": batch_size,
    }
    identity_path = run_dir / "run_identity.json"
    if identity_path.is_file():
        if json.loads(identity_path.read_text(encoding="utf-8")) != identity:
            raise ContractError("corrected O4a primary scan run-key collision")
    else:
        _atomic_json(identity_path, identity)
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError(f"corrected O4a primary scan has a recorded failure: {failure_path}")
    database_path = run_dir / "primary_scan.sqlite"
    connection = _open_scan_database(database_path, identity=identity)
    thresholds = _threshold_map(calibration)
    lookup = _ScanIdentityLookup(root=root)
    scorer = _primary_scorer(root=root, protocol=protocol, device=device)
    for detector in ("H1", "L1"):
        seen = {
            float(row[0])
            for row in connection.execute(
                "SELECT gps_start FROM windows WHERE detector=?", (detector,)
            )
        }
        producer = PatchProducer(
            raw_root,
            detector,
            workers=workers,
            batch_size=batch_size,
            raw_manifest=root
            / "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl",
            raw_root=raw_root,
            manifest_targets=True,
            incomplete_context_policy="record_and_skip",
        )
        if seen:
            producer.resume_gps = max(seen)
        for gps_batch, images in producer:
            fresh = [index for index, gps in enumerate(gps_batch) if float(gps) not in seen]
            if not fresh:
                continue
            fresh_gps = [float(gps_batch[index]) for index in fresh]
            fresh_images = [images[index] for index in fresh]
            identities = [lookup.lookup(detector, gps) for gps in fresh_gps]
            if any(row["context_disposition"] != "COMPLETE_SYMMETRIC_4S" for row in identities):
                raise ContractError("producer emitted a frozen component-edge exclusion")
            tokens = scorer.encode_patch_tokens(fresh_images)
            score_rows = scorer.score_patch_tokens(tokens, 1.0, output_mode="score_only")
            scores = [float(row["novelty_score"]) for row in score_rows]
            candidate_indices = []
            passing_sessions_by_index: dict[int, list[int]] = {}
            for index, (row, score) in enumerate(zip(identities, scores, strict=True)):
                passing = [
                    session_id
                    for session_id in row["historical_session_ids"]
                    if score > thresholds[(int(session_id), detector)]
                ]
                if passing:
                    candidate_indices.append(index)
                    passing_sessions_by_index[index] = passing
            full_by_index: dict[int, dict[str, Any]] = {}
            if candidate_indices:
                import torch

                selection = torch.as_tensor(candidate_indices, device=tokens.device)
                selected = tokens.index_select(0, selection)
                full_rows = scorer.score_patch_tokens(selected, 1.0, output_mode="full")
                for index, full in zip(candidate_indices, full_rows, strict=True):
                    if abs(float(full["novelty_score"]) - scores[index]) > SCORE_ATOL:
                        raise ContractError("candidate full/score-only paths diverged")
                    full_by_index[index] = full
            records = []
            for index, (gps, image, row, score) in enumerate(
                zip(fresh_gps, fresh_images, identities, scores, strict=True)
            ):
                full = full_by_index.get(index)
                passing = passing_sessions_by_index.get(index, [])
                records.append(
                    (
                        detector,
                        gps,
                        score,
                        np.float32(score).tobytes().hex(),
                        json.dumps(row["historical_session_ids"], separators=(",", ":")),
                        min(passing) if passing else None,
                        1 if passing else 0,
                        canonical_json_sha256(row),
                        hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest(),
                        None
                        if full is None
                        else np.ascontiguousarray(full["mil_vector"], dtype=np.float32).tobytes(),
                        None
                        if full is None
                        else np.ascontiguousarray(full["top_k_indices"], dtype=np.int32).tobytes(),
                        None
                        if full is None
                        else np.ascontiguousarray(full["patch_anomaly_scores"], dtype=np.float32).tobytes(),
                    )
                )
            with connection:
                connection.executemany(
                    """
                    INSERT INTO windows(
                      detector,gps_start,primary_score,score_float32_hex,
                      session_ids_json,passing_session,is_candidate,identity_digest,
                      image_sha256,mil_vector,top_k_indices,patch_anomaly_scores
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    records,
                )
            seen.update(fresh_gps)
    counts = {
        detector: int(
            connection.execute(
                "SELECT COUNT(*) FROM windows WHERE detector=?", (detector,)
            ).fetchone()[0]
        )
        for detector in ("H1", "L1")
    }
    expected = protocol["scan_population"]["eligible_counts"]
    if counts != expected:
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAILED_CARDINALITY",
            "run_key": run_key,
            "actual_counts": counts,
            "expected_counts": expected,
        }
        _atomic_json(failure_path, failure)
        connection.close()
        raise ContractError(f"corrected O4a scan cardinality mismatch: {counts} != {expected}")
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    summary = verify_primary_scan(
        root=root,
        external_root=external_root,
        database_path=database_path,
        expected_run_key=run_key,
        write_summary=False,
    )[0]
    _atomic_json(run_dir / "primary_scan_summary.json", summary)
    _atomic_json(root / COMPACT_SCAN_REL, summary)
    return summary, run_dir


def verify_primary_scan(
    *,
    root: Path = ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    database_path: Path | None = None,
    expected_run_key: str | None = None,
    write_summary: bool = True,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    external_root = external_root.resolve()
    protocol = _load_protocol(root)
    calibration, _ = verify_primary_calibration(root=root, external_root=external_root)
    references = _scan_references(root)
    run_key = _scan_run_key(
        protocol=protocol, calibration=calibration, references=references
    )
    if expected_run_key is not None and run_key != expected_run_key:
        raise ContractError("corrected O4a primary scan run key changed during execution")
    run_dir = external_root / f"primary_scan_{run_key}"
    path = database_path or (run_dir / "primary_scan.sqlite")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    meta = connection.execute("SELECT value FROM metadata WHERE key='run_identity'").fetchone()
    if meta is None or json.loads(meta[0])["run_key"] != run_key:
        connection.close()
        raise ContractError("corrected O4a primary scan database identity mismatch")
    cursor = connection.execute(
        "SELECT detector,gps_start,primary_score,score_float32_hex,session_ids_json,"
        "passing_session,is_candidate,identity_digest,mil_vector,top_k_indices,"
        "patch_anomaly_scores FROM windows ORDER BY detector,gps_start"
    )
    threshold = _threshold_map(calibration)
    candidate_counts = Counter()
    counts = Counter()
    db_rows = iter(cursor)
    for expected in iter_scan_identities(root):
        actual = next(db_rows, None)
        if actual is None:
            connection.close()
            raise ContractError("corrected O4a primary scan database is truncated")
        detector, gps, score, score_hex, sessions_json, passing, is_candidate, identity_digest, mil, topk, patch = actual
        if (detector, float(gps)) != (
            expected["detector"],
            float(expected["analysis_gps_start"]),
        ):
            connection.close()
            raise ContractError("corrected O4a primary scan identity ordering mismatch")
        score = float(score)
        sessions = json.loads(sessions_json)
        expected_passing = [
            int(session_id)
            for session_id in sessions
            if score > threshold[(int(session_id), str(detector))]
        ]
        candidate = bool(expected_passing)
        if (
            sessions != expected["historical_session_ids"]
            or identity_digest != canonical_json_sha256(expected)
            or score_hex != np.float32(score).tobytes().hex()
            or bool(is_candidate) != candidate
            or passing != (min(expected_passing) if expected_passing else None)
            or (candidate and (mil is None or topk is None or patch is None))
            or (not candidate and (mil is not None or topk is not None or patch is not None))
        ):
            connection.close()
            raise ContractError("corrected O4a primary scan row contract mismatch")
        if candidate:
            if (
                len(mil) != 384 * 4
                or len(topk) != int(protocol["representation"]["top_k"]) * 4
                or len(patch) != 1369 * 4
            ):
                connection.close()
                raise ContractError("corrected O4a primary candidate tensor shape mismatch")
            candidate_counts[str(detector)] += 1
        counts[str(detector)] += 1
    if next(db_rows, None) is not None:
        connection.close()
        raise ContractError("corrected O4a primary scan database has extra rows")
    connection.close()
    if dict(counts) != protocol["scan_population"]["eligible_counts"]:
        raise ContractError("corrected O4a primary scan final counts mismatch")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_COMPLETE_PRIMARY_SCAN",
        "run_key": run_key,
        "protocol_digest": protocol["protocol_digest"],
        "calibration_artifact_digest": calibration["artifact_digest"],
        "window_counts": dict(counts),
        "window_total": sum(counts.values()),
        "candidate_counts": {
            detector: int(candidate_counts[detector]) for detector in ("H1", "L1")
        },
        "candidate_total": sum(candidate_counts.values()),
        "database": {
            "filename": path.name,
            "sha256": sha256_path(path),
            "size_bytes": path.stat().st_size,
        },
        "excluded_component_edge_total": protocol["scan_population"][
            "excluded_component_edge_total"
        ],
        "excluded_component_edge_digest": protocol["scan_population"][
            "excluded_identity_jsonl_sha256"
        ],
        "invalid_or_silent_drop_count": 0,
        "references": references,
        "scientific_boundary": {
            "primary_discovery_only": True,
            "native_classification_executed": False,
            "taxonomy_coincidence_PEM_executed": False,
            "publication_authorized": False,
        },
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    if write_summary:
        saved = json.loads((run_dir / "primary_scan_summary.json").read_text(encoding="utf-8"))
        if saved != summary:
            raise ContractError("corrected O4a primary scan summary is stale")
    return summary, run_dir
