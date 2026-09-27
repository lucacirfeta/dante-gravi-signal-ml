"""O4a PEM context replay with the published manifest-to-download URL mapping.

The v1 runner and its failed, zero-frame run remain historical evidence. Only
the transport URL mapping changes; frame and context validation are inherited.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.request import urlopen

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_pem_raw_replay import (
    FRAME_NAME,
    ROOT,
    _atomic_bytes,
    _atomic_json,
    _atomic_jsonl,
    _download,
    _jsonl,
    context_digest,
    load_contract as load_v1_contract,
    load_targets,
    parse_manifest,
    required_frames,
    validate_frame,
)

CONTRACT_REL = Path("config/dante_o3a_o4a_pem_raw_replay_v2.json")
URL_POLICY = "REMOVE_LEADING_DETECTOR_DIRECTORY"
COMPLETE = "PASS_COMPLETE_O4A_PEM_RAW_REPLAY_V2"
VERIFIED = "PASS_VERIFIED_O4A_PEM_RAW_REPLAY_V2"


def validate_contract(contract: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    """Require exact v1 scientific inputs plus the single approved URL rule."""
    body = deepcopy(contract)
    digest = body.pop("contract_digest", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("O4a PEM raw-replay v2 contract digest mismatch")
    previous = deepcopy(load_v1_contract(root))
    previous.pop("contract_digest")
    previous["contract_id"] = "dante-o4a-pem-raw-replay-v2"
    previous["schema_version"] = 2
    previous["source"]["manifest_download_url_policy"] = URL_POLICY
    if body != previous:
        raise ContractError("O4a PEM raw-replay v2 changes more than URL mapping")
    return contract


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_contract(
        json.loads((root / CONTRACT_REL).read_text(encoding="utf-8")), root=root
    )


def archive_url(frame: dict[str, Any], source: dict[str, Any]) -> str:
    """Manifest ``H1/epoch/file`` maps to GWOSC ``epoch/file`` only."""
    if source.get("manifest_download_url_policy") != URL_POLICY:
        raise ContractError("O4a PEM raw-replay URL policy changed")
    parts = PurePosixPath(str(frame["relative_path"])).parts
    if len(parts) != 3 or parts[0] != frame["detector"] or not parts[1].isdigit():
        raise ContractError("GWOSC manifest path cannot map to an archive URL")
    name = FRAME_NAME.fullmatch(parts[2])
    if (
        name is None
        or name.group("detector") != parts[0]
        or int(name.group("start")) != frame["gps_start"]
    ):
        raise ContractError("GWOSC archive URL frame identity mismatch")
    return source["archive_url_prefix"] + parts[1] + "/" + parts[2]


def _run_key(contract: dict[str, Any], manifest_sha: str) -> str:
    return canonical_json_sha256(
        {
            "contract_digest": contract["contract_digest"],
            "target_sha256": contract["historical_targets"]["sha256"],
            "manifest_sha256": manifest_sha,
        }
    )


def run_replay(
    *, root: Path = ROOT, external_root: Path
) -> tuple[dict[str, Any], Path]:
    contract = load_contract(root)
    targets = load_targets(contract)
    with urlopen(contract["source"]["manifest_url"], timeout=60) as response:
        manifest_bytes = response.read()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    frames = required_frames(
        targets, parse_manifest(manifest_bytes, contract["source"]["release"])
    )
    run_key = _run_key(contract, manifest_sha)
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
    frame_receipts: list[dict[str, Any]] = []
    for index, frame in enumerate(frames, start=1):
        relative = Path(str(frame["relative_path"]))
        destination = run_dir / "frames" / relative
        url = archive_url(frame, contract["source"])
        if not destination.is_file():
            _download(url, destination)
        receipt = validate_frame(destination, frame, contract["source"])
        frame_receipts.append({**receipt, "url": url})
        frame_paths[(str(frame["detector"]), int(frame["gps_start"]))] = destination
        _atomic_json(
            run_dir / "progress.json",
            {
                "status": "RUNNING",
                "frames_verified": index,
                "frames_total": len(frames),
                "targets_verified": 0,
                "targets_total": len(targets),
            },
        )
    target_receipts: list[dict[str, Any]] = []
    for index, target in enumerate(targets, start=1):
        digest = context_digest(target, frame_paths, contract["source"])
        target_receipts.append(
            {
                "detector": target["detector"],
                "gps_start": target["gps_start"],
                "population": target["population"],
                "identity_digest": target["identity_digest"],
                "context_sha256": digest,
                "historic_local_sources": [
                    {"relative_path": item["relative_path"], "sha256": item["sha256"]}
                    for item in target["context_sources"]
                ],
            }
        )
        _atomic_json(
            run_dir / "progress.json",
            {
                "status": "RUNNING",
                "frames_verified": len(frames),
                "frames_total": len(frames),
                "targets_verified": index,
                "targets_total": len(targets),
            },
        )
    _atomic_jsonl(run_dir / "frames.jsonl", frame_receipts)
    _atomic_jsonl(run_dir / "targets.jsonl", target_receipts)
    summary = {
        "schema_version": 2,
        "status": COMPLETE,
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "historical_target_sha256": contract["historical_targets"]["sha256"],
        "manifest_sha256": manifest_sha,
        "frame_count": len(frame_receipts),
        "target_count": len(target_receipts),
        "frame_receipts_sha256": sha256_file(run_dir / "frames.jsonl"),
        "target_receipts_sha256": sha256_file(run_dir / "targets.jsonl"),
        "historical_local_file_byte_parity_claimed": False,
        "diagnostic_only": True,
    }
    _atomic_json(run_dir / "summary.json", summary)
    _atomic_json(
        run_dir / "progress.json",
        {
            "status": "COMPLETE",
            "frames_verified": len(frames),
            "frames_total": len(frames),
            "targets_verified": len(targets),
            "targets_total": len(targets),
        },
    )
    return summary, run_dir


def verify_replay(*, root: Path = ROOT, run_dir: Path) -> dict[str, Any]:
    contract = load_contract(root)
    targets = load_targets(contract)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    manifest_bytes = (run_dir / "gwosc_strain_hdf_md5.txt").read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    frames = required_frames(
        targets, parse_manifest(manifest_bytes, contract["source"]["release"])
    )
    if (
        run_dir.name != f"raw_replay_{_run_key(contract, manifest_sha)}"
        or summary["run_key"] != _run_key(contract, manifest_sha)
        or summary["contract_digest"] != contract["contract_digest"]
        or summary["manifest_sha256"] != manifest_sha
        or summary["historical_target_sha256"]
        != contract["historical_targets"]["sha256"]
    ):
        raise ContractError("O4a PEM raw-replay v2 identity changed")
    frame_rows = _jsonl(run_dir / "frames.jsonl")
    target_rows = _jsonl(run_dir / "targets.jsonl")
    if (
        len(frame_rows) != len(frames)
        or len(target_rows) != len(targets)
        or summary["frame_count"] != len(frames)
        or summary["target_count"] != len(targets)
        or sha256_file(run_dir / "frames.jsonl") != summary["frame_receipts_sha256"]
        or sha256_file(run_dir / "targets.jsonl") != summary["target_receipts_sha256"]
    ):
        raise ContractError("O4a PEM raw-replay v2 receipt cardinality or seal changed")
    paths: dict[tuple[str, int], Path] = {}
    for frozen, receipt in zip(frames, frame_rows, strict=True):
        relative = Path(str(frozen["relative_path"]))
        path = run_dir / "frames" / relative
        replayed = validate_frame(path, frozen, contract["source"])
        if receipt != {**replayed, "url": archive_url(frozen, contract["source"])}:
            raise ContractError("O4a PEM raw-replay v2 frame receipt changed")
        paths[(str(frozen["detector"]), int(frozen["gps_start"]))] = path
    for target, receipt in zip(targets, target_rows, strict=True):
        digest = context_digest(target, paths, contract["source"])
        expected = {
            "detector": target["detector"],
            "gps_start": target["gps_start"],
            "population": target["population"],
            "identity_digest": target["identity_digest"],
            "context_sha256": digest,
            "historic_local_sources": [
                {"relative_path": item["relative_path"], "sha256": item["sha256"]}
                for item in target["context_sources"]
            ],
        }
        if receipt != expected:
            raise ContractError("O4a PEM raw-replay v2 target receipt changed")
    if (
        summary["schema_version"] != 2
        or summary["status"] != COMPLETE
        or summary["historical_local_file_byte_parity_claimed"] is not False
        or summary["diagnostic_only"] is not True
    ):
        raise ContractError("O4a PEM raw-replay v2 interpretation changed")
    return {**summary, "status": VERIFIED}
