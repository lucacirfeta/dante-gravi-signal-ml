"""Build and verify the minimal DANTE workflow architecture arXiv bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


PAPER_DIR = Path(__file__).resolve().parent
RELEASE_DIR = PAPER_DIR / "release"
MANIFEST_PATH = RELEASE_DIR / "SOURCE_MANIFEST.json"
BUNDLE_PATH = RELEASE_DIR / "dante_workflow_architecture_v1_arxiv_source.zip"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
TEXT_SUFFIXES = {".tex", ".bib"}
SOURCE_FILES = (
    Path("main.tex"),
    Path("references.bib"),
    Path("figures/fig_workflow_dag.pdf"),
    Path("figures/fig_evidence_lifecycle.pdf"),
    Path("figures/fig_runtime_boundary.pdf"),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def source_payload(relative_path: Path) -> tuple[bytes, str]:
    data = (PAPER_DIR / relative_path).read_bytes()
    if relative_path.suffix in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return data, "line_endings_lf"
    return data, "none"


def archive_info(name: str) -> zipfile.ZipInfo:
    canonical = PurePosixPath(name)
    if canonical.is_absolute() or ".." in canonical.parts:
        raise ValueError(f"unsafe archive path: {name}")
    info = zipfile.ZipInfo(canonical.as_posix(), date_time=FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build() -> dict:
    entries = []
    payloads: dict[str, bytes] = {}
    for source in SOURCE_FILES:
        data, normalization = source_payload(source)
        archive_path = source.as_posix()
        payloads[archive_path] = data
        entries.append(
            {
                "archive_path": archive_path,
                "normalization": normalization,
                "sha256": sha256_bytes(data),
                "size_bytes": len(data),
                "source_path": source.as_posix(),
            }
        )

    manifest = {
        "bundle_role": "arxiv_source_not_submitted",
        "entries": entries,
        "paper": "DANTE workflow architecture v1",
        "schema_version": 1,
        "software_baseline_commit": "e8f2098e99c9103514702ab680e9952333dc4eb7",
        "software_baseline_tag": "dante-workflow-productization-v1",
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_bytes(manifest_bytes)
    with zipfile.ZipFile(
        BUNDLE_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name in sorted(payloads):
            archive.writestr(
                archive_info(name),
                payloads[name],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return check()


def check() -> dict:
    external_manifest = MANIFEST_PATH.read_bytes()
    manifest = json.loads(external_manifest)
    expected_names = {entry["archive_path"] for entry in manifest["entries"]}

    for entry in manifest["entries"]:
        current, normalization = source_payload(Path(entry["source_path"]))
        if normalization != entry["normalization"]:
            raise ValueError(f"normalization mismatch: {entry['source_path']}")
        if len(current) != entry["size_bytes"]:
            raise ValueError(f"source size mismatch: {entry['source_path']}")
        if sha256_bytes(current) != entry["sha256"]:
            raise ValueError(f"source digest mismatch: {entry['source_path']}")

    with zipfile.ZipFile(BUNDLE_PATH) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("bundle contains duplicate paths")
        if set(names) != expected_names:
            raise ValueError(
                f"bundle members differ: expected={sorted(expected_names)}, "
                f"actual={sorted(names)}"
            )
        if archive.testzip() is not None:
            raise ValueError("bundle CRC verification failed")
        for entry in manifest["entries"]:
            data = archive.read(entry["archive_path"])
            if len(data) != entry["size_bytes"]:
                raise ValueError(f"size mismatch: {entry['archive_path']}")
            if sha256_bytes(data) != entry["sha256"]:
                raise ValueError(f"digest mismatch: {entry['archive_path']}")

    result = {
        "bundle_path": str(BUNDLE_PATH),
        "bundle_sha256": sha256_file(BUNDLE_PATH),
        "file_count": len(expected_names),
        "manifest_path": str(MANIFEST_PATH),
        "manifest_sha256": sha256_bytes(external_manifest),
        "status": "PASS_ARXIV_SOURCE_BUNDLE",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "check"))
    args = parser.parse_args()
    if args.command == "build":
        build()
    else:
        check()


if __name__ == "__main__":
    main()
