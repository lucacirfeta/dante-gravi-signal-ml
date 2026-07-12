"""Unit tests for the norm-leakage experiment components and the
Fase-2 prerequisite fixes (B-4 guard-time, M-4 full window, M-5 taper)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# B-4 — guard-time sampling
# ---------------------------------------------------------------------------

def test_sample_guarded_times_respects_separation():
    from src.pipeline_v3_multiscale.sampling import sample_guarded_times

    rng = np.random.default_rng(0)
    times = sample_guarded_times(rng, 0, 100_000, n=200, guard=96.0)
    assert len(times) == 200
    assert np.min(np.diff(times)) >= 96.0


def test_respects_guard_edge_cases():
    from src.pipeline_v3_multiscale.sampling import respects_guard

    assert respects_guard(100.0, [])
    assert respects_guard(100.0, [300.0], guard=96.0)
    assert not respects_guard(100.0, [150.0], guard=96.0)
    assert respects_guard(100.0, [196.0], guard=96.0)  # exactly at guard: ok


def test_fpr_o3a_enforces_guard_time():
    """B-4 regression: the O3a FPR script must reject centers closer than
    the guard-time to already-accepted ones."""
    src = (REPO_ROOT / "src/pipeline_v3_multiscale/test_fpr_o3a.py").read_text()
    assert "respects_guard" in src


def test_fpr_o3a_uses_full_run_window():
    """M-4 regression: DQ segments must cover the full O3a run, not the
    first 23 days."""
    src = (REPO_ROOT / "src/pipeline_v3_multiscale/test_fpr_o3a.py").read_text()
    assert "1253977218" in src.split("def test_fpr_o3a")[1].split("np.random.seed")[0]


def test_o3a_builder_has_no_taper():
    """M-5 regression: the O3a dictionary builder must not taper per scale
    (the O4a builder does not — asymmetric preprocessing between
    dictionaries is a confounder)."""
    src = (REPO_ROOT /
           "src/pipeline_v3_multiscale/build_multiscale_dictionaries_o3a.py").read_text()
    assert ".taper(" not in src


def test_v3_builders_use_production_k():
    """B-5: dictionary size must match the verified production value."""
    import re
    for f in ("build_multiscale_dictionaries.py",
              "build_multiscale_dictionaries_o3a.py"):
        src = (REPO_ROOT / "src/pipeline_v3_multiscale" / f).read_text()
        assert not re.search(r"n_clusters\s*=\s*281|k_clusters\s*=\s*281", src), \
            f"{f} still uses legacy K=281"
        assert re.search(r"n_clusters\s*=\s*(k_clusters|275)|k_clusters\s*=\s*275", src), \
            f"{f} does not use production K=275"


# ---------------------------------------------------------------------------
# B2 normalization scheme
# ---------------------------------------------------------------------------

def test_fixed_normalizer_is_image_independent():
    """The defining property: the pixel<->energy mapping must NOT depend on
    the image's own max. Doubling one pixel must leave the others' mapped
    values untouched (min-max fails exactly this)."""
    from src.core.utils import normalize_spectrogram, normalize_spectrogram_fixed

    rng = np.random.default_rng(1)
    img = rng.uniform(0, 10, size=(32, 32))
    img2 = img.copy()
    img2[0, 0] = 40.0  # a loud "spectral line"

    fx1 = normalize_spectrogram_fixed(img, e_max=50.0)
    fx2 = normalize_spectrogram_fixed(img2, e_max=50.0)
    assert np.allclose(fx1[1:, :], fx2[1:, :]), \
        "fixed normalization leaked the image max into other pixels"

    mm1 = normalize_spectrogram(img)
    mm2 = normalize_spectrogram(img2)
    assert not np.allclose(mm1[1:, :], mm2[1:, :]), \
        "min-max should exhibit contrast coupling (sanity check of the test)"


def test_fixed_normalizer_clips_and_scales():
    from src.core.utils import normalize_spectrogram_fixed

    arr = np.array([[-1.0, 0.0], [5.0, 20.0]])
    out = normalize_spectrogram_fixed(arr, e_max=10.0)
    assert out.min() >= 0.0 and out.max() <= 1.0
    assert out[1, 1] == 1.0  # clipped
    assert out[1, 0] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        normalize_spectrogram_fixed(arr, e_max=0.0)


def test_frozen_emax_is_required_for_fixed_scheme(tmp_path, monkeypatch):
    """Scheme B2 must refuse to run without the frozen E_max file —
    silently re-deriving it per run would reintroduce the leakage."""
    from src.pipeline_v3_multiscale.norm_leakage import common

    monkeypatch.setattr(common, "OUT_ROOT", tmp_path / "nowhere")
    with pytest.raises(FileNotFoundError, match="pretest_max_ks"):
        common.get_normalizer("fixed")


def test_generate_qtransform_default_normalizer_unchanged():
    """Production behavior must be untouched: with no normalizer argument,
    generate_qtransform uses per-image min-max."""
    import inspect
    from src.core.preprocessor import generate_qtransform

    sig = inspect.signature(generate_qtransform)
    assert sig.parameters["normalizer"].default is None


# ---------------------------------------------------------------------------
# scoring rule parity
# ---------------------------------------------------------------------------

def test_topk_score_matches_production_rule():
    """topk_score must reproduce the PatchScorer rule: mean of the top-68
    values of (1 - max cosine sim)."""
    from src.pipeline_v3_multiscale.norm_leakage.common import topk_score

    rng = np.random.default_rng(2)
    tokens = rng.normal(size=(1369, 384)).astype(np.float32)
    tokens /= np.linalg.norm(tokens, axis=1, keepdims=True)
    cents = rng.normal(size=(275, 384)).astype(np.float32)
    cents /= np.linalg.norm(cents, axis=1, keepdims=True)

    got = topk_score(tokens, cents, k=68)
    anomaly = 1.0 - (tokens @ cents.T).max(axis=1)
    expected = float(np.sort(anomaly)[-68:].mean())
    assert got == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# V3 integration — multiscale characterization
# ---------------------------------------------------------------------------

def test_multiscale_thresholds_are_run_gated():
    """The characterization layer must refuse thresholds calibrated on a
    different run than the candidates (no silent cross-run application)."""
    import json
    from src.pipeline_v3_multiscale import multiscale_candidates as mc

    thr_path = REPO_ROOT / "results/micro_mdc/multiscale/L1_thresholds.json"
    if not thr_path.exists():
        pytest.skip("no calibrated thresholds in this checkout")
    thr = json.loads(thr_path.read_text())
    assert thr.get("calibration_run") == "O4a"
    # same run: passes
    mc.load_thresholds("L1", "O4a")
    # different run: refused
    with pytest.raises(RuntimeError, match="Cross-run"):
        mc.load_thresholds("L1", "O3a")


def test_multiscale_profile_handles_missing_taxonomy(tmp_path):
    """With no taxonomy the characterization must return None loudly, not
    crash nor fabricate output."""
    from src.pipeline_v3_multiscale.multiscale_candidates import profile_candidates

    assert profile_candidates(run="O3a", aggregated_dir=tmp_path) is None


def test_encode_batch_matches_single(monkeypatch):
    """encode_batch must be numerically consistent with encode_rgb (the
    production V2 scorer path); guards the in-memory batching refactor."""
    pytest.importorskip("torch")
    import torch
    if not torch.cuda.is_available():
        pytest.skip("GPU busy/absent — parity check is GPU-tied")
    from src.pipeline_v3_multiscale.norm_leakage.common import PatchEncoder
    import numpy as np

    enc = PatchEncoder()
    rng = np.random.default_rng(0)
    rgbs = [rng.integers(0, 255, size=(256, 256, 3), dtype=np.uint8)
            for _ in range(3)]
    batch = enc.encode_batch(rgbs)
    singles = np.stack([enc.encode_rgb(r) for r in rgbs])
    assert np.allclose(batch, singles, atol=1e-4)


# ---------------------------------------------------------------------------
# data_loader — indice locale dei blocchi (ottimizzazione, coerenza cache)
# ---------------------------------------------------------------------------

def test_local_block_index_finds_and_registers(tmp_path):
    """The per-process block index must (a) find pre-existing blocks without
    re-scanning per call and (b) see blocks saved AFTER the first scan via
    _register_local_block — otherwise cache_raw writes become invisible for
    the rest of the process."""
    from src.core import data_loader as dl

    d = tmp_path / "raw"
    d.mkdir()
    (d / "L1_100_200.hdf5").touch()
    dl._LOCAL_BLOCK_INDEX.clear()

    idx = dl._local_block_index(d, "L1")
    assert [(s, e) for s, e, _ in idx] == [(100.0, 200.0)]

    newf = d / "L1_300_400.hdf5"
    newf.touch()
    # not visible without registration (index is cached)...
    assert len(dl._local_block_index(d, "L1")) == 1
    # ...but registration keeps it coherent
    dl._register_local_block(newf, "L1")
    assert [(s, e) for s, e, _ in dl._local_block_index(d, "L1")] == [
        (100.0, 200.0), (300.0, 400.0)]
    dl._LOCAL_BLOCK_INDEX.clear()
