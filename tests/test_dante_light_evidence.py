from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from src.dante_light.contracts import (
    CalibrationEpochContract,
    ContractError,
    LightDisposition,
    LightRecord,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light import evidence
from src.dante_light.evidence import compare_exact_runs


REPRESENTATION = RepresentationContract.from_reference_manifest(
    "config/reference_artifacts.json"
)


def _record(window: WindowIdentity, score: float) -> dict:
    body = LightRecord(
        window=window,
        representation_sha256=REPRESENTATION.contract_sha256,
        disposition=LightDisposition.NOT_ESCALATED,
        epoch_id=f"fixture-{window.detector.lower()}",
        scores=(("native", score), ("primary", score + 0.1)),
    ).to_dict()
    body["evidence"] = {
        "strain_sha256": "a" * 64,
        "image_sha256": "b" * 64,
        "primary_top_k_sha256": "c" * 64,
        "primary_mil_vector_sha256": "d" * 64,
    }
    return {**body, "record_id": f"dlr1-{canonical_json_sha256(body)[:24]}"}


def _run(
    root: Path,
    name: str,
    engine: str,
    records: list[dict],
    *,
    prospective: bool = False,
    epochs_payload: dict | None = None,
    latency_objective_s: float | None = None,
) -> Path:
    source = root / "src/dante_light/runner.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# fixture runner\n", encoding="utf-8", newline="\n")
    directory = root / name
    directory.mkdir()
    manifest_body = {
        "schema_version": 1,
        "mode": "shadow" if prospective else "historical_replay",
        "scientific_engine": engine,
        "prefilter": "none",
        "prospective": prospective,
        "representation": REPRESENTATION.to_dict(),
        "epochs": epochs_payload if epochs_payload is not None else {"fixture": True},
        "replay_manifest_sha256": "1" * 64,
        "replay_entries_file_sha256": "2" * 64,
        "roles": ["background_stratified"],
        "limit": len(records),
        "cat1_provenance": "GWOSC CBC_CAT1 whole-window containment",
        "local_only": False,
        "strain_source": "gwosc-only",
        "data_availability_mode": (
            "prestage_before_task_submission" if prospective else "inline"
        ),
        "pre_registered_latency_objective_s": latency_objective_s,
        "executor_config": {
            "requested_device": "cpu",
            "workers": 2,
            "batch_size": 8,
            "max_preprocess_in_flight": 16,
            "max_pending_writes": 2,
        },
        "runtime_provenance": {
            "code_state": {
                "commit": "e" * 40,
                "branch": "fixture",
                "tracked_dirty": False,
            },
            "source_sha256": {
                "src/dante_light/runner.py": hashlib.sha256(
                    b"# fixture runner\n"
                ).hexdigest()
            },
            "source_hash_semantics": "utf8_lf_v1",
            "environment": {
                "python": "fixture",
                "packages": {"numpy": "fixture"},
            },
        },
    }
    manifest = {
        **manifest_body,
        "manifest_sha256": canonical_json_sha256(manifest_body),
    }
    (directory / "run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (directory / "records.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    summary = {
        "schema_version": 1,
        "status": "complete",
        "records_total": len(records),
        "executor": {
            "submitted": len(records),
            "written": len(records),
            "deferred": 0,
            "drops": 0,
            "failures": [],
            "latency_s": [0.2 + index * 0.1 for index in range(len(records))],
        },
        "acquisition": {
            "mode": (
                "prestage_before_task_submission" if prospective else "none"
            ),
            "windows": len(records) if prospective else 0,
            "failures": [],
            "elapsed_s": 1.0 if prospective else 0.0,
            "duration_s": [0.4 + index * 0.1 for index in range(len(records))]
            if prospective
            else [],
        },
    }
    (directory / "summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
    return directory


def _bundle(root: Path) -> Path:
    path = root / "bundle.zip"
    member = b"fixture\n"
    manifest = f"{hashlib.sha256(member).hexdigest()}  fixture.txt\n".encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fixture.txt", member)
        archive.writestr("MANIFEST.sha256", manifest)
    return path


def test_exact_evidence_pair_validates_scores_hashes_and_latency(tmp_path) -> None:
    records = [
        _record(WindowIdentity("O4A", "H1", 1000 + index), 0.1 + index * 0.01)
        for index in range(2)
    ]
    canonical = _run(tmp_path, "canonical", "canonical", records)
    shared = _run(
        tmp_path, "shared", "shared_encoder_score_only", [dict(row) for row in records]
    )
    result = compare_exact_runs(
        canonical, shared, root=tmp_path, prospective=False
    )
    assert result["windows"] == 2
    assert result["max_abs_score_delta"] == 0.0
    assert result["disposition_mismatches"] == 0
    assert result["failures"] == []
    assert result["shared"].summary["executor"]["latency_s"] == pytest.approx(
        [0.2, 0.3]
    )


def test_exact_evidence_pair_rejects_score_and_manifest_tampering(tmp_path) -> None:
    record = _record(WindowIdentity("O4A", "L1", 2000), 0.1)
    canonical = _run(tmp_path, "canonical", "canonical", [record])
    shared_record = json.loads(json.dumps(record))
    shared_record["scores"]["native"] = 0.2
    body = dict(shared_record)
    body.pop("record_id")
    shared_record["record_id"] = f"dlr1-{canonical_json_sha256(body)[:24]}"
    shared = _run(
        tmp_path, "shared", "shared_encoder_score_only", [shared_record]
    )
    with pytest.raises(ContractError, match="score tolerance"):
        compare_exact_runs(canonical, shared, root=tmp_path, prospective=False)

    manifest_path = canonical / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["limit"] = 99
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ContractError, match="manifest digest"):
        compare_exact_runs(canonical, shared, root=tmp_path, prospective=False)


def test_prepublish_builder_cannot_masquerade_as_public_evidence(
    tmp_path, monkeypatch
) -> None:
    records = [_record(WindowIdentity("O4A", "H1", 1000), 0.1)]
    canonical = _run(tmp_path, "canonical", "canonical", records)
    shared = _run(
        tmp_path, "shared", "shared_encoder_score_only", [dict(row) for row in records]
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config/reference_artifacts.json").write_bytes(
        Path("config/reference_artifacts.json").read_bytes()
    )
    monkeypatch.setattr(
        evidence,
        "git_checkout_provenance",
        lambda _root: {
            "clean_clone": True,
            "tracked_dirty": False,
            "commit": "e" * 40,
            "origin_url": "https://example.test/repository.git",
        },
    )
    output = tmp_path / "preflight.json"
    payload = evidence.build_public_replay_evidence(
        canonical,
        shared,
        bundle_path=_bundle(tmp_path),
        output_path=output,
        root=tmp_path,
        mode="prepublish",
    )
    assert payload["mode"] == "clean_clone_prepublish_preflight"
    assert payload["public_sources_only"] is False
    assert payload["bundle_source"]["download_verified"] is False
    with pytest.raises(ContractError, match="differs from public contract"):
        evidence.build_public_replay_evidence(
            canonical,
            shared,
            bundle_path=_bundle(tmp_path),
            output_path=tmp_path / "public.json",
            root=tmp_path,
            mode="public",
        )


def _prospective_fixture(tmp_path: Path, monkeypatch, *, objective: float = 0.5):
    epochs_payload = {"schema_version": 1, "status": "fixture", "epochs": {}}
    epochs = {
        detector: CalibrationEpochContract(
            epoch_id=f"fixture-{detector.lower()}",
            run="O4A",
            detector=detector,
            cutoff_gps=1000.0,
            threshold=0.2,
            threshold_artifact_sha256="1" * 64,
            native_index_sha256=REPRESENTATION.native_index_sha256,
            causal=True,
        )
        for detector in ("H1", "L1")
    }
    records = [
        _record(WindowIdentity("O4A", detector, 1100.0), 0.1)
        for detector in ("H1", "L1")
    ]
    canonical = _run(
        tmp_path,
        "prospective-canonical",
        "canonical",
        records,
        prospective=True,
        epochs_payload=epochs_payload,
        latency_objective_s=objective,
    )
    shared = _run(
        tmp_path,
        "prospective-shared",
        "shared_encoder_score_only",
        [dict(row) for row in records],
        prospective=True,
        epochs_payload=epochs_payload,
        latency_objective_s=objective,
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config/reference_artifacts.json").write_bytes(
        Path("config/reference_artifacts.json").read_bytes()
    )
    epochs_path = tmp_path / "epochs.json"
    epochs_path.write_text(json.dumps(epochs_payload), encoding="utf-8")
    protocol = tmp_path / "docs/DANTE_LIGHT_PROSPECTIVE_PROTOCOL.md"
    protocol.parent.mkdir()
    protocol.write_text("locked fixture\n", encoding="utf-8")
    monkeypatch.setattr(
        evidence, "_load_verified_epochs", lambda *_args, **_kwargs: (epochs_payload, epochs)
    )
    monkeypatch.setattr(
        evidence,
        "git_checkout_provenance",
        lambda _root: {
            "clean_clone": True,
            "tracked_dirty": False,
            "commit": "e" * 40,
            "origin_url": "https://example.test/repository.git",
        },
    )
    return canonical, shared, epochs_path, _bundle(tmp_path), epochs


def test_prospective_builder_records_causal_coverage_and_durable_latency(
    tmp_path, monkeypatch
) -> None:
    canonical, shared, epochs_path, bundle, _epochs = _prospective_fixture(
        tmp_path, monkeypatch
    )
    payload = evidence.build_prospective_evidence(
        canonical,
        shared,
        epochs_path=epochs_path,
        bundle_path=bundle,
        output_path=tmp_path / "prospective-preflight.json",
        root=tmp_path,
        latency_objective_s=0.5,
        mode="preflight",
    )
    assert payload["mode"] == "prospective_shadow_preflight"
    assert payload["public_sources_only"] is False
    assert payload["latency_semantics"].endswith("durable record write")
    assert payload["latency_s"]["p99"] == pytest.approx(0.299)
    assert payload["latency_objective_met"] is True
    assert payload["data_availability"]["canonical"]["p99_s"] == pytest.approx(
        0.499
    )
    assert payload["execution"]["executor_config"]["workers"] == 2
    assert (tmp_path / "prospective-preflight.json").is_file()
    assert payload["coverage"]["windows"] == 2
    assert payload["coverage"]["deferred_windows"] == 0
    assert set(payload["detectors"]) == {"H1", "L1"}


def test_prospective_builder_preserves_unmet_latency_endpoint(
    tmp_path, monkeypatch
) -> None:
    canonical, shared, epochs_path, bundle, _epochs = _prospective_fixture(
        tmp_path, monkeypatch, objective=0.25
    )
    payload = evidence.build_prospective_evidence(
        canonical,
        shared,
        epochs_path=epochs_path,
        bundle_path=bundle,
        output_path=tmp_path / "prospective-negative.json",
        root=tmp_path,
        latency_objective_s=0.25,
        mode="preflight",
    )
    assert payload["status"] == "complete"
    assert payload["latency_objective_met"] is False


def test_prospective_builder_rejects_partial_resume_latency(
    tmp_path, monkeypatch
) -> None:
    canonical, shared, epochs_path, bundle, _epochs = _prospective_fixture(
        tmp_path, monkeypatch
    )
    summary_path = shared / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["executor"]["submitted"] = 1
    summary["executor"]["written"] = 1
    summary["executor"]["latency_s"] = [0.2]
    summary["acquisition"]["windows"] = 1
    summary["acquisition"]["duration_s"] = [0.4]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ContractError, match="executor/record count mismatch"):
        evidence.build_prospective_evidence(
            canonical,
            shared,
            epochs_path=epochs_path,
            bundle_path=bundle,
            output_path=tmp_path / "partial.json",
            root=tmp_path,
            latency_objective_s=0.5,
            mode="preflight",
        )


