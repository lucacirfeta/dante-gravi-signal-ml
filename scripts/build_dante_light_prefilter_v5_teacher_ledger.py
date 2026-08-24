#!/usr/bin/env python3
"""Build the deterministic training-only native-O4a teacher ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import RepresentationContract  # noqa: E402
from src.dante_light.prefilter_v5_protocol import repository_reference  # noqa: E402
from src.dante_light.prefilter_v5_teacher import (  # noqa: E402
    ExactNativeTeacher,
    build_teacher_ledger,
    default_cache_root,
    load_teacher_contract,
    prepare_teacher_input,
)


DEFAULT_ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_training/teacher_ledger_summary_v5.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--device", default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit-blocks", type=int, default=None)
    args = parser.parse_args()
    contract = load_teacher_contract(root=ROOT)
    representation = RepresentationContract(**{
        key: value for key, value in contract["representation"].items()
        if key != "contract_sha256"
    })
    teacher = ExactNativeTeacher(
        root=ROOT, representation=representation, device=args.device
    )
    code_paths = {
        "artifact_manifest": "src/core/artifact_manifest.py",
        "core_preprocessor": "src/core/preprocessor.py",
        "core_utils": "src/core/utils.py",
        "dante_preprocessing": "src/dante_light/preprocessing.py",
        "data_loader": "src/core/data_loader.py",
        "encoder": "src/core/encoder.py",
        "ledger_builder": Path(__file__).relative_to(ROOT).as_posix(),
        "model_loader": "src/core/model_loader.py",
        "patch_scorer": "src/core/patch_scorer.py",
        "runtime_config": "config.yaml",
        "teacher_implementation": "src/dante_light/prefilter_v5_teacher.py",
    }
    code_references = {
        label: repository_reference(ROOT, ROOT / path)
        for label, path in code_paths.items()
    }
    summary = build_teacher_ledger(
        root=ROOT,
        contract=contract,
        cache_root=args.cache_root or default_cache_root(),
        compact_artifact_path=args.artifact,
        code_references=code_references,
        prepare=lambda window: prepare_teacher_input(
            window, representation=representation, local_only=True
        ),
        score=teacher.score,
        workers=args.workers,
        limit_blocks=args.limit_blocks,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
