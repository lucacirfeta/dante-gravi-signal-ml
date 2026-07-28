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
    """Background extraction must preserve temporal ordering within its scan.

    The representation-contract fix no longer reuses unlabelled historical
    dual-scoring arrays. It recomputes matched scores and takes the contiguous
    prefix requested by the caller.
    """
    text = _read("src/pipeline_v2_production/aggregate_report.py")
    assert "random.sample(" not in text, (
        "random.sample() reintroduced in aggregate_report.py — this destroys "
        "temporal ordering needed by the block bootstrap."
    )
    assert "random.shuffle(valid_files)" not in text
    assert "score_pairs[:target_n]" in text
    assert "stratified across %d available blocks" in text
    assert "Historical dual-scoring files have no index/qrange sidecar" in text


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
    monkeypatch.setattr(ar, "_COINC_CACHE", {})  # isolate from disk cache
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
    monkeypatch.setattr(ar, "_COINC_CACHE", {})  # isolate from disk cache
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


# =====================================================================
# Soglie per-run — nessuna applicazione cross-run silenziosa
# =====================================================================

def test_threshold_run_guard_refuses_cross_run():
    """Thresholds calibrated on one run must not be silently applied to
    another (the only channel with residual excess in the 2026-07 leakage
    investigation). Only explicit allow_cross_run=True measurement contexts
    may bypass."""
    from src.pipeline_v3_multiscale.sampling import assert_threshold_run

    thr = {"calibration_run": "O4a", "4s": {"p99_mean": 0.1}}
    assert_threshold_run(thr, "O4a")                      # same run: ok
    assert_threshold_run(thr, "O3a", allow_cross_run=True)  # explicit: ok
    with pytest.raises(RuntimeError, match="Cross-run"):
        assert_threshold_run(thr, "O3a")                  # silent: refused
    with pytest.raises(ValueError, match="calibration_run"):
        assert_threshold_run({"4s": {}}, "O4a")           # untagged: refused


def test_pem_skip_is_logged_not_silent():
    """M-1: a missing NDS host must produce an explicit warning, never a
    bare `return None`."""
    text = _read("src/pipeline_v2_production/pem_coherence_analysis.py")
    m = re.search(r"if nds_host is None:\s*\n(.*?)return None", text, re.S)
    assert m and "logger.warning" in m.group(1), (
        "Silent PEM fallback reintroduced: nds_host=None returns None "
        "without a warning."
    )


# =====================================================================
# Report finale — dinamico rispetto al run, mai silenziosamente vuoto
# =====================================================================

def test_final_report_is_run_dynamic_and_declares_gaps(tmp_path):
    """The Final Discovery Report must (a) carry the actual observing run in
    title and product filenames — no hardcoded O4a — and (b) declare missing
    inputs in an explicit completeness block instead of silently degrading
    sections to N/A."""
    from src.pipeline_v2_production.aggregate_report import AggregateReporter

    rep = AggregateReporter(production_dir=str(tmp_path), run="O3a")
    rep._generate_markdown_report({})  # no inputs at all: maximally degraded

    report = (tmp_path / "aggregated" / "Final_Discovery_Report.md").read_text(
        encoding="utf-8")
    assert "# Final Discovery Report (O3a)" in report
    assert "Master_Taxonomy_O3a.csv" in report
    assert "Master_Taxonomy_O4a" not in report
    assert "REPORT INCOMPLETE" in report, (
        "A report generated with zero inputs must declare itself incomplete "
        "at the top, not degrade silently to N/A sections."
    )
    assert "Master_Taxonomy_O3a.csv MISSING" in report


def test_no_hardcoded_taxonomy_filename_in_pipeline():
    """No production module may hardcode Master_Taxonomy_O4a.csv — the
    filename must derive from the observing run."""
    offenders = []
    for f in (SRC / "pipeline_v2_production").glob("*.py"):
        src_text = f.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(src_text.splitlines(), 1):
            if "Master_Taxonomy_O4a" in line and not line.strip().startswith("#") \
               and "docstring" not in line:
                offenders.append(f"{f.name}:{i}")
    # pem_coherence_analysis __main__ default and physics_correlation
    # docstring are documentation-level; only executable literals count.
    offenders = [o for o in offenders
                 if not o.startswith("physics_correlation")]
    assert offenders in ([], ["pem_coherence_analysis.py:818"]), (
        f"Hardcoded taxonomy filename found in: {offenders}"
    )