def test_prospective_builder_rejects_at_cutoff_window(tmp_path, monkeypatch) -> None:
    canonical, shared, epochs_path, bundle, epochs = _prospective_fixture(
        tmp_path, monkeypatch
    )
    epochs["H1"] = CalibrationEpochContract(
        epoch_id="fixture-h1",
        run="O4A",
        detector="H1",
        cutoff_gps=1100.0,
        threshold=0.2,
        threshold_artifact_sha256="1" * 64,
        native_index_sha256=REPRESENTATION.native_index_sha256,
        causal=True,
    )
    with pytest.raises(ContractError, match="non-causal prospective window"):
        evidence.build_prospective_evidence(
            canonical,
            shared,
            epochs_path=epochs_path,
            bundle_path=bundle,
            output_path=tmp_path / "invalid.json",
            root=tmp_path,
            latency_objective_s=0.5,
            mode="preflight",
        )


def test_operational_prospective_requires_exact_public_bundle(
    tmp_path, monkeypatch
) -> None:
    canonical, shared, epochs_path, bundle, _epochs = _prospective_fixture(
        tmp_path, monkeypatch
    )
    with pytest.raises(ContractError, match="differs from public contract"):
        evidence.build_prospective_evidence(
            canonical,
            shared,
            epochs_path=epochs_path,
            bundle_path=bundle,
            output_path=tmp_path / "operational.json",
            root=tmp_path,
            latency_objective_s=0.5,
            mode="operational",
        )
