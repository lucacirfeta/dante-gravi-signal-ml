"""Native-only orchestrator entry; copied independently from frozen scientific sources."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", required=True)
    args, _ = parser.parse_known_args()
    policy = json.loads(Path(args.config).read_text())
    sys.path.insert(0, policy["repository_root"])
    code_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "native_calibration_execution",
        code_root / "src/dante_workflow/native_calibration.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
