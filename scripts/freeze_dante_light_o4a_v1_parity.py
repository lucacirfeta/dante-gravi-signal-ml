#!/usr/bin/env python3
"""Freeze the 10,429-candidate retrospective O4a v1 parity corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_v1_parity import (  # noqa: E402
    build_parity_freeze,
    validate_parity_freeze,
    write_parity_freeze,
)


CONTRACT = ROOT / "config/dante_light_o4a_v1_parity_contract.json"
HEADER = ROOT / "config/dante_light_o4a_v1_parity_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    contract, header, entries, missing = build_parity_freeze(ROOT)
    validate_parity_freeze(contract, header, entries, missing, root=ROOT)
    if args.check:
        stored_contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        stored_header = json.loads(HEADER.read_text(encoding="utf-8"))
        stored_entries = [json.loads(line) for line in (ROOT / stored_header["entries_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
        stored_missing = [json.loads(line) for line in (ROOT / stored_header["missing_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
        validate_parity_freeze(stored_contract, stored_header, stored_entries, stored_missing, root=ROOT)
        print(f"PASS {HEADER} {stored_header['manifest_digest']}")
        return 0
    write_parity_freeze(CONTRACT, HEADER, contract, header, entries, missing)
    print(json.dumps(header["counts"], indent=2, sort_keys=True))
    print(f"FROZEN {HEADER} {header['manifest_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
