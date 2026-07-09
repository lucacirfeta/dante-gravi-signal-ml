"""Regression tests for the experimentally-validated hard constraints.

Each test guards one bug that was found (or fixed) during the V2/V3 audit.
They are designed to FAIL if the bug is ever reintroduced. Do not weaken
a test to make it pass — fix the production code instead.

Constraint numbering follows the audit report (B-* = blocking findings).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"


def _read(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


# =====================================================================
# Vincolo 1 — whitening con padding: whiten() diretto deve restare vietato
# =====================================================================

def test_direct_whiten_is_forbidden():
    """whiten() on an exactly-cropped segment causes FIR tapering artifacts.
    The public whiten() must raise and point to whiten_context()."""
    from gwpy.timeseries import TimeSeries
    from src.core.preprocessor import whiten

    ts = TimeSeries(np.random.default_rng(0).normal(size=4096 * 4),
                    sample_rate=4096, t0=0)
    with pytest.raises(RuntimeError, match="whiten_context"):
        whiten(ts)


def test_whiten_context_pads_before_crop():
    """whiten_context must whiten a padded block (pad=4.0s default) and
    extract_clean_subwindow must crop AFTER whitening, returning exactly
    the requested window."""
    from gwpy.timeseries import TimeSeries
    from src.core.preprocessor import whiten_context, extract_clean_subwindow

    rng = np.random.default_rng(1)
    ts_full = TimeSeries(rng.normal(size=4096 * 48), sample_rate=4096, t0=1000)

    ts_w, pad_info = whiten_context(ts_full, 1008, 1040, pad=4.0)
    # The whitened context must INCLUDE the pad on both sides
    assert float(ts_w.t0.value) <= 1004.0 + 1e-6
    assert float(ts_w.t0.value + ts_w.duration.value) >= 1044.0 - 1e-6
    assert pad_info["effective_left"] == pytest.approx(4.0)
    assert pad_info["effective_right"] == pytest.approx(4.0)

    ts_clean = extract_clean_subwindow(ts_w, 1008, 1040)
    assert float(ts_clean.t0.value) == pytest.approx(1008.0)
    assert float(ts_clean.duration.value) == pytest.approx(32.0)


# =====================================================================
# B-1 — nessun doppio bandpass: whiten_context applica già il bandpass,
# nessun modulo di produzione/V3 deve riapplicarlo sull'output.
# =====================================================================

# Modules exempt from the rule: legacy pipeline (frozen) and the
# preprocessor itself (bandpass lives inside whiten_context there).
_B1_EXEMPT = {"pipeline_v1_legacy"}

_DOUBLE_BP_RE = re.compile(
    r"(\w+)\s*(?:,\s*_)?\s*=\s*(?:whiten_context|extract_clean_subwindow)\([^\n]*\)"
    r"(?:.|\n)*?bandpass\(\s*\1\b"
)


def _double_bandpass_files() -> list[str]:
    offenders = []
    py_files = list(SRC.rglob("*.py")) + [REPO_ROOT / "main.py"]
    for f in py_files:
        if any(part in _B1_EXEMPT for part in f.parts):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        # Track variables assigned from extract_clean_subwindow (already
        # whitened AND bandpassed) that are then fed to bandpass() again.
        assigned = re.findall(r"(\w+)\s*=\s*extract_clean_subwindow\(", text)
        # whiten_context returns a bandpassed series too
        assigned += re.findall(r"(\w+)\s*,\s*\w+\s*=\s*whiten_context\(", text)
        for var in set(assigned):
            if re.search(rf"bandpass\(\s*{re.escape(var)}\b", text):
                offenders.append(str(f.relative_to(REPO_ROOT)))
                break
    return sorted(offenders)


def test_b1_no_double_bandpass():
    """The reference index (K=275, MD5-pinned) was built with a SINGLE
    bandpass (the one inside whiten_context). Re-applying bandpass() to
    the output of whiten_context/extract_clean_subwindow puts queries in
    a different filter domain than the reference — a run-independent
    leakage channel. No production/V3 module may do it."""
    offenders = _double_bandpass_files()
    assert offenders == [], (
        "Double bandpass detected (bandpass() applied to already-"
        f"bandpassed whiten_context output) in: {offenders}"
    )


# =====================================================================
# B-2 — il bootstrap V3 deve essere un VERO block-bootstrap
# =====================================================================

def _iid_bootstrap_p99_std(scores: np.ndarray, B: int = 300, seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    n = len(scores)
    p99s = [np.percentile(scores[rng.integers(0, n, size=n)], 99.0)
            for _ in range(B)]
    return float(np.std(p99s))


def test_b2_v3_bootstrap_preserves_block_structure():
    """ViT receptive fields overlap -> scores are autocorrelated. An i.i.d.
    bootstrap underestimates the variance of the p99 estimate. On strongly
    autocorrelated data, a genuine block bootstrap must report a p99
    standard deviation well above the i.i.d. one. If someone replaces the
    block resampling with per-sample resampling, this test fails."""
    from src.pipeline_v3_multiscale.micro_mdc_multiscale import block_bootstrap_p99

    rng = np.random.default_rng(42)
    # 50 blocks of 100 identical values: extreme but legal autocorrelation
    scores = np.repeat(rng.normal(size=50), 100)

    _, block_std = block_bootstrap_p99(scores, B=300, seed=42)
    iid_std = _iid_bootstrap_p99_std(scores, B=300, seed=42)

    assert block_std > 1.5 * iid_std, (
        f"block bootstrap std ({block_std:.4f}) is not distinguishable from "
        f"i.i.d. bootstrap std ({iid_std:.4f}): the implementation is not "
        "resampling contiguous blocks."
    )


# =====================================================================
# Vincolo 3 — shuffle-at-file-level + slice contigua (già fixato in V2):
# nessun random.sample sugli score temporali di produzione.
# =====================================================================

def test_no_random_sample_on_timeseries_scores():
    """aggregate_report must keep the file-level shuffle + contiguous slice.
    random.sample() on the concatenated score series would destroy the
    temporal autocorrelation required by the block bootstrap."""
    text = _read("src/pipeline_v2_production/aggregate_report.py")
    assert "random.sample(" not in text, (
        "random.sample() reintroduced in aggregate_report.py — this destroys "
        "temporal ordering needed by the block bootstrap."
    )
    # The contiguous-slice fix must remain
    assert "scores_list[:5000]" in text


# =====================================================================
# Vincolo 4 — soglia VQ fallback = 0.80
# =====================================================================

def test_vq_fallback_threshold_is_080():
    text = _read("src/pipeline_v2_production/production_report.py")
    assert re.search(r"max_sim\s*>=\s*0\.80\b", text), (
        "VQ fallback threshold must be 0.80 (calibrated on genuine Gravity "
        "Spy events at 0.82-0.88), not any other value."
    )


# =====================================================================
# K=275 — l'indice di riferimento in produzione non deve cambiare
# =====================================================================

def test_reference_index_is_k275_and_md5_pinned():
    """Empirically verified: the production VQ index has exactly 275
    centroids and its MD5 matches the constant pinned in PatchScorer."""
    idx = REPO_ROOT / "data/reference/patch_compressed_index_o3b.npz"
    if not idx.exists():
        pytest.skip("production reference index not present in this checkout")
    import hashlib
    data = np.load(idx, allow_pickle=True)
    assert data["embeddings"].shape == (275, 384)
    md5 = hashlib.md5(idx.read_bytes()).hexdigest()
    scorer_src = _read("src/core/patch_scorer.py")
    assert md5 in scorer_src, "PatchScorer pinned MD5 no longer matches the index"


# =====================================================================
# B-3 — semantica della coincidenza: osservabilità != assenza di anomalia
# =====================================================================

def test_b3_resolver_never_claims_no_anomaly(monkeypatch):
    """_resolve_coincidence_status only checks whether the partner detector
    was recording ({DET}_DATA). It must NEVER return ACTIVE_NO_ANOMALY —
    that verdict requires an actual morphological search, which only
    cross_detector_veto performs."""
    from src.pipeline_v2_production import aggregate_report as ar

    import gwosc.timeline
    monkeypatch.setattr(gwosc.timeline, "get_segments",
                        lambda flag, s, e: [(s, e)])
    status = ar._resolve_coincidence_status(1369000000.0, "H1")
    assert status != "ACTIVE_NO_ANOMALY", (
        "Partner merely being ON was reported as 'no anomaly found'. "
        "Observability must not be conflated with a negative search result."
    )


def test_b3_resolver_returns_unobservable_when_partner_off(monkeypatch):
    from src.pipeline_v2_production import aggregate_report as ar

    import gwosc.timeline
    monkeypatch.setattr(gwosc.timeline, "get_segments", lambda flag, s, e: [])
    assert ar._resolve_coincidence_status(1369000000.0, "H1") == "UNOBSERVABLE"


def test_b3_enum_contains_unobservable():
    """UNOBSERVABLE is produced by the resolver and must be a valid enum
    value — INACTIVE and UNOBSERVABLE are distinct states (constraint 6)."""
    from src.pipeline_v2_production.aggregate_report import _COINCIDENCE_ENUM
    assert "UNOBSERVABLE" in _COINCIDENCE_ENUM


# =====================================================================
# B-3-bis — lo stato COINCIDENT_TRANSIENT deve essere raggiungibile
# =====================================================================

def test_b3bis_coincident_transient_is_reachable():
    """production_report routes on status == 'COINCIDENT_TRANSIENT' and
    aggregate_report maps it, but no code ever ASSIGNED it: the entire
    'confirmed astrophysical' branch was dead. The morphological match in
    cross_detector_veto must assign exactly this status."""
    veto_src = _read("src/pipeline_v2_production/cross_detector_veto.py")
    assert '"COINCIDENT_TRANSIENT"' in veto_src, (
        "cross_detector_veto no longer assigns COINCIDENT_TRANSIENT — the "
        "astrophysical-confirmation branch of the state machine is dead code."
    )


def test_b3bis_veto_errors_do_not_become_confirmed_local():
    """I/O failures (missing HDF5, failed fetch/encode) must route the
    candidate to the UNVERIFIABLE table, never to 'Confirmed Local
    Glitches'. A network error is not evidence of a local glitch."""
    veto_src = _read("src/pipeline_v2_production/cross_detector_veto.py")
    # Every `except`/failure branch that used to do local_rows.append(row)
    # must now append to unverifiable_rows. We assert the specific bug
    # pattern is gone: a warning log followed by local_rows.append.
    bug_pattern = re.compile(
        r"logger\.warning\([^\n]*\)\s*\n\s*local_rows\.append\(row\)"
    )
    assert not bug_pattern.search(veto_src), (
        "cross_detector_veto still routes I/O failures into local_rows "
        "(Table 3a 'Confirmed Local Glitches')."
    )


