from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from src.dante_light.contracts import (
    ContractError,
    LightDisposition,
    LightRecord,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light.prefilter import ExcessEnergyFeatures
from src.dante_light.prefilter_features import (
    build_shadow_feature_ledger,
    build_split_feature_ledger,
)
from src.dante_light.preprocessing import PreparedPrefilterFeatures


def _case(tmp_path):
    representation = "b" * 64
    entries = []
    records = []
    prepared = {}
    for index in range(3):
        window = WindowIdentity("O4B", "H1", 1400000000 + index * 32)
        entry = {
            "case_id": f"case-{index}",
            "window": window.to_dict(),
            "roles": ["shadow"],
        }
        entries.append(entry)
        strain_sha = f"{index + 1:064x}"
        record = LightRecord(
            window=window,
            representation_sha256=representation,
            disposition=LightDisposition.ESCALATE if index == 0 else LightDisposition.NOT_ESCALATED,
            epoch_id="fixture",
            scores=(("native", 0.2 if index == 0 else 0.1),),
        ).to_dict()
        record["evidence"] = {"strain_sha256": strain_sha}
        record["record_id"] = f"dlr1-{canonical_json_sha256(record)[:24]}"
        records.append(record)
        prepared[window.window_id] = PreparedPrefilterFeatures(
            features=ExcessEnergyFeatures(1.0, 6.0 - index, 0.1, 3.0),
            strain_sha256=strain_sha,
            timings={"data_read_s": 0.1},
        )
    entries_path = tmp_path / "entries.jsonl"
    entries_path.write_text("".join(json.dumps(row) + "\n" for row in entries), encoding="utf-8")
    manifest = {
        "entries_path": entries_path.name,
        "entries_file_sha256": hashlib.sha256(entries_path.read_bytes()).hexdigest(),
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    records_path = tmp_path / "records.jsonl"
    records_path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    return manifest_path, records_path, prepared


def test_build_shadow_feature_ledger_is_bound_and_deterministic(tmp_path):
    manifest, records, prepared = _case(tmp_path)
    output = tmp_path / "output"
    ledger = build_shadow_feature_ledger(
        root=tmp_path,
        manifest_path=manifest,
        records_path=records,
        output_dir=output,
        prepare=lambda task: prepared[task.window.window_id],
    )
    assert ledger["status"] == "complete"
    assert ledger["row_count"] == 3
    assert not (output / "shadow_features_v1.partial.jsonl").exists()
    first = (output / "shadow_features_v1.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(first)["exact_disposition"] == "ESCALATE"


def test_limited_feature_extraction_is_marked_smoke_only(tmp_path):
    manifest, records, prepared = _case(tmp_path)
    ledger = build_shadow_feature_ledger(
        root=tmp_path,
        manifest_path=manifest,
        records_path=records,
        output_dir=tmp_path / "smoke",
        limit=1,
        prepare=lambda task: prepared[task.window.window_id],
    )
    assert ledger["status"] == "smoke_only"
    assert ledger["selection_limit"] == 1


def test_shadow_feature_ledger_rejects_changed_raw_strain(tmp_path):
    manifest, records, prepared = _case(tmp_path)
    first = next(iter(prepared))
    prepared[first] = replace(prepared[first], strain_sha256="f" * 64)
    with pytest.raises(ContractError, match="raw strain digest changed"):
        build_shadow_feature_ledger(
            root=tmp_path,
            manifest_path=manifest,
            records_path=records,
            output_dir=tmp_path / "output",
            prepare=lambda task: prepared[task.window.window_id],
        )


def test_shadow_feature_ledger_resumes_partial_rows(tmp_path):
    manifest, records, prepared = _case(tmp_path)
    output = tmp_path / "output"
    calls = []

    def first_pass(task):
        calls.append(task.window.window_id)
        if len(calls) == 2:
            raise RuntimeError("interrupted")
        return prepared[task.window.window_id]

    with pytest.raises(RuntimeError, match="interrupted"):
        build_shadow_feature_ledger(
            root=tmp_path,
            manifest_path=manifest,
            records_path=records,
            output_dir=output,
            prepare=first_pass,
        )
    assert len((output / "shadow_features_v1.partial.jsonl").read_text().splitlines()) == 1
    resumed = []
    ledger = build_shadow_feature_ledger(
        root=tmp_path,
        manifest_path=manifest,
        records_path=records,
        output_dir=output,
        prepare=lambda task: resumed.append(task.window.window_id) or prepared[task.window.window_id],
    )
    assert ledger["row_count"] == 3
    assert len(resumed) == 2


def test_build_split_feature_ledger_preserves_frozen_partition(tmp_path):
    prepared = PreparedPrefilterFeatures(
        features=ExcessEnergyFeatures(1.0, 3.0, 0.1, 2.0),
        strain_sha256="a" * 64,
        timings={"data_read_s": 0.1},
    )
    ledger = build_split_feature_ledger(
        root=".",
        split_path="config/dante_light_prefilter_splits_v1.json",
        role="robust_candidate",
        output_dir=tmp_path,
        limit=2,
        prepare=lambda _task: prepared,
    )
    assert ledger["status"] == "smoke_only"
    rows = [
        json.loads(line)
        for line in (tmp_path / "robust_candidate_features_v1.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rows) == 2
    assert all(row["roles"] == ["robust_candidate"] for row in rows)
    assert all(row["exact_disposition"] == "NOT_APPLICABLE" for row in rows)
    assert all(row["partition"] in {"development", "evaluation"} for row in rows)


def test_split_feature_ledger_parallel_output_is_finally_deterministic(tmp_path):
    prepared = PreparedPrefilterFeatures(
        features=ExcessEnergyFeatures(1.0, 3.0, 0.1, 2.0),
        strain_sha256="a" * 64,
        timings={"data_read_s": 0.1},
    )
    ledger = build_split_feature_ledger(
        root=".",
        split_path="config/dante_light_prefilter_splits_v1.json",
        role="robust_candidate",
        output_dir=tmp_path,
        limit=8,
        workers=3,
        prepare=lambda _task: prepared,
    )
    assert ledger["row_count"] == 8
    assert ledger["extraction_workers"] == 3
    rows = [json.loads(line) for line in (tmp_path / ledger["rows_path"]).read_text().splitlines()]
    assert [row["cohort_id"] for row in rows] == sorted(row["cohort_id"] for row in rows)
