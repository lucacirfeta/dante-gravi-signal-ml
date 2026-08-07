"""Regression guards for the v6 critical scientific corrections."""

from __future__ import annotations

import json
import inspect
from pathlib import Path

import numpy as np
import pytest
import h5py
import pandas as pd

from src.core.index_contract import (
    load_index_contract,
    load_taxonomy_view,
    qrange_tag,
    validate_native_index,
)


def _write_index(path, *, qrange=None) -> None:
    payload = {
        "embeddings": np.ones((2, 384), dtype=np.float32),
        "labels": np.array(["BG", "BG"]),
    }
    if qrange is not None:
        payload["meta"] = json.dumps({"qrange": list(qrange)})
    np.savez(path, **payload)


def test_index_contract_refuses_silent_legacy_inference(tmp_path) -> None:
    index = tmp_path / "patch_compressed_index_o4a_ex.npz"
    _write_index(index)

    with pytest.raises(RuntimeError, match="no qrange contract"):
        load_index_contract(index)


def test_index_contract_legacy_mode_is_explicit_and_labelled(tmp_path) -> None:
    index = tmp_path / "patch_compressed_index_o4a_ex.npz"
    _write_index(index)

    contract = load_index_contract(index, allow_legacy_inference=True)

    assert contract.qrange == (4, 32)
    assert contract.legacy_inferred is True
    assert contract.declared is False


def test_declared_qrange_round_trip(tmp_path) -> None:
    index = tmp_path / "patch_compressed_index_o4a_q4-64_ex.npz"
    _write_index(index, qrange=(4, 64))

    contract = load_index_contract(index)

    assert contract.qrange == (4, 64)
    assert contract.tag == "q4-64"
    assert contract.declared is True
    assert contract.legacy_inferred is False
    assert len(contract.sha256) == 64


def _write_coherent_taxonomy_contract(
    aggregated,
    rows,
    *,
    total_failed: int = 0,
) -> tuple:
    representation = "idxq4-64_queryq4-64"
    taxonomy = aggregated / (
        f"Master_Taxonomy_O4a_{representation}.csv"
    )
    pd.DataFrame(rows).to_csv(taxonomy, index=False)
    audit = aggregated / (
        f"dsd_transition_audit_o4a_{representation}.json"
    )
    audit.write_text(
        json.dumps(
            {
                "experiment_run": True,
                "total_evaluated": len(rows),
                "total_failed": total_failed,
                "taxonomy_artifact": str(taxonomy),
                "representation": {
                    "coherent": True,
                    "variant": representation,
                },
            }
        ),
        encoding="utf-8",
    )
    return taxonomy, audit


def test_taxonomy_contract_exposes_only_coherent_scientific_aliases(
    tmp_path,
) -> None:
    taxonomy, _ = _write_coherent_taxonomy_contract(
        tmp_path,
        [
            {
                "detector": "H1",
                "gps_start": 100,
                "robustness_class": "BACKGROUND",
                "native_o4a_score": 0.1,
                "robustness_class_idxq4_64_queryq4_64": "ROBUST",
                "native_score_idxq4_64_queryq4_64": 0.5,
            }
        ],
    )

    frame, contract = load_taxonomy_view(tmp_path, "O4a")

    assert contract.path == taxonomy
    assert contract.representation == "idxq4-64_queryq4-64"
    assert frame.loc[0, "robustness_class"] == "BACKGROUND"
    assert frame.loc[0, "dsd_class"] == "ROBUST"
    assert frame.loc[0, "dsd_score"] == pytest.approx(0.5)


def test_taxonomy_contract_refuses_incomplete_dsd_population(tmp_path) -> None:
    _write_coherent_taxonomy_contract(
        tmp_path,
        [
            {
                "detector": "H1",
                "gps_start": 100,
                "robustness_class_idxq4_64_queryq4_64": "ROBUST",
                "native_score_idxq4_64_queryq4_64": 0.5,
            }
        ],
        total_failed=1,
    )

    with pytest.raises(RuntimeError, match="failed candidate evaluations"):
        load_taxonomy_view(tmp_path, "O4a")


def test_taxonomy_contract_never_falls_back_to_legacy_implicitly(
    tmp_path,
) -> None:
    pd.DataFrame(
        [
            {
                "detector": "H1",
                "gps_start": 100,
                "robustness_class": "ROBUST",
                "native_o4a_score": 0.5,
            }
        ]
    ).to_csv(tmp_path / "Master_Taxonomy_O4a.csv", index=False)

    with pytest.raises(RuntimeError, match="Refusing legacy"):
        load_taxonomy_view(tmp_path, "O4a")


def test_taxonomy_audit_accepts_windows_relative_path_under_shared_fs(
    monkeypatch,
    tmp_path,
) -> None:
    aggregated = tmp_path / "data" / "production" / "aggregated"
    aggregated.mkdir(parents=True)
    taxonomy, audit = _write_coherent_taxonomy_contract(
        aggregated,
        [
            {
                "detector": "H1",
                "gps_start": 100,
                "robustness_class_idxq4_64_queryq4_64": "ROBUST",
                "native_score_idxq4_64_queryq4_64": 0.5,
            }
        ],
    )
    payload = json.loads(audit.read_text(encoding="utf-8"))
    payload["taxonomy_artifact"] = (
        "data\\production\\aggregated\\" + taxonomy.name
    )
    audit.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    frame, contract = load_taxonomy_view(aggregated, "O4a")

    assert len(frame) == 1
    assert contract.path == taxonomy


