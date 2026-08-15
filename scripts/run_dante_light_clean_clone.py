#!/usr/bin/env python3
"""Run paired exact DANTE-Light replay in a clean checkout and build evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.artifact_manager import (
    download_reference_bundle,
    install_reference_bundle,
)
from src.dante_light.contracts import ContractError
from src.dante_light.evidence import (
    build_public_replay_evidence,
    git_checkout_provenance,
)


def _run_light(
    *,
    output_dir: Path,
    engine: str,
    limit: int,
    device: str | None,
) -> None:
    command = [
        sys.executable,
        "main.py",
        "dante-light-replay",
        "--output-dir",
        str(output_dir),
        "--role",
        "background_stratified",
        "--limit",
        str(limit),
        "--engine",
        engine,
        "--strain-source",
        "gwosc-only",
        "--cat1-mode",
        "gwosc",
    ]
    if device:
        command.extend(("--device", device))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def run_clean_clone(
    *,
    mode: str,
    output_root: str | Path,
    bundle_path: str | Path | None,
    limit: int,
    device: str | None,
) -> dict:
    if mode not in {"prepublish", "public"}:
        raise ContractError(f"unsupported clean-clone mode: {mode}")
    if limit <= 0:
        raise ContractError("clean-clone replay limit must be positive")
    git_checkout_provenance(PROJECT_ROOT)
    output_root = Path(output_root).resolve()
    if mode == "public":
        if bundle_path is not None:
            raise ContractError("public mode downloads the configured bundle itself")
        bundle = download_reference_bundle(
            PROJECT_ROOT / "artifacts/dante_light/downloads/dante_reference_artifacts_v1.zip"
        )
    else:
        if bundle_path is None:
            raise ContractError("prepublish mode requires --bundle")
        bundle = Path(bundle_path).resolve()
    install_reference_bundle(bundle, project_root=PROJECT_ROOT)

    canonical = output_root / "canonical"
    shared = output_root / "shared_encoder_score_only"
    _run_light(
        output_dir=canonical,
        engine="canonical",
        limit=limit,
        device=device,
    )
    _run_light(
        output_dir=shared,
        engine="shared_encoder_score_only",
        limit=limit,
        device=device,
    )
    evidence_path = (
        PROJECT_ROOT / "artifacts/dante_light/public_replay_validation_v1.json"
        if mode == "public"
        else PROJECT_ROOT
        / "artifacts/dante_light/prepublish_clean_clone_preflight_v1.json"
    )
    return build_public_replay_evidence(
        canonical,
        shared,
        bundle_path=bundle,
        output_path=evidence_path,
        root=PROJECT_ROOT,
        mode=mode,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepublish", "public"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/dante_light/clean_clone_run_v1"),
    )
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--device")
    args = parser.parse_args()
    payload = run_clean_clone(
        mode=args.mode,
        output_root=args.output_root,
        bundle_path=args.bundle,
        limit=args.limit,
        device=args.device,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
