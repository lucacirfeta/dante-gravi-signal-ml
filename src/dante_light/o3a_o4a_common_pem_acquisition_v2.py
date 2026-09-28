"""Versioned frame-byte acquisition with a probe inside a planned span.

The v1 frame-start probe could inspect samples outside every selected
background span. Its failed run and source stay frozen. This transport-only
adapter changes only the deterministic location of the one-second probe.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_o4a_common_pem_acquisition import (
    _atomic_json,
    _receipt_path,
    required_frames,
    sealed_json,
)
from src.dante_light.o3a_o4a_common_pem_background import (
    OfficialBackgroundReader,
    verify_background_receipt,
)


def required_frames_with_probes(
    spans: Sequence[Mapping[str, Any]],
    *,
    manifest: Mapping[tuple[str, int], Mapping[str, Any]],
    frame_duration_s: int,
) -> list[dict[str, Any]]:
    """Bind each frame to the earliest planned, one-second span overlap."""
    frames = required_frames(
        spans, manifest=manifest, frame_duration_s=frame_duration_s
    )
    selected: list[dict[str, Any]] = []
    for frame in frames:
        frame_start = int(frame["gps_start"])
        frame_end = frame_start + frame_duration_s
        starts = [
            max(frame_start, int(span["interval_gps"][0]))
            for span in spans
            if span["detector"] == frame["detector"]
            and max(frame_start, int(span["interval_gps"][0]))
            < min(frame_end, int(span["interval_gps"][1]))
        ]
        if not starts:
            raise ContractError("common PEM v2 frame has no planned span overlap")
        probe_start = min(starts)
        selected.append({**frame, "probe_interval_gps": [probe_start, probe_start + 1]})
    return selected


def verify_frame_v2(
    frame: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    manifest: Mapping[tuple[str, int], Mapping[str, Any]],
    run_dir: Path,
) -> dict[str, Any]:
    """Replay the sealed probe from official bytes, including its position."""
    path = _receipt_path(run_dir, frame)
    if not path.is_file():
        raise ContractError("common PEM v2 frame receipt is missing")
    receipt = sealed_json(path)
    expected = {
        "status": "PASS_ACQUIRED_OFFICIAL_FRAME_BYTES_V2_ONLY",
        "release": source["release"],
        "frame": dict(frame),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ContractError("common PEM v2 frame receipt identity changed")
    probe = receipt.get("probe")
    if not isinstance(probe, Mapping) or probe.get("interval_gps") != frame.get(
        "probe_interval_gps"
    ):
        raise ContractError("common PEM v2 frame probe position changed")
    verified = verify_background_receipt(
        probe,
        source=source,
        manifest=manifest,
        cache_dir=run_dir / "frames",
    )
    if verified["status"] != "PASS_VERIFIED_BACKGROUND_SPAN":
        raise ContractError("common PEM v2 frame probe replay failed")
    return receipt


def acquire_frame_v2(
    frame: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    manifest: Mapping[tuple[str, int], Mapping[str, Any]],
    run_dir: Path,
) -> dict[str, Any]:
    """Acquire a frame once; fail closed on any existing unverified receipt."""
    path = _receipt_path(run_dir, frame)
    if path.exists():
        return verify_frame_v2(frame, source=source, manifest=manifest, run_dir=run_dir)
    probe_start, probe_end = frame["probe_interval_gps"]
    reader = OfficialBackgroundReader(
        source=source,
        manifest=manifest,
        cache_dir=run_dir / "frames",
    )
    reader(str(frame["detector"]), int(probe_start), int(probe_end))
    probe = reader.receipts[-1]
    verify_background_receipt(
        probe, source=source, manifest=manifest, cache_dir=run_dir / "frames"
    )
    body = {
        "status": "PASS_ACQUIRED_OFFICIAL_FRAME_BYTES_V2_ONLY",
        "release": source["release"],
        "frame": dict(frame),
        "probe": probe,
    }
    _atomic_json(path, {**body, "receipt_digest": canonical_json_sha256(body)})
    return verify_frame_v2(frame, source=source, manifest=manifest, run_dir=run_dir)
