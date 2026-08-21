from __future__ import annotations

import json

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.followup import (
    build_catalog_crossmatch,
    build_followup_manifest,
    load_followup_manifest,
)


def _record(detector: str, gps: float, *, disposition: str, score: float) -> dict:
    window = {
        "schema_version": 1,
        "run": "O4B",
        "detector": detector,
        "gps_start": gps,
        "duration_s": 32.0,
        "window_id": f"{detector}-{int(gps)}",
    }
    return {
        "schema_version": 1,
        "record_id": f"record-{detector}-{int(gps)}",
        "window": window,
        "representation_sha256": "a" * 64,
        "disposition": disposition,
        "epoch_id": f"epoch-{detector}",
        "scores": {"native": score, "primary": score + 0.1},
        "evidence": {
            "strain_sha256": "b" * 64,
            "image_sha256": "c" * 64,
            "decision_score": "native",
            "decision_threshold": 0.2,
            "primary_top_k_indices": [0, 1, 37, 38],
            "primary_top_k_sha256": "d" * 64,
            "primary_mil_vector_sha256": "e" * 64,
        },
    }


def _write(path, rows):
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_manifest_freezes_only_exact_escalations(tmp_path) -> None:
    rows = [
        _record("H1", 1000.0, disposition="ESCALATE", score=0.3),
        _record("L1", 2000.0, disposition="NOT_ESCALATED", score=0.1),
    ]
    canonical, shared = tmp_path / "canonical.jsonl", tmp_path / "shared.jsonl"
    _write(canonical, rows)
    _write(shared, json.loads(json.dumps(rows)))
    output = tmp_path / "manifest.json"

    payload = build_followup_manifest(
        canonical_records=canonical, shared_records=shared, output_path=output
    )

    assert payload["selection"]["n_source_windows"] == 2
    assert payload["selection"]["n_candidates"] == 1
    assert payload["candidates"][0]["frozen_dsd_class"] == "ROBUST"
    assert load_followup_manifest(output) == payload


def test_manifest_rejects_canonical_shared_scientific_mismatch(tmp_path) -> None:
    left = [_record("H1", 1000.0, disposition="ESCALATE", score=0.3)]
    right = json.loads(json.dumps(left))
    right[0]["evidence"]["primary_top_k_indices"] = [2, 3, 39, 40]
    canonical, shared = tmp_path / "canonical.jsonl", tmp_path / "shared.jsonl"
    _write(canonical, left)
    _write(shared, right)

    with pytest.raises(ContractError, match="canonical/shared evidence"):
        build_followup_manifest(
            canonical_records=canonical,
            shared_records=shared,
            output_path=tmp_path / "manifest.json",
        )


def test_manifest_rejects_tampering(tmp_path) -> None:
    rows = [_record("H1", 1000.0, disposition="ESCALATE", score=0.3)]
    canonical, shared = tmp_path / "canonical.jsonl", tmp_path / "shared.jsonl"
    _write(canonical, rows)
    _write(shared, rows)
    output = tmp_path / "manifest.json"
    payload = build_followup_manifest(
        canonical_records=canonical, shared_records=shared, output_path=output
    )
    payload["candidates"][0]["decision_score"] = 999.0
    output.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match="manifest digest"):
        load_followup_manifest(output)


def test_candidate_digest_is_canonical() -> None:
    candidate = {"window_id": "x", "decision_score": 0.3}
    assert canonical_json_sha256(candidate) == canonical_json_sha256(
        {"decision_score": 0.3, "window_id": "x"}
    )


def test_catalog_crossmatch_reports_matches_without_calling_them_novel(tmp_path) -> None:
    rows = [_record("H1", 1000.0, disposition="ESCALATE", score=0.3)]
    canonical, shared = tmp_path / "canonical.jsonl", tmp_path / "shared.jsonl"
    _write(canonical, rows)
    _write(shared, rows)
    manifest = tmp_path / "manifest.json"
    build_followup_manifest(
        canonical_records=canonical, shared_records=shared, output_path=manifest
    )
    result = build_catalog_crossmatch(
        {
            "next": None,
            "results_count": 2,
            "results": [
                {
                    "name": "GW-fixture-in",
                    "version": 1,
                    "gps": 1010.0,
                    "detectors": ["H1", "L1"],
                    "catalog": "GWTC-5.0",
                },
                {
                    "name": "GW-fixture-out",
                    "version": 1,
                    "gps": 2000.0,
                    "detectors": ["H1"],
                    "catalog": "GWTC-5.0",
                },
            ],
        },
        manifest_path=manifest,
        output_path=tmp_path / "catalog.json",
        response_sha256="f" * 64,
    )
    assert result["catalog_event_count"] == 2
    assert result["n_candidates_with_catalog_match"] == 1
    assert "does not establish" in result["scientific_boundary"]


def test_catalog_crossmatch_rejects_incomplete_page(tmp_path) -> None:
    rows = [_record("H1", 1000.0, disposition="ESCALATE", score=0.3)]
    canonical, shared = tmp_path / "canonical.jsonl", tmp_path / "shared.jsonl"
    _write(canonical, rows)
    _write(shared, rows)
    manifest = tmp_path / "manifest.json"
    build_followup_manifest(
        canonical_records=canonical, shared_records=shared, output_path=manifest
    )
    with pytest.raises(ContractError, match="paginated"):
        build_catalog_crossmatch(
            {"next": "page-2", "results_count": 0, "results": []},
            manifest_path=manifest,
            output_path=tmp_path / "catalog.json",
            response_sha256="f" * 64,
        )