def test_native_index_validation_checks_shape_norms_and_time_sidecar(
    tmp_path,
) -> None:
    path = tmp_path / "patch_compressed_index_o4a_q4-64_ex.npz"
    embeddings = np.eye(3, 384, dtype=np.float32)
    raw = np.eye(2, 384, dtype=np.float32)
    np.savez(
        path,
        embeddings=embeddings,
        labels=np.array(["BG"] * 3),
        raw_embeddings_sample=raw,
        meta=json.dumps(
            {
                "qrange": [4, 64],
                "K": 3,
                "detector": "both",
                "n_segments": 2,
            }
        ),
    )
    path.with_suffix(".t_bg.json").write_text(
        json.dumps([100.0, 200.0]),
        encoding="utf-8",
    )

    result = validate_native_index(
        path,
        expected_qrange=(4, 64),
        expected_k=3,
    )
    assert result["K"] == 3
    assert result["n_segments"] == 2
    assert result["max_centroid_norm_error"] == pytest.approx(0.0)

    embeddings[0] *= 2
    np.savez(
        path,
        embeddings=embeddings,
        labels=np.array(["BG"] * 3),
        raw_embeddings_sample=raw,
        meta=json.dumps(
            {
                "qrange": [4, 64],
                "K": 3,
                "detector": "both",
                "n_segments": 2,
            }
        ),
    )
    with pytest.raises(RuntimeError, match="not L2-normalized"):
        validate_native_index(
            path,
            expected_qrange=(4, 64),
            expected_k=3,
        )


def test_qrange_tag_validates_order() -> None:
    assert qrange_tag((4, 64)) == "q4-64"
    with pytest.raises(ValueError, match="Invalid qrange"):
        qrange_tag((64, 4))


def test_native_builder_default_name_is_versioned(monkeypatch, tmp_path) -> None:
    from src.pipeline_v2_production import build_native_index as builder

    monkeypatch.setattr(builder, "_candidate_exclusions", lambda *_args: [])
    monkeypatch.setattr(builder, "PatchEncoder", lambda: None)
    monkeypatch.setattr(
        builder,
        "iter_clean_segments",
        lambda *_args, **_kwargs: iter(()),
    )

    # The thin-background guard fires after the versioned path is resolved.
    with pytest.raises(RuntimeError, match="unrepresentative background"):
        builder.build_native_index(
            "O4a",
            "both",
            n_dict=100,
            qrange=(4, 64),
            out_dir=tmp_path,
            aggregated_dir=tmp_path,
        )

    assert not (tmp_path / "patch_compressed_index_o4a_ex.npz").exists()


def test_processed_window_ledger_is_exact_and_deduplicated(
    monkeypatch,
    tmp_path,
) -> None:
    from src.pipeline_v2_production import production_writer
    from src.pipeline_v2_production.processed_window_ledger import (
        load_exact_processed_coverage,
    )

    monkeypatch.setattr(production_writer, "record_environment", lambda *_a, **_k: None)
    writer = production_writer.ProductionWriter(tmp_path, "1234567890", "H1")
    writer.verify_and_init(
        {"reference_md5": "test", "k": 2},
        np.array([0.1], dtype=np.float32),
        0.5,
    )
    writer.append_processed([100.0, 132.0])
    writer.append_processed([132.0, 164.0])

    coverage = load_exact_processed_coverage(tmp_path, "H1")

    assert coverage is not None
    assert coverage["quality"] == "exact_successfully_scored_windows"
    assert coverage["n_windows"] == 3
    assert coverage["intervals"] == [[100.0, 196.0]]

    with h5py.File(writer.hdf5_path, "r") as handle:
        assert handle["processed_windows"].attrs["gps_semantics"] == (
            "analysis_window_start"
        )


def test_raw_block_coverage_is_labelled_as_proxy(tmp_path) -> None:
    from src.pipeline_v2_production.processed_window_ledger import (
        reconstruct_raw_block_coverage,
    )

    checkpoint = (
        tmp_path
        / "production"
        / "1234567890"
        / "checkpoints"
        / "last_gps_1234567890_H1.txt"
    )
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("DONE", encoding="utf-8")
    raw = tmp_path / "raw" / "1234567890"
    raw.mkdir(parents=True)
    (raw / "H1_100_196.hdf5").touch()

    coverage = reconstruct_raw_block_coverage(
        tmp_path / "production",
        "H1",
        data_directories=[tmp_path / "raw"],
    )

    assert coverage is not None
    assert coverage["source"] == "completed_session_raw_blocks"
    assert coverage["quality"].startswith("upper_bound_proxy")
    assert coverage["n_windows"] == 3
    assert coverage["livetime_s"] == pytest.approx(96.0)


def test_catalog_circular_shift_null_is_deterministic_and_long_form() -> None:
    from src.pipeline_v2_production.catalog_cross_match import (
        _circular_shift_null,
    )

    times = np.array([105.0, 405.0])
    coverage = {
        "H1": [(0.0, 1000.0)],
        "L1": [(0.0, 1000.0)],
    }
    candidates = {
        "H1": [(100.0, 132.0)],
        "L1": [],
    }

    first, summary_first = _circular_shift_null(
        times,
        coverage,
        candidates,
        run_bounds=(0.0, 1000.0),
        observed_any=1,
        observed_both=0,
        n_shifts=100,
        seed=11,
        minimum_shift_s=32.0,
    )
    second, summary_second = _circular_shift_null(
        times,
        coverage,
        candidates,
        run_bounds=(0.0, 1000.0),
        observed_any=1,
        observed_both=0,
        n_shifts=100,
        seed=11,
        minimum_shift_s=32.0,
    )

    assert first.equals(second)
    assert summary_first == summary_second
    assert len(first) == 100
    assert set(first.columns) == {
        "shift_id",
        "offset_s",
        "covered_any",
        "covered_both",
        "overlap_any",
        "overlap_both",
    }
    p_value = summary_first["overlap_any"]["empirical_p_ge_observed"]
    assert 1 / 101 <= p_value <= 1.0


