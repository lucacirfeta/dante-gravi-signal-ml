#!/usr/bin/env python3
"""Write or verify the corrected O4a edge-context protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_corrected_protocol import (  # noqa: E402
    OUTPUT_REL,
    build_corrected_protocol,
    validate_corrected_protocol,
    write_corrected_protocol,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / OUTPUT_REL)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.check:
        stored = json.loads(output.read_text(encoding="utf-8"))
        validate_corrected_protocol(stored, ROOT)
        if stored != build_corrected_protocol(ROOT):
            raise RuntimeError("corrected O4a protocol is stale")
        print(f"PASS {output} {stored['protocol_digest']}")
        return 0
    value = write_corrected_protocol(output, ROOT)
    print(f"FROZEN {output} {value['protocol_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

