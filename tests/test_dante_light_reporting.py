from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.reporting import build_run_report, verify_run_report


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _prospective() -> dict:
    return {
        "schema_version": 1,
        "status": "complete",
        "mode": "prospective_shadow",
        "public_sources_only": True,
        "strain_source": "gwosc-only",
        "prefilter": "none",
        "run_commit": "a" * 40,
        "pre_registered_latency_objective_s": 60.0,
        "latency_objective_met": True,
        "latency_semantics": "task submission through completed durable record write",
        "latency_s": {"p50": 2.0, "p95": 3.0, "p99": 4.0},
        "coverage": {
            "windows": 5,
            "drops": 0,
            "duplicate_identities": 0,
            "deferred_windows": 0,
            "defer_rate": 0.0,
            "defer_reasons": {},
            "failures": [],
        },
        "exact_replay": {
            "score_atol": 2e-7,
            "max_abs_score_delta": 0.0,
            "disposition_mismatches": 0,
        },
        "detectors": {
            "H1": {
                "epoch_id": "past-only-h1",
                "evaluation_start_gps": 2000.0,
                "evaluation_end_gps": 2100.0,
                "windows": 2,
            },
            "L1": {
                "epoch_id": "past-only-l1",
                "evaluation_start_gps": 2000.0,
                "evaluation_end_gps": 2100.0,
                "windows": 3,
            },
        },
        "artifacts": [],
    }


def _followup(directory: Path) -> None:
    manifest_body = {
        "schema_version": 1,
        "status": "frozen",
        "selection": {
            "disposition": "ESCALATE",
            "n_source_windows": 5,
            "n_candidates": 2,
            "detector_counts": {"H1": 1, "L1": 1},
        },
        "candidates": [
            {"window_id": "h1", "detector": "H1"},
            {"window_id": "l1", "detector": "L1"},
        ],
    }
    manifest = {
        **manifest_body,
        "manifest_sha256": canonical_json_sha256(manifest_body),
    }
    _write_json(directory / "manifest_v1.json", manifest)
    _write_json(
        directory / "physical_v1.json",
        {
            "schema_version": 1,
            "status": "complete_with_unavailable",
            "manifest_sha256": manifest["manifest_sha256"],
            "failures": [],
            "summary": {
                "n_candidates": 2,
                "n_accounted": 2,
                "n_physical_measured": 1,
                "n_data_unavailable": 1,
                "n_failed": 0,
                "n_null_values": 7,
                "n_per_event_null_exceeded": 0,
                "pooled_null_p99_diagnostic": 0.25,
            },
        },
    )
    _write_json(
        directory / "catalog_v1.json",
        {
            "schema_version": 1,
            "status": "complete",
            "manifest_sha256": manifest["manifest_sha256"],
            "n_candidates": 2,
            "n_candidates_with_catalog_match": 0,
        },
    )
    _write_json(
        directory / "gallery_v1.json",
        {
            "schema_version": 1,
            "status": "complete",
            "manifest_sha256": manifest["manifest_sha256"],
            "n_candidates": 2,
            "n_exact_image_hash": 2,
            "n_exact_strain_hash": 2,
        },
    )


def _auxiliary(path: Path) -> None:
    body = {
        "schema_version": 1,
        "status": "PASS",
        "scientific_status": "DIAGNOSTIC_ONLY",
        "n_events": 2,
        "n_calibration_epochs": 1,
        "detector_counts": {"H1": 1, "L1": 1},
        "verdict_counts": {
            "NO_AUXILIARY_EXCESS": 1,
            "PERSISTENT_BASELINE_COMPATIBLE": 1,
        },
        "events": [
            {"detector": "H1", "gps_start": 2000, "diagnostic_verdict": "NO_AUXILIARY_EXCESS"},
            {
                "detector": "L1",
                "gps_start": 2032,
                "diagnostic_verdict": "PERSISTENT_BASELINE_COMPATIBLE",
            },
        ],
        "calibration_artifacts": [],
        "provenance": {"implementation_sha256": {}},
        "interpretation": "Diagnostic only.",
    }
    _write_json(path, {**body, "result_sha256": canonical_json_sha256(body)})