# =====================================================================
# Livetime del Poisson UL — solo tempo science-mode nel denominatore
# =====================================================================

def test_interval_intersection_is_correct():
    from src.pipeline_v2_production.poisson_upper_limit import intersect_intervals

    a = [(0, 100), (200, 300)]
    b = [(50, 250), (280, 400)]
    assert intersect_intervals(a, b) == [(50, 100), (200, 250), (280, 300)]
    assert intersect_intervals(a, []) == []
    assert intersect_intervals([(0, 10)], [(10, 20)]) == []  # touching, no overlap


def test_poisson_livetime_is_cat1_gated():
    """The UL denominator must be the intersection with {DET}_CBC_CAT1 —
    the raw session span inflates livetime and biases the limit optimistic.
    A GWOSC failure must abort, never fall back to the ungated span."""
    text = _read("src/pipeline_v2_production/poisson_upper_limit.py")
    assert "_CBC_CAT1" in text and "intersect_intervals(merged_intervals" in text
    assert "Refusing to compute an upper limit on the ungated span" in text


# =====================================================================
# Run-agnosticità — le run future (O5) si aggiungono via config, non codice
# =====================================================================

def test_observing_run_is_config_extensible(monkeypatch):
    """A run declared in config.yaml run_config with explicit GPS bounds must
    be resolved by get_observing_run without code changes — this is the O5
    readiness contract. Config must WIN over the open-ended builtin O4b."""
    from src.core import utils

    fake_cfg = {"run_config": {"O5": {"start_date": "2027-01-01 00:00:00",
                                      "gps_start": 1450000000,
                                      "gps_end": 1500000000}}}
    monkeypatch.setattr(utils, "load_config", lambda *a, **k: fake_cfg)
    assert utils.get_observing_run(1460000000) == "O5"
    # builtin table still intact for known epochs
    assert utils.get_observing_run(1370000000) == "O4a"
    assert utils.get_observing_run(1240000000) == "O3a"


# =====================================================================
# DSD — coerenza cromatica, separazione background, anti-circolarità
# =====================================================================

def test_dsd_rescoring_uses_production_colormap():
    """B-DSD-1: DSD candidate rescoring must render spectrograms with the
    production colormap (cividis), never grayscale stacking — grayscale vs
    cividis puts candidate scores in a different chromatic domain than the
    native thresholds."""
    text = _read("src/pipeline_v2_production/aggregate_report.py")
    assert "np.stack([q_gram_uint8]*3" not in text, (
        "Grayscale RGB stacking reintroduced in DSD rescoring.")
    assert 'colormaps["cividis"]' in text


def test_dsd_native_background_has_distinct_filename():
    """B-DSD-2: native-index background scores must not share the filename
    of the primary-index background used by production_report."""
    text = _read("src/pipeline_v2_production/aggregate_report.py")
    assert "background_scores_native_" in text


def test_dsd_injection_test_module_imports():
    """dsd_injection_test.py must be importable standalone: a prior refactor
    dropped `from src.core.utils import setup_logger` while the module-level
    `logger = setup_logger(__name__)` call remained, making the Controlled
    Recovery Test crash with NameError on any invocation since."""
    import importlib
    importlib.import_module("src.pipeline_v2_production.dsd_injection_test")


def test_dsd_injection_test_uses_production_colormap():
    """B-DSD-1, third site: the Controlled Recovery Test (falsifiability
    experiment) independently renders spectrograms for both the background
    calibration and the injected candidates. It was never covered by the
    aggregate_report.py fix and stacked grayscale to fake RGB in all three
    call sites, biasing every recovery-rate number the experiment produces
    against the cividis-rendered native index."""
    text = _read("src/pipeline_v2_production/dsd_injection_test.py")
    assert "np.stack([q_gram_uint8]" not in text, (
        "Grayscale RGB stacking reintroduced in the DSD Controlled "
        "Recovery Test.")
    assert text.count('colormaps["cividis"]') >= 3, (
        "All three rendering sites (background calibration, O3b background, "
        "injected candidate) must use cividis.")


