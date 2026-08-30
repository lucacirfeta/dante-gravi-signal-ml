from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.dante_light.o4a_corrected_cold_path_v3 import (
    CONTRACT_REL,
    DEFAULT_EXTERNAL_ROOT,
    ROOT,
    build_contract,
    run_benchmark,
    validate_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("freeze", "run", "verify"), required=True)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.stage == "freeze":
        value = build_contract(ROOT)
        path = ROOT / CONTRACT_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(value["contract_digest"])
    elif args.stage == "verify":
        value = validate_contract(
            json.loads((ROOT / CONTRACT_REL).read_text(encoding="utf-8")), ROOT
        )
        print(value["contract_digest"])
    else:
        result, run_dir = run_benchmark(
            root=ROOT,
            raw_root=args.raw_root,
            external_root=args.external_root,
            device=args.device,
        )
        print(json.dumps({
            "status": result["status"],
            "artifact_digest": result["artifact_digest"],
            "run_dir": str(run_dir),
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
