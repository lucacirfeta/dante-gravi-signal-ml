from __future__ import annotations

import json

from src.dante_light.o4a_overlap_audit import OUTPUT_REL, ROOT, validate_overlap_audit


def test_saved_overlapping_raw_span_audit_is_fail_closed() -> None:
    path = ROOT / OUTPUT_REL
    if not path.is_file():
        return
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_overlap_audit(value)
    assert value["pair_count"] == 6
    assert value["duplicate_window_memberships"] == {"H1": 72, "L1": 328}
