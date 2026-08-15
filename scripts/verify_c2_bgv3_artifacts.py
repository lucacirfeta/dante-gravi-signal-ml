"""Fail-closed verification gate for the C2/BGV3 paper artifacts.

This script checks provenance links, sample sizes, representation identifiers,
hashes, finite values, and endpoint identities.  It deliberately does not decide
whether an effect is scientifically interesting; it decides whether an artifact
is internally consistent and eligible for interpretation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
AGG = ROOT / "data" / "production" / "aggregated"
REP = "idxq4-64_queryq4-64"
REP_COLUMN = "idxq4_64_queryq4_64"
EXPECTED_COUNTS = {
    "H1": {"ROBUST": 2227, "AMBIGUOUS": 562, "BACKGROUND": 1622},
    "L1": {"ROBUST": 4138, "AMBIGUOUS": 713, "BACKGROUND": 1167},
}
EXPECTED_CANDIDATES = 10_429


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _json(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"missing JSON artifact: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"expected JSON object: {path}")
    _finite_tree(value, str(path))
    return value


def _finite_tree(value: Any, label: str) -> None:
    if isinstance(value, float):
        _require(math.isfinite(value), f"non-finite value in {label}")
    elif isinstance(value, dict):
        for child in value.values():
            _finite_tree(child, label)
    elif isinstance(value, list):
        for child in value:
            _finite_tree(child, label)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_artifact_path(raw: str | Path) -> Path:
    text = str(raw)
    if text.startswith("/mnt/c/"):
        path = Path("C:/" + text[len("/mnt/c/"):])
    else:
        path = Path(text)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _check_hash(raw_path: str | Path, expected: str, label: str) -> Path:
    path = _resolve_artifact_path(raw_path)
    _require(path.is_file(), f"{label} is missing: {path}")
    actual = _sha256(path)
    _require(actual == expected, f"{label} SHA256 mismatch: {actual} != {expected}")
    return path


def _taxonomy() -> tuple[pd.DataFrame, dict[str, Any]]:
    threshold_path = AGG / f"dsd_thresholds_o4a_{REP}.json"
    threshold = _json(threshold_path)
    rep = threshold["representation"]
    _require(rep["coherent"] is True and rep["variant"] == REP,
             "threshold representation is not coherent C2")
    _require(rep["index_qrange"] == [4, 64] and rep["query_qrange"] == [4, 64],
             "threshold Q-range mismatch")

    for detector in ("H1", "L1"):
        record = threshold["thresholds"][detector]
        _require(record["bootstrap_replicates"] == 1_000_000,
                 f"{detector} threshold is not the B=1,000,000 result")
        _require(record["n_background"] == 5000,
                 f"{detector} background count is not 5000")
        _require(record["ci_lower"] <= record["p99"] <= record["ci_upper"],
                 f"{detector} P99 is outside its interval")
        _check_hash(
            record["background_ledger_path"],
            record["background_ledger_sha256"],
            f"{detector} calibration ledger",
        )
        scores = np.load(_resolve_artifact_path(record["background_scores_path"]))
        _require(scores.shape == (5000,) and np.isfinite(scores).all(),
                 f"{detector} calibration scores are invalid")

    taxonomy_path = AGG / f"Master_Taxonomy_O4a_{REP}.csv"
    taxonomy = pd.read_csv(taxonomy_path)
    score_column = f"native_score_{REP_COLUMN}"
    class_column = f"robustness_class_{REP_COLUMN}"
    required = {"detector", "gps_start", score_column, class_column}
    _require(required.issubset(taxonomy.columns),
             f"taxonomy lacks columns: {sorted(required - set(taxonomy.columns))}")
    _require(
        len(taxonomy) == EXPECTED_CANDIDATES,
        f"taxonomy row count is not {EXPECTED_CANDIDATES:,}",
    )
    _require(
        not taxonomy.duplicated(["detector", "gps_start"]).any(),
        "taxonomy candidate keys are not unique",
    )
    _require(np.isfinite(taxonomy[score_column].to_numpy(float)).all(),
             "taxonomy contains non-finite C2 scores")

    for detector in ("H1", "L1"):
        subset = taxonomy[taxonomy.detector == detector]
        actual = subset[class_column].value_counts().to_dict()
        _require(actual == EXPECTED_COUNTS[detector],
                 f"{detector} class counts changed: {actual}")
        lower = threshold["thresholds"][detector]["ci_lower"]
        upper = threshold["thresholds"][detector]["ci_upper"]
        score = subset[score_column].to_numpy(float)
        expected_class = np.where(
            score > upper,
            "ROBUST",
            np.where(score >= lower, "AMBIGUOUS", "BACKGROUND"),
        )
        _require(
            np.array_equal(expected_class, subset[class_column].to_numpy(str)),
            f"{detector} taxonomy labels do not reproduce the C2 thresholds",
        )
    taxonomy["dsd_score"] = taxonomy[score_column]
    taxonomy["dsd_class"] = taxonomy[class_column]

    audit = _json(AGG / f"dsd_transition_audit_o4a_{REP}.json")
    _require(
        audit["total_failed"] == 0
        and audit["total_evaluated"] == EXPECTED_CANDIDATES,
             "DSD transition audit is incomplete")
    reuse = audit["candidate_score_reuse"]
    _require(
        reuse["mode"] == "verified_subset_candidate_score_reuse"
        and reuse["exact_key_subset"]
        and reuse["unique_candidate_keys"]
        and reuse["all_scores_finite"],
        "candidate-score reuse did not pass every identity check",
    )
    _require(
        reuse["current_candidate_count"] == EXPECTED_CANDIDATES
        and reuse["n_reused"] + reuse["n_newly_scored"] == EXPECTED_CANDIDATES,
        "candidate-score reuse counts do not cover the current catalogue",
    )
    proof = reuse.get("posthoc_exact_reuse_verification", {})
    proof_path = _check_hash(
        proof.get("path", ""),
        proof.get("sha256", ""),
        "candidate-score reuse verification source",
    )
    prior = pd.read_csv(proof_path)
    proof_score = proof.get("score_column")
    _require(
        {"detector", "gps_start", proof_score}.issubset(prior.columns),
        "candidate-score reuse verification source lacks required columns",
    )
    _require(
        len(prior) == reuse["n_reused"]
        and not prior.duplicated(["detector", "gps_start"]).any(),
        "candidate-score reuse verification keys are incomplete or duplicated",
    )
    prior_score_column = f"{proof_score}_prior"
    comparison = prior[["detector", "gps_start", proof_score]].rename(
        columns={proof_score: prior_score_column}
    ).merge(
        taxonomy[["detector", "gps_start", score_column]],
        on=["detector", "gps_start"],
        how="left",
        validate="one_to_one",
    )
    delta = np.abs(
        comparison[prior_score_column].to_numpy(float)
        - comparison[score_column].to_numpy(float)
    )
    _require(
        len(comparison) == proof["n_verified"]
        and np.isfinite(delta).all()
        and np.array_equal(delta, np.zeros_like(delta))
        and proof["exact_float_equality"]
        and proof["max_absolute_score_difference"] == 0.0,
        "reused candidate scores do not exactly match their archived source",
    )
    return taxonomy, threshold


def verify_p5() -> None:
    taxonomy, _ = _taxonomy()
    artifact = _json(AGG / f"dsd_index_stability_o4a_{REP}.json")
    _require(artifact["representation"] == REP, "P5 representation mismatch")
    _require(
        (
            artifact["n_candidates"],
            artifact["n_robust"],
            artifact["n_rejected"],
            artifact["n_draws"],
            artifact["n_background"],
            artifact["seed"],
        )
        == (160, 80, 80, 4, 1300, 42),
        "P5 sample or randomization contract changed",
    )
    _require(
        artifact["sample_class_counts"] == {"ROBUST": 80, "AMBIGUOUS": 80},
        "P5 must compare the two sides of the robust boundary explicitly",
    )
    candidate_cache = _check_hash(
        artifact["candidate_token_cache"],
        artifact["candidate_token_cache_sha256"],
        "P5 candidate cache",
    )
    background_cache = _check_hash(
        artifact["background_token_cache"],
        artifact["background_token_cache_sha256"],
        "P5 background cache",
    )
    ledger_path = _check_hash(
        artifact["background_ledger"],
        artifact["background_ledger_sha256"],
        "P5 background ledger",
    )
    with np.load(candidate_cache, allow_pickle=False) as cache:
        _require(str(cache["representation"].item()) == REP,
                 "P5 candidate-cache representation mismatch")
        _require(cache["cand"].shape == (160, 1369, 384),
                 "P5 candidate-token shape mismatch")
        _require(cache["pca_feat"].shape[0] == 160,
                 "P5 shared P10 candidate features are incomplete")
        _require(np.isfinite(cache["cand"]).all() and np.isfinite(cache["pca_feat"]).all(),
                 "P5 candidate cache contains non-finite values")
        _require(str(cache["candidate_keys_sha256"].item())
                 == artifact["candidate_keys_sha256"],
                 "P5 candidate key hash mismatch")
        candidate_keys = cache["candidate_keys"].astype(str)
    current_class = {
        f"{row.detector}:{int(float(row.gps_start))}": row.dsd_class
        for row in taxonomy.itertuples()
    }
    selected_classes = np.asarray(
        [current_class.get(key, "MISSING") for key in candidate_keys]
    )
    selected_detectors = np.asarray(
        [key.split(":", 1)[0] for key in candidate_keys]
    )
    selected_counts = {
        detector: {
            klass: int(
                np.sum(
                    (selected_detectors == detector)
                    & (selected_classes == klass)
                )
            )
            for klass in ("ROBUST", "AMBIGUOUS")
        }
        for detector in ("H1", "L1")
    }
    _require(
        selected_counts
        == {
            "H1": {"ROBUST": 40, "AMBIGUOUS": 40},
            "L1": {"ROBUST": 40, "AMBIGUOUS": 40},
        },
        "P5 candidate sample does not reproduce its classes under the current taxonomy",
    )
    with np.load(background_cache, allow_pickle=False) as cache:
        _require(str(cache["representation"].item()) == REP,
                 "P5 background-cache representation mismatch")
        _require(cache["bg"].shape == (1300, 1369, 384),
                 "P5 background-token shape mismatch")
        _require(cache["hold"].shape[0] == 300,
                 "P5 held-out background count mismatch")
        _require(cache["pca_bg_feat"].shape[0] == 1300,
                 "P5 shared P10 background features are incomplete")
        _require(np.isfinite(cache["bg"]).all() and np.isfinite(cache["hold"]).all(),
                 "P5 background cache contains non-finite values")
    ledger = pd.read_csv(ledger_path)
    _require(len(ledger) == 1600, "P5 background ledger row count mismatch")
    _require(ledger["t_bg"].nunique() == 1600, "P5 background GPS values are not unique")
    _require(
        ledger["role"].value_counts().to_dict()
        == {"index_pool": 1300, "held_out": 300},
        "P5 background roles are invalid",
    )


def verify_p4() -> None:
    verify_p5()
    p5 = _json(AGG / f"dsd_index_stability_o4a_{REP}.json")
    artifact = _json(AGG / f"dsd_k_sensitivity_o4a_{REP}.json")
    _require(artifact["representation"] == REP, "P4 representation mismatch")
    _require(artifact["n_candidates"] == 160, "P4 candidate count mismatch")
    _require(artifact["k_values"] == [512, 1024, 1216, 2048],
             "P4 K grid mismatch")
    _require(artifact["production_k"] == 1216, "P4 production K mismatch")
    _require(artifact["n_background_segments"] == 1300,
             "P4 background count mismatch")
    _require(
        artifact["sample_class_counts"] == {"ROBUST": 80, "AMBIGUOUS": 80},
        "P4 class composition differs from P5",
    )
    _require(
        artifact["candidate_token_cache_sha256"]
        == p5["candidate_token_cache_sha256"]
        and artifact["background_token_cache_sha256"]
        == p5["background_token_cache_sha256"]
        and artifact["candidate_keys_sha256"] == p5["candidate_keys_sha256"],
        "P4 did not consume the exact P5 caches/sample",
    )


def verify_p10() -> None:
    verify_p5()
    p5 = _json(AGG / f"dsd_index_stability_o4a_{REP}.json")
    artifact = _json(AGG / f"pca_baseline_o4a_{REP}.json")
    _require(artifact["representation"] == REP, "P10 representation mismatch")
    _require(
        (artifact["n_candidates"], artifact["n_robust"],
         artifact["n_rejected"], artifact["n_background"], artifact["seed"])
        == (160, 80, 80, 1300, 42),
        "P10 sample contract changed",
    )
    _require(
        artifact["sample_class_counts"] == {"ROBUST": 80, "AMBIGUOUS": 80},
        "P10 class composition differs from P5",
    )
    _require(artifact["candidate_keys_sha256"] == p5["candidate_keys_sha256"],
             "P10 and P5 candidate samples differ")
    for endpoint in ("pca_reconstruction_residual", "spectral_energy"):
        result = artifact[endpoint]
        _require(0.0 <= result["auc_robust_vs_rejected"] <= 1.0,
                 f"P10 {endpoint} AUC is invalid")
    _check_hash(
        artifact["candidate_feature_cache"],
        artifact["candidate_feature_cache_sha256"],
        "P10 candidate-feature cache",
    )
    _check_hash(
        artifact["background_feature_cache"],
        artifact["background_feature_cache_sha256"],
        "P10 background-feature cache",
    )
    _check_hash(
        artifact["background_ledger"],
        artifact["background_ledger_sha256"],
        "P10 background ledger",
    )


def verify_multiscale() -> None:
    taxonomy, _ = _taxonomy()
    path = AGG / f"Multiscale_Profile_O4a_{REP}.csv"
    _require(path.is_file(), f"missing multiscale artifact: {path}")
    frame = pd.read_csv(path)
    required = {
        "gps_start", "detector", "scale_s", "score", "p99_threshold",
        "status", "taxonomy_representation",
    }
    _require(required.issubset(frame.columns), "multiscale schema mismatch")
    _require(set(frame["taxonomy_representation"]) == {REP},
             "multiscale representation mismatch")
    _require(not frame.duplicated(["detector", "gps_start", "scale_s"]).any(),
             "multiscale rows are duplicated")
    _require(set(frame["scale_s"]) == {0.5, 1.0, 2.0, 4.0},
             "multiscale grid mismatch")
    groups = frame.groupby(["detector", "gps_start"])
    _require((groups.size() == 4).all(), "not every multiscale candidate has four scales")
    _require(set(frame["status"]) == {"OK"}, "multiscale contains failed/unavailable rows")
    _require(np.isfinite(frame[["score", "p99_threshold"]].to_numpy(float)).all(),
             "multiscale contains non-finite scores")
    current = taxonomy[["detector", "gps_start", "dsd_class"]]
    selected = frame[["detector", "gps_start"]].drop_duplicates().merge(
        current,
        on=["detector", "gps_start"],
        how="left",
        validate="one_to_one",
    )
    _require(
        selected["dsd_class"].notna().all()
        and (selected["dsd_class"] == "ROBUST").all(),
        "multiscale sample is not ROBUST under the current taxonomy",
    )


def verify_cohesion() -> None:
    taxonomy, _ = _taxonomy()
    artifact = _json(AGG / f"background_cohesion_o4a_{REP}.json")
    _require(artifact["representation"] == REP, "cohesion representation mismatch")
    expected_groups = {"NATIVE_BACKGROUND", "ROBUST", "AMBIGUOUS", "BACKGROUND"}
    _require(set(artifact["full"]) == expected_groups,
             "cohesion class coverage mismatch")
    _require(set(artifact["size_matched"]) == expected_groups,
             "cohesion size-matched class coverage mismatch")
    _require(artifact["full"]["NATIVE_BACKGROUND"]["n"] == 3000,
             "cohesion native-background count mismatch")
    _require(artifact["n_matched"] > 1, "cohesion matched sample is degenerate")
    for klass in ("ROBUST", "AMBIGUOUS", "BACKGROUND"):
        expected = int((taxonomy["dsd_class"] == klass).sum())
        _require(artifact["full"][klass]["n"] == expected,
                 f"cohesion {klass} count does not match taxonomy")


def verify_whitening() -> None:
    taxonomy, threshold = _taxonomy()
    artifact = _json(AGG / f"whitening_context_sensitivity_o4a_{REP}.json")
    _require(artifact["representation"]["variant"] == REP,
             "whitening representation mismatch")
    _require(artifact["pads"] == [4.0, 16.0, 64.0, 128.0],
             "whitening pad grid mismatch")
    _require(
        (
            artifact["n_candidates"],
            artifact["n_robust"],
            artifact["n_rejected"],
        )
        == (60, 30, 30),
        "whitening selected sample mismatch",
    )
    selection = artifact["candidate_selection"]
    expected_selected = {
        "H1": {"ROBUST": 15, "BACKGROUND": 15},
        "L1": {"ROBUST": 15, "BACKGROUND": 15},
    }
    _require(
        selection["ordering"] == "nearest_class_boundary_first"
        and selection["reserve_per_detector_class"] == 5
        and selection["selected_counts"] == expected_selected,
        "whitening reserve-selection contract mismatch",
    )
    n_attempted = int(artifact["n_attempted"])
    n_failed = int(artifact["n_failed_scoring"])
    _require(
        60 <= n_attempted <= 80
        and n_failed == n_attempted - 60,
        "whitening attempted/failed candidate accounting mismatch",
    )
    failure_ledger = _check_hash(
        selection["failure_ledger"],
        selection["failure_ledger_sha256"],
        "whitening candidate failure ledger",
    )
    _require(
        len(pd.read_csv(failure_ledger)) == n_failed,
        "whitening failure-ledger row count mismatch",
    )
    anchor = artifact["reproduction_pad4_vs_stored"]
    _require(anchor["passed"] is True and anchor["n_failed"] == 0,
             "whitening pad=4 production anchor failed")
    for pad, detector_records in artifact["thresholds_by_pad"].items():
        for detector in ("H1", "L1"):
            record = detector_records[detector]
            _require(record["n_background"] == 5000,
                     f"whitening pad {pad}/{detector} background count mismatch")
            _require(record["bootstrap_replicates"] == 1_000_000,
                     f"whitening pad {pad}/{detector} bootstrap count mismatch")
    matrix = _resolve_artifact_path(artifact["score_matrix"])
    frame = pd.read_csv(matrix)
    _require(len(frame) == 240, "whitening score matrix row count mismatch")
    _require(not frame.duplicated(["detector", "gps_start", "pad_s"]).any(),
             "whitening score matrix has duplicate candidate/pad rows")
    _require(
        (frame.groupby(["detector", "gps_start"]).size() == 4).all(),
        "not every whitening candidate has four pad measurements",
    )
    selected = frame[["detector", "gps_start"]].drop_duplicates().merge(
        taxonomy[["detector", "gps_start", "dsd_class"]],
        on=["detector", "gps_start"],
        how="left",
        validate="one_to_one",
    )
    actual_selected = {
        detector: selected[selected.detector == detector]["dsd_class"]
        .value_counts()
        .to_dict()
        for detector in ("H1", "L1")
    }
    _require(
        actual_selected == expected_selected,
        "whitening sample classes do not match the current taxonomy",
    )
    pad4 = frame[frame["pad_s"] == 4.0]
    for detector in ("H1", "L1"):
        rows = pad4[pad4.detector == detector]
        record = threshold["thresholds"][detector]
        _require(
            np.allclose(rows["pad_specific_ci_lower"], record["ci_lower"])
            and np.allclose(rows["pad_specific_ci_upper"], record["ci_upper"]),
            f"whitening pad=4 thresholds are stale for {detector}",
        )


def verify_p9() -> None:
    _, threshold = _taxonomy()
    artifact = _json(AGG / f"astrophysical_injection_o4a_{REP}.json")
    _require(artifact["taxonomy_representation"] == REP,
             "P9 representation mismatch")
    _require(artifact["qrange"] == [4, 64], "P9 Q-range mismatch")
    _require(artifact["n_trials"] == 25 and artifact["seed"] == 42,
             "P9 trial contract mismatch")
    for detector in ("H1", "L1"):
        record = threshold["thresholds"][detector]
        _require(
            artifact["thresholds"][f"dsd_{detector}"] == record["ci_upper"]
            and artifact["thresholds"][f"dsd_{detector}_lower"] == record["ci_lower"],
            f"P9 uses stale DSD thresholds for {detector}",
        )
    uncertainty = artifact["binomial_uncertainty"]
    _require(
        uncertainty["method"] == "Wilson score interval"
        and uncertainty["confidence_level"] == 0.95,
        "P9 binomial uncertainty contract mismatch",
    )
    _require(len(artifact["rows"]) == 15 and artifact["n_trial_rows"] == 375,
             "P9 completed-cell/trial count mismatch")
    _require(
        {row["system"] for row in artifact["rows"]}
        == {"BBH_30_30", "BBH_10_10", "NSBH_10_1.4"},
        "P9 system coverage changed; BNS must remain explicitly unmeasured",
    )
    for row in artifact["rows"]:
        for detector in ("H1", "L1"):
            rates = row[f"dsd_class_rate_{detector}"]
            _require(
                set(rates) == {"ROBUST", "AMBIGUOUS", "BACKGROUND"}
                and abs(sum(rates.values()) - 1.0) < 1e-12,
                f"P9 {detector} class rates are incomplete",
            )
        endpoint_records = row["binomial_endpoints"]
        _require(
            {
                "flag_H1", "flag_L1", "flag_either",
                "dsd_robust_H1", "dsd_robust_L1",
                "coincidence_localized_any", "coincidence_recovery",
                "coincidence_oracle_recovery",
                "coincidence_given_primary_flag",
            }
            == set(endpoint_records),
            "P9 binomial endpoint coverage mismatch",
        )
        for name, record in endpoint_records.items():
            _require(
                0 <= record["k"] <= record["n"] <= 25
                and (
                    record["rate"] is None
                    or abs(record["rate"] - record["k"] / record["n"]) < 1e-12
                ),
                f"P9 {name} count/rate mismatch",
            )
            interval = record["wilson_ci95"]
            _require(
                (
                    record["n"] == 0
                    and interval == [None, None]
                )
                or (
                    0.0 <= interval[0] <= record["rate"] <= interval[1] <= 1.0
                ),
                f"P9 {name} Wilson interval mismatch",
            )
    trial_path = _check_hash(
        artifact["trial_level_path"],
        artifact["trial_level_sha256"],
        "P9 trial-level ledger",
    )
    trials = pd.read_csv(trial_path)
    _require(len(trials) == 375, "P9 trial-level ledger is incomplete")
    required = {
        "cc_localized_H1", "cc_localized_L1", "cc_oracle_center",
        "flag_H1", "flag_L1", "coincidence_recovered_H1",
        "coincidence_recovered_L1", "coincidence_recovered",
        "coincidence_oracle_recovered", "threshold_flag_o3b",
        "threshold_tau_cc", "dsd_class_H1", "dsd_class_L1",
        "threshold_dsd_H1_lower", "threshold_dsd_H1",
        "threshold_dsd_L1_lower", "threshold_dsd_L1",
        "taxonomy_representation",
    }
    _require(required.issubset(trials.columns), "P9 trial-level endpoint schema mismatch")
    _require(set(trials["taxonomy_representation"]) == {REP},
             "P9 trial-level representation mismatch")
    h1 = trials["flag_H1"].astype(bool) & trials["coincidence_recovered_H1"].astype(bool)
    l1 = trials["flag_L1"].astype(bool) & trials["coincidence_recovered_L1"].astype(bool)
    _require(np.array_equal((h1 | l1), trials["coincidence_recovered"].astype(bool)),
             "P9 end-to-end coincidence endpoint is not flag AND localization")
    expected_h1 = (
        trials["flag_H1"].astype(bool)
        & (trials["cc_localized_H1"] > trials["threshold_tau_cc"])
    )
    expected_l1 = (
        trials["flag_L1"].astype(bool)
        & (trials["cc_localized_L1"] > trials["threshold_tau_cc"])
    )
    _require(
        np.array_equal(expected_h1, trials["coincidence_recovered_H1"].astype(bool))
        and np.array_equal(expected_l1, trials["coincidence_recovered_L1"].astype(bool)),
        "P9 directional recovery columns do not reproduce the saved statistics",
    )
    for detector in ("H1", "L1"):
        score = trials[f"score_{detector}_native"].to_numpy(float)
        lower = trials[f"threshold_dsd_{detector}_lower"].to_numpy(float)
        upper = trials[f"threshold_dsd_{detector}"].to_numpy(float)
        expected_class = np.where(
            score > upper,
            "ROBUST",
            np.where(score >= lower, "AMBIGUOUS", "BACKGROUND"),
        )
        _require(
            np.array_equal(expected_class, trials[f"dsd_class_{detector}"].to_numpy(str)),
            f"P9 {detector} trial classes do not reproduce C2 thresholds",
        )


def verify_r5() -> None:
    taxonomy, _ = _taxonomy()
    artifact = _json(AGG / f"inter_session_recurrence_o4a_{REP}.json")
    _require(artifact["representation"] == REP and artifact["population"] == "ROBUST",
             "R5 population/representation mismatch")
    for detector in ("H1", "L1"):
        expected = int(
            ((taxonomy.detector == detector) & (taxonomy.dsd_class == "ROBUST")).sum()
        )
        _require(artifact["detectors"][detector]["n_candidates"] == expected,
                 f"R5 {detector} count does not match the taxonomy")


def verify_p11() -> None:
    _taxonomy()
    summary = _json(
        AGG / f"catalog_cross_match_circular_shift_v2_{REP}_o4a.json"
    )
    _require(summary["representation"] == REP,
             "P11 representation mismatch")
    _require(summary["circular_shift_null"]["n_shifts"] == 10_000,
             "P11 null does not contain 10,000 shifts")
    _require(summary["coverage_exact_for_all_detectors"] is False,
             "P11 historical coverage must remain labelled proxy")
    manifest = _json(
        AGG / f"catalog_cross_match_manifest_circular_shift_v2_{REP}_o4a.json"
    )
    for record in manifest["files"]:
        _check_hash(record["path"], record["sha256"], f"P11 {record['role']}")


def verify_pem() -> None:
    taxonomy, _ = _taxonomy()
    pem_dir = AGG / "pem" / REP
    manifest = _json(pem_dir / "selection_manifest.json")
    _require(manifest["taxonomy_representation"] == REP,
             "PEM representation mismatch")
    _require(manifest["n_targets"] == 141, "PEM target count mismatch")
    _require(manifest["n_reused_events"] == 5,
             "PEM validated-reuse count mismatch")
    validation = manifest["reuse_validation"]
    _require(all(validation.values()), "PEM reuse validation is incomplete")
    targets = pd.read_csv(pem_dir / "selected_targets.csv")
    _require(len(targets) == 141, "PEM selected-target ledger is incomplete")
    joined_targets = targets.merge(
        taxonomy[["detector", "gps_start", "dsd_class", "dsd_score"]],
        on=["detector", "gps_start"],
        how="left",
        validate="one_to_one",
        suffixes=("_pem", "_taxonomy"),
    )
    _require(
        joined_targets["dsd_class_taxonomy"].notna().all()
        and np.array_equal(
            joined_targets["dsd_class_pem"].to_numpy(str),
            joined_targets["dsd_class_taxonomy"].to_numpy(str),
        )
        and np.allclose(
            joined_targets["dsd_score_pem"].to_numpy(float),
            joined_targets["dsd_score_taxonomy"].to_numpy(float),
            rtol=0.0,
            atol=0.0,
        ),
        "PEM selected targets do not exactly match the current taxonomy",
    )
    rejoin = manifest.get("taxonomy_rejoin", {})
    _require(
        rejoin.get("mode")
        == "fixed_measured_cohort_detector_gps_exact_rejoin"
        and rejoin.get("n_exact_key_matches") == 141
        and rejoin.get("n_class_transitions") == 8
        and rejoin.get("measurements_recomputed") is False
        and rejoin.get("null_calibrations_recomputed") is False,
        "PEM taxonomy rejoin provenance is incomplete",
    )
    report = pem_dir / "coherence_report.csv"
    verdicts = pem_dir / "pem_family_wise_verdicts.csv"
    _require(report.is_file() and verdicts.is_file(),
             "PEM full coherence/null artifacts are not complete")
    verdict_frame = pd.read_csv(verdicts)
    _require(len(verdict_frame) == 141, "PEM verdict ledger is incomplete")
    _require(
        not verdict_frame.duplicated(["detector", "gps_start"]).any(),
        "PEM verdict keys are not unique",
    )
    target_keys = set(
        zip(
            targets["detector"].astype(str),
            targets["gps_start"].astype(int),
        )
    )
    verdict_keys = set(
        zip(
            verdict_frame["detector"].astype(str),
            verdict_frame["gps_start"].astype(int),
        )
    )
    _require(
        verdict_keys == target_keys,
        "PEM verdict ledger does not exactly match selected targets",
    )
    _require(set(verdict_frame["taxonomy_representation"]) == {REP},
             "PEM verdict representation mismatch")
    _require(
        set(verdict_frame["verdict_tier"])
        <= {"COUPLED", "SUSPECT", "NO_CORRELATION", "UNCALIBRATED"},
        "PEM contains an unknown verdict tier",
    )
    _require(
        "UNCALIBRATED" not in set(verdict_frame["verdict_tier"]),
        "PEM contains uncalibrated events",
    )
    numeric_columns = [
        "m_channels",
        "n_windows",
        "n_surrogate_pairs",
        "threshold_fw",
        "cmax_observed",
        "top_channel_baseline",
        "threshold_zero_lag",
        "dsd_score",
    ]
    for column in numeric_columns:
        values = pd.to_numeric(verdict_frame[column], errors="coerce").to_numpy()
        _require(
            np.isfinite(values).all(),
            f"PEM verdict column {column} contains non-finite values",
        )
    for column in (
        "threshold_fw",
        "cmax_observed",
        "top_channel_baseline",
        "threshold_zero_lag",
    ):
        values = verdict_frame[column].to_numpy(float)
        _require(
            ((0.0 <= values) & (values <= 1.0)).all(),
            f"PEM correlation column {column} lies outside [0, 1]",
        )
    _require(
        (
            verdict_frame["n_surrogate_pairs"].to_numpy(int)
            == (
                verdict_frame["n_windows"].to_numpy(int)
                * (verdict_frame["n_windows"].to_numpy(int) - 1)
            )
        ).all(),
        "PEM ordered-pair count is inconsistent with n_windows",
    )

    expected_tier = np.where(
        verdict_frame["cmax_observed"].to_numpy(float)
        <= verdict_frame["threshold_fw"].to_numpy(float),
        "NO_CORRELATION",
        np.where(
            verdict_frame["cmax_observed"].to_numpy(float)
            > verdict_frame["threshold_zero_lag"].to_numpy(float),
            "COUPLED",
            "SUSPECT",
        ),
    )
    _require(
        np.array_equal(expected_tier, verdict_frame["verdict_tier"].to_numpy()),
        "PEM verdict tiers do not reproduce the two-null decision rule",
    )

    null_paths = sorted(pem_dir.glob("null_calibration_*.json"))
    _require(len(null_paths) == 141, "PEM null calibration count is not 141")
    null_keys = set()
    for path in null_paths:
        calibration = _json(path)
        key = (
            str(calibration["detector"]),
            int(float(calibration["event_gps"])),
        )
        _require(key not in null_keys, f"duplicate PEM null calibration: {key}")
        null_keys.add(key)
        n_windows = int(calibration["n_windows"])
        _require(
            int(calibration["n_surrogate_pairs"])
            == n_windows * (n_windows - 1),
            f"PEM null pair count mismatch for {key}",
        )
        _require(
            int(calibration["m_channels"])
            == len(calibration["channels"]) > 0,
            f"PEM null channel count mismatch for {key}",
        )
        low, high = calibration["threshold_fw_ci95"]
        _require(
            low <= calibration["threshold_fw"] <= high,
            f"PEM threshold lies outside its CI for {key}",
        )
    _require(
        null_keys == target_keys,
        "PEM null calibrations do not exactly match selected targets",
    )

    association = _json(pem_dir / "pem_class_association.json")
    _require(
        association["n_events"] == 141
        and association["n_calibrated"] == 141
        and association["n_uncalibrated"] == 0,
        "PEM association calibration coverage is inconsistent",
    )
    _require(
        association["n_suspect_time_shift_only"]
        == int((verdict_frame["verdict_tier"] == "SUSPECT").sum()),
        "PEM association SUSPECT count does not match the verdict ledger",
    )
    for dsd_class in ("ROBUST", "AMBIGUOUS", "BACKGROUND"):
        subset = verdict_frame[verdict_frame["dsd_class"] == dsd_class]
        endpoint = association["endpoints"]["zero_lag_confirmed"][
            "by_class"
        ][dsd_class]
        _require(
            endpoint["n_calibrated"] == len(subset)
            and endpoint["n_positive"]
            == int((subset["verdict_tier"] == "COUPLED").sum()),
            f"PEM association endpoint mismatch for {dsd_class}",
        )

    provenance = _json(pem_dir / "pem_provenance_manifest.json")
    _require(
        provenance["schema_version"] == 1
        and provenance["taxonomy_representation"] == REP
        and provenance["n_targets"] == 141
        and provenance["n_null_calibrations"] == 141,
        "PEM provenance manifest header is inconsistent",
    )
    records = provenance["files"]
    _require(records, "PEM provenance manifest has no file records")
    for record in records:
        _check_hash(record["path"], record["sha256"], "PEM provenance file")
    output_names = {
        _resolve_artifact_path(record["path"]).name
        for record in records
        if record["role"] == "output"
    }
    _require(
        {
            "pem_family_wise_verdicts.csv",
            "pem_class_association.json",
        }.issubset(output_names)
        and len(
            [name for name in output_names if name.startswith("null_calibration_")]
        )
        == 141,
        "PEM provenance does not cover all final scientific outputs",
    )


STAGES: dict[str, Callable[[], None]] = {
    "p5": verify_p5,
    "p4": verify_p4,
    "p10": verify_p10,
    "multiscale": verify_multiscale,
    "cohesion": verify_cohesion,
    "whitening": verify_whitening,
    "p9": verify_p9,
    "r5": verify_r5,
    "p11": verify_p11,
    "pem": verify_pem,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=[*STAGES, "all"], required=True)
    args = parser.parse_args()
    selected = STAGES if args.stage == "all" else {args.stage: STAGES[args.stage]}
    for name, verifier in selected.items():
        verifier()
        print(f"PASS {name}")


if __name__ == "__main__":
    main()
