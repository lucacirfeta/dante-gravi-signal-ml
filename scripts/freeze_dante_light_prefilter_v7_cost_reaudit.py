#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_cost_reaudit import (
    DEFAULT_CONTRACT,
    build_contract,
    cost_code_references,
)
from src.dante_light.prefilter_v7_training import _atomic_json


contract = build_contract(root=ROOT, code_references=cost_code_references(ROOT))
_atomic_json(DEFAULT_CONTRACT, contract)
print(json.dumps({"status": contract["status"], "digest": contract["contract_digest"]}, indent=2, sort_keys=True))
