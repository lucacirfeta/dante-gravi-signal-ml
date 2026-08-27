#!/usr/bin/env python3
"""Build the frozen Phase-B native-O4a teacher ledger and clean strain."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import RepresentationContract
from src.dante_light.prefilter_v5_protocol import repository_reference
from src.dante_light.prefilter_v5_teacher import ExactNativeTeacher, prepare_teacher_input
from src.dante_light.prefilter_v6_teacher import build_teacher_ledger, load_teacher_contract


DEFAULT_RAW_CACHE = Path(os.environ.get("DANTE_V6_RAW_CACHE_ROOT", r"E:\dante_cache\dante_light\prefilter_l4_v6_raw"))
DEFAULT_TRAINING_CACHE = Path(os.environ.get("DANTE_V6_TRAINING_CACHE_ROOT", r"E:\dante_cache\dante_light\prefilter_l4_v6_training"))
DEFAULT_ARTIFACT = ROOT / "artifacts/dante_light/prefilter_l4_v6_training/teacher_ledger_summary_v6.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-cache-root", type=Path, default=DEFAULT_RAW_CACHE)
    parser.add_argument("--training-cache-root", type=Path, default=DEFAULT_TRAINING_CACHE)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--device", default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit-blocks", type=int, default=None)
    args = parser.parse_args()
    contract = load_teacher_contract(root=ROOT)
    raw_summary = json.loads((ROOT / contract["source_references"]["raw_cache_summary"]["path"]).read_text(encoding="utf-8"))
    raw_run_dir = args.raw_cache_root.resolve() / raw_summary["cache_location"]["run_subdirectory"]
    existing = os.environ.get("DANTE_DATA_DIRS", "")
    os.environ["DANTE_DATA_DIRS"] = str(raw_run_dir) + (os.pathsep + existing if existing else "")
    representation = RepresentationContract(**{
        key: value for key, value in contract["representation"].items()
        if key != "contract_sha256"
    })
    teacher = ExactNativeTeacher(root=ROOT, representation=representation, device=args.device)
    paths = {
        "artifact_manifest": "src/core/artifact_manifest.py",
        "core_preprocessor": "src/core/preprocessor.py",
        "core_utils": "src/core/utils.py",
        "data_loader": "src/core/data_loader.py",
        "encoder": "src/core/encoder.py",
        "ledger_builder": Path(__file__).relative_to(ROOT).as_posix(),
        "model_loader": "src/core/model_loader.py",
        "patch_scorer": "src/core/patch_scorer.py",
        "runtime_config": "config.yaml",
        "teacher_implementation": "src/dante_light/prefilter_v6_teacher.py",
        "teacher_input_implementation": "src/dante_light/prefilter_v5_teacher.py"
    }
    references = {name: repository_reference(ROOT, ROOT / path) for name, path in paths.items()}
    summary = build_teacher_ledger(
        root=ROOT,
        contract=contract,
        cache_root=args.training_cache_root.resolve(),
        artifact_path=args.artifact.resolve(),
        code_references=references,
        prepare=lambda window: prepare_teacher_input(window, representation=representation, local_only=True),
        score=teacher.score,
        workers=args.workers,
        limit_blocks=args.limit_blocks,
    )
    print(json.dumps({
        "status": summary["status"],
        "run_key": summary["run_key"],
        "row_count": summary["row_count"],
        "artifact_digest": summary["artifact_digest"]
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