def test_build_run_report_is_generic_and_records_source_hashes(tmp_path: Path) -> None:
    prospective = tmp_path / "prospective.json"
    followup = tmp_path / "followup"
    auxiliary = tmp_path / "auxiliary.json"
    output = tmp_path / "final.md"
    receipt = tmp_path / "final.json"
    _write_json(prospective, _prospective())
    _followup(followup)
    _auxiliary(auxiliary)

    result = build_run_report(
        prospective_path=prospective,
        output_path=output,
        receipt_path=receipt,
        followup_dir=followup,
        auxiliary_path=auxiliary,
        root=tmp_path,
    )

    assert result["status"] == "COMPLETE"
    assert result["coverage"]["windows"] == 5
    assert result["followup"]["n_candidates"] == 2
    assert result["auxiliary"]["n_events"] == 2
    assert result["report_hash_semantics"] == "raw_utf8_lf_bytes_v1"
    assert len(result["source_artifacts"]) == 6
    assert receipt.is_file()
    assert verify_run_report(receipt, root=tmp_path) == result
    text = output.read_text(encoding="utf-8")
    assert "DANTE-Light run report" in text
    assert "not a physical classification" in text
    assert "past-only-h1" in text


def test_report_without_optional_followup_is_explicit(tmp_path: Path) -> None:
    prospective = tmp_path / "prospective.json"
    output = tmp_path / "final.md"
    _write_json(prospective, _prospective())

    result = build_run_report(
        prospective_path=prospective,
        output_path=output,
        root=tmp_path,
    )

    assert result["status"] == "COMPLETE_WITHOUT_OPTIONAL_FOLLOWUP"
    assert "was not supplied" in output.read_text(encoding="utf-8")


def test_report_accepts_physical_followup_while_catalog_is_pending(tmp_path: Path) -> None:
    prospective = tmp_path / "prospective.json"
    followup = tmp_path / "followup"
    output = tmp_path / "final.md"
    _write_json(prospective, _prospective())
    _followup(followup)
    (followup / "catalog_v1.json").unlink()

    result = build_run_report(
        prospective_path=prospective,
        output_path=output,
        followup_dir=followup,
        root=tmp_path,
    )

    assert result["status"] == "COMPLETE"
    assert result["followup"]["catalog_status"] == "NOT_SUPPLIED"
    assert result["followup"]["n_catalog_matches"] is None
    assert "no zero-match inference" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["coverage"].update(windows=6), "detector window count"),
        (lambda value: value["latency_s"].update(p95=1.0), "latency quantiles"),
        (
            lambda value: value["exact_replay"].update(disposition_mismatches=1),
            "disposition mismatch",
        ),
    ],
)
def test_report_rejects_inconsistent_primary_evidence(
    tmp_path: Path, mutation, message: str
) -> None:
    payload = _prospective()
    mutation(payload)
    prospective = tmp_path / "prospective.json"
    _write_json(prospective, payload)

    with pytest.raises(ContractError, match=message):
        build_run_report(
            prospective_path=prospective,
            output_path=tmp_path / "final.md",
            root=tmp_path,
        )


def test_report_rejects_auxiliary_self_hash_mismatch(tmp_path: Path) -> None:
    prospective = tmp_path / "prospective.json"
    followup = tmp_path / "followup"
    auxiliary = tmp_path / "auxiliary.json"
    _write_json(prospective, _prospective())
    _followup(followup)
    _auxiliary(auxiliary)
    payload = json.loads(auxiliary.read_text(encoding="utf-8"))
    payload["n_events"] = 3
    _write_json(auxiliary, payload)

    with pytest.raises(ContractError, match="self-hash"):
        build_run_report(
            prospective_path=prospective,
            output_path=tmp_path / "final.md",
            followup_dir=followup,
            auxiliary_path=auxiliary,
            root=tmp_path,
        )


def test_report_rejects_unlinked_auxiliary_cohort(tmp_path: Path) -> None:
    prospective = tmp_path / "prospective.json"
    auxiliary = tmp_path / "auxiliary.json"
    _write_json(prospective, _prospective())
    _auxiliary(auxiliary)

    with pytest.raises(ContractError, match="validated follow-up cohort"):
        build_run_report(
            prospective_path=prospective,
            output_path=tmp_path / "final.md",
            auxiliary_path=auxiliary,
            root=tmp_path,
        )


def test_report_verifier_rejects_rendered_report_tampering(tmp_path: Path) -> None:
    prospective = tmp_path / "prospective.json"
    output = tmp_path / "final.md"
    _write_json(prospective, _prospective())
    result = build_run_report(
        prospective_path=prospective,
        output_path=output,
        root=tmp_path,
    )
    output.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ContractError, match="rendered report hash"):
        verify_run_report(output.with_suffix(".md.json"), root=tmp_path)


def test_repository_forces_lf_for_generated_reports() -> None:
    attributes = (Path(__file__).resolve().parents[1] / ".gitattributes").read_text(
        encoding="utf-8"
    )
    assert "artifacts/dante_light/*.generated.md text eol=lf" in attributes