def test_catalog_manifest_hashes_inputs_and_outputs(tmp_path) -> None:
    from src.pipeline_v2_production.catalog_cross_match import _write_manifest

    source = tmp_path / "input.json"
    result = tmp_path / "result.csv"
    source.write_text('{"x": 1}', encoding="utf-8")
    result.write_text("value\n2\n", encoding="utf-8")
    manifest = _write_manifest(
        result,
        run_name="O4a",
        inputs=[source],
        outputs=[result],
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert [row["role"] for row in payload["files"]] == ["input", "output"]
    assert all(len(row["sha256"]) == 64 for row in payload["files"])


def test_pem_manifest_hashes_complete_inputs_and_outputs(tmp_path) -> None:
    from src.pipeline_v2_production.pem_null_calibration import (
        write_pem_provenance_manifest,
    )

    pem_dir = tmp_path / "pem" / "idxq4-64_queryq4-64"
    pem_dir.mkdir(parents=True)
    taxonomy = tmp_path / "taxonomy.csv"
    audit = tmp_path / "audit.json"
    thresholds = tmp_path / "thresholds.json"
    taxonomy.write_text("detector,gps_start\nH1,100\n", encoding="utf-8")
    audit.write_text('{"ok": true}', encoding="utf-8")
    thresholds.write_text('{"ok": true}', encoding="utf-8")
    (pem_dir / "selection_manifest.json").write_text(
        json.dumps(
            {
                "taxonomy_representation": "idxq4-64_queryq4-64",
                "taxonomy_path": str(taxonomy),
                "taxonomy_audit_path": str(audit),
                "channel_thresholds_path": str(thresholds),
                "n_targets": 1,
            }
        ),
        encoding="utf-8",
    )
    (pem_dir / "selected_targets.csv").write_text(
        "detector,gps_start\nH1,100\n",
        encoding="utf-8",
    )
    (pem_dir / "coherence_report.csv").write_text(
        "detector,gps_start\nH1,100\n",
        encoding="utf-8",
    )
    (pem_dir / "null_calibration_H1_100.json").write_text(
        '{"event_gps": 100}',
        encoding="utf-8",
    )
    (pem_dir / "pem_family_wise_verdicts.csv").write_text(
        "detector,gps_start\nH1,100\n",
        encoding="utf-8",
    )
    (pem_dir / "pem_class_association.json").write_text(
        '{"n_events": 1}',
        encoding="utf-8",
    )

    manifest = write_pem_provenance_manifest(
        pem_dir,
        run="O4a",
        aggregated_dir=tmp_path,
        parameters={"alpha": 0.01},
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["n_targets"] == 1
    assert payload["n_null_calibrations"] == 1
    assert payload["parameters"]["alpha"] == 0.01
    assert len(payload["files"]) == 9
    assert {row["role"] for row in payload["files"]} == {"input", "output"}
    assert all(len(row["sha256"]) == 64 for row in payload["files"])


def test_blind_spot_injection_is_centred_and_qmax_text_is_current() -> None:
    from src.pipeline_v2_production import blind_spot_map

    gps = 1_382_955_253.0
    assert blind_spot_map._injection_center(gps) == pytest.approx(
        gps + blind_spot_map.SEGMENT_LENGTH / 2.0
    )
    assert blind_spot_map.Q_MAX == 64.0
    assert blind_spot_map.ANALYSIS_VERSION == "centered_q64_v3"
    assert blind_spot_map.QRANGE == (4, 64)
    assert "Qrange 4-64" in blind_spot_map.__doc__


def test_historical_catalog_offset_is_an_explicit_dsd_contract(
    monkeypatch,
    tmp_path,
) -> None:
    from src.pipeline_v2_production import aggregate_report

    monkeypatch.setattr(
        "src.core.utils.record_environment",
        lambda *_args, **_kwargs: None,
    )
    reporter = aggregate_report.AggregateReporter(
        production_dir=tmp_path,
        run="O4a",
        candidate_window_offset=4.0,
    )
    assert reporter._analysis_window_start(100.0) == 104.0

    current = aggregate_report.AggregateReporter(
        production_dir=tmp_path,
        run="O4a",
        candidate_window_offset=0.0,
    )
    assert current._analysis_window_start(100.0) == 100.0


def test_whitening_recalibration_helpers_are_deterministic_and_stratified() -> None:
    from src.pipeline_v2_production.whitening_context_sensitivity import (
        _block_bootstrap_p99_ci,
        _classify,
        _sample_near_threshold,
    )

    background = np.linspace(0.0, 1.0, 250)
    first = _block_bootstrap_p99_ci(background, B=100, seed=7)
    second = _block_bootstrap_p99_ci(background, B=100, seed=7)
    assert first == second
    assert first[1] <= first[2]
    assert first[0] == pytest.approx(np.percentile(background, 99))
    assert _classify(0.9, 0.4, 0.6) == "ROBUST"
    assert _classify(0.5, 0.4, 0.6) == "AMBIGUOUS"
    assert _classify(0.3, 0.4, 0.6) == "BACKGROUND"

    rows = []
    for det in ("H1", "L1"):
        for idx, (score, klass) in enumerate(
            [(0.35, "BACKGROUND"), (0.39, "BACKGROUND"),
             (0.61, "ROBUST"), (0.65, "ROBUST")]
        ):
            rows.append(
                {
                    "gps_start": idx + (0 if det == "H1" else 10),
                    "detector": det,
                    "score_v": score,
                    "class_v": klass,
                }
            )
    sample = _sample_near_threshold(
        pd.DataFrame(rows),
        n_each=1,
        thresholds={
            "H1": {"ci_lower": 0.4, "ci_upper": 0.6},
            "L1": {"ci_lower": 0.4, "ci_upper": 0.6},
        },
        score_column="score_v",
        class_column="class_v",
    )
    assert len(sample) == 4
    assert set(sample.class_v) == {"ROBUST", "BACKGROUND"}


def test_background_recalibration_does_not_override_requested_pad() -> None:
    from src.pipeline_v2_production.aggregate_report import AggregateReporter
    from src.pipeline_v2_production.background_calibration import (
        build_calibration_block_plan,
    )

    source = inspect.getsource(AggregateReporter._extract_detector_background)
    planner_source = inspect.getsource(build_calibration_block_plan)
    assert "pad = 4.0" not in source
    assert "random.shuffle(valid_files)" not in source
    assert 'pad=float(pad)' in source
    assert "build_calibration_block_plan(" in source
    assert "np.linspace(" in planner_source
    assert "block_len" in source
    assert "run_bounds=run_bounds" in source
    assert "forbidden_intervals=forbidden_intervals" in source


def test_background_extractor_empty_result_keeps_reuse_contract(
    tmp_path, monkeypatch
) -> None:
    import numpy as np

    from src.core import data_loader
    from src.pipeline_v2_production.aggregate_report import AggregateReporter

    monkeypatch.setattr(data_loader, "_DATA_DIRECTORIES", [])
    reporter = AggregateReporter(
        production_dir=tmp_path,
        run="O4a",
        native_background_n=2,
    )
    scores, ledger, reuse = reporter._extract_detector_background(
        scorer=object(),
        det_name="H1",
        target_n=2,
        run_bounds=(0.0, 1000.0),
        forbidden_intervals=[],
    )

    assert isinstance(scores, np.ndarray) and scores.size == 0
    assert ledger == []
    assert reuse == {"n_reused": 0, "n_computed": 0}


def test_o4a_calibration_bounds_match_the_gwosc_release() -> None:
    from src.core.utils import load_config
    from src.pipeline_v2_production.background_calibration import (
        resolve_run_bounds,
    )

    bounds = resolve_run_bounds(load_config(), "O4a")

    assert bounds == (1368975618.0, 1389456018.0)


def test_calibration_plan_rejects_cross_run_and_guarded_windows() -> None:
    from src.pipeline_v2_production.background_calibration import (
        RawBlock,
        build_calibration_block_plan,
        validate_calibration_ledger,
    )

    records = [
        RawBlock(100.0, 900.0, Path("L1_old.hdf5")),
        RawBlock(1000.0, 9000.0, Path("L1_o4a.hdf5")),
    ]
    forbidden = [
        (1200.0, 1232.0, "candidate"),
        (2000.0, 2032.0, "native_index"),
    ]

    blocks = build_calibration_block_plan(
        records,
        target_n=12,
        run_bounds=(1000.0, 9000.0),
        forbidden_intervals=forbidden,
        guard_s=96.0,
        block_length=2,
        pad_s=4.0,
        window_s=32.0,
        stride_s=64.0,
    )
    ledger = [window for block in blocks for window in block.windows][:12]
    audit = validate_calibration_ledger(
        ledger,
        run_bounds=(1000.0, 9000.0),
        forbidden_intervals=forbidden,
        guard_s=96.0,
    )

    assert len(ledger) == 12
    assert {window.source_path.name for window in ledger} == {"L1_o4a.hdf5"}
    assert all(len(block.windows) == 2 for block in blocks)
    assert all(
        block.windows[1].gps_start - block.windows[0].gps_start == 64.0
        for block in blocks
    )
    assert audit == {
        "n_windows": 12,
        "outside_run": 0,
        "forbidden_overlap": 0,
        "self_overlap": 0,
    }


def test_calibration_plan_deduplicates_overlapping_raw_archives() -> None:
    from src.pipeline_v2_production.background_calibration import (
        RawBlock,
        build_calibration_block_plan,
        validate_calibration_ledger,
    )

    records = [
        RawBlock(1000.0, 9000.0, Path("primary/L1_1000_9000.hdf5")),
        RawBlock(1000.0, 9000.0, Path("mirror/L1_1000_9000.hdf5")),
        RawBlock(5000.0, 13000.0, Path("overlap/L1_5000_13000.hdf5")),
    ]
    blocks = build_calibration_block_plan(
        records,
        target_n=40,
        run_bounds=(1000.0, 13000.0),
        forbidden_intervals=[],
        guard_s=96.0,
        block_length=4,
    )
    windows = [window for block in blocks[:10] for window in block.windows]
    audit = validate_calibration_ledger(
        windows,
        run_bounds=(1000.0, 13000.0),
        forbidden_intervals=[],
        guard_s=96.0,
    )

    assert len(windows) == 40
    assert audit["self_overlap"] == 0


def test_block_bootstrap_is_batched_deterministic_and_production_sized() -> None:
    from src.pipeline_v2_production.background_calibration import (
        DEFAULT_BOOTSTRAP_REPLICATES,
        block_bootstrap_p99_ci,
    )

    scores = np.linspace(0.0, 1.0, 250, dtype=np.float64)
    small_chunks = block_bootstrap_p99_ci(
        scores,
        B=200,
        seed=7,
        chunk_size=7,
    )
    large_chunks = block_bootstrap_p99_ci(
        scores,
        B=200,
        seed=7,
        chunk_size=200,
    )

    assert small_chunks == large_chunks
    assert small_chunks["ci_lower"] <= small_chunks["ci_upper"]
    assert small_chunks["p99"] == pytest.approx(np.percentile(scores, 99))
    assert small_chunks["block_length"] == int(len(scores) ** (1 / 3))
    assert DEFAULT_BOOTSTRAP_REPLICATES == 1_000_000

    from src.pipeline_v2_production.dsd_threshold_mc_error import (
        _bootstrap_p99,
    )

    assert _bootstrap_p99(scores, B=200, seed=7).shape == (200,)


def test_calibration_ledger_audit_detects_leakage() -> None:
    from src.pipeline_v2_production.background_calibration import (
        CalibrationWindow,
        validate_calibration_ledger,
    )

    ledger = [
        CalibrationWindow(
            gps_start=900.0,
            gps_end=932.0,
            source_path=Path("old.hdf5"),
            source_start=800.0,
            source_end=1200.0,
        ),
        CalibrationWindow(
            gps_start=1200.0,
            gps_end=1232.0,
            source_path=Path("candidate.hdf5"),
            source_start=1000.0,
            source_end=2000.0,
        ),
    ]

    audit = validate_calibration_ledger(
        ledger,
        run_bounds=(1000.0, 2000.0),
        forbidden_intervals=[(1210.0, 1242.0, "candidate")],
        guard_s=0.0,
    )

    assert audit["outside_run"] == 1
    assert audit["forbidden_overlap"] == 1


def test_dsd_transition_does_not_overwrite_legacy_taxonomy_columns() -> None:
    from src.pipeline_v2_production.aggregate_report import AggregateReporter

    source = inspect.getsource(AggregateReporter._run_domain_shift_defense)
    assert 'tax_df["robustness_class"] = tax_df.apply' not in source
    assert 'tax_df["native_score"] = tax_df.apply' not in source
    assert 'class_column = f"robustness_class_{variant_column}"' in source
    assert 'score_column = f"native_score_{variant_column}"' in source
    assert '"NOT_EVALUATED"' in source
    assert 'metrics["total_failed"] = total - evaluated_total' in source
    assert "variant_tax_path" in source
    assert "temporary_tax_path.replace(variant_tax_path)" in source
    assert "batch_size = 32" in source
    assert "scorer.score_spectrogram(\n                    batch_images" in source


def test_dsd_transition_entrypoint_writes_a_separate_audit(
    monkeypatch,
    tmp_path,
) -> None:
    from src.pipeline_v2_production import dsd_transition_audit

    aggregated = tmp_path / "aggregated"
    aggregated.mkdir()
    pd.DataFrame(
        [{"gps_start": 100, "detector": "H1", "robustness_class": "ROBUST"}]
    ).to_csv(aggregated / "Master_Taxonomy_O4a.csv", index=False)

    class DummyReporter:
        def __init__(self, **kwargs):
            assert kwargs["candidate_window_offset"] == 4.0

        def _run_domain_shift_defense(self, taxonomy):
            assert len(taxonomy) == 1
            return {
                "experiment_run": True,
                "representation": {"variant": "idxq4-64_queryq4-64"},
            }

    monkeypatch.setattr(dsd_transition_audit, "AggregateReporter", DummyReporter)
    monkeypatch.setattr(
        dsd_transition_audit,
        "validate_native_index",
        lambda *_args, **_kwargs: {
            "validated": True,
            "qrange": [4, 64],
        },
    )
    monkeypatch.setattr(
        dsd_transition_audit,
        "_validate_builder_provenance",
        lambda *_args, **_kwargs: {"validated": True},
    )
    monkeypatch.setattr(
        dsd_transition_audit,
        "record_environment",
        lambda *_args, **_kwargs: None,
    )
    metrics = dsd_transition_audit.run(
        run_name="O4a",
        production_dir=tmp_path,
        native_index_path=tmp_path / "index.npz",
    )

    assert metrics["experiment_run"] is True
    assert (
        aggregated
        / "dsd_transition_audit_o4a_idxq4-64_queryq4-64.json"
    ).exists()


def test_dirty_builder_provenance_requires_and_hashes_source_snapshot(
    tmp_path,
) -> None:
    from src.pipeline_v2_production.dsd_transition_audit import (
        _validate_builder_provenance,
    )

    index = tmp_path / "patch_compressed_index_o4a_q4-64_ex.npz"
    index.touch()
    snapshot = tmp_path / "source_state_build_native_index_o4a_q4-64.zip"
    snapshot.write_bytes(b"source-state")
    digest = __import__("hashlib").sha256(snapshot.read_bytes()).hexdigest()
    environment = tmp_path / "environment_build_native_index_o4a_q4-64.json"
    environment.write_text(
        json.dumps(
            {
                "context": "build_native_index_o4a_q4-64",
                "note": f"native index {index.name}",
                "git_commit": "abc",
                "git_dirty": True,
                "dirty_source_snapshot": str(snapshot),
                "dirty_source_snapshot_sha256": digest,
                "python": "3.11",
                "packages": {"gwpy": "4.0.1"},
                "torch": {"version": "test"},
            }
        ),
        encoding="utf-8",
    )

    result = _validate_builder_provenance(
        index,
        run_name="O4a",
        qrange=(4, 64),
    )
    assert result["dirty_source_snapshot_sha256"] == digest
    snapshot.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="does not match"):
        _validate_builder_provenance(
            index,
            run_name="O4a",
            qrange=(4, 64),
        )


def test_verified_dsd_score_reuse_requires_exact_scientific_population(
    tmp_path,
) -> None:
    from src.pipeline_v2_production.dsd_transition_audit import (
        _validate_reusable_candidate_scores,
    )

    representation = "idxq4-64_queryq4-64"
    index_sha256 = "a" * 64
    taxonomy = pd.DataFrame(
        {
            "gps_start": [100.0, 200.0],
            "detector": ["H1", "L1"],
        }
    )
    scores = pd.DataFrame(
        {
            "candidate_id": ["100.0_H1", "200.0_L1"],
            "gps_start": [100.0, 200.0],
            "detector": ["H1", "L1"],
            "score": [0.1, 0.2],
            "variant": [representation, representation],
        }
    )
    score_path = tmp_path / "scores.csv"
    scores.to_csv(score_path, index=False)
    source_taxonomy_path = tmp_path / (
        "Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"
    )
    taxonomy.assign(
        native_score_idxq4_64_queryq4_64=[0.1, 0.2]
    ).to_csv(source_taxonomy_path, index=False)
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "experiment_run": True,
                "total_failed": 0,
                "total_evaluated": 2,
                "long_form_scores": str(score_path),
                "taxonomy_artifact": str(source_taxonomy_path),
                "representation": {
                    "variant": representation,
                    "coherent": True,
                    "index_sha256": index_sha256,
                    "catalog_gps_to_analysis_window_offset_s": 4.0,
                },
            }
        ),
        encoding="utf-8",
    )

    validated, provenance = _validate_reusable_candidate_scores(
        taxonomy,
        score_path,
        audit_path,
        representation=representation,
        index_sha256=index_sha256,
        candidate_window_offset=4.0,
    )
    assert len(validated) == 2
    assert provenance["exact_candidate_key_match"] is True
    assert provenance["all_scores_finite"] is True

    scores.loc[1, "gps_start"] = 300.0
    scores.to_csv(score_path, index=False)
    with pytest.raises(RuntimeError, match="population mismatch"):
        _validate_reusable_candidate_scores(
            taxonomy,
            score_path,
            audit_path,
            representation=representation,
            index_sha256=index_sha256,
            candidate_window_offset=4.0,
        )


