"""How many DSD verdicts flip when the whitening context changes?

`ts.whiten()` estimates the amplitude spectral density over whatever stretch of
data it is handed, so the whitened window -- and every score downstream of it --
depends on how much surrounding data the whitening saw. LAB_NOTEBOOK section 12
established this for a single candidate: its native score swung ~0.05-0.09 across
context lengths from +-4 s to +-256 s, comparable to the DSD threshold spacing.
That left a stated-but-unquantified limitation: in principle a context change can
push a borderline candidate across the DSD cut, but the *population* rate was
never measured.

This measures it. A sample of near-threshold candidates is re-scored against the
native O4a index (K=1216) at several whitening pad lengths, and the DSD verdict
is recomputed both at the fixed production boundary and at a separately
calibrated per-pad boundary. The result is:

* **Per-candidate score std across contexts** -- how much the DSD score itself
  moves when only the whitening context changes.
* **Verdict flip rate** -- of the near-threshold candidates, how many change
  ROBUST/not-ROBUST relative to the production pad=4 context.

The production context (pad=4) is the reference. A hard reproduction gate is
built in: at pad=4 the re-scored native value must match the stored score from
the same versioned index/query representation within a declared tolerance, or
the experiment aborts. Each pad also receives its own background calibration;
fixed-threshold score sensitivity and recalibrated-pipeline verdict changes are
reported separately.

Catalogues before 2026-07-24 label the padded crop, so the analysis window is
[gps + 4, gps + 36] (the reproducibility note).

Usage
-----
    python -m src.pipeline_v2_production.whitening_context_sensitivity --pilot
    python -m src.pipeline_v2_production.whitening_context_sensitivity --n-candidates 15

Writes a representation-versioned summary JSON plus a long-form candidate x
pad score matrix and representation-matched background score arrays. The
invalid pre-audit summary is never overwritten.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.utils import record_environment, setup_logger
logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
SEGMENT_LENGTH = 32.0
WINDOW_OFFSET = 4.0          # catalogue GPS labels the padded crop
PRODUCTION_PAD = 4.0
DEFAULT_PADS = (4.0, 16.0, 64.0, 128.0)
LARGE_SWING = 0.02          # a score swing this size can cross the DSD spacing
ANCHOR_TOLERANCE = 1e-3
MIN_BACKGROUND = 100
RESERVE_PER_STRATUM = 5


def _score_at_pads(
    cands: pd.DataFrame,
    pads,
    scorer,
    *,
    qrange: tuple[int, int],
    window_offset: float,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Native score at each pad, plus the kept mask and failure ledger.

    Whitening requires the complete requested context.  The data loader's
    ``edge_tolerance`` is therefore deliberately zero: setting it to ``pad``
    can select a shorter local block and defer the missing edge to
    ``whiten_context``, which used to make candidates disappear silently.
    """
    import warnings
    import matplotlib

    from src.core.data_loader import fetch_local_or_remote_strain
    from src.core.preprocessor import (whiten_context, extract_clean_subwindow,
                                       generate_qtransform)

    scores = np.full((len(cands), len(pads)), np.nan)
    kept = np.zeros(len(cands), dtype=bool)
    failures: list[dict] = []
    for r, (_, c) in enumerate(cands.iterrows()):
        w0 = float(c.gps_start) + float(window_offset)
        ok = True
        for j, pad in enumerate(pads):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    ts = fetch_local_or_remote_strain(
                        c.detector,
                        w0 - pad,
                        w0 + SEGMENT_LENGTH + pad,
                        edge_tolerance=0.0,
                        cache_raw=True,
                    )
                    tw, pad_info = whiten_context(
                        ts,
                        w0,
                        w0 + SEGMENT_LENGTH,
                        pad=pad,
                    )
                    if pad_info["left"] or pad_info["right"]:
                        raise RuntimeError(
                            f"incomplete whitening context: {pad_info}"
                        )
                    clean = extract_clean_subwindow(tw, w0, w0 + SEGMENT_LENGTH)
                    spec = generate_qtransform(
                        clean,
                        qrange=qrange,
                        output_size=(256, 256),
                        save_path=None,
                        cmap="cividis",
                    )
                rgb = (matplotlib.colormaps["cividis"](spec)[:, :, :3] * 255).astype(np.uint8)
                scores[r, j] = float(scorer.score_spectrogram([rgb], threshold=0.0)[0]
                                     ["novelty_score"])
            except Exception as e:  # noqa: BLE001
                failure = {
                    "detector": str(c.detector),
                    "gps_start": int(c.gps_start),
                    "analysis_start": float(w0),
                    "pad_s": float(pad),
                    "error_type": type(e).__name__,
                    "error": str(e),
                }
                failures.append(failure)
                logger.warning(
                    "candidate %s/%s pad %s failed: %s",
                    c.detector,
                    c.gps_start,
                    pad,
                    e,
                )
                ok = False
                break
        kept[r] = ok
    return scores, kept, failures


