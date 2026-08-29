from __future__ import annotations

import json

from src.dante_light.o4a_window_validity_audit import (
    OUTPUT_REL,
    ROOT,
    validate_window_validity_summary,
)


def test_saved_raw_window_validity_audit_is_fail_closed_when_present() -> None:
    path = ROOT / OUTPUT_REL
    if not path.is_file():
        return
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_window_validity_summary(value)
    assert value["span_count"] == 6_928
    assert value["provenance_boundary"]["full_scoring_rechecks_each_selected_file_sha256"] is True