def test_patch_production_refuses_silent_legacy_native_dual_scoring() -> None:
    import main

    source = inspect.getsource(main.cmd_patch_production)
    assert "load_index_contract(candidate_index)" in source
    assert "allow_legacy_inference=True" not in source
    assert "No declared native index matches PatchProducer qrange" in source


def test_near_threshold_sampling_uses_coherent_nonrobust_boundary() -> None:
    from src.pipeline_v2_production.dsd_index_stability import _sample

    rows = []
    for detector in ("H1", "L1"):
        rows.extend(
            [
                {
                    "detector": detector,
                    "gps_start": 1,
                    "dsd_class": "BACKGROUND",
                    "dsd_score": 0.20,
                },
                {
                    "detector": detector,
                    "gps_start": 2,
                    "dsd_class": "AMBIGUOUS",
                    "dsd_score": 0.41,
                },
                {
                    "detector": detector,
                    "gps_start": 3,
                    "dsd_class": "ROBUST",
                    "dsd_score": 0.43,
                },
                {
                    "detector": detector,
                    "gps_start": 4,
                    "dsd_class": "ROBUST",
                    "dsd_score": 0.50,
                },
            ]
        )
    selected = _sample(
        pd.DataFrame(rows),
        1,
        {
            "H1": {"ci_upper": 0.42},
            "L1": {"ci_upper": 0.42},
        },
    )

    assert len(selected) == 4
    assert set(selected.dsd_class) == {"ROBUST", "AMBIGUOUS"}
    assert not selected.dsd_class.eq("BACKGROUND").any()


