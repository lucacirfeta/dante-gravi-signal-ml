"""Transport-only acquisition of source-bound PEM background frames.

This stage verifies individual official frame bytes and metadata. It does not
compute a four-hour null, a PEM verdict, or a comparative scientific result.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_o4a_common_pem_background import (
    OfficialBackgroundReader,
    verify_background_receipt,
)
from src.dante_light.o3a_o4a_common_pem_gate import plan_background_frames


def required_frames(
    spans: Sequence[Mapping[str, Any]],
    *,
    manifest: Mapping[tuple[str, int], Mapping[str, Any]],
    frame_duration_s: int,
) -> list[dict[str, Any]]:
    """Select unique official frames without reading strain or PEM outcomes."""
    selected: dict[tuple[str, int], dict[str, Any]] = {}
    for span in spans:
        detector = str(span["detector"])
        start, end = (int(value) for value in span["interval_gps"])
        for piece in plan_background_frames(
            detector=detector,
            start=start,
            end=end,
            manifest=manifest,
            frame_duration_s=frame_duration_s,
        ):
            key = detector, int(piece["gps_start"])
            frame = {
                key: value for key, value in piece.items() if key != "used_interval_gps"
            }
            if key in selected and selected[key] != frame:
                raise ContractError(
                    "common PEM background frame identity is inconsistent"
                )
            selected[key] = frame
    return [selected[key] for key in sorted(selected)]


def _atomic_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                document, stream, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sealed_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ContractError("common PEM acquisition receipt is not an object")
    body = dict(document)
    if body.pop("receipt_digest", None) != canonical_json_sha256(body):
        raise ContractError("common PEM acquisition receipt seal changed")
    return document


def _receipt_path(run_dir: Path, frame: Mapping[str, Any]) -> Path:
    filename = str(frame["filename"])
    if Path(filename).name != filename or not filename.endswith(".hdf5"):
        raise ContractError("common PEM acquisition frame filename is invalid")
    return run_dir / "receipts" / f"{filename}.json"


def verify_frame(
    frame: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    manifest: Mapping[tuple[str, int], Mapping[str, Any]],
    run_dir: Path,
) -> dict[str, Any]:
    """Independently replay a one-second probe of an acquired official frame."""
    path = _receipt_path(run_dir, frame)
    if not path.is_file():
        raise ContractError("common PEM acquisition frame receipt is missing")
    receipt = sealed_json(path)
    expected = {
        "status": "PASS_ACQUIRED_OFFICIAL_FRAME_BYTES_ONLY",
        "release": source["release"],
        "frame": dict(frame),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ContractError("common PEM acquisition frame receipt identity changed")
    start = int(frame["gps_start"])
    probe = receipt.get("probe")
    if not isinstance(probe, Mapping) or probe.get("interval_gps") != [
        start,
        start + 1,
    ]:
        raise ContractError("common PEM acquisition frame probe changed")
    verified = verify_background_receipt(
        probe,
        source=source,
        manifest=manifest,
        cache_dir=run_dir / "frames",
    )
    if verified["status"] != "PASS_VERIFIED_BACKGROUND_SPAN":
        raise ContractError("common PEM acquisition frame replay failed")
    return receipt


def acquire_frame(
    frame: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    manifest: Mapping[tuple[str, int], Mapping[str, Any]],
    run_dir: Path,
) -> dict[str, Any]:
    """Fetch only a missing frame; always verify existing receipts before reuse."""
    path = _receipt_path(run_dir, frame)
    if path.exists():
        return verify_frame(frame, source=source, manifest=manifest, run_dir=run_dir)
    reader = OfficialBackgroundReader(
        source=source,
        manifest=manifest,
        cache_dir=run_dir / "frames",
    )
    start = int(frame["gps_start"])
    reader(str(frame["detector"]), start, start + 1)
    probe = reader.receipts[-1]
    verify_background_receipt(
        probe, source=source, manifest=manifest, cache_dir=run_dir / "frames"
    )
    body = {
        "status": "PASS_ACQUIRED_OFFICIAL_FRAME_BYTES_ONLY",
        "release": source["release"],
        "frame": dict(frame),
        "probe": probe,
    }
    receipt = {**body, "receipt_digest": canonical_json_sha256(body)}
    _atomic_json(path, receipt)
    return verify_frame(frame, source=source, manifest=manifest, run_dir=run_dir)