def _score_balanced_at_pads(
    candidate_pool: pd.DataFrame,
    pads,
    scorer,
    *,
    qrange: tuple[int, int],
    window_offset: float,
    class_column: str,
    score_column: str,
    n_each: int,
    anchor_tolerance: float,
) -> tuple[pd.DataFrame, np.ndarray, list[dict], dict, dict]:
    """Select the nearest fully usable candidates within each stratum.

    Candidates remain ordered by distance from their class boundary as emitted
    by :func:`_sample_near_threshold`.  A candidate with incomplete/non-finite
    raw context, or whose pad-4 score does not reproduce its stored production
    score, is recorded and the next candidate in the same detector/class
    stratum is tried.  This preserves the balanced design without silently
    reducing a stratum or substituting across strata.
    """
    selected_frames = []
    selected_scores = []
    failures: list[dict] = []
    attempted_counts: dict[str, dict[str, int]] = {}
    selected_counts: dict[str, dict[str, int]] = {}
    production_pad_index = tuple(pads).index(PRODUCTION_PAD)

    for detector in ("H1", "L1"):
        attempted_counts[detector] = {}
        selected_counts[detector] = {}
        for klass in ("ROBUST", "BACKGROUND"):
            stratum = candidate_pool[
                (candidate_pool.detector == detector)
                & (candidate_pool[class_column] == klass)
            ]
            attempted = 0
            selected = 0
            for _, candidate in stratum.iterrows():
                one = candidate.to_frame().T
                one_scores, kept, one_failures = _score_at_pads(
                    one,
                    pads,
                    scorer,
                    qrange=qrange,
                    window_offset=window_offset,
                )
                attempted += 1
                failures.extend(one_failures)
                if bool(kept[0]):
                    stored_score = float(candidate[score_column])
                    anchor_delta = abs(
                        float(one_scores[0, production_pad_index])
                        - stored_score
                    )
                    if anchor_delta > anchor_tolerance:
                        failures.append(
                            {
                                "detector": str(candidate.detector),
                                "gps_start": int(candidate.gps_start),
                                "analysis_start": (
                                    float(candidate.gps_start)
                                    + float(window_offset)
                                ),
                                "pad_s": float(PRODUCTION_PAD),
                                "error_type": "AnchorMismatch",
                                "error": (
                                    "pad-4 score does not reproduce stored "
                                    f"production score: abs_delta={anchor_delta:.12g}, "
                                    f"tolerance={anchor_tolerance:.12g}"
                                ),
                            }
                        )
                    else:
                        selected_frames.append(one)
                        selected_scores.append(one_scores[0])
                        selected += 1
                if selected == n_each:
                    break
            attempted_counts[detector][klass] = attempted
            selected_counts[detector][klass] = selected

    if selected_frames:
        selected_frame = pd.concat(selected_frames).reset_index(drop=True)
        score_matrix = np.vstack(selected_scores)
    else:
        selected_frame = candidate_pool.iloc[0:0].copy()
        score_matrix = np.empty((0, len(pads)), dtype=float)
    return (
        selected_frame,
        score_matrix,
        failures,
        attempted_counts,
        selected_counts,
    )


