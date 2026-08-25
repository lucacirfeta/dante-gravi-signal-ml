#!/usr/bin/env python3
"""Build or verify the outcome-blind DANTE-Light v5 identity audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v5_identity import (
    build_identity_artifact,
    compact_raw_manifest,
    hash_raw_files,
    load_identity_config,
    load_quarantine_record,
    parse_raw_file,
    prior_o4a_blocks,
    validate_identity_artifact,
    validate_hdf5_metadata,
    validate_raw_rows,
)


DEFAULT_CONFIG = ROOT / "config/dante_light_prefilter_v5_identity_audit.json"
DEFAULT_ARTIFACT = (
    ROOT / "artifacts/dante_light/prefilter_l4_v5_design/identity_audit_v5.json"
)
DEFAULT_MANIFEST = (
    ROOT / "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl"
)


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _write_jsonl_atomic(path: Path, rows: list[dict[str, object]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False))
            stream.write("\n")
    os.replace(temporary, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(args: argparse.Namespace) -> dict[str, object]:
    config_path = args.config.resolve()
    artifact_path = args.artifact.resolve()
    manifest_path = args.manifest.resolve()
    raw_root = args.raw_root.resolve()
    cache_root = args.cache_root.resolve()
    if not raw_root.is_dir():
        raise ContractError(f"raw O4a mirror is unavailable: {raw_root}")
    config = load_identity_config(config_path)
    paths = sorted(raw_root.rglob("*.hdf5"), key=lambda path: path.relative_to(raw_root).as_posix())
    identities = [parse_raw_file(raw_root, path) for path in paths]
    physical_rows = hash_raw_files(
        raw_root,
        identities,
        cache_path=cache_root / "raw_file_sha256_cache_v5.json",
        checkpoint_every=args.cache_checkpoint_every,
        force_rehash=not args.reuse_hash_cache,
    )
    validate_raw_rows(physical_rows, detectors=config["raw_mirror_contract"]["detectors"])
    compact_rows = compact_raw_manifest(physical_rows)
    validate_hdf5_metadata(
        raw_root,
        compact_rows,
        sample_rate_hz=int(config["raw_mirror_contract"]["raw_sample_rate_hz"]),
    )
    manifest_sha256 = _write_jsonl_atomic(manifest_path, compact_rows)
    prior_blocks, prior_sources = prior_o4a_blocks(ROOT, config)
    artifact = build_identity_artifact(
        root=ROOT,
        config_path=config_path,
        config=config,
        source_path=ROOT / "src/dante_light/prefilter_v5_identity.py",
        script_path=Path(__file__).resolve(),
        physical_rows=physical_rows,
        compact_rows=compact_rows,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        prior_blocks=prior_blocks,
        prior_sources=prior_sources,
        all_files_rehashed_in_current_run=not args.reuse_hash_cache,
    )
    _write_json_atomic(artifact_path, artifact)
    validate_identity_artifact(artifact, root=ROOT, manifest_path=manifest_path)
    return artifact


def verify(args: argparse.Namespace) -> dict[str, object]:
    artifact_path = args.artifact.resolve()
    manifest_path = args.manifest.resolve()
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    validate_identity_artifact(artifact, root=ROOT, manifest_path=manifest_path)
    config = load_identity_config(args.config.resolve())
    load_quarantine_record(ROOT, config["known_raw_quarantine_reference"])
    prior_blocks, prior_sources = prior_o4a_blocks(ROOT, config)
    if sorted(prior_blocks) != artifact["prior_usage"]["union_o4a_block_keys"]:
        raise ContractError("v5 prior exclusions no longer recompute")
    if prior_sources != artifact["source_references"]["prior_identity_sources"]:
        raise ContractError("v5 prior source summaries no longer recompute")
    for key, path in (
        ("config", args.config.resolve()),
        ("implementation", ROOT / "src/dante_light/prefilter_v5_identity.py"),
        ("cli", Path(__file__).resolve()),
    ):
        from src.dante_light.prefilter_v4_protocol import repository_reference

        if repository_reference(ROOT, path) != artifact["source_references"][key]:
            raise ContractError(f"v5 identity source reference changed: {key}")
    if (
        config["known_raw_quarantine_reference"]
        != artifact["source_references"]["known_raw_quarantine"]
    ):
        raise ContractError("v5 raw-quarantine source reference changed")
    return artifact


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    value.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    value.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    value.add_argument("--raw-root", type=Path, default=Path(os.environ.get("DANTE_O4A_RAW_ROOT", r"E:\o4a")))
    value.add_argument(
        "--cache-root",
        type=Path,
        default=Path(
            os.environ.get(
                "DANTE_V5_IDENTITY_CACHE_ROOT",
                r"E:\dante_cache\dante_light_prefilter_l4_v5_design",
            )
        ),
    )
    value.add_argument("--cache-checkpoint-every", type=int, default=25)
    value.add_argument(
        "--reuse-hash-cache",
        action="store_true",
        help="Reuse fingerprint-guarded local hashes; final evidence should omit this flag.",
    )
    value.add_argument("--verify", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        artifact = verify(args) if args.verify else build(args)
    except (ContractError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    summary = {
        "status": artifact["status"],
        "artifact_digest": artifact["artifact_digest"],
        "physical_files": artifact["raw_mirror"]["physical_file_count"],
        "unique_spans": artifact["raw_mirror"]["unique_span_count"],
        "prior_o4a_blocks": artifact["prior_usage"]["union_o4a_block_count"],
        "fresh_full_blocks": artifact["capacity"]["fresh_fully_covered_block_count"],
        "fresh_full_by_detector": artifact["capacity"]["fresh_fully_covered_by_detector"],
        "protected_outcomes_used": [],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