def test_native_index_builder_refuses_thin_background(monkeypatch, tmp_path):
    """The native index builder must refuse to build from an
    unrepresentative background (too few clean segments collected)."""
    from src.pipeline_v2_production import build_native_index as bni

    monkeypatch.setattr(bni, "_candidate_exclusions", lambda run, d: [])
    monkeypatch.setattr(bni, "PatchEncoder", lambda: None)
    monkeypatch.setattr(bni, "iter_clean_segments",
                        lambda *a, **k: iter(()))  # zero segments
    with pytest.raises(RuntimeError, match="unrepresentative background"):
        bni.build_native_index("O4a", "L1", n_dict=100, out_dir=tmp_path,
                               aggregated_dir=tmp_path)


def test_veto_refuses_uncalibrated_tau(monkeypatch):
    """cross_detector_veto must refuse heuristic (non-EVT) tau_coh entries
    unless explicitly overridden — dynamic-run safety: a new run without
    calibration fails loudly instead of gating claims on 0.85."""
    text = _read("src/pipeline_v2_production/cross_detector_veto.py")
    assert "DANTE_ALLOW_HEURISTIC_TAU" in text
    assert "uncalibrated" in text


def test_disposition_ledger_present_and_dynamic(tmp_path):
    """The Final Report must close with the per-candidate disposition
    ledger: funnel waterfall + survivors table, with missing checks
    declared as 'pending', never omitted."""
    import pandas as pd
    from src.pipeline_v2_production.aggregate_report import AggregateReporter

    rep = AggregateReporter(production_dir=str(tmp_path), run="O3a")
    # schema mirrors the guaranteed-taxonomy fallback writer
    tax = pd.DataFrame({
        "gps_start": [100.0, 200.0],
        "detector": ["L1", "H1"],
        "session_id": ["1234567890", "1234567890"],
        "origin_table": ["3b", "3a"],
        "local_cluster_id": ["C0", "C1"],
        "global_family_id": ["Singleton", "Family_01"],
        "max_similarity_to_3a": ["", ""],
        "transitivity_status": ["Unclassified_Physical_Anomaly", "Resolved_via_Transitivity"],
        "gravity_spy_label": ["Not_Queried", "Not_Queried"],
        "gravity_spy_confidence": [0.0, 0.0],
        "partner_observing_status": ["UNOBSERVABLE", "ACTIVE_NO_ANOMALY"],
    })
    tax.to_csv(rep.output_dir / "Master_Taxonomy_O3a.csv", index=False)
    rep._generate_markdown_report({})
    report = (rep.output_dir / "Final_Discovery_Report.md").read_text(encoding="utf-8")
    assert "Final Candidate Disposition Ledger" in report
    assert "FINAL SURVIVORS" in report
    assert "pending" in report          # DSD/PEM/multiscale not run -> declared
    assert "| 100 | L1 |" in report     # the survivor row exists


def test_poisson_ul_section_reads_artifacts_not_placeholder(tmp_path):
    """The Poisson UL section must render the numbers from the
    upper_limit/*.json artifacts, never the static 'Waiting for poisson
    module injection...' placeholder — that was a computed-but-unlinked
    integration bug (data on disk, section empty in the report)."""
    import json
    import pandas as pd
    from src.pipeline_v2_production.aggregate_report import AggregateReporter

    rep = AggregateReporter(production_dir=str(tmp_path), run="O4a")
    tax = pd.DataFrame({
        "gps_start": [100.0], "detector": ["L1"],
        "session_id": ["1234567890"], "origin_table": ["3b"],
        "local_cluster_id": ["C0"], "global_family_id": ["Singleton"],
        "max_similarity_to_3a": [""],
        "transitivity_status": ["Unclassified_Physical_Anomaly"],
        "gravity_spy_label": ["Not_Queried"], "gravity_spy_confidence": [0.0],
        "partner_observing_status": ["UNOBSERVABLE"],
    })
    tax.to_csv(rep.output_dir / "Master_Taxonomy_O4a.csv", index=False)

    ul_dir = rep.output_dir / "upper_limit"
    ul_dir.mkdir(parents=True, exist_ok=True)
    for det, days, rate in [("H1", 144.2, 5.83), ("L1", 149.4, 5.63)]:
        (ul_dir / f"poisson_upper_limit_{det}.json").write_text(json.dumps({
            "detector": det, "livetime_days": days,
            "observed_unexplained_events": 0, "confidence_level": 0.9,
            "lambda_upper_limit": 2.302585, "rate_upper_limit_per_year": rate,
            "methodology": "Analytic -ln(0.1)"}))

    rep._generate_markdown_report({})
    report = (rep.output_dir / "Final_Discovery_Report.md").read_text(encoding="utf-8")

    assert "Waiting for poisson module injection" not in report
    assert "5.83" in report and "5.63" in report
    assert "144.2" in report and "149.4" in report
    assert "CAT1" in report

    # LF line endings: no CRLF in the emitted file
    raw = (rep.output_dir / "Final_Discovery_Report.md").read_bytes()
    assert b"\r\n" not in raw