def _block_bootstrap_p99_ci(
    scores: np.ndarray,
    *,
    B: int | None = None,
    seed: int = 42,
) -> tuple[float, float, float]:
    """P99 and percentile bootstrap CI using contiguous score blocks."""
    from src.pipeline_v2_production.background_calibration import (
        block_bootstrap_p99_ci,
    )

    kwargs = {"seed": seed}
    if B is not None:
        kwargs["B"] = B
    result = block_bootstrap_p99_ci(scores, **kwargs)
    return (
        result["p99"],
        result["ci_lower"],
        result["ci_upper"],
    )


def _classify(score: float, lower: float, upper: float) -> str:
    if score > upper:
        return "ROBUST"
    if score >= lower:
        return "AMBIGUOUS"
    return "BACKGROUND"


def _sample_near_threshold(
    taxonomy: pd.DataFrame,
    *,
    n_each: int,
    thresholds: dict,
    score_column: str,
    class_column: str,
) -> pd.DataFrame:
    """Balanced near-boundary sample under the representation being tested."""
    picks = []
    for det in ("H1", "L1"):
        d = taxonomy[taxonomy.detector == det]
        lower = thresholds[det]["ci_lower"]
        upper = thresholds[det]["ci_upper"]
        robust = d[
            (d[class_column] == "ROBUST")
            & (d[score_column] < upper + 0.04)
        ].nsmallest(n_each, score_column)
        rejected = d[
            (d[class_column] == "BACKGROUND")
            & (d[score_column] > lower - 0.06)
        ].nlargest(n_each, score_column)
        picks.extend([robust, rejected])
    return (
        pd.concat(picks)
        .drop_duplicates(["detector", "gps_start"])
        .reset_index(drop=True)
    )


