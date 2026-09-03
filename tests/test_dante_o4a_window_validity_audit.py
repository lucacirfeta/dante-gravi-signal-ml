from __future__ import annotations

import json

from src.dante_light.o4a_window_validity_audit import (
    OUTPUT_REL,
    ROOT,
    _derive_invalid_rows,
    validate_window_validity_summary,
)


def test_context_nonfinite_is_mapped_to_adjacent_targets() -> None:
    windows = {("H1", 100.0), ("H1", 132.0), ("H1", 164.0)}
    rows = _derive_invalid_rows(
        all_windows=windows,
        target_nonfinite={("H1", 132.0)},
        target_allzero=set(),
        first_pad_nonfinite={("H1", 164.0)},
        last_pad_nonfinite={("H1", 100.0)},
    )
    assert rows == [
        {
            "detector": "H1",
            "gps_start": 132.0,
            "reasons": [
                "LEFT_CONTEXT_NONFINITE",
                "RIGHT_CONTEXT_NONFINITE",
                "TARGET_NONFINITE",
            ],
        }
    ]


def test_saved_raw_window_validity_audit_is_fail_closed_when_present() -> None:
    path = ROOT / OUTPUT_REL
    if not path.is_file():
        return
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_window_validity_summary(value)
    assert value["span_count"] == 6_928
    assert value["provenance_boundary"]["full_scoring_rechecks_each_selected_file_sha256"] is True