def test_class_dependent_v6_modules_resolve_coherent_taxonomy() -> None:
    from src.pipeline_v2_production import (
        background_cohesion_test,
        catalog_cross_match,
        dsd_index_stability,
        dsd_k_sensitivity,
        inter_session_recurrence,
        pca_baseline,
        pem_coherence_analysis,
    )

    modules = (
        background_cohesion_test,
        catalog_cross_match,
        dsd_index_stability,
        dsd_k_sensitivity,
        inter_session_recurrence,
        pca_baseline,
        pem_coherence_analysis,
    )
    for module in modules:
        source = inspect.getsource(module)
        assert "load_taxonomy_view" in source, module.__name__
        assert "native_o4a_score" not in source, module.__name__
        assert '["robustness_class"]' not in source, module.__name__


def test_injection_controls_do_not_open_the_legacy_native_index() -> None:
    from src.pipeline_v2_production import (
        astrophysical_injection,
        blind_spot_map,
    )

    for module in (astrophysical_injection, blind_spot_map):
        source = inspect.getsource(module)
        assert "patch_compressed_index_o4a_ex.npz" not in source
        assert "patch_compressed_index_o4a_q4-64_ex.npz" in source
        assert "idxq4-64_queryq4-64" not in source


def test_p9_dsd_classification_uses_both_c2_interval_endpoints() -> None:
    from src.pipeline_v2_production.astrophysical_injection import _dsd_class

    assert _dsd_class(0.10, 0.15, 0.22) == "BACKGROUND"
    assert _dsd_class(0.15, 0.15, 0.22) == "AMBIGUOUS"
    assert _dsd_class(0.22, 0.15, 0.22) == "AMBIGUOUS"
    assert _dsd_class(0.220001, 0.15, 0.22) == "ROBUST"


