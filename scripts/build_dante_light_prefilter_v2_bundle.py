#!/usr/bin/env python3
"""Build or verify the deterministic L4 v2 development-evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v2_screening import _load_ledger


ROLES = ("background", "robust_candidate", "known_glitch", "injection")
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
README = """# DANTE-Light L4 v2 development evidence

This deterministic bundle contains the frozen protocol and split, the complete
feature ledgers needed to recompute development screening, the immutable
NOT_READY screening result, and post-hoc diagnostic-only ROC-AUC/C-sweep
results. O4b outcomes and O4b feature rows are deliberately absent.

The diagnostic artifact is not eligible for PASS/FAIL gating and cannot revise
the frozen v2 result. Run the repository verifier and diagnostic script against
the extracted files using the paths recorded in BUNDLE_PROVENANCE.json.
"""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _zip_info(name: str) -> zipfile.ZipInfo:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ContractError(f"unsafe bundle member: {name}")
    info = zipfile.ZipInfo(path.as_posix(), FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def _add(entries: dict[str, bytes], name: str, value: bytes) -> None:
    canonical = _zip_info(name).filename
    if canonical in entries:
        raise ContractError(f"duplicate bundle member: {canonical}")
    entries[canonical] = value


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid bundle JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"bundle JSON input is not an object: {path}")
    return value


def build_bundle(*, ledgers: dict[str, Path], output: Path, root: Path = ROOT) -> dict:
    root = root.resolve()
    protocol_path = root / "config/dante_light_prefilter_protocol_v2.json"
    diagnostic_config_path = root / "config/dante_light_prefilter_v2_diagnostics.json"
    split_path = root / "config/dante_light_prefilter_splits_v2.json"
    split_rows_path = root / "config/dante_light_prefilter_splits_v2.jsonl"
    screening_path = root / "artifacts/dante_light/prefilter_l4_v2/screening_result_v2.json"
    diagnostics_path = root / "artifacts/dante_light/prefilter_l4_v2/diagnostics_v2.json"
    note_path = root / "docs/DANTE_LIGHT_L4_PREFILTER_V2_NOT_READY_2026-08-22.md"
    for path in (
        protocol_path,
        diagnostic_config_path,
        split_path,
        split_rows_path,
        screening_path,
        diagnostics_path,
        note_path,
    ):
        if not path.is_file():
            raise ContractError(f"bundle input is missing: {path}")

    screening = _read_json(screening_path)
    diagnostics = _read_json(diagnostics_path)
    for payload, field, label in (
        (screening, "artifact_digest", "screening"),
        (diagnostics, "artifact_digest", "diagnostics"),
    ):
        body = dict(payload)
        if body.pop(field, None) != canonical_json_sha256(body):
            raise ContractError(f"{label} artifact digest mismatch")
    if screening.get("status") != "NOT_READY" or diagnostics.get("status") != "COMPLETE_DIAGNOSTIC_ONLY":
        raise ContractError("bundle requires the frozen negative screen and completed diagnostics")
    if diagnostics.get("eligible_for_pass_fail_gate") is not False:
        raise ContractError("diagnostics unexpectedly entered the gate")

    entries: dict[str, bytes] = {}
    fixed = {
        "config/dante_light_prefilter_protocol_v2.json": protocol_path,
        "config/dante_light_prefilter_v2_diagnostics.json": diagnostic_config_path,
        "config/dante_light_prefilter_splits_v2.json": split_path,
        "config/dante_light_prefilter_splits_v2.jsonl": split_rows_path,
        "artifacts/screening_result_v2.json": screening_path,
        "artifacts/diagnostics_v2.json": diagnostics_path,
        "docs/DANTE_LIGHT_L4_PREFILTER_V2_NOT_READY_2026-08-22.md": note_path,
    }
    for name, path in fixed.items():
        _add(entries, name, path.read_bytes())

    expected_sources = {
        record["role"]: record for record in screening.get("source_ledgers", [])
    }
    if set(expected_sources) != set(ROLES):
        raise ContractError("screening source-ledger coverage is incomplete")
    source_records = []
    for role in ROLES:
        try:
            ledger_path = ledgers[role].resolve()
        except KeyError as exc:
            raise ContractError(f"missing bundle ledger for {role}") from exc
        ledger, _rows = _load_ledger(ledger_path)
        if ledger.get("role") != role:
            raise ContractError(f"bundle ledger role mismatch for {role}")
        rows_path = ledger_path.parent / ledger["rows_path"]
        ledger_name = f"ledgers/{role}/{ledger_path.name}"
        rows_name = f"ledgers/{role}/{rows_path.name}"
        ledger_bytes = ledger_path.read_bytes()
        rows_bytes = rows_path.read_bytes()
        expected = expected_sources[role]
        if (
            ledger_path.name != expected["file_name"]
            or _sha256_bytes(ledger_bytes) != expected["sha256"]
            or _sha256_bytes(rows_bytes) != expected["rows_sha256"]
            or ledger["cohort_split_sha256_by_role"].get(role)
            != expected["role_split_sha256"]
        ):
            raise ContractError(f"bundle ledger provenance differs from frozen screen for {role}")
        _add(entries, ledger_name, ledger_bytes)
        _add(entries, rows_name, rows_bytes)
        source_records.append(
            {
                "role": role,
                "ledger_path": ledger_name,
                "ledger_sha256": _sha256_bytes(ledger_bytes),
                "rows_path": rows_name,
                "rows_sha256": _sha256_bytes(rows_bytes),
                "row_count": int(ledger["row_count"]),
            }
        )

    provenance = {
        "schema_version": 1,
        "status": "complete_unpublished_bundle",
        "scientific_mode": "frozen_v2_development_evidence_only",
        "contains_o4b_outcomes": False,
        "contains_o4b_features": False,
        "routing_enabled": False,
        "screening_status": screening["status"],
        "screening_artifact_digest": screening["artifact_digest"],
        "diagnostic_status": diagnostics["status"],
        "diagnostic_artifact_digest": diagnostics["artifact_digest"],
        "source_ledgers": source_records,
    }
    _add(
        entries,
        "BUNDLE_PROVENANCE.json",
        (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _add(entries, "README.md", README.encode("utf-8"))
    manifest = "".join(
        f"{_sha256_bytes(value)}  {name}\n" for name, value in sorted(entries.items())
    ).encode("utf-8")
    _add(entries, "MANIFEST.sha256", manifest)

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, value in sorted(entries.items()):
            archive.writestr(_zip_info(name), value, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    verify_bundle(output)
    return {
        "schema_version": 1,
        "status": "built_not_published",
        "file_name": output.name,
        "bytes": output.stat().st_size,
        "sha256": _sha256_bytes(output.read_bytes()),
        "entries": len(entries),
        "screening_artifact_digest": screening["artifact_digest"],
        "diagnostic_artifact_digest": diagnostics["artifact_digest"],
    }


def verify_bundle(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ContractError("bundle ZIP CRC verification failed")
            names = archive.namelist()
            if len(names) != len(set(names)) or any(
                "\\" in name
                or PurePosixPath(name).is_absolute()
                or ".." in PurePosixPath(name).parts
                for name in names
            ):
                raise ContractError("bundle ZIP paths are non-portable or duplicated")
            manifest_lines = archive.read("MANIFEST.sha256").decode("utf-8").splitlines()
            expected = {}
            for line in manifest_lines:
                digest, name = line.split("  ", 1)
                if name in expected:
                    raise ContractError(f"duplicate bundle manifest member: {name}")
                expected[name] = digest
            if set(expected) != set(names) - {"MANIFEST.sha256"}:
                raise ContractError("bundle manifest coverage mismatch")
            for name, digest in expected.items():
                if _sha256_bytes(archive.read(name)) != digest:
                    raise ContractError(f"bundle member hash mismatch: {name}")
            provenance = json.loads(archive.read("BUNDLE_PROVENANCE.json"))
            if (
                provenance.get("contains_o4b_outcomes") is not False
                or provenance.get("contains_o4b_features") is not False
                or provenance.get("routing_enabled") is not False
                or provenance.get("screening_status") != "NOT_READY"
                or provenance.get("diagnostic_status") != "COMPLETE_DIAGNOSTIC_ONLY"
            ):
                raise ContractError("bundle scientific boundary is invalid")
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v2 development bundle: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--background", required=True, type=Path)
    build.add_argument("--robust", required=True, type=Path)
    build.add_argument("--known-glitch", dest="known_glitch", required=True, type=Path)
    build.add_argument("--injection", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    check = subparsers.add_parser("check")
    check.add_argument("--bundle", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check":
            verify_bundle(args.bundle.resolve())
            print(f"PASS: {args.bundle}")
        else:
            result = build_bundle(
                ledgers={
                    "background": args.background,
                    "robust_candidate": args.robust,
                    "known_glitch": args.known_glitch,
                    "injection": args.injection,
                },
                output=args.output,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
