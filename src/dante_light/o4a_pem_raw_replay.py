"""Versioned official-frame replay for diagnostic O4a PEM event contexts.

This does not replace the historic local-HDF5 receipt. It independently
verifies the numerical samples used by each frozen historical PEM target.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import h5py
import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_pem_raw_replay_v1.json")
FRAME_NAME = re.compile(r"(?P<initial>[HL])-(?P<detector>[HL]1)_GWOSC_O4a_4KHZ_R1-(?P<start>\d+)-4096\.hdf5")
MANIFEST_LINE = re.compile(r"(?P<md5>[0-9a-f]{32})\s+(?P<path>[HL]1/\d+/[^\s]+)")
HEX64 = re.compile(r"[0-9a-f]{64}")


def _file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_bytes(path, (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _atomic_bytes(path, "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows).encode())


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _host_path(value: str) -> Path:
    if re.fullmatch(r"[A-Za-z]:/.*", value) and os.name != "nt":
        return Path("/mnt") / value[0].lower() / value[3:]
    return Path(value)


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    contract = json.loads((root / CONTRACT_REL).read_text(encoding="utf-8"))
    body = dict(contract)
    digest = body.pop("contract_digest", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("O4a PEM raw-replay contract digest mismatch")
    if contract.get("contract_id") != "dante-o4a-pem-raw-replay-v1" or contract.get("schema_version") != 1:
        raise ContractError("O4a PEM raw-replay contract identity changed")
    policy = contract["provenance_policy"]
    if policy != {
        "historic_local_file_sha256": "RECORD_ONLY_NOT_A_PASS_GATE",
        "official_file_md5": "MATCH_PUBLISHED_MANIFEST",
        "official_file_sha256": "RECORD_AND_REVERIFY",
        "historical_context_sha256": "EXACT_FLOAT64_BYTES_EACH_TARGET",
        "historical_receipts_immutable": True,
        "diagnostic_only": True,
    }:
        raise ContractError("O4a PEM raw-replay provenance policy changed")
    source = contract["source"]
    if source["release"] != "O4a_4KHZ_R1" or source["manifest_url"] != "https://gwosc.org/archive/md5/O4a_4KHZ_R1/strain-hdf.txt" or source["archive_url_prefix"] != "https://gwosc.org/archive/data/O4a_4KHZ_R1/":
        raise ContractError("O4a PEM raw-replay release changed")
    if source["frame_duration_s"] != 4096 or source["sample_rate_hz"] != 4096 or source["context_duration_s"] != 40 or source["context_lead_s"] != 4:
        raise ContractError("O4a PEM raw-replay geometry changed")
    if source["strain_channel"] != {"H1": "H1:GDS-CALIB_STRAIN_CLEAN_AR", "L1": "L1:GDS-CALIB_STRAIN_CLEAN_AR"} or source["frame_type"] != {"H1": "H1_HOFT_C00_AR", "L1": "L1_HOFT_C00_AR"}:
        raise ContractError("O4a PEM raw-replay calibration product changed")
    return contract


def load_targets(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    ref = contract["historical_targets"]
    path = _host_path(str(ref["path"]))
    if not path.is_file() or sha256_file(path) != ref["sha256"]:
        raise ContractError("historical O4a PEM target ledger changed or is unavailable")
    targets = _jsonl(path)
    if len(targets) != int(ref["expected_count"]):
        raise ContractError("historical O4a PEM target count changed")
    identities: set[tuple[str, float, str]] = set()
    rate = int(contract["source"]["sample_rate_hz"])
    lead = int(contract["source"]["context_lead_s"])
    duration = int(contract["source"]["context_duration_s"])
    for target in targets:
        detector, gps, population = target["detector"], float(target["gps_start"]), target["population"]
        identity = (detector, gps, population)
        if detector not in ("H1", "L1") or population not in ("primary", "diagnostic") or identity in identities:
            raise ContractError("historical O4a PEM target identity invalid or duplicated")
        identities.add(identity)
        if not HEX64.fullmatch(str(target["raw_context_sha256"])):
            raise ContractError("historical O4a PEM context digest invalid")
        cursor = gps - lead
        sources = target["context_sources"]
        if not sources:
            raise ContractError("historical O4a PEM target lacks context source")
        for source in sources:
            relative = Path(str(source["relative_path"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise ContractError("historical O4a PEM context path escaped root")
            match = re.fullmatch(r"([HL]1)_(\d+)_(\d+)\.hdf5", relative.name)
            if match is None or match.group(1) != detector:
                raise ContractError("historical O4a PEM context filename invalid")
            start, end = (int(match.group(i)) for i in (2, 3))
            if end - start != int(contract["source"]["frame_duration_s"]) or source["block_interval"] != [float(start), float(end)]:
                raise ContractError("historical O4a PEM block interval invalid")
            used_start, used_end = (float(value) for value in source["used_interval"])
            if used_start != cursor or used_end <= used_start or used_start < start or used_end > end or (used_end - used_start) * rate != round((used_end - used_start) * rate):
                raise ContractError("historical O4a PEM used interval invalid")
            if not HEX64.fullmatch(str(source["sha256"])):
                raise ContractError("historical O4a PEM local-file digest invalid")
            cursor = used_end
        if cursor != gps - lead + duration:
            raise ContractError("historical O4a PEM target context is incomplete")
    return targets


def parse_manifest(data: bytes, release: str) -> dict[tuple[str, int], dict[str, str]]:
    rows: dict[tuple[str, int], dict[str, str]] = {}
    for line in data.decode("ascii").splitlines():
        match = MANIFEST_LINE.fullmatch(line.strip())
        if match is None:
            raise ContractError("GWOSC published checksum manifest has an invalid row")
        relative = match.group("path")
        name = FRAME_NAME.fullmatch(Path(relative).name)
        if name is None or name.group("detector") != relative[:2] or name.group("initial") != relative[0]:
            raise ContractError("GWOSC published checksum frame identity invalid")
        key = name.group("detector"), int(name.group("start"))
        if key in rows:
            raise ContractError("GWOSC published checksum frame duplicated")
        rows[key] = {"relative_path": relative, "md5": match.group("md5"), "release": release}
    if not rows:
        raise ContractError("GWOSC published checksum manifest is empty")
    return rows


def _coverage(
    detector: str,
    start: float,
    end: float,
    frames: Mapping[tuple[str, int], Any],
    duration: int,
) -> list[tuple[tuple[str, int], float, float]]:
    starts = sorted(gps for ifo, gps in frames if ifo == detector)
    pieces: list[tuple[tuple[str, int], float, float]] = []
    cursor = start
    while cursor < end:
        position = bisect_right(starts, cursor) - 1
        if position < 0 or cursor >= starts[position] + duration:
            raise ContractError("official O4a release has a gap in a historical PEM context")
        frame_start = starts[position]
        piece_end = min(end, frame_start + duration)
        pieces.append(((detector, frame_start), cursor, piece_end))
        cursor = piece_end
    return pieces


def required_frames(targets: Sequence[Mapping[str, Any]], manifest: Mapping[tuple[str, int], Mapping[str, str]]) -> list[dict[str, str | int]]:
    frames: dict[tuple[str, int], dict[str, str | int]] = {}
    historic_sha: dict[str, str] = {}
    for target in targets:
        detector = str(target["detector"])
        for source in target["context_sources"]:
            local_path, local_sha = str(source["relative_path"]), str(source["sha256"])
            if local_path in historic_sha and historic_sha[local_path] != local_sha:
                raise ContractError("historical O4a PEM file receipt inconsistent")
            historic_sha[local_path] = local_sha
            for key, _, _ in _coverage(detector, *source["used_interval"], manifest, 4096):
                frames[key] = {"detector": detector, "gps_start": key[1], **manifest[key]}
    return [frames[key] for key in sorted(frames)]


def validate_frame(path: Path, frame: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    if not path.is_file() or _file_digest(path, "md5") != frame["md5"]:
        raise ContractError("official O4a frame MD5 does not match GWOSC manifest")
    start = int(frame["gps_start"])
    detector = str(frame["detector"])
    with h5py.File(path, "r") as handle:
        meta = handle.get("meta")
        dataset = handle.get("strain/Strain")
        if meta is None or dataset is None:
            raise ContractError("official O4a frame HDF5 structure invalid")
        def meta_value(key: str) -> str:
            value = meta[key][()]
            return value.decode() if isinstance(value, bytes) else str(value)
        if meta_value("Detector") != detector or meta_value("GPSstart") != str(start) or meta_value("Duration") != str(source["frame_duration_s"]) or meta_value("FrameType") != source["frame_type"][detector] or meta_value("StrainChannel") != source["strain_channel"][detector]:
            raise ContractError("official O4a frame release/calibration metadata mismatch")
        if dataset.shape != (int(source["frame_duration_s"] * source["sample_rate_hz"]),) or dataset.dtype != np.dtype("float64") or float(dataset.attrs["Xstart"]) != start or float(dataset.attrs["Xspacing"]) != 1 / int(source["sample_rate_hz"]):
            raise ContractError("official O4a frame geometry mismatch")
    return {**frame, "sha256": _file_digest(path, "sha256"), "size_bytes": path.stat().st_size}


def context_digest(target: Mapping[str, Any], frame_paths: Mapping[tuple[str, int], Path], source: Mapping[str, Any]) -> str:
    rate = int(source["sample_rate_hz"])
    parts: list[np.ndarray] = []
    for item in target["context_sources"]:
        for key, used_start, used_end in _coverage(
            str(target["detector"]),
            float(item["used_interval"][0]),
            float(item["used_interval"][1]),
            frame_paths,
            int(source["frame_duration_s"]),
        ):
            path = frame_paths[key]
            first = int(round((used_start - key[1]) * rate))
            last = int(round((used_end - key[1]) * rate))
            with h5py.File(path, "r") as handle:
                values = np.asarray(handle["strain/Strain"][first:last], dtype=np.float64)
            if len(values) != last - first or not np.isfinite(values).all():
                raise ContractError("official O4a PEM context is incomplete or nonfinite")
            parts.append(values)
    raw = np.ascontiguousarray(np.concatenate(parts))
    if raw.shape != (int(source["context_duration_s"] * rate),):
        raise ContractError("official O4a PEM context shape mismatch")
    digest = hashlib.sha256(raw.tobytes()).hexdigest()
    if digest != target["raw_context_sha256"]:
        raise ContractError("official O4a PEM numerical context differs from historical target")
    return digest


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as output, urlopen(url, timeout=90) as response:
            while chunk := response.read(8 * 1024 * 1024):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def run_replay(*, root: Path = ROOT, external_root: Path) -> tuple[dict[str, Any], Path]:
    contract = load_contract(root)
    targets = load_targets(contract)
    manifest_url = contract["source"]["manifest_url"]
    with urlopen(manifest_url, timeout=60) as response:
        manifest_bytes = response.read()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = parse_manifest(manifest_bytes, contract["source"]["release"])
    frames = required_frames(targets, manifest)
    run_key = canonical_json_sha256({"contract_digest": contract["contract_digest"], "target_sha256": contract["historical_targets"]["sha256"], "manifest_sha256": manifest_sha})
    run_dir = external_root.resolve() / f"raw_replay_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "summary.json").exists():
        return verify_replay(root=root, run_dir=run_dir), run_dir
    snapshot = run_dir / "gwosc_strain_hdf_md5.txt"
    if snapshot.exists():
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != manifest_sha:
            raise ContractError("GWOSC manifest snapshot changed")
    else:
        _atomic_bytes(snapshot, manifest_bytes)
    frame_paths: dict[tuple[str, int], Path] = {}
    receipts: list[dict[str, Any]] = []
    for index, frame in enumerate(frames, start=1):
        relative = Path(str(frame["relative_path"]))
        destination = run_dir / "frames" / relative
        if not destination.is_file():
            _download(contract["source"]["archive_url_prefix"] + relative.as_posix(), destination)
        receipt = validate_frame(destination, frame, contract["source"])
        receipts.append({**receipt, "url": contract["source"]["archive_url_prefix"] + relative.as_posix()})
        frame_paths[(str(frame["detector"]), int(frame["gps_start"]))] = destination
        _atomic_json(run_dir / "progress.json", {"status": "RUNNING", "frames_verified": index, "frames_total": len(frames), "targets_verified": 0, "targets_total": len(targets)})
    target_receipts = []
    for index, target in enumerate(targets, start=1):
        digest = context_digest(target, frame_paths, contract["source"])
        target_receipts.append({"detector": target["detector"], "gps_start": target["gps_start"], "population": target["population"], "identity_digest": target["identity_digest"], "context_sha256": digest, "historic_local_sources": [{"relative_path": item["relative_path"], "sha256": item["sha256"]} for item in target["context_sources"]]})
        _atomic_json(run_dir / "progress.json", {"status": "RUNNING", "frames_verified": len(frames), "frames_total": len(frames), "targets_verified": index, "targets_total": len(targets)})
    _atomic_jsonl(run_dir / "frames.jsonl", receipts)
    _atomic_jsonl(run_dir / "targets.jsonl", target_receipts)
    summary = {"schema_version": 1, "status": "PASS_COMPLETE_O4A_PEM_RAW_REPLAY", "run_key": run_key, "contract_digest": contract["contract_digest"], "historical_target_sha256": contract["historical_targets"]["sha256"], "manifest_sha256": manifest_sha, "frame_count": len(receipts), "target_count": len(target_receipts), "frame_receipts_sha256": sha256_file(run_dir / "frames.jsonl"), "target_receipts_sha256": sha256_file(run_dir / "targets.jsonl"), "historical_local_file_byte_parity_claimed": False, "diagnostic_only": True}
    _atomic_json(run_dir / "summary.json", summary)
    _atomic_json(run_dir / "progress.json", {"status": "COMPLETE", "frames_verified": len(frames), "frames_total": len(frames), "targets_verified": len(targets), "targets_total": len(targets)})
    return summary, run_dir


def verify_replay(*, root: Path = ROOT, run_dir: Path) -> dict[str, Any]:
    contract = load_contract(root)
    targets = load_targets(contract)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    manifest_bytes = (run_dir / "gwosc_strain_hdf_md5.txt").read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = parse_manifest(manifest_bytes, contract["source"]["release"])
    frames = required_frames(targets, manifest)
    expected_key = canonical_json_sha256({"contract_digest": contract["contract_digest"], "target_sha256": contract["historical_targets"]["sha256"], "manifest_sha256": manifest_sha})
    if run_dir.name != f"raw_replay_{expected_key}" or summary["run_key"] != expected_key or summary["contract_digest"] != contract["contract_digest"] or summary["manifest_sha256"] != manifest_sha or summary["historical_target_sha256"] != contract["historical_targets"]["sha256"]:
        raise ContractError("O4a PEM raw-replay identity changed")
    frame_rows = _jsonl(run_dir / "frames.jsonl")
    target_rows = _jsonl(run_dir / "targets.jsonl")
    if len(frame_rows) != len(frames) or len(target_rows) != len(targets) or summary["frame_count"] != len(frames) or summary["target_count"] != len(targets) or sha256_file(run_dir / "frames.jsonl") != summary["frame_receipts_sha256"] or sha256_file(run_dir / "targets.jsonl") != summary["target_receipts_sha256"]:
        raise ContractError("O4a PEM raw-replay receipt cardinality or seal changed")
    paths: dict[tuple[str, int], Path] = {}
    for frozen, receipt in zip(frames, frame_rows, strict=True):
        relative = Path(str(frozen["relative_path"]))
        path = run_dir / "frames" / relative
        replayed = validate_frame(path, frozen, contract["source"])
        if receipt != {**replayed, "url": contract["source"]["archive_url_prefix"] + relative.as_posix()}:
            raise ContractError("O4a PEM raw-replay frame receipt changed")
        paths[(str(frozen["detector"]), int(frozen["gps_start"]))] = path
    for target, receipt in zip(targets, target_rows, strict=True):
        digest = context_digest(target, paths, contract["source"])
        expected = {"detector": target["detector"], "gps_start": target["gps_start"], "population": target["population"], "identity_digest": target["identity_digest"], "context_sha256": digest, "historic_local_sources": [{"relative_path": item["relative_path"], "sha256": item["sha256"]} for item in target["context_sources"]]}
        if receipt != expected:
            raise ContractError("O4a PEM raw-replay target receipt changed")
    if summary["status"] != "PASS_COMPLETE_O4A_PEM_RAW_REPLAY" or summary["historical_local_file_byte_parity_claimed"] is not False or summary["diagnostic_only"] is not True:
        raise ContractError("O4a PEM raw-replay interpretation changed")
    return {**summary, "status": "PASS_VERIFIED_O4A_PEM_RAW_REPLAY"}
