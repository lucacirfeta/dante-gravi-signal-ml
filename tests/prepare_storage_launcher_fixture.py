"""New-only tiny byte fixtures for Windows->WSL launcher qualification."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.dante_workflow.storage_probe import (  # noqa: E402
    BOUNDARY,
    _hash,
    confined,
    new_report,
    separate,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--fixture-directory", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    args = parser.parse_args()
    root = confined(args.repository_root)
    fixture = confined(args.fixture_directory)
    if not fixture.is_relative_to(root / ".gsd"):
        raise ValueError("owned .gsd fixture directory required")
    _, work = separate(root, args.workspace_root)
    fixture.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    source = work / "source"
    source.mkdir()
    (source / "opaque.bin").write_bytes(b"TEST FIXTURE ONLY\r\n")
    parent = {}
    for name, status in (
        ("summary", "PASS_COMPLETE_EXPANDED_CALIBRATION_PREPROCESSING_ONLY"),
        ("verification", "PASS_VERIFIED_EXPANDED_CALIBRATION_PREPROCESSING_ONLY"),
    ):
        path = source / f"{name}.json"
        new_report(path, {"status": status, "test_fixture_only": True})
        parent[f"{name}_sha256"] = _hash(path)
    profile = fixture / "profile.json"
    profile.write_text(json.dumps({"preprocessing_parent": parent}))
    config = fixture / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "ISOLATED_STORAGE_PROBE_V1",
                "boundary": BOUNDARY,
                "repetitions": 1,
                "source_pins": [],
                "productive_profile": {
                    "path": profile.relative_to(root).as_posix(),
                    "sha256": _hash(profile),
                },
                "source_directory": str(source),
                "workspace": str(work / "probe"),
                "test_fixture_only": True,
            }
        )
    )
    print("GENERATED_TEST_FIXTURE_ONLY", config, _hash(config))


if __name__ == "__main__":
    main()
