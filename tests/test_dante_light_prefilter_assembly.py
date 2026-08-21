from __future__ import annotations

import hashlib
import json

import pytest

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_assembly import assemble_prefilter_evaluation


ROLES = ("background", "shadow", "robust_candidate", "known_glitch", "injection")


def _write_source(tmp_path, role, rows, split_hash, representation):
    directory = tmp_path / role
    directory.mkdir()
    rows_path = directory / "rows.jsonl"
    rows_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    ledger = {
        "schema_version": 1,
        "status": "complete",
        "feature_source": "canonical_whitened_subwindow_v1",
        "representation_sha256": representation,
        "cohort_split_sha256_by_role": {role: split_hash},
        "row_count": len(rows),
        "rows_path": rows_path.name,
        "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
    }
    if role != "shadow":
        ledger["role"] = role
    ledger["ledger_digest"] = canonical_json_sha256(ledger)
    path = directory / "ledger.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    return path, ledger


def _row(index, role, partition, detector="H1"):
    morphology = {
        "background": "clean_background",
        "shadow": None,
        "robust_candidate": "unknown",
        "known_glitch": "Blip",
        "injection": "BBH_30_30",
    }[role]
    window = WindowIdentity("TEST", detector, 1000 + index * 32)
    return {
        "window": window.to_dict(),
        "roles": [role],
        "partition": partition,
        "split_artifact_sha256_by_role": {role: f"{ROLES.index(role) + 1:064x}"},
        "detector": detector,
        "morphology": morphology,
        "retention_target": role != "background",
        "exact_disposition": "ESCALATE" if role == "shadow" else "NOT_APPLICABLE",
        "representation_sha256": "a" * 64,
        "strain_sha256": f"{index + 20:064x}",
        "features": {
            "rms": 1.0,
            "crest_factor": 8.0,
            "peak_band_fraction": 0.2,
            "high_quantile_power": 2.0,
        },
    }


def _case(tmp_path):
    rows_by_role = {
        "background": [_row(0, "background", "development")],
        "shadow": [
            _row(1, "shadow", "evaluation", "H1"),
            _row(2, "shadow", "evaluation", "L1"),
        ],
        "robust_candidate": [
            _row(3, "robust_candidate", "development"),
            _row(4, "robust_candidate", "evaluation"),
        ],
        "known_glitch": [
            _row(5, "known_glitch", "development"),
            _row(6, "known_glitch", "evaluation"),
        ],
        "injection": [
            _row(7, "injection", "development"),
            _row(8, "injection", "evaluation"),
        ],
    }
    paths = {}
    ledgers = {}
    for role in ROLES:
        split_hash = f"{ROLES.index(role) + 1:064x}"
        paths[role], ledgers[role] = _write_source(
            tmp_path, role, rows_by_role[role], split_hash, "a" * 64
        )
    source_records = []
    for role in ("background", "robust_candidate", "known_glitch", "injection"):
        path = paths[role]
        ledger = ledgers[role]
        source_records.append({
            "role": role,
            "file_name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows_sha256": ledger["rows_sha256"],
            "role_split_sha256": ledger["cohort_split_sha256_by_role"][role],
        })
    tuning = {
        "schema_version": 1,
        "status": "PASS",
        "scientific_mode": "development_only_prefilter_tuning",
        "routing_enabled": False,
        "evaluation_outcomes_used": [],
        "representation_sha256": "a" * 64,
        "cohort_split_sha256_by_role": {
            role: ledgers[role]["cohort_split_sha256_by_role"][role]
            for role in ("background", "robust_candidate", "known_glitch", "injection")
        },
        "source_ledgers": source_records,
        "search": {"audit_fraction": 0.05, "audit_seed": 42},
        "operating_point": {"crest_threshold": 5.0, "band_fraction_threshold": 0.1},
    }
    tuning["artifact_digest"] = canonical_json_sha256(tuning)
    tuning_path = tmp_path / "tuning.json"
    tuning_path.write_text(json.dumps(tuning), encoding="utf-8")
    return paths, tuning_path


def test_assembly_includes_only_heldout_rows_and_locks_contract(tmp_path):
    paths, tuning_path = _case(tmp_path)
    output = tmp_path / "output"
    contract, ledger = assemble_prefilter_evaluation(
        ledgers=paths, tuning_path=tuning_path, output_dir=output
    )
    assert contract["status"] == "locked_before_evaluation"
    assert contract["required_detectors"] == ["H1", "L1"]
    assert ledger["row_count"] == 5
    rows = [json.loads(line) for line in (output / ledger["rows_path"]).read_text().splitlines()]
    assert all(row["partition"] == "evaluation" for row in rows)
    assert all(row["roles"] != ["background"] for row in rows)
    assert (output / contract["threshold_tuning_artifact"]["path"]).is_file()


def test_assembly_rejects_tuning_bound_to_changed_split(tmp_path):
    paths, tuning_path = _case(tmp_path)
    tuning = json.loads(tuning_path.read_text())
    tuning["cohort_split_sha256_by_role"]["known_glitch"] = "f" * 64
    body = dict(tuning)
    body.pop("artifact_digest")
    tuning["artifact_digest"] = canonical_json_sha256(body)
    tuning_path.write_text(json.dumps(tuning), encoding="utf-8")
    with pytest.raises(ContractError, match="source cohort splits"):
        assemble_prefilter_evaluation(
            ledgers=paths, tuning_path=tuning_path, output_dir=tmp_path / "output"
        )
