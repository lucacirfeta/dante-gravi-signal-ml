"""Build the compact public evidence bundle for the O4a provenance rerun."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (
    ROOT / "artifacts" / "dante_light" / "o4a_v1_parity" / "provenance_rerun_v1"
)
TRANSPARENCY_NOTE = (
    ROOT / "docs" / "DANTE_O4A_PROVENANCE_TRANSPARENCY_DRAFT_2026-09-12.md"
)
EVIDENCE_FILES = (
    "corrected_native_cohort.json",
    "corrected_native_index.json",
    "corrected_native_calibration.json",
    "corrected_native_rescore.json",
    "corrected_native_thresholds.json",
    "corrected_native_classification.json",
    "corrected_native_taxonomy.json",
    "corrected_native_coincidence.json",
    "corrected_native_pem.json",
    "corrected_final_comparison_v2.json",
)
CANONICAL_RERUN_COMMIT = "cf774dd059e5b26da205e5abed3073d574e53c30"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.create_system = 3
    # Stored members avoid zlib-version differences between Windows and WSL.
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o100644 << 16
    return info


def build_bundle(output: Path) -> dict[str, object]:
    sources: list[tuple[str, Path]] = [
        ("DANTE_O4A_PROVENANCE_TRANSPARENCY_NOTE.md", TRANSPARENCY_NOTE),
        *((f"evidence/{name}", EVIDENCE_ROOT / name) for name in EVIDENCE_FILES),
    ]
    missing = [str(path) for _, path in sources if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing required release evidence: {missing}")

    payloads = {name: path.read_bytes() for name, path in sources}
    stages = []
    for name in EVIDENCE_FILES:
        evidence = json.loads((EVIDENCE_ROOT / name).read_text(encoding="utf-8"))
        stages.append(
            {
                "file": f"evidence/{name}",
                "status": evidence["status"],
                "run_key": evidence["run_key"],
                "contract_digest": evidence["contract_digest"],
            }
        )

    manifest: dict[str, object] = {
        "schema_version": "dante-o4a-provenance-release-bundle-v1",
        "release_version": "3.8.1",
        "canonical_rerun_commit": CANONICAL_RERUN_COMMIT,
        "result": "BYTE_IDENTICAL_SCIENTIFIC_OUTPUTS",
        "scientific_change": False,
        "files": {
            name: {"sha256": _sha256(payload), "size_bytes": len(payload)}
            for name, payload in sorted(payloads.items())
        },
        "stages": stages,
    }
    manifest_payload = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(_zip_info("MANIFEST.json"), manifest_payload)
        for name, payload in sorted(payloads.items()):
            archive.writestr(_zip_info(name), payload)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "dante-o4a-provenance-evidence-v3.8.1.zip",
    )
    args = parser.parse_args()
    manifest = build_bundle(args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "sha256": _sha256(args.output.resolve().read_bytes()),
                "files": len(manifest["files"]),
                "stages": len(manifest["stages"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
