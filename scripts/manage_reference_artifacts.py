#!/usr/bin/env python3
"""Public artifact-management CLI for clean-clone DANTE setup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.artifact_manager import (
    build_reference_bundle,
    download_reference_bundle,
    install_reference_bundle,
    model_contract_summary,
    verify_reference_bundle,
    verify_reference_indices,
)
from src.core.model_loader import load_dinov2_model


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify/acquire immutable DANTE indices and DINOv2 inputs."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "config/reference_artifacts.json",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="Verify installed indices and model contract")
    verify.add_argument("--allow-missing-indices", action="store_true")
    model = sub.add_parser("acquire-model", help="Acquire and verify pinned model inputs")
    model.add_argument("--offline", action="store_true")
    build = sub.add_parser("build-bundle", help="Build the validated index bundle")
    build.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "paper_draft/v6_paper/release/dante_reference_artifacts_v1.zip",
    )
    check = sub.add_parser("verify-bundle", help="Verify a reference bundle ZIP")
    check.add_argument("bundle", type=Path)
    acquire = sub.add_parser("download-bundle", help="Download the deposited bundle")
    acquire.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "paper_draft/v6_paper/release/dante_reference_artifacts_v1.zip",
    )
    install = sub.add_parser("install-bundle", help="Safely install a verified bundle")
    install.add_argument("bundle", type=Path)
    args = parser.parse_args()

    if args.command == "verify":
        payload = {
            "indices": verify_reference_indices(
                manifest_path=args.manifest,
                allow_missing=args.allow_missing_indices,
            ),
            "model_contract": model_contract_summary(manifest_path=args.manifest),
        }
    elif args.command == "acquire-model":
        model_instance = load_dinov2_model(
            "cpu",
            manifest_path=args.manifest,
            allow_download=not args.offline,
        )
        payload = model_instance.dante_model_provenance
    elif args.command == "build-bundle":
        payload = build_reference_bundle(args.output, project_root=PROJECT_ROOT)
    elif args.command == "verify-bundle":
        payload = verify_reference_bundle(args.bundle)
    elif args.command == "download-bundle":
        bundle = download_reference_bundle(
            args.output,
            manifest_path=args.manifest,
        )
        payload = verify_reference_bundle(bundle)
    else:
        payload = install_reference_bundle(
            args.bundle,
            project_root=PROJECT_ROOT,
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
