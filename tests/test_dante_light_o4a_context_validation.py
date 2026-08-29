from __future__ import annotations

import json

from src.dante_light.contracts import canonical_json_sha256
from src.dante_light.o4a_context_validation import OUTPUT


def test_saved_real_context_validation_is_self_consistent() -> None:
    value = json.loads(OUTPUT.read_text(encoding="utf-8"))
    body = dict(value)
    assert body.pop("artifact_digest") == canonical_json_sha256(body)
    assert value["status"] == "PASS_SAMPLE_EXACT"
    assert value["sample_count"] == 40 * 4096
    assert value["maximum_absolute_sample_difference"] == 0.0
    assert value["stitched_strain_sha256"] == value["parity_cache_strain_sha256"]
    assert len(value["sources"]) == 2
    assert value["scientific_boundary"]["establishes_full_corrected_o4a_run"] is False
