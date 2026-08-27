#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from src.dante_light.prefilter_v7_risk_calibration import DEFAULT_AUTHORIZATION, build_authorization, risk_code_references
from src.dante_light.prefilter_v7_training import _atomic_json
payload = build_authorization(root=ROOT, code_references=risk_code_references(ROOT))
_atomic_json(DEFAULT_AUTHORIZATION, payload)
print(json.dumps({"status": payload["status"], "authorization_digest": payload["authorization_digest"], "gate_interpretation": payload["gate_interpretation"]}, indent=2, sort_keys=True))