def test_p9_attaches_count_based_wilson_intervals() -> None:
    from src.pipeline_v2_production.astrophysical_injection import (
        _attach_binomial_uncertainty,
        _wilson_interval,
    )

    trials = pd.DataFrame(
        {
            "system": ["BBH"] * 4,
            "distance_mpc": [100.0] * 4,
            "flag_H1": [True, True, False, False],
            "flag_L1": [False, True, False, False],
            "dsd_class_H1": [
                "ROBUST", "AMBIGUOUS", "BACKGROUND", "BACKGROUND"
            ],
            "dsd_class_L1": [
                "BACKGROUND", "ROBUST", "BACKGROUND", "BACKGROUND"
            ],
            "coincidence_localized_H1": [True, False, False, False],
            "coincidence_localized_L1": [False, True, False, False],
            "coincidence_recovered": [True, True, False, False],
            "coincidence_oracle_recovered": [True, False, False, False],
        }
    )
    rows = [{"system": "BBH", "distance_mpc": 100.0, "n": 4}]
    _attach_binomial_uncertainty(rows, trials)

    endpoints = rows[0]["binomial_endpoints"]
    assert endpoints["flag_either"]["k"] == 2
    assert endpoints["flag_either"]["n"] == 4
    assert endpoints["coincidence_given_primary_flag"]["k"] == 2
    assert endpoints["coincidence_given_primary_flag"]["n"] == 2
    assert rows[0]["dsd_class_binomial_H1"]["ROBUST"]["k"] == 1
    assert _wilson_interval(0, 25)[0] == 0.0
    assert _wilson_interval(0, 25)[1] == pytest.approx(0.13319225094)
    assert _wilson_interval(25, 25)[0] == pytest.approx(0.86680774906)
    assert _wilson_interval(25, 25)[1] == 1.0


def test_c2_queue_has_a_fail_closed_artifact_gate_after_each_gpu_stage() -> None:
    script = Path("scripts/run_c2_bgv3_gpu_queue.ps1").read_text(
        encoding="utf-8"
    )

    for stage in (
        "p5",
        "p4",
        "p10",
        "multiscale",
        "cohesion",
        "whitening",
        "p9",
    ):
        assert f'"--stage", "{stage}"' in script
    assert "verify_c2_bgv3_artifacts.py" in script