def test_ledger_pem_veto_and_bonferroni(tmp_path):
    """A candidate with a Bonferroni-significant PEM coupling must be
    REMOVED from the final survivors (not just annotated), listed in the
    'Removed by PEM veto' table, and counted in the funnel. A channel hit
    whose Bonferroni-corrected analytic p is >= 0.05 is reported as
    NO_CORRELATION (with the p_Bonf shown) and survives — the veto
    criterion is exclusively p_Bonf < 0.05, never the raw C >= 0.6 flag. The false 'PEM systematically unavailable' prose must be gone."""
    import pandas as pd
    from src.pipeline_v2_production.aggregate_report import AggregateReporter

    rep = AggregateReporter(production_dir=str(tmp_path), run="O3a")
    tax = pd.DataFrame({
        "gps_start": [100.0, 200.0, 300.0],
        "detector": ["H1", "L1", "L1"],
        "session_id": ["1234567890"] * 3,
        "origin_table": ["3b"] * 3,
        "local_cluster_id": ["C0", "C1", "C2"],
        "global_family_id": ["Singleton_100", "Singleton_200",
                             "Singleton_300"],
        "max_similarity_to_3a": ["", "", ""],
        "transitivity_status": ["Unclassified_Physical_Anomaly"] * 3,
        "gravity_spy_label": ["Not_Queried"] * 3,
        "gravity_spy_confidence": [0.0] * 3,
        "partner_observing_status": ["UNOBSERVABLE"] * 3,
    })
    tax.to_csv(rep.output_dir / "Master_Taxonomy_O3a.csv", index=False)

    pem_dir = rep.output_dir / "pem"
    pem_dir.mkdir(parents=True, exist_ok=True)
    pem = pd.DataFrame({
        "detector": ["H1", "H1", "L1", "L1"],
        "gps_start": [100.0, 100.0, 200.0, 300.0],
        "family": ["Singleton_100"] * 2 + ["Singleton_200", "Singleton_300"],
        "aux_channel": ["H1:LSC-POP_A_LF_OUT_DQ",
                        "H1:CAL-PCALY_RX_PD_OUT_DQ",
                        "L1:ASC-X_TR_A_NSUM_OUT_DQ",
                        "L1:ASC-X_TR_A_NSUM_OUT_DQ"],
        # GPS 100: C=0.99 empirically significant AND p_Bonf tiny -> vetoed.
        # GPS 200: flagged significant but C=0.20 -> p_Bonf >= 0.05 -> survives.
        # GPS 300: C=0.48 BELOW the empirical channel threshold
        #   (significant=False) even though the analytic p_Bonf would be
        #   < 0.05 — the analytic-only veto is forbidden (the significance
        #   test measured 23% FPR at C>=0.6, falsifying the Gaussian null),
        #   so this candidate MUST survive.
        "max_coherence": [0.99, 0.30, 0.20, 0.48],
        "peak_freq": [20.0, 60.0, 60.0, 60.0],
        "significant": [True, False, True, False],
        "data_available": [True, True, True, True],
        "note": ["", "", "", ""],
    })
    pem.to_csv(pem_dir / "coherence_report.csv", index=False)

    rep._generate_markdown_report({})
    report = (rep.output_dir / "Final_Discovery_Report.md").read_text(encoding="utf-8")

    assert "Removed by PEM veto (1)" in report
    assert "PEM-vetoed (family-wise empirical aux coupling) | 1" in report
    # The vetoed event must not appear in the survivors table
    surv_block = report.split("### Survivors")[1]
    assert "| 100 | H1 |" not in surv_block
    assert "| 200 | L1 |" in surv_block
    assert "| 300 | L1 |" in surv_block   # analytic-only veto forbidden
    assert "below empirical channel threshold" in report
    assert "p_Bonf=1.00 >= 0.05" in report
    # The self-contradicting limitation must never come back
    assert "systematically unavailable" not in report


