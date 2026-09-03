#!/usr/bin/env python3
"""Verify the frozen O4a v1 parity contract without rescoring strain."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_v1_parity import validate_parity_freeze  # noqa: E402


def main() -> int:
    contract = json.loads((ROOT / "config/dante_light_o4a_v1_parity_contract.json").read_text(encoding="utf-8"))
    header = json.loads((ROOT / "config/dante_light_o4a_v1_parity_manifest.json").read_text(encoding="utf-8"))
    entries = [json.loads(line) for line in (ROOT / header["entries_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    missing = [json.loads(line) for line in (ROOT / header["missing_path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    validate_parity_freeze(contract, header, entries, missing, root=ROOT)
    print(f"PASS entries={len(entries)} missing={len(missing)} digest={header['manifest_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
