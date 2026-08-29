"""Input acquisition and resumable execution support for corrected O4a."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_protocol import (
    OUTPUT_REL as PROTOCOL_REL,
    ROOT,
    iter_calibration_identities,
    validate_corrected_protocol,
)
from src.dante_light.prefilter_v5_protocol import repository_reference, sha256_path


SCHEMA_VERSION = 1
DEFAULT_EXTERNAL_ROOT = Path("E:/dante_cache/dante_light/o4a_corrected_v2")
COMPACT_ACQUISITION_REL = "artifacts/dante_light/o4a_v1_parity/corrected_input_acquisition.json"
IMPLEMENTATION_REL = "src/dante_light/o4a_corrected_execution.py"


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
        "implementation_reference": repository_reference(
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