def test_report_uses_coherent_aliases_and_versioned_pem_without_fallback() -> None:
    from src.pipeline_v2_production.aggregate_report import AggregateReporter

    report_source = inspect.getsource(
        AggregateReporter._generate_markdown_report
    )
    ledger_source = inspect.getsource(
        AggregateReporter._build_disposition_ledger
    )
    assert 'tax_df["robustness_class"] = tax_df["dsd_class"]' in report_source
    assert 'tax_df["native_o4a_score"] = tax_df["dsd_score"]' in report_source
    assert '"taxonomy_representation"' in report_source
    assert "coherent_pem" in ledger_source
    assert "no legacy " in ledger_source
    assert "analytic fallback permitted)" in ledger_source


def test_pem_existing_sample_propagation_changes_the_inference(
    monkeypatch,
    tmp_path,
) -> None:
    from src.pipeline_v2_production import pem_class_propagation

    rows = []
    verdicts = []
    # Legacy: ROBUST 2/3 coupled, BACKGROUND 0/3.
    # Coherent: one coupled legacy ROBUST moves to BACKGROUND, so the apparent
    # enrichment disappears. The test checks the exact join, not a hardcoded
    # production number.
    specifications = [
        ("ROBUST", "ROBUST", "COUPLED"),
        ("ROBUST", "BACKGROUND", "COUPLED"),
        ("ROBUST", "ROBUST", "NO_CORRELATION"),
        ("BACKGROUND", "BACKGROUND", "NO_CORRELATION"),
        ("BACKGROUND", "ROBUST", "NO_CORRELATION"),
        ("BACKGROUND", "BACKGROUND", "NO_CORRELATION"),
    ]
    for gps, (legacy, coherent, verdict) in enumerate(
        specifications,
        start=100,
    ):
        rows.append(
            {
                "detector": "H1",
                "gps_start": gps,
                "robustness_class": legacy,
                "native_o4a_score": 0.1,
                "robustness_class_idxq4_64_queryq4_64": coherent,
                "native_score_idxq4_64_queryq4_64": 0.5,
            }
        )
        verdicts.append(
            {
                "detector": "H1",
                "gps_start": gps,
                "verdict_tier": verdict,
            }
        )
    _write_coherent_taxonomy_contract(tmp_path, rows)
    verdict_path = tmp_path / "legacy_verdicts.csv"
    pd.DataFrame(verdicts).to_csv(verdict_path, index=False)
    monkeypatch.setattr(
        pem_class_propagation,
        "record_environment",
        lambda *_args, **_kwargs: None,
    )

    result = pem_class_propagation.run(
        "O4a",
        aggregated_dir=tmp_path,
        legacy_verdicts=verdict_path,
    )

    assert result["n_matched"] == 6
    assert result["n_class_changed"] == 2
    assert (
        result["legacy_class_result"]["odds_ratio"]
        != result["coherent_class_result"]["odds_ratio"]
    )
    assert Path(result["rows_path"]).exists()


def test_gpu_queue_uses_native_exit_codes_not_stderr_warnings() -> None:
    script = Path("scripts/run_v6_coherent_gpu_queue.ps1").read_text(
        encoding="utf-8"
    )

    assert '$ErrorActionPreference = "Continue"' in script
    assert "$stepExitCode = $LASTEXITCODE" in script
    assert "if ($stepExitCode -ne 0)" in script
    assert "$p9ExitCode = $LASTEXITCODE" in script
    assert "if ($p9ExitCode -ne 0)" in script


def test_pem_class_association_excludes_uncalibrated_events() -> None:
    from src.pipeline_v2_production.pem_null_calibration import (
        _pem_class_association_summary,
    )

    rows = []
    for klass, coupled, suspect, negative, uncalibrated in (
        ("ROBUST", 3, 3, 17, 0),
        ("AMBIGUOUS", 4, 5, 11, 0),
        ("BACKGROUND", 5, 21, 65, 7),
    ):
        rows.extend(
            {
                "dsd_class": klass,
                "verdict": "COUPLED",
                "verdict_tier": "COUPLED",
                "taxonomy_representation": "idxq4-64_queryq4-64",
            }
            for _ in range(coupled)
        )
        rows.extend(
            {
                "dsd_class": klass,
                "verdict": "COUPLED",
                "verdict_tier": "SUSPECT",
                "taxonomy_representation": "idxq4-64_queryq4-64",
            }
            for _ in range(suspect)
        )
        rows.extend(
            {
                "dsd_class": klass,
                "verdict": "NO_CORRELATION",
                "verdict_tier": "NO_CORRELATION",
                "taxonomy_representation": "idxq4-64_queryq4-64",
            }
            for _ in range(negative)
        )
        rows.extend(
            {
                "dsd_class": klass,
                "verdict": "UNCALIBRATED",
                "verdict_tier": "UNCALIBRATED",
                "taxonomy_representation": "idxq4-64_queryq4-64",
            }
            for _ in range(uncalibrated)
        )

    summary = _pem_class_association_summary(pd.DataFrame(rows))
    primary = summary["endpoints"]["zero_lag_confirmed"]

    assert summary["n_events"] == 141
    assert summary["n_calibrated"] == 134
    assert summary["n_uncalibrated"] == 7
    assert primary["by_class"]["ROBUST"]["n_positive"] == 3
    assert primary["by_class"]["ROBUST"]["n_calibrated"] == 23
    assert primary["by_class"]["BACKGROUND"]["n_positive"] == 5
    assert primary["by_class"]["BACKGROUND"]["n_calibrated"] == 91
    assert primary["robust_vs_background"]["table_positive_negative"] == [
        [3, 20],
        [5, 86],
    ]