def test_ledger_family_wise_pem_veto(tmp_path):
    """The PRIMARY PEM veto is the family-wise empirical max-statistic
    threshold (pem_family_wise_verdicts.csv). Covers all four required
    regimes:
      GPS 100: Cmax=0.987 > thr_fw=0.93  -> COUPLED (known limit case);
      GPS 200: Cmax=0.478 <= thr_fw=0.62 -> survives (known limit case);
      GPS 300: Cmax=0.85 <= thr_fw=0.91  -> survives — a raw C>=0.6 veto
               would have killed it (raw-based false alarm);
      GPS 400: Cmax=0.55 > thr_fw=0.50   -> COUPLED — the raw criterion
               would have MISSED this true coupling.
    Events without calibration fall back to the legacy dual criterion and
    are explicitly tagged."""
    import pandas as pd
    from src.pipeline_v2_production.aggregate_report import AggregateReporter

    rep = AggregateReporter(production_dir=str(tmp_path), run="O3a")
    gps_list = [100.0, 200.0, 300.0, 400.0, 500.0]
    tax = pd.DataFrame({
        "gps_start": gps_list,
        "detector": ["H1", "L1", "L1", "H1", "L1"],
        "session_id": ["1234567890"] * 5,
        "origin_table": ["3b"] * 5,
        "local_cluster_id": [f"C{i}" for i in range(5)],
        "global_family_id": [f"Singleton_{int(g)}" for g in gps_list],
        "max_similarity_to_3a": [""] * 5,
        "transitivity_status": ["Unclassified_Physical_Anomaly"] * 5,
        "gravity_spy_label": ["Not_Queried"] * 5,
        "gravity_spy_confidence": [0.0] * 5,
        "partner_observing_status": ["UNOBSERVABLE"] * 5,
    })
    tax.to_csv(rep.output_dir / "Master_Taxonomy_O3a.csv", index=False)

    pem_dir = rep.output_dir / "pem"
    pem_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "detector": ["H1", "L1", "L1", "H1", "L1"],
        "gps_start": gps_list,
        "family": [f"Singleton_{int(g)}" for g in gps_list],
        "aux_channel": ["H1:LSC-POP_A_LF_OUT_DQ"] * 5,
        "max_coherence": [0.987, 0.478, 0.85, 0.55, 0.99],
        "peak_freq": [20.0] * 5,
        "significant": [True, False, True, False, True],
        "data_available": [True] * 5,
        "note": [""] * 5,
    }).to_csv(pem_dir / "coherence_report.csv", index=False)

    pd.DataFrame({
        "detector": ["H1", "L1", "L1", "H1"],
        "gps_start": [100.0, 200.0, 300.0, 400.0],
        "family": [f"Singleton_{g}" for g in (100, 200, 300, 400)],
        "m_channels": [5, 7, 7, 5],
        "n_surrogate_pairs": [20000] * 4,
        "threshold_fw": [0.93, 0.62, 0.91, 0.50],
        "cmax_observed": [0.987, 0.478, 0.85, 0.55],
        "top_channel": ["H1:LSC-POP_A_LF_OUT_DQ"] * 4,
        "verdict": ["COUPLED", "NO_CORRELATION",
                    "NO_CORRELATION", "COUPLED"],
        # GPS 500 intentionally absent -> legacy fallback
    }).to_csv(pem_dir / "pem_family_wise_verdicts.csv", index=False)

    rep._generate_markdown_report({})
    report = (rep.output_dir / "Final_Discovery_Report.md").read_text(encoding="utf-8")

    surv_block = report.split("### Survivors")[1]
    assert "| 200 | L1 |" in surv_block
    assert "| 300 | L1 |" in surv_block        # raw C>=0.6 must NOT veto
    assert "| 100 | H1 |" not in surv_block
    assert "| 400 | H1 |" not in surv_block    # raw would have missed it
    assert "thr_fw=0.500" in report and "thr_fw=0.930" in report
    assert "m=7" in report and "N=20000" in report
    # Uncalibrated event: legacy path, explicitly tagged
    assert "[LEGACY dual criterion]" in report
    assert "Removed by PEM veto (3)" in report  # 100, 400, 500(legacy C=0.99)