def run(
    run_name: str = "O4a",
    n_candidates: int = 15,
    pads=DEFAULT_PADS,
    seed: int = 42,
    *,
    native_index_path: str | Path | None = None,
    n_background: int = 5000,
    anchor_tolerance: float = ANCHOR_TOLERANCE,
    window_offset: float = WINDOW_OFFSET,
) -> dict:
    import hashlib

    from src.core.patch_scorer import PatchScorer
    from src.core.index_contract import load_index_contract, qrange_tag
    from src.core.utils import get_reference_dir, load_config
    from src.pipeline_v2_production.aggregate_report import AggregateReporter
    from src.pipeline_v2_production.background_calibration import (
        CalibrationWindow,
        resolve_run_bounds,
        validate_calibration_ledger,
    )

    pads = tuple(float(p) for p in pads)
    if PRODUCTION_PAD not in pads:
        pads = (PRODUCTION_PAD,) + pads
    if n_background < MIN_BACKGROUND:
        raise ValueError(
            f"n_background={n_background} is below the machinery floor "
            f"{MIN_BACKGROUND}"
        )
    ref = get_reference_dir()
    config = load_config()
    production_qrange = tuple(
        int(v) for v in config["preprocessing"]["qrange"]
    )
    if native_index_path is None:
        native_index_path = (
            ref
            / f"patch_compressed_index_{run_name.lower()}_"
              f"{qrange_tag(production_qrange)}_ex.npz"
        )
    contract = load_index_contract(native_index_path)
    if tuple(contract.qrange) != production_qrange:
        raise RuntimeError(
            "Whitening experiment requires an index/query coherent with the "
            f"production qrange {production_qrange}; got {contract.qrange}"
        )
    scorer = PatchScorer(
        reference_index_path=str(contract.path),
        verify_md5=False)

    reporter = AggregateReporter(
        production_dir=AGG.parent,
        run=run_name,
        native_index_path=contract.path,
        candidate_window_offset=window_offset,
    )
    representation = (
        f"idx{contract.tag}_query{qrange_tag(production_qrange)}"
    )
    variant_column = representation.replace("-", "_")
    score_column = f"native_score_{variant_column}"
    class_column = f"robustness_class_{variant_column}"

    tax_path = AGG / (
        f"Master_Taxonomy_{run_name}_{representation}.csv"
    )
    if not tax_path.exists():
        raise RuntimeError(
            "Versioned coherent taxonomy is missing; run the DSD transition "
            f"audit first: {tax_path}"
        )
    tax = pd.read_csv(tax_path)
    tax["gps_start"] = tax.gps_start.astype(int)
    missing = [
        col for col in (score_column, class_column)
        if col not in tax.columns
    ]
    if missing:
        raise RuntimeError(
            "Run the coherent DSD transition audit before the whitening "
            f"experiment; missing taxonomy columns: {missing}"
        )

    run_bounds = resolve_run_bounds(config, run_name)
    guard_s = 96.0

    def file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    exclusion_by_detector = {
        det: reporter._calibration_forbidden_intervals(
            tax,
            det,
            contract,
        )
        for det in ("H1", "L1")
    }
    dsd_threshold_path = AGG / (
        f"dsd_thresholds_{run_name.lower()}_{representation}.json"
    )
    if not dsd_threshold_path.exists():
        raise RuntimeError(
            f"Canonical DSD thresholds are missing: {dsd_threshold_path}"
        )
    dsd_threshold_record = json.loads(
        dsd_threshold_path.read_text(encoding="utf-8")
    )
    dsd_representation = dsd_threshold_record.get("representation", {})
    if (
        dsd_representation.get("variant") != representation
        or dsd_representation.get("index_sha256") != contract.sha256
        or not dsd_representation.get("coherent")
    ):
        raise RuntimeError(
            "Canonical DSD threshold representation/index mismatch"
        )

    thresholds_by_pad: dict[str, dict] = {}
    for pad in pads:
        det_thresholds = {}
        for det in ("H1", "L1"):
            forbidden_intervals, exclusion_meta = exclusion_by_detector[det]
            if pad == PRODUCTION_PAD:
                canonical = dsd_threshold_record["thresholds"][det]
                cache = Path(canonical["background_scores_path"])
                ledger_path = Path(canonical["background_ledger_path"])
                cache_meta_path = cache.with_suffix(".json")
            else:
                cache = AGG / (
                    f"background_scores_whitening_{det}_{run_name}_"
                    f"{representation}_pad{pad:g}_bgv3_"
                    f"{contract.sha256[:8]}_"
                    f"{exclusion_meta['candidate_windows_sha256'][:8]}_"
                    f"{exclusion_meta['index_training_ledger_sha256'][:8]}.npy"
                )
                cache_meta_path = cache.with_suffix(".json")
                ledger_path = cache.with_name(f"{cache.stem}_ledger.csv")
            expected = {
                "schema_version": 3,
                "detector": det,
                "calibration_run": run_name,
                "index_sha256": contract.sha256,
                "index_qrange": list(contract.qrange),
                "query_qrange": list(production_qrange),
                "whitening_pad_s": float(pad),
                "requested_n_scores": int(n_background),
                "run_bounds_gps": list(run_bounds),
                "guard_s": guard_s,
                "candidate_window_offset_s": float(window_offset),
                "sampling_strategy": (
                    "run_bounded_candidate_index_guarded_blocks_v3"
                ),
                "candidate_windows_sha256": exclusion_meta[
                    "candidate_windows_sha256"
                ],
                "index_training_ledger_sha256": exclusion_meta[
                    "index_training_ledger_sha256"
                ],
            }
            if cache.exists():
                if not cache_meta_path.exists():
                    raise RuntimeError(
                        f"Whitening background cache {cache} has no sidecar"
                    )
                cache_meta = json.loads(
                    cache_meta_path.read_text(encoding="utf-8")
                )
                for key, value in expected.items():
                    if cache_meta.get(key) != value:
                        raise RuntimeError(
                            f"Whitening cache contract mismatch for {det}, "
                            f"pad={pad:g}: {key}"
                        )
                if not ledger_path.exists():
                    raise RuntimeError(
                        f"Whitening background cache {cache} has no GPS ledger"
                    )
                if cache_meta.get("ledger_sha256") != file_sha256(ledger_path):
                    raise RuntimeError(
                        f"Whitening background ledger hash mismatch for "
                        f"{det}, pad={pad:g}"
                    )
                ledger_frame = pd.read_csv(ledger_path)
                ledger_windows = [
                    CalibrationWindow(
                        gps_start=float(row.gps_start),
                        gps_end=float(row.gps_end),
                        source_path=Path(str(row.source_path)),
                        source_start=float(row.source_start),
                        source_end=float(row.source_end),
                    )
                    for row in ledger_frame.itertuples(index=False)
                ]
                ledger_audit = validate_calibration_ledger(
                    ledger_windows,
                    run_bounds=run_bounds,
                    forbidden_intervals=forbidden_intervals,
                    guard_s=guard_s,
                )
                if (
                    ledger_audit["outside_run"]
                    or ledger_audit["forbidden_overlap"]
                    or ledger_audit["self_overlap"]
                ):
                    raise RuntimeError(
                        f"Whitening background ledger audit failed for "
                        f"{det}, pad={pad:g}: {ledger_audit}"
                    )
                bg_scores = np.load(cache)
                if len(bg_scores) != len(ledger_frame):
                    raise RuntimeError(
                        f"Whitening score/ledger length mismatch for {det}, "
                        f"pad={pad:g}"
                    )
            else:
                bg_scores, ledger_records = (
                    reporter._extract_detector_background(
                        scorer,
                        det,
                        n_background,
                        qrange=production_qrange,
                        pad=pad,
                        run_bounds=run_bounds,
                        forbidden_intervals=forbidden_intervals,
                        guard_s=guard_s,
                    )
                )
                if len(bg_scores) == n_background:
                    ledger_frame = pd.DataFrame(ledger_records)
                    if len(ledger_frame) != len(bg_scores):
                        raise RuntimeError(
                            f"Whitening score/ledger length mismatch for "
                            f"{det}, pad={pad:g}"
                        )
                    ledger_windows = [
                        CalibrationWindow(
                            gps_start=float(row.gps_start),
                            gps_end=float(row.gps_end),
                            source_path=Path(str(row.source_path)),
                            source_start=float(row.source_start),
                            source_end=float(row.source_end),
                        )
                        for row in ledger_frame.itertuples(index=False)
                    ]
                    ledger_audit = validate_calibration_ledger(
                        ledger_windows,
                        run_bounds=run_bounds,
                        forbidden_intervals=forbidden_intervals,
                        guard_s=guard_s,
                    )
                    if (
                        ledger_audit["outside_run"]
                        or ledger_audit["forbidden_overlap"]
                        or ledger_audit["self_overlap"]
                    ):
                        raise RuntimeError(
                            f"New whitening background ledger audit failed "
                            f"for {det}, pad={pad:g}: {ledger_audit}"
                        )
                    np.save(cache, bg_scores)
                    ledger_frame.to_csv(ledger_path, index=False)
                    cache_meta_path.write_text(
                        json.dumps(
                            {
                                **expected,
                                "index_path": str(contract.path),
                                "n_scores": int(len(bg_scores)),
                                "ledger_path": str(ledger_path),
                                "ledger_sha256": file_sha256(ledger_path),
                                "ledger_audit": ledger_audit,
                                **exclusion_meta,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
            if len(bg_scores) < n_background:
                raise RuntimeError(
                    f"Only {len(bg_scores)}/{n_background} background scores "
                    f"for {det}, pad={pad:g}; refusing partial calibration"
                )
            p99, lower, upper = _block_bootstrap_p99_ci(
                bg_scores,
                seed=seed,
            )
            det_thresholds[det] = {
                "p99": p99,
                "ci_lower": lower,
                "ci_upper": upper,
                "bootstrap_replicates": 1_000_000,
                "bootstrap_seed": int(seed),
                "n_background": int(len(bg_scores)),
                "scores_path": str(cache),
                "ledger_path": str(ledger_path),
                "ledger_sha256": file_sha256(ledger_path),
                "pad4_reuses_canonical_dsd_calibration": bool(
                    pad == PRODUCTION_PAD
                ),
            }
        thresholds_by_pad[str(pad)] = det_thresholds
    pool_each = int(n_candidates) + RESERVE_PER_STRATUM
    candidate_pool = _sample_near_threshold(
        tax,
        n_each=pool_each,
        thresholds=thresholds_by_pad[str(PRODUCTION_PAD)],
        score_column=score_column,
        class_column=class_column,
    )
    expected_pool = 4 * pool_each
    pool_counts = (
        candidate_pool.groupby(["detector", class_column]).size().to_dict()
    )
    expected_pool_counts = {
        (detector, klass): pool_each
        for detector in ("H1", "L1")
        for klass in ("ROBUST", "BACKGROUND")
    }
    if (
        len(candidate_pool) != expected_pool
        or pool_counts != expected_pool_counts
    ):
        raise RuntimeError(
            "Whitening near-threshold reserve pool is incomplete: "
            f"expected {expected_pool_counts}, got {pool_counts}"
        )
    logger.info(
        "%d near-threshold candidates plus %d reserves per stratum; pads %s",
        4 * int(n_candidates),
        RESERVE_PER_STRATUM,
        list(pads),
    )

    (
        cands,
        scores,
        failures,
        attempted_counts,
        selected_counts,
    ) = _score_balanced_at_pads(
        candidate_pool,
        pads,
        scorer,
        qrange=production_qrange,
        window_offset=window_offset,
        class_column=class_column,
        score_column=score_column,
        n_each=int(n_candidates),
        anchor_tolerance=float(anchor_tolerance),
    )
    failure_path = AGG / (
        f"whitening_context_scoring_failures_{run_name.lower()}_"
        f"{representation}.csv"
    )
    pd.DataFrame(
        failures,
        columns=[
            "detector",
            "gps_start",
            "analysis_start",
            "pad_s",
            "error_type",
            "error",
        ],
    ).to_csv(failure_path, index=False)
    expected_selected_counts = {
        detector: {
            "ROBUST": int(n_candidates),
            "BACKGROUND": int(n_candidates),
        }
        for detector in ("H1", "L1")
    }
    if selected_counts != expected_selected_counts:
        raise RuntimeError(
            "Whitening candidate scoring is incomplete: "
            f"expected {expected_selected_counts}, got {selected_counts}; "
            f"diagnostics: {failure_path}"
        )
    logger.info(f"{len(cands)} candidates scored at all pads")

    pad_idx = pads.index(PRODUCTION_PAD)
    prod_score = scores[:, pad_idx]
    stored = cands[score_column].to_numpy(dtype=np.float64)

    # Reproduction anchor: pad=4 re-score must match the stored production score.
    repro_abs = np.abs(prod_score - stored)
    logger.info(f"pad=4 reproduction vs stored: max |delta| {repro_abs.max():.4f}, "
                f"median {np.median(repro_abs):.4f}")
    anchor_pass = bool(np.all(repro_abs <= anchor_tolerance))

    rows = []
    fixed_verdict = np.empty(scores.shape, dtype=object)
    recalibrated_verdict = np.empty(scores.shape, dtype=object)
    for r, c in cands.iterrows():
        det = str(c.detector)
        prod_thr = thresholds_by_pad[str(PRODUCTION_PAD)][det]
        for j, pad in enumerate(pads):
            pad_thr = thresholds_by_pad[str(pad)][det]
            fixed_class = _classify(
                scores[r, j],
                prod_thr["ci_lower"],
                prod_thr["ci_upper"],
            )
            recal_class = _classify(
                scores[r, j],
                pad_thr["ci_lower"],
                pad_thr["ci_upper"],
            )
            fixed_verdict[r, j] = fixed_class
            recalibrated_verdict[r, j] = recal_class
            rows.append(
                {
                    "gps_start": int(c.gps_start),
                    "analysis_start": (
                        float(c.gps_start) + float(window_offset)
                    ),
                    "detector": det,
                    "pad_s": float(pad),
                    "score": float(scores[r, j]),
                    "stored_pad4_score": float(stored[r]),
                    "pad4_anchor_abs_delta": (
                        float(repro_abs[r]) if pad == PRODUCTION_PAD else None
                    ),
                    "fixed_pad4_threshold_class": fixed_class,
                    "pad_specific_threshold_class": recal_class,
                    "pad_specific_ci_lower": pad_thr["ci_lower"],
                    "pad_specific_ci_upper": pad_thr["ci_upper"],
                    "representation": representation,
                }
            )
    matrix_path = AGG / (
        f"whitening_context_scores_{run_name.lower()}_{representation}.csv"
    )
    pd.DataFrame(rows).to_csv(matrix_path, index=False)

    anchor_status = {
        "passed": anchor_pass,
        "tolerance": float(anchor_tolerance),
        "n_failed": int((repro_abs > anchor_tolerance).sum()),
        "max_abs_delta": float(repro_abs.max()),
        "median_abs_delta": float(np.median(repro_abs)),
    }
    if not anchor_pass:
        failed_path = AGG / (
            f"whitening_context_anchor_failure_{run_name.lower()}_"
            f"{representation}.json"
        )
        failed_path.write_text(
            json.dumps(
                {
                    "run": run_name,
                    "representation": representation,
                    "index_path": str(contract.path),
                    "index_sha256": contract.sha256,
                    "window_offset_s": float(window_offset),
                    "anchor": anchor_status,
                    "score_matrix": str(matrix_path),
                    "status": "INVALID_REPRODUCTION_ANCHOR",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        raise RuntimeError(
            "Whitening reproduction anchor failed: "
            f"{anchor_status['n_failed']}/{len(cands)} exceed "
            f"{anchor_tolerance:g}; diagnostics: {failed_path}"
        )

    fixed_prod = fixed_verdict[:, pad_idx]
    recal_prod = recalibrated_verdict[:, pad_idx]

    # Context swing = full range of a candidate's score across the pad ladder.
    per_cand_std = np.nanstd(scores, axis=1)
    per_cand_swing = np.nanmax(scores, axis=1) - np.nanmin(scores, axis=1)
    n_large_swing = int((per_cand_swing > LARGE_SWING).sum())
    fixed_flips = {}
    recalibrated_flips = {}
    for j, pad in enumerate(pads):
        if pad == PRODUCTION_PAD:
            continue
        fixed_changed = fixed_verdict[:, j] != fixed_prod
        recal_changed = recalibrated_verdict[:, j] != recal_prod
        fixed_flips[str(pad)] = {
            "n_flipped": int(fixed_changed.sum()),
            "flip_rate": float(fixed_changed.mean()),
            "flipped_gps": [
                int(g) for g in cands.gps_start[fixed_changed].tolist()
            ],
        }
        recalibrated_flips[str(pad)] = {
            "n_flipped": int(recal_changed.sum()),
            "flip_rate": float(recal_changed.mean()),
            "flipped_gps": [
                int(g) for g in cands.gps_start[recal_changed].tolist()
            ],
        }
        logger.info(
            "pad=%s: fixed-threshold flips %d/%d; recalibrated flips %d/%d",
            pad,
            int(fixed_changed.sum()),
            len(cands),
            int(recal_changed.sum()),
            len(cands),
        )

    out = {
        "run": run_name, "seed": seed, "pads": list(pads),
        "production_pad": PRODUCTION_PAD,
        "window_offset_s": float(window_offset),
        "representation": {
            "variant": representation,
            "index_path": str(contract.path),
            "index_sha256": contract.sha256,
            "index_qrange": list(contract.qrange),
            "query_qrange": list(production_qrange),
        },
        "thresholds_by_pad": thresholds_by_pad,
        "candidate_selection": {
            "ordering": "nearest_class_boundary_first",
            "reserve_per_detector_class": RESERVE_PER_STRATUM,
            "attempted_counts": attempted_counts,
            "selected_counts": selected_counts,
            "failure_ledger": str(failure_path),
            "failure_ledger_sha256": file_sha256(failure_path),
        },
        "n_attempted": int(
            sum(sum(counts.values()) for counts in attempted_counts.values())
        ),
        "n_failed_scoring": int(len(failures)),
        "n_candidates": int(len(cands)),
        "n_robust": int((cands[class_column] == "ROBUST").sum()),
        "n_rejected": int((cands[class_column] == "BACKGROUND").sum()),
        "reproduction_pad4_vs_stored": anchor_status,
        "per_candidate_score_std_median": float(np.median(per_cand_std)),
        "per_candidate_score_std_max": float(per_cand_std.max()),
        "per_candidate_swing_median": float(np.median(per_cand_swing)),
        "per_candidate_swing_max": float(per_cand_swing.max()),
        "n_large_swing": n_large_swing,
        "large_swing_threshold": LARGE_SWING,
        "fixed_pad4_threshold_flips": fixed_flips,
        "pad_recalibrated_pipeline_flips": recalibrated_flips,
        "score_matrix": str(matrix_path),
        "interpretation_note": (
            "per_candidate_swing is a candidate's score range across pad 4->128, "
            "i.e. how much the native DSD score moves when only the whitening "
            "context changes. n_large_swing counts candidates whose swing exceeds "
            f"{LARGE_SWING} (enough to matter at the DSD spacing) -- these are the "
            "LAB_NOTEBOOK section 12 singleton's kind, and the point is whether "
            "they are typical or rare. verdict flip rate is the fraction of "
            "near-threshold candidates that cross the DSD cut between production "
            "pad=4 and a longer context. fixed_pad4_threshold_flips isolates "
            "score sensitivity at a fixed decision boundary; "
            "pad_recalibrated_pipeline_flips uses a separately calibrated "
            "background threshold at every pad. Because the sample is selected "
            "near the production boundary, neither rate is a survey-wide upper "
            "bound."),
    }
    dest = AGG / (
        f"whitening_context_sensitivity_{run_name.lower()}_"
        f"{representation}.json"
    )
    if dest.exists():
        raise FileExistsError(
            f"Refusing to overwrite whitening artifact {dest}"
        )
    dest.write_text(json.dumps(out, indent=2))
    logger.info(
        f"context swing median {out['per_candidate_swing_median']:.4f} "
        f"(max {out['per_candidate_swing_max']:.4f}); {n_large_swing}/{len(cands)} "
        f"exceed {LARGE_SWING}; recalibrated flip rates "
        f"{ {p: round(f['flip_rate'], 3) for p, f in recalibrated_flips.items()} }")
    logger.info(f"wrote {dest}")
    record_environment(
        AGG,
        f"whitening_context_sensitivity_{run_name.lower()}_{representation}",
    )
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--n-candidates", type=int, default=15,
                   help="Near-threshold candidates per (class, detector).")
    p.add_argument("--pads", type=float, nargs="+", default=list(DEFAULT_PADS))
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--native-index", default=None)
    p.add_argument("--n-background", type=int, default=5000)
    p.add_argument("--anchor-tolerance", type=float, default=ANCHOR_TOLERANCE)
    p.add_argument("--window-offset", type=float, default=WINDOW_OFFSET)
    p.add_argument("--pilot", action="store_true",
                   help="Fast machinery + reproduction check on a few candidates.")
    a = p.parse_args()
    if a.pilot:
        run(
            a.run,
            n_candidates=2,
            pads=(4.0, 64.0),
            seed=a.seed,
            native_index_path=a.native_index,
            n_background=max(MIN_BACKGROUND, min(a.n_background, 200)),
            anchor_tolerance=a.anchor_tolerance,
            window_offset=a.window_offset,
        )
    else:
        run(
            a.run,
            n_candidates=a.n_candidates,
            pads=a.pads,
            seed=a.seed,
            native_index_path=a.native_index,
            n_background=a.n_background,
            anchor_tolerance=a.anchor_tolerance,
            window_offset=a.window_offset,
        )


if __name__ == "__main__":
    main()