def test_whitening_candidate_scoring_requires_exact_context(
    monkeypatch,
) -> None:
    from src.core import data_loader, preprocessor
    from src.pipeline_v2_production.whitening_context_sensitivity import (
        _score_at_pads,
    )

    calls = []

    def fake_fetch(detector, start, end, **kwargs):
        calls.append((detector, start, end, kwargs))
        return object()

    monkeypatch.setattr(data_loader, "fetch_local_or_remote_strain", fake_fetch)
    monkeypatch.setattr(
        preprocessor,
        "whiten_context",
        lambda ts, start, end, pad: (object(), {"left": 0.0, "right": 0.0}),
    )
    monkeypatch.setattr(
        preprocessor,
        "extract_clean_subwindow",
        lambda ts, start, end: object(),
    )
    monkeypatch.setattr(
        preprocessor,
        "generate_qtransform",
        lambda *args, **kwargs: np.zeros((2, 2), dtype=float),
    )

    class FakeScorer:
        def score_spectrogram(self, images, threshold):
            return [{"novelty_score": 0.25}]

    candidates = pd.DataFrame(
        [{"detector": "H1", "gps_start": 100}]
    )
    scores, kept, failures = _score_at_pads(
        candidates,
        (4.0, 16.0),
        FakeScorer(),
        qrange=(4, 64),
        window_offset=4.0,
    )

    assert kept.tolist() == [True]
    assert failures == []
    assert scores.tolist() == [[0.25, 0.25]]
    assert [call[3]["edge_tolerance"] for call in calls] == [0.0, 0.0]


def test_whitening_candidate_scoring_records_failures(
    monkeypatch,
) -> None:
    from src.core import data_loader
    from src.pipeline_v2_production.whitening_context_sensitivity import (
        _score_at_pads,
    )

    monkeypatch.setattr(
        data_loader,
        "fetch_local_or_remote_strain",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("missing exact context")
        ),
    )
    candidates = pd.DataFrame(
        [{"detector": "L1", "gps_start": 200}]
    )
    scores, kept, failures = _score_at_pads(
        candidates,
        (4.0, 16.0),
        object(),
        qrange=(4, 64),
        window_offset=4.0,
    )

    assert kept.tolist() == [False]
    assert np.isnan(scores).all()
    assert failures == [
        {
            "detector": "L1",
            "gps_start": 200,
            "analysis_start": 204.0,
            "pad_s": 4.0,
            "error_type": "RuntimeError",
            "error": "missing exact context",
        }
    ]


def test_whitening_balanced_scoring_uses_same_stratum_reserve(
    monkeypatch,
) -> None:
    from src.pipeline_v2_production import whitening_context_sensitivity

    class_column = "class"
    rows = []
    gps = 100
    for detector in ("H1", "L1"):
        for klass in ("ROBUST", "BACKGROUND"):
            for _ in range(3):
                rows.append(
                    {
                        "detector": detector,
                        "gps_start": gps,
                        class_column: klass,
                        "stored_score": 0.25,
                    }
                )
                gps += 1
    pool = pd.DataFrame(rows)

    def fake_score(candidates, pads, scorer, **kwargs):
        candidate = candidates.iloc[0]
        failed = int(candidate.gps_start) == 100
        scores = np.full((1, len(pads)), np.nan if failed else 0.25)
        failures = (
            [{
                "detector": candidate.detector,
                "gps_start": int(candidate.gps_start),
                "analysis_start": float(candidate.gps_start + 4),
                "pad_s": float(pads[0]),
                "error_type": "ValueError",
                "error": "non-finite raw data",
            }]
            if failed
            else []
        )
        return scores, np.array([not failed]), failures

    monkeypatch.setattr(
        whitening_context_sensitivity,
        "_score_at_pads",
        fake_score,
    )
    selected, scores, failures, attempted, counts = (
        whitening_context_sensitivity._score_balanced_at_pads(
            pool,
            (4.0, 16.0),
            object(),
            qrange=(4, 64),
            window_offset=4.0,
            class_column=class_column,
            score_column="stored_score",
            n_each=2,
            anchor_tolerance=1e-3,
        )
    )

    assert len(selected) == 8
    assert scores.shape == (8, 2)
    assert 100 not in selected.gps_start.tolist()
    assert selected[
        (selected.detector == "H1") & (selected[class_column] == "ROBUST")
    ].gps_start.tolist() == [101, 102]
    assert attempted["H1"]["ROBUST"] == 3
    assert counts == {
        "H1": {"ROBUST": 2, "BACKGROUND": 2},
        "L1": {"ROBUST": 2, "BACKGROUND": 2},
    }
    assert len(failures) == 1


def test_whitening_balanced_scoring_replaces_anchor_mismatch(
    monkeypatch,
) -> None:
    from src.pipeline_v2_production import whitening_context_sensitivity

    pool = pd.DataFrame(
        [
            {
                "detector": detector,
                "gps_start": gps,
                "class": klass,
                "stored_score": 0.25,
            }
            for detector, klass, gps in (
                ("H1", "ROBUST", 100),
                ("H1", "ROBUST", 101),
                ("H1", "BACKGROUND", 200),
                ("L1", "ROBUST", 300),
                ("L1", "BACKGROUND", 400),
            )
        ]
    )

    def fake_score(candidates, pads, scorer, **kwargs):
        gps = int(candidates.iloc[0].gps_start)
        value = 0.50 if gps == 100 else 0.25
        return (
            np.full((1, len(pads)), value),
            np.array([True]),
            [],
        )

    monkeypatch.setattr(
        whitening_context_sensitivity,
        "_score_at_pads",
        fake_score,
    )
    selected, _, failures, attempted, counts = (
        whitening_context_sensitivity._score_balanced_at_pads(
            pool,
            (4.0, 16.0),
            object(),
            qrange=(4, 64),
            window_offset=4.0,
            class_column="class",
            score_column="stored_score",
            n_each=1,
            anchor_tolerance=1e-3,
        )
    )

    assert 100 not in selected.gps_start.tolist()
    assert 101 in selected.gps_start.tolist()
    assert attempted["H1"]["ROBUST"] == 2
    assert counts["H1"]["ROBUST"] == 1
    assert len(failures) == 1
    assert failures[0]["error_type"] == "AnchorMismatch"