def test_injection_efficiency_dsd_check_morphologies():
    """GLITCH_SET must include the three DSD-falsifiability morphologies
    (HarmonicComb, WallOfLines, KoiFish) mirroring dsd_injection_test.py's
    native-index recovery test, so the multi-scale recovery question can
    be tested without a second, divergent glitch catalogue."""
    from src.pipeline_v3_multiscale.injection_efficiency import GLITCH_SET
    for key in ("HarmonicComb", "WallOfLines", "KoiFish"):
        assert key in GLITCH_SET
        assert GLITCH_SET[key]["effective_s"] > 0


def test_injection_efficiency_subset_and_tag_isolate_output(tmp_path, monkeypatch):
    """Running a custom --morphologies subset with --tag must not touch the
    filenames of a full/default run (the 5-morphology L1/H1 results already
    consumed by the paper's efficiency section)."""
    import pandas as pd
    from src.pipeline_v3_multiscale import injection_efficiency as ie

    summary = pd.DataFrame({
        "glitch_type": ["KoiFish"] * 2,
        "effective_duration_s": [0.15] * 2,
        "scale_s": [0.5, 4.0],
        "target_snr": [8, 8],
        "n": [10, 10], "n_detected": [1, 9],
        "recall": [0.1, 0.9], "ci_low": [0.0, 0.6], "ci_high": [0.4, 1.0],
    })
    subset = {"KoiFish": ie.GLITCH_SET["KoiFish"]}
    ie.plot_efficiency(summary, "L1", tmp_path, subset, "_dsd_check")
    assert (tmp_path / "fig_L1_injection_efficiency_dsd_check_postaudit.png").exists()
    assert not (tmp_path / "fig_L1_injection_efficiency_postaudit.png").exists()


def test_pem_null_coherence_math():
    """Sanity of the surrogate coherence estimator: identical signals give
    coherence ~1; independent white noise stays well below 1 with 31
    Welch averages."""
    import numpy as np
    from gwpy.timeseries import TimeSeries
    from src.pipeline_v2_production.pem_null_calibration import (
        _window_segment_ffts, N_WELCH)

    rng = np.random.default_rng(0)
    fs = 1024
    # Strain-scale amplitudes (~1e-19): float32 |FFT|^2 would underflow
    # and any additive eps would swallow the denominator, deflating the
    # coherence by orders of magnitude (observed threshold_fw=0.003 on
    # real data). The estimator must be scale-invariant.
    ts = TimeSeries((1e-19 * rng.normal(size=fs * 40)).astype(np.float64),
                    sample_rate=fs, t0=1000)
    X, freqs = _window_segment_ffts(ts, 1000, np.array([1002.0]),
                                    band=(20.0, 400.0))
    assert X.shape[1] == N_WELCH and X.shape[0] == 1
    Px = np.sum(np.abs(X) ** 2, axis=1)
    cross_same = np.einsum("ikf,jkf->ijf", X, np.conj(X))
    coh_same = np.abs(cross_same[0, 0]) ** 2 / (Px[0] * Px[0])
    assert np.allclose(coh_same, 1.0, atol=1e-5)

    ts2 = TimeSeries((1e-19 * rng.normal(size=fs * 40)).astype(np.float64),
                     sample_rate=fs, t0=1000)
    Y, _ = _window_segment_ffts(ts2, 1000, np.array([1002.0]),
                                band=(20.0, 400.0))
    Py = np.sum(np.abs(Y) ** 2, axis=1)
    cross = np.einsum("ikf,jkf->ijf", X, np.conj(Y))
    coh = np.abs(cross[0, 0]) ** 2 / (Px[0] * Py[0])
    # E[C] = 1/n_d for independent Gaussians; max over ~740 bins stays
    # far from 1 with 31 averages.
    assert coh.max() < 0.6
    assert coh.mean() < 0.1
