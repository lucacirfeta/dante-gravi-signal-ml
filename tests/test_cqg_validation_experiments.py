from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.pipeline_v2_production import dsd_absorption_threshold as ABSORPTION


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate_cross_run_domain_shift.py"
SPEC = importlib.util.spec_from_file_location("validate_cross_run_domain_shift", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
DOMAIN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DOMAIN
SPEC.loader.exec_module(DOMAIN)

ABSORPTION_MATRIX_PATH = ROOT / "scripts" / "run_cqg_absorption_matrix.py"
MATRIX_SPEC = importlib.util.spec_from_file_location(
    "run_cqg_absorption_matrix", ABSORPTION_MATRIX_PATH
)
assert MATRIX_SPEC is not None and MATRIX_SPEC.loader is not None
MATRIX = importlib.util.module_from_spec(MATRIX_SPEC)
sys.modules[MATRIX_SPEC.name] = MATRIX
MATRIX_SPEC.loader.exec_module(MATRIX)

KNOWN_PATH = ROOT / "scripts" / "validate_known_glitch_controls.py"
KNOWN_SPEC = importlib.util.spec_from_file_location(
    "validate_known_glitch_controls", KNOWN_PATH
)
assert KNOWN_SPEC is not None and KNOWN_SPEC.loader is not None
KNOWN = importlib.util.module_from_spec(KNOWN_SPEC)
sys.modules[KNOWN_SPEC.name] = KNOWN
KNOWN_SPEC.loader.exec_module(KNOWN)

ROBUSTNESS_PATH = ROOT / "scripts" / "run_cqg_robustness_replicates.py"
ROBUSTNESS_SPEC = importlib.util.spec_from_file_location(
    "run_cqg_robustness_replicates", ROBUSTNESS_PATH
)
assert ROBUSTNESS_SPEC is not None and ROBUSTNESS_SPEC.loader is not None
ROBUSTNESS = importlib.util.module_from_spec(ROBUSTNESS_SPEC)
sys.modules[ROBUSTNESS_SPEC.name] = ROBUSTNESS
ROBUSTNESS_SPEC.loader.exec_module(ROBUSTNESS)


def test_topk_scores_matches_manual_nearest_centroid() -> None:
    rng = np.random.default_rng(4)
    tokens = rng.normal(size=(3, 80, 6))
    tokens /= np.linalg.norm(tokens, axis=2, keepdims=True)
    centres = rng.normal(size=(7, 6))
    centres /= np.linalg.norm(centres, axis=1, keepdims=True)
    observed = DOMAIN.topk_scores(tokens, centres)
    expected = []
    for segment in tokens:
        nearest = (1.0 - segment @ centres.T).min(axis=1)
        expected.append(np.sort(nearest)[-DOMAIN.TOP_K :].mean())
    np.testing.assert_allclose(observed, expected)


def test_time_blocks_are_chronological_within_each_run() -> None:
    gps = np.array([4, 1, 3, 2, 104, 101, 103, 102], dtype=float)
    labels = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    blocks = DOMAIN.time_block_ids(gps, labels, n_blocks=2)
    for label in (0, 1):
        idx = np.flatnonzero(labels == label)
        ordered = idx[np.argsort(gps[idx])]
        assert blocks[ordered].tolist() == [0, 0, 1, 1]


def test_probe_detects_real_shift_and_not_shuffled_labels() -> None:
    rng = np.random.default_rng(7)
    n = 100
    x0 = rng.normal(0.0, 0.4, size=(n, 10))
    x1 = rng.normal(1.2, 0.4, size=(n, 10))
    features = np.r_[x0, x1]
    labels = np.r_[np.zeros(n, dtype=int), np.ones(n, dtype=int)]
    gps = np.r_[np.arange(n), np.arange(n) + 1000]
    real = DOMAIN.probe_auc(features, labels, gps, seed=11)
    shuffled = DOMAIN.probe_auc(features, labels, gps, seed=11, shuffle=True)
    assert real["auc_oof"] > 0.95
    assert 0.25 < shuffled["auc_oof"] < 0.75


def test_bootstrap_mean_difference_sign_and_interval() -> None:
    a = np.arange(100, dtype=float)
    b = a + 3.0
    result = DOMAIN.bootstrap_mean_difference(a, b, seed=5, n_boot=500)
    assert result["difference"] == 3.0
    assert result["ci95"][0] < 3.0 < result["ci95"][1]


def test_domain_cache_identity_changes_with_sample_contract() -> None:
    baseline = DOMAIN.cache_identity("o3b", "L1", 12, 42)
    assert baseline != DOMAIN.cache_identity("o4a", "L1", 12, 42)
    assert baseline != DOMAIN.cache_identity("o3b", "H1", 12, 42)
    assert baseline != DOMAIN.cache_identity("o3b", "L1", 13, 42)
    assert baseline != DOMAIN.cache_identity("o3b", "L1", 12, 43)
    assert baseline["qrange"] == [4, 64]
    assert baseline["source_sha256"]


def test_domain_cache_identity_pins_model_contract() -> None:
    identity = DOMAIN.cache_identity("o3b", "L1", 12, 42)
    assert identity["schema_version"] == DOMAIN.CACHE_SCHEMA_VERSION == 3
    assert identity["encoder"]["revision"] == (
        "7b187bd4df8efce2cbcbbb67bd01532c19bf4c9c"
    )
    assert identity["encoder"]["source_python_tree_sha256"] == (
        "ca377bf21900d316a2c17dbff04b0e01d44770fe2706becb94a79ac3b60b74ef"
    )
    assert identity["encoder"]["weights_sha256"] == (
        "f433177089a681826f849f194ece3bb48f4d63fb38d32fc837e3dc7a4e5641fb"
    )
    assert "src/core/model_loader.py" in identity["source_sha256"]


def test_exact_legacy_domain_cache_is_compatible_but_mutation_is_not() -> None:
    identity = DOMAIN.legacy_v2_cache_identity("o3b", "L1", 12, 42)
    assert DOMAIN.legacy_v2_runtime_equivalence_is_valid()
    assert DOMAIN.cache_identity_is_compatible(identity, "o3b", "L1", 12, 42)

    mutated = json.loads(json.dumps(identity))
    mutated["source_sha256"]["src/core/preprocessor.py"] = "0" * 64
    assert not DOMAIN.cache_identity_is_compatible(
        mutated, "o3b", "L1", 12, 42
    )


def test_compatible_cache_record_reuses_only_exact_legacy_cache(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(DOMAIN, "OUT", tmp_path)
    identity = DOMAIN.legacy_v2_cache_identity("o3b", "L1", 2, 7)
    cache = DOMAIN._cache_path("o3b", "L1", 2, 7, 2)
    np.savez_compressed(
        cache,
        gps=np.array([1.0, 2.0]),
        tokens=np.zeros((2, 1369, 384), dtype=np.float32),
        identity_json=json.dumps(identity, sort_keys=True),
    )
    record = DOMAIN.compatible_cache_record("o3b", "L1", 2, 7)
    assert record is not None
    assert record[0] == cache
    assert record[1] == identity

    identity["seed"] = 8
    np.savez_compressed(
        cache,
        gps=np.array([1.0, 2.0]),
        tokens=np.zeros((2, 1369, 384), dtype=np.float32),
        identity_json=json.dumps(identity, sort_keys=True),
    )
    assert DOMAIN.compatible_cache_record("o3b", "L1", 2, 7) is None


def test_exact_legacy_known_glitch_cache_is_compatible() -> None:
    kwargs = {
        "detector": "L1",
        "pool_digest": "a" * 64,
        "pool_n": 150,
        "n_per_class": 30,
    }
    identity = KNOWN.legacy_v2_known_cache_identity(**kwargs)
    assert KNOWN.known_cache_identity_is_compatible(identity, **kwargs)

    mutated = json.loads(json.dumps(identity))
    mutated["quality_gate"] = "different"
    assert not KNOWN.known_cache_identity_is_compatible(mutated, **kwargs)


def test_current_known_glitch_cache_identity_pins_model() -> None:
    identity = KNOWN.known_cache_identity(
        detector="H1", pool_digest="b" * 64, pool_n=150, n_per_class=30
    )
    assert identity["schema_version"] == 3
    assert identity["encoder"]["revision"] == (
        "7b187bd4df8efce2cbcbbb67bd01532c19bf4c9c"
    )
    assert identity["encoder"]["weights_sha256"] == (
        "f433177089a681826f849f194ece3bb48f4d63fb38d32fc837e3dc7a4e5641fb"
    )


def _absorption_identity(**overrides):
    values = {
        "run_name": "O4a",
        "detector": "L1",
        "morphology": "Blip",
        "amplitude": 12.0,
        "duration": 1.0,
        "n_background": 300,
        "n_holdout_bg": 150,
        "n_holdout_inj": 60,
        "prevalences": (0.0, 0.05, 0.4),
        "seed": 42,
        "qrange": (4, 64),
    }
    values.update(overrides)
    return ABSORPTION._experiment_identity(**values)


def test_absorption_cache_identity_changes_for_every_sampling_input() -> None:
    baseline = _absorption_identity()
    baseline_stem = ABSORPTION._artifact_stem(baseline)
    variants = [
        _absorption_identity(run_name="O3b"),
        _absorption_identity(detector="H1"),
        _absorption_identity(duration=1.5),
        _absorption_identity(n_holdout_bg=120),
        _absorption_identity(prevalences=(0.0, 0.2)),
        _absorption_identity(seed=43),
        _absorption_identity(qrange=(4, 32)),
    ]
    assert len({ABSORPTION._artifact_stem(value) for value in variants}) == len(variants)
    assert all(ABSORPTION._artifact_stem(value) != baseline_stem for value in variants)


def test_absorption_background_cache_is_shared_only_for_same_sampling_split() -> None:
    blip = _absorption_identity(morphology="Blip", duration=1.0)
    scattered = _absorption_identity(
        morphology="ScatteredLight", duration=1.5
    )
    different_seed = _absorption_identity(seed=43)
    assert (
        ABSORPTION._background_cache_identity(blip)
        == ABSORPTION._background_cache_identity(scattered)
    )
    assert (
        ABSORPTION._background_cache_identity(blip)
        != ABSORPTION._background_cache_identity(different_seed)
    )
    assert (
        ABSORPTION._whitened_segment_cache_identity(blip, 100)
        == ABSORPTION._whitened_segment_cache_identity(scattered, 100)
    )
    assert (
        ABSORPTION._whitened_segment_cache_identity(blip, 100)
        != ABSORPTION._whitened_segment_cache_identity(blip, 101)
    )


def test_seeded_glitch_is_reproducible_and_restores_global_rng() -> None:
    class FakeGenerator:
        @staticmethod
        def generate(*_args, **_kwargs):
            return np.random.standard_normal(8)

    np.random.seed(99)
    state = np.random.get_state()
    first = ABSORPTION._seeded_glitch(
        FakeGenerator(), "Blip", 12.0, 1.0, np.random.default_rng(17)
    )
    after = np.random.standard_normal(5)
    np.random.set_state(state)
    expected_after = np.random.standard_normal(5)
    second = ABSORPTION._seeded_glitch(
        FakeGenerator(), "Blip", 12.0, 1.0, np.random.default_rng(17)
    )
    np.testing.assert_allclose(first, second)
    np.testing.assert_allclose(after, expected_after)


def test_partial_absorption_encoding_is_rejected() -> None:
    good = np.zeros((4, 2, 3), dtype=np.float32)
    with np.testing.assert_raises_regex(RuntimeError, "partial absorption encoding"):
        ABSORPTION._validate_encoded_counts(
            good[:3],
            np.zeros((3, 2, 3), dtype=np.float32),
            good,
            good,
            n_background=4,
            n_holdout_bg=4,
            n_holdout_inj=4,
            max_prevalence=0.5,
        )
    tokens = np.zeros((1, 1369, 384), dtype=np.float32)
    assert ABSORPTION._valid_token_array(tokens, 1)
    tokens[0, 0, 0] = np.nan
    assert not ABSORPTION._valid_token_array(tokens, 1)


def _matrix_cell(z_values=(5.0, 2.0), flagged=(0.8, 0.4), seed=42):
    gps_groups = {
        "background": [1.0, 2.0],
        "holdout_background": [3.0, 4.0],
        "holdout_injected_source": [5.0, 6.0],
        "index_injected_source": [7.0, 8.0],
    }
    rows = []
    for prevalence, z_value, fraction in zip((0.0, 0.1), z_values, flagged):
        background = np.linspace(0.0, 1.0, 10)
        bg_mean = background.mean()
        bg_std = background.std(ddof=1)
        count = int(round(fraction * 10))
        target_mean = bg_mean + z_value * bg_std
        high = target_mean + 1.0
        low = (10 * target_mean - count * high) / (10 - count)
        injected = np.r_[np.full(count, high), np.full(10 - count, low)]
        control_injected = np.full(10, bg_mean + 6.0 * bg_std)
        observed_z = (injected.mean() - bg_mean) / bg_std
        rows.append(
            {
                "prevalence": prevalence,
                "score_injected_mean": float(injected.mean()),
                "score_background_mean": float(bg_mean),
                "score_background_std": float(bg_std),
                "z_injected_vs_background": float(observed_z),
                "z_injected_vs_background_ci95": [
                    observed_z - 0.5,
                    observed_z + 0.5,
                ],
                "z_control_same_size_all_background": 6.0,
                "flagged_fraction": count / 10,
                "flagged_count": count,
                "flagged_total": 10,
                "flagged_fraction_wilson95": [0.1, 0.9],
                "raw_scores": {
                    "injected_mixed_index": injected.tolist(),
                    "background_mixed_index": background.tolist(),
                    "injected_same_size_control": control_injected.tolist(),
                    "background_same_size_control": background.tolist(),
                },
            }
        )
    return {
        "morphology": "Blip",
        "qrange": [4, 64],
        "n_holdout_bg": 10,
        "n_holdout_inj": 10,
        "seed": seed,
        "gps_groups": gps_groups,
        "rows": rows,
    }


def test_absorption_matrix_rejects_query_index_gps_leakage() -> None:
    cell = _matrix_cell()
    MATRIX.validate_cell(cell)
    cell["gps_groups"]["holdout_background"][0] = 1.0
    with np.testing.assert_raises_regex(ValueError, "GPS leakage"):
        MATRIX.validate_cell(cell)


def test_absorption_crossing_rule_and_seed_summary_are_predeclared() -> None:
    first = _matrix_cell(seed=42)
    second = _matrix_cell(z_values=(4.5, 2.5), flagged=(0.7, 0.5), seed=43)
    assert MATRIX.cell_crossing(first) == 0.1
    summary = MATRIX.summarize_cells([first, second])["Blip"]
    assert summary["n_seeds"] == 2
    assert summary["seed_crossings"] == [0.1, 0.1]
    assert np.isclose(summary["rows"][1]["z_median"], 2.25)


def test_known_glitch_manifest_is_deterministic_and_guarded() -> None:
    rows = []
    for label_index, label in enumerate(KNOWN.LABELS):
        for event_index in range(5):
            rows.append(
                {
                    "event_time": 1000.0 * (label_index + 1) + 200.0 * event_index,
                    "ifo": "L1",
                    "ml_label": label,
                    "ml_confidence": 0.99,
                    "snr": 12.0,
                    "gravityspy_id": f"{label}-{event_index}",
                }
            )
    catalog = pd.DataFrame(rows)
    excluded = np.array([1000.0])
    first = KNOWN.select_manifest(
        catalog,
        detector="L1",
        labels=KNOWN.LABELS,
        n_per_class=2,
        seed=7,
        excluded_gps=excluded,
    )
    second = KNOWN.select_manifest(
        catalog,
        detector="L1",
        labels=KNOWN.LABELS,
        n_per_class=2,
        seed=7,
        excluded_gps=excluded,
    )
    assert first == second
    assert len(first) == 6
    assert all(abs(event["event_time"] - 1000.0) >= KNOWN.GUARD_S for event in first)


def test_known_glitch_auc_reports_effect_and_uncertainty() -> None:
    result = KNOWN.stratified_auc(
        np.arange(10.0, 20.0),
        np.arange(0.0, 10.0),
        seed=8,
        n_boot=200,
    )
    assert result["auc"] == 1.0
    assert result["auc_bootstrap_ci95"] == [1.0, 1.0]
    assert result["n_positive"] == result["n_negative"] == 10


def test_known_glitch_query_fetch_retries_transient_failures(monkeypatch) -> None:
    calls = []

    def fetcher(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) < 3:
            raise OSError("temporary GWOSC error")
        return "strain"

    monkeypatch.setattr(KNOWN.time, "sleep", lambda _: None)
    result = KNOWN.fetch_query_strain(fetcher, "L1", 100.0, 140.0)

    assert result == "strain"
    assert len(calls) == 3
    assert all(call[1]["cache_raw"] is True for call in calls)
    assert all(call[1]["edge_tolerance"] == 4.0 for call in calls)


def test_p9_reclassification_reuses_native_scores_only(
    tmp_path, monkeypatch
) -> None:
    import json

    from src.core.index_contract import sha256_file
    from src.pipeline_v2_production import astrophysical_injection as p9

    trial_path = tmp_path / "trials.csv"
    pd.DataFrame(
        {
            "system": ["BBH", "BBH"],
            "distance_mpc": [100.0, 100.0],
            "score_H1_native": [0.25, 0.15],
            "score_L1_native": [0.30, 0.10],
            "flag_H1": [True, False],
            "flag_L1": [False, True],
            "coincidence_recovered": [True, False],
            "coincidence_localized_H1": [True, False],
            "coincidence_localized_L1": [False, False],
            "coincidence_oracle_recovered": [True, False],
        }
    ).to_csv(trial_path, index=False)
    threshold_path = tmp_path / "thresholds.json"
    threshold_path.write_text(
        json.dumps(
            {
                "representation": {"variant": "rep"},
                "thresholds": {
                    "H1": {"ci_lower": 0.16, "ci_upper": 0.20},
                    "L1": {"ci_lower": 0.12, "ci_upper": 0.22},
                },
            }
        ),
        encoding="utf-8",
    )
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(
        json.dumps(
            {
                "run": "O4a",
                "taxonomy_representation": "rep",
                "trial_level_path": str(trial_path),
                "trial_level_sha256": sha256_file(trial_path),
                "n_trial_rows": 2,
                "dsd_threshold_path": str(threshold_path),
                "thresholds": {
                    "dsd_H1": 9.0,
                    "dsd_H1_lower": 8.0,
                    "dsd_L1": 9.0,
                    "dsd_L1_lower": 8.0,
                },
                "rows": [{"system": "BBH", "distance_mpc": 100.0, "n": 2}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(p9, "AGG", tmp_path)

    result = p9.reclassify_existing_artifact(
        artifact_path, threshold_path
    )
    trials = pd.read_csv(trial_path)

    assert trials["dsd_class_H1"].tolist() == ["ROBUST", "BACKGROUND"]
    assert trials["dsd_class_L1"].tolist() == ["ROBUST", "BACKGROUND"]
    assert result["rows"][0]["dsd_survive_H1"] == 0.5
    assert result["dsd_reclassification"]["measurements_recomputed"] is False
    assert result["trial_level_sha256"] == sha256_file(trial_path)


def test_pem_taxonomy_rejoin_preserves_fixed_measured_keys(
    tmp_path, monkeypatch
) -> None:
    import json
    from types import SimpleNamespace

    from src.pipeline_v2_production import pem_null_calibration as pem

    pem_dir = tmp_path / "pem" / "rep"
    pem_dir.mkdir(parents=True)
    keys = [("H1" if i < 70 else "L1", 1000 + i) for i in range(141)]
    targets = pd.DataFrame(
        {
            "detector": [key[0] for key in keys],
            "gps_start": [key[1] for key in keys],
            "family": ["old"] * 141,
            "dsd_class": ["BACKGROUND"] * 141,
            "dsd_score": [0.1] * 141,
        }
    )
    targets.to_csv(pem_dir / "selected_targets.csv", index=False)
    report = targets.copy()
    report["aux_channel"] = "AUX"
    report["taxonomy_representation"] = "rep"
    report.to_csv(pem_dir / "coherence_report.csv", index=False)
    taxonomy = targets[["detector", "gps_start"]].copy()
    taxonomy["dsd_class"] = ["ROBUST"] + ["BACKGROUND"] * 140
    taxonomy["dsd_score"] = [0.3] + [0.1] * 140
    taxonomy["global_family_id"] = ["new"] * 141
    taxonomy_path = tmp_path / "taxonomy.csv"
    taxonomy.to_csv(taxonomy_path, index=False)
    audit_path = tmp_path / "audit.json"
    audit_path.write_text("{}", encoding="utf-8")
    (pem_dir / "selection_manifest.json").write_text(
        json.dumps(
            {
                "taxonomy_path": "old.csv",
                "taxonomy_audit_path": "old.json",
                "taxonomy_representation": "rep",
            }
        ),
        encoding="utf-8",
    )
    contract = SimpleNamespace(
        path=taxonomy_path,
        audit_path=audit_path,
        representation="rep",
    )
    monkeypatch.setattr(
        pem,
        "load_taxonomy_view",
        lambda aggregated_dir, run: (taxonomy, contract),
    )

    result = pem.rejoin_existing_pem_taxonomy(
        "O4a", pem_dir=pem_dir, aggregated_dir=tmp_path
    )
    updated = pd.read_csv(pem_dir / "selected_targets.csv")

    assert len(updated) == 141
    assert list(zip(updated.detector, updated.gps_start)) == keys
    assert updated.iloc[0].dsd_class == "ROBUST"
    assert result["n_exact_key_matches"] == 141
    assert result["n_class_transitions"] == 1
    assert result["measurements_recomputed"] is False


def test_unconditioned_sample_does_not_use_score_or_class() -> None:
    frame = pd.DataFrame(
        {
            "detector": ["H1"] * 10 + ["L1"] * 10,
            "gps_start": np.r_[np.arange(10), np.arange(100, 110)],
            "dsd_class": ["ROBUST", "BACKGROUND"] * 10,
            "dsd_score": np.linspace(0.0, 1.0, 20),
        }
    )
    first = ROBUSTNESS.sample_unconditioned(
        frame, n_per_detector=4, seed=5, excluded_keys={"H1:0"}
    )
    second = ROBUSTNESS.sample_unconditioned(
        frame, n_per_detector=4, seed=5, excluded_keys={"H1:0"}
    )
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 8
    assert not (
        (first["detector"] == "H1") & (first["gps_start"] == 0)
    ).any()


def test_robustness_model_identity_separates_draw_seed_kmeans_seed_and_k() -> None:
    common = {
        "background_sha256": "a",
        "population_hashes": {"near": "b"},
        "n_background": 1300,
    }
    baseline = ROBUSTNESS.model_identity(
        **common, k=1216, km_seed=42, draw_seed=None
    )
    assert baseline != ROBUSTNESS.model_identity(
        **common, k=1024, km_seed=42, draw_seed=None
    )
    assert baseline != ROBUSTNESS.model_identity(
        **common, k=1216, km_seed=43, draw_seed=None
    )
    assert baseline != ROBUSTNESS.model_identity(
        **common, k=1216, km_seed=42, draw_seed=101
    )


def test_robustness_summary_reports_rank_and_candidate_uncertainty() -> None:
    base = np.arange(30, dtype=float)
    matrix = np.stack([base, base + 0.1, base + np.sin(base) * 0.01])
    result = ROBUSTNESS.summarize_score_matrix(matrix, seed=3, n_boot=100)
    assert result["pairwise_spearman_mean"] > 0.99
    assert result["n_models"] == 3
    assert result["n_candidates"] == 30
    assert len(result["bootstrap_ci95"]["pairwise_spearman_mean"]) == 2
