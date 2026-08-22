import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts.build_dante_light_prefilter_v2_bundle import build_bundle, verify_bundle
from src.dante_light.contracts import ContractError, canonical_json_sha256


ROLES = ("background", "robust_candidate", "known_glitch", "injection")


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    root = tmp_path / "root"
    for relative in (
        "config/dante_light_prefilter_protocol_v2.json",
        "config/dante_light_prefilter_v2_diagnostics.json",
        "config/dante_light_prefilter_splits_v2.json",
        "config/dante_light_prefilter_splits_v2.jsonl",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    note = root / "docs/DANTE_LIGHT_L4_PREFILTER_V2_NOT_READY_2026-08-22.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("diagnostic-only\n", encoding="utf-8")

    ledgers = {}
    sources = []
    for index, role in enumerate(ROLES):
        directory = tmp_path / "ledgers" / role
        directory.mkdir(parents=True)
        rows_path = directory / f"{role}_rows.jsonl"
        rows_path.write_text(json.dumps({"row": index}) + "\n", encoding="utf-8")
        split_sha = hashlib.sha256(f"split:{role}".encode()).hexdigest()
        ledger = {
            "schema_version": 2,
            "status": "complete",
            "role": role,
            "cohort_split_sha256_by_role": {role: split_sha},
            "row_count": 1,
            "rows_path": rows_path.name,
            "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
        }
        ledger["ledger_digest"] = canonical_json_sha256(ledger)
        ledger_path = directory / f"{role}_feature_ledger_v2.json"
        _write_json(ledger_path, ledger)
        ledgers[role] = ledger_path
        sources.append(
            {
                "file_name": ledger_path.name,
                "role": role,
                "role_split_sha256": split_sha,
                "rows_sha256": ledger["rows_sha256"],
                "sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
            }
        )

    screening = {
        "schema_version": 2,
        "status": "NOT_READY",
        "source_ledgers": sorted(sources, key=lambda item: item["role"]),
    }
    screening["artifact_digest"] = canonical_json_sha256(screening)
    _write_json(
        root / "artifacts/dante_light/prefilter_l4_v2/screening_result_v2.json",
        screening,
    )
    diagnostics = {
        "schema_version": 1,
        "status": "COMPLETE_DIAGNOSTIC_ONLY",
        "eligible_for_pass_fail_gate": False,
    }
    diagnostics["artifact_digest"] = canonical_json_sha256(diagnostics)
    _write_json(
        root / "artifacts/dante_light/prefilter_l4_v2/diagnostics_v2.json",
        diagnostics,
    )
    return root, ledgers


def test_bundle_is_deterministic_portable_and_complete(tmp_path):
    root, ledgers = _fixture(tmp_path)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first_result = build_bundle(ledgers=ledgers, output=first, root=root)
    second_result = build_bundle(ledgers=ledgers, output=second, root=root)

    assert first.read_bytes() == second.read_bytes()
    assert first_result["sha256"] == second_result["sha256"]
    verify_bundle(first)
    with zipfile.ZipFile(first) as archive:
        assert all("\\" not in name for name in archive.namelist())
        provenance = json.loads(archive.read("BUNDLE_PROVENANCE.json"))
        assert provenance["contains_o4b_outcomes"] is False
        assert provenance["contains_o4b_features"] is False
        assert len(provenance["source_ledgers"]) == 4


def test_bundle_rejects_ledger_not_bound_to_frozen_screen(tmp_path):
    root, ledgers = _fixture(tmp_path)
    ledger_path = ledgers["background"]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["extra"] = "changed"
    ledger.pop("ledger_digest")
    ledger["ledger_digest"] = canonical_json_sha256(ledger)
    _write_json(ledger_path, ledger)

    with pytest.raises(ContractError, match="provenance differs"):
        build_bundle(ledgers=ledgers, output=tmp_path / "invalid.zip", root=root)