# =====================================================================
# B-6 — build_multiscale_dictionaries_o3a deve poter salvare i risultati
# =====================================================================

def test_b6_o3a_builder_has_no_invalid_json_call():
    """json.json(...) does not exist: the O3a dictionary builder crashed
    with AttributeError after hours of GPU extraction, before saving."""
    text = _read("src/pipeline_v3_multiscale/build_multiscale_dictionaries_o3a.py")
    assert "json.json(" not in text, (
        "json.json() is not a function — this crashes the O3a builder "
        "before any dictionary is saved."
    )


# =====================================================================
# Vincolo 8 — canali PEM unsafe esclusi dalla produzione
# =====================================================================

def test_unsafe_pem_channels_not_in_production_list():
    """PEM-EX_VMON and PEM-EY_MAINSMON (FPR 23% on time-shifted background,
    Soni et al. 2025) must not appear in the AUX_CHANNELS production list.
    (pem_significance_test.py legitimately includes them: it is the script
    that MEASURES their FPR to justify the exclusion.)"""
    from src.pipeline_v2_production.pem_coherence_analysis import AUX_CHANNELS
    flat = [ch for chans in AUX_CHANNELS.values() for ch in chans]
    for banned in ("PEM-EX_VMON", "PEM-EY_MAINSMON"):
        assert not any(banned in ch for ch in flat), (
            f"Unsafe channel {banned} reintroduced in production AUX_CHANNELS"
        )
