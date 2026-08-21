from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path

import pytest

from scripts import build_dante_light_followup as cli


def _args(tmp_path: Path, stage: str, **updates) -> Namespace:
    values = {
        "stage": stage,
        "output_dir": tmp_path / "run_followup",
        "canonical_records": None,
        "shared_records": None,
        "primary_index": tmp_path / "index.npz",
        "catalog_url": "https://example.invalid/catalog",
        "device": "cpu",
        "no_iou": False,
    }
    values.update(updates)
    return Namespace(**values)


def test_manifest_stage_requires_explicit_paired_records(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical-records"):
        cli.run_stage(_args(tmp_path, "manifest"))


def test_manifest_stage_routes_to_new_run_directory(monkeypatch, tmp_path: Path) -> None:
    canonical = tmp_path / "canonical" / "records.jsonl"
    shared = tmp_path / "shared" / "records.jsonl"
    canonical.parent.mkdir()
    shared.parent.mkdir()
    row = json.dumps({"window": {"run": "O5"}}) + "\n"
    canonical.write_text(row, encoding="utf-8")
    shared.write_text(row, encoding="utf-8")
    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return {"status": "frozen"}

    monkeypatch.setattr(cli, "build_followup_manifest", fake_build)
    result = cli.run_stage(
        _args(
            tmp_path,
            "manifest",
            canonical_records=canonical,
            shared_records=shared,
        )
    )

    assert result["status"] == "frozen"
    assert result["run"] == "O5"
    assert captured == {
        "canonical_records": canonical,
        "shared_records": shared,
        "output_path": tmp_path / "run_followup" / "manifest_v1.json",
    }


def test_later_stage_refuses_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="manifest does not exist"):
        cli.run_stage(_args(tmp_path, "physical"))


def test_catalog_stage_uses_run_scoped_outputs(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "run_followup"
    output.mkdir()
    (output / "manifest_v1.json").write_text(
        json.dumps({"run": "O4B"}), encoding="utf-8"
    )
    captured = {}

    def fake_catalog(**kwargs):
        captured.update(kwargs)
        return {"status": "complete"}

    monkeypatch.setattr(cli, "fetch_and_crossmatch_gwtc5", fake_catalog)
    cli.run_stage(_args(tmp_path, "catalog"))

    assert captured["manifest_path"] == output / "manifest_v1.json"
    assert captured["output_path"] == output / "catalog_v1.json"
    assert captured["raw_output_path"] == output / "gwtc5_events_raw_v1.json"


def test_catalog_stage_rejects_unvalidated_later_run(tmp_path: Path) -> None:
    output = tmp_path / "run_followup"
    output.mkdir()
    (output / "manifest_v1.json").write_text(
        json.dumps({"run": "O5"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="validated only for O4B"):
        cli.run_stage(_args(tmp_path, "catalog"))
