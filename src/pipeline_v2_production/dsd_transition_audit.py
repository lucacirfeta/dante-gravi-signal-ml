"""Run only the versioned DSD representation-transition audit.

This entry point avoids rerunning unrelated aggregate-report phases. It loads
the frozen master taxonomy, scores every candidate with an explicit native
index contract, calibrates representation-matched detector backgrounds, and
writes a legacy-to-new transition artifact without overwriting legacy columns.

When the candidate scores have already been fully evaluated and independently
verified, ``--verified-score-csv`` can reuse those immutable scores while
recomputing only the bootstrap threshold and the derived class labels. This is
not a generic cache shortcut: the source audit, index hash, representation,
candidate key population, and score finiteness are all required to match.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.index_contract import (
    load_index_contract,
    qrange_tag,
    validate_native_index,
)
from src.core.utils import load_config, record_environment, setup_logger
from src.pipeline_v2_production.aggregate_report import AggregateReporter

logger = setup_logger(__name__)


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_keys(frame: pd.DataFrame) -> list[tuple[float, str]]:
    return list(
        zip(
            frame["gps_start"].astype(float),
            frame["detector"].astype(str),
        )
    )


def _classify_score(score: float, lower: float, upper: float) -> str:
    if score > upper:
        return "ROBUST"
    if score >= lower:
        return "AMBIGUOUS"
    return "BACKGROUND"


def _validate_reusable_candidate_scores(
    taxonomy: pd.DataFrame,
    score_path: str | Path,
    source_audit_path: str | Path,
    *,
    representation: str,
    index_sha256: str,
    candidate_window_offset: float,
) -> tuple[pd.DataFrame, dict]:
    """Validate a complete prior score population before threshold-only reuse."""
    score_path = Path(score_path)
    source_audit_path = Path(source_audit_path)
    if not score_path.exists():
        raise FileNotFoundError(score_path)
    if not source_audit_path.exists():
        raise FileNotFoundError(source_audit_path)

    source_audit = json.loads(source_audit_path.read_text(encoding="utf-8"))
    source_representation = source_audit.get("representation", {})
    if not source_audit.get("experiment_run"):
        raise RuntimeError("Reusable candidate-score audit is not complete")
    if int(source_audit.get("total_failed", -1)) != 0:
        raise RuntimeError("Reusable candidate-score audit contains failures")
    if source_representation.get("variant") != representation:
        raise RuntimeError("Reusable candidate-score representation mismatch")
    if source_representation.get("index_sha256") != index_sha256:
        raise RuntimeError("Reusable candidate-score index hash mismatch")
    if not source_representation.get("coherent"):
        raise RuntimeError("Reusable candidate scores are not representation-coherent")
    if (
        float(
            source_representation.get(
                "catalog_gps_to_analysis_window_offset_s",
                np.nan,
            )
        )
        != float(candidate_window_offset)
    ):
        raise RuntimeError("Reusable candidate-score window offset mismatch")

    scores = pd.read_csv(score_path)
    required = {
        "candidate_id",
        "gps_start",
        "detector",
        "score",
        "variant",
    }
    missing = required.difference(scores.columns)
    if missing:
        raise RuntimeError(
            f"Reusable candidate scores lack columns: {sorted(missing)}"
        )
    if set(scores["variant"].astype(str)) != {representation}:
        raise RuntimeError("Reusable score rows contain another representation")
    numeric_scores = pd.to_numeric(scores["score"], errors="coerce")
    if not np.isfinite(numeric_scores.to_numpy(dtype=float)).all():
        raise RuntimeError("Reusable candidate scores contain non-finite values")
    scores = scores.copy()
    scores["score"] = numeric_scores.astype(float)

    taxonomy_keys = _candidate_keys(taxonomy)
    score_keys = _candidate_keys(scores)
    if len(set(taxonomy_keys)) != len(taxonomy_keys):
        raise RuntimeError("Master taxonomy candidate keys are not unique")
    if len(set(score_keys)) != len(score_keys):
        raise RuntimeError("Reusable candidate-score keys are not unique")
    if set(taxonomy_keys) != set(score_keys):
        missing_keys = set(taxonomy_keys).difference(score_keys)
        extra_keys = set(score_keys).difference(taxonomy_keys)
        raise RuntimeError(
            "Reusable candidate-score population mismatch: "
            f"missing={len(missing_keys)}, extra={len(extra_keys)}"
        )
    if int(source_audit.get("total_evaluated", -1)) != len(scores):
        raise RuntimeError(
            "Reusable score row count disagrees with its source audit"
        )
    recorded_score_name = Path(
        str(source_audit.get("long_form_scores", "")).replace("\\", "/")
    ).name
    if recorded_score_name != score_path.name:
        raise RuntimeError(
            "Reusable score filename disagrees with its source audit"
        )
    recorded_taxonomy_name = Path(
        str(source_audit.get("taxonomy_artifact", "")).replace("\\", "/")
    ).name
    source_taxonomy_path = score_path.parent / recorded_taxonomy_name
    if not recorded_taxonomy_name or not source_taxonomy_path.exists():
        raise RuntimeError(
            "Reusable score source taxonomy is missing beside the archive"
        )
    source_taxonomy = pd.read_csv(source_taxonomy_path)
    source_score_column = (
        f"native_score_{representation.replace('-', '_')}"
    )
    if source_score_column not in source_taxonomy.columns:
        raise RuntimeError(
            "Reusable score source taxonomy lacks its native-score column"
        )
    source_taxonomy_scores = {
        key: float(value)
        for key, value in zip(
            _candidate_keys(source_taxonomy),
            source_taxonomy[source_score_column],
        )
    }
    long_form_scores = {
        key: float(value)
        for key, value in zip(score_keys, scores["score"])
    }
    if source_taxonomy_scores.keys() != long_form_scores.keys() or any(
        source_taxonomy_scores[key] != long_form_scores[key]
        for key in source_taxonomy_scores
    ):
        raise RuntimeError(
            "Reusable long-form scores disagree with the source taxonomy"
        )

    provenance = {
        "mode": "verified_complete_candidate_score_reclassification",
        "score_path": str(score_path),
        "score_sha256": _file_sha256(score_path),
        "source_audit_path": str(source_audit_path),
        "source_audit_sha256": _file_sha256(source_audit_path),
        "source_taxonomy_path": str(source_taxonomy_path),
        "source_taxonomy_sha256": _file_sha256(source_taxonomy_path),
        "scores_match_source_taxonomy_exactly": True,
        "n_scores": int(len(scores)),
        "exact_candidate_key_match": True,
        "unique_candidate_keys": True,
        "all_scores_finite": True,
        "representation": representation,
        "index_sha256": index_sha256,
        "candidate_window_offset_s": float(candidate_window_offset),
        "scientific_scope": (
            "Candidate native scores are unchanged; only the production-size "
            "bootstrap thresholds and deterministic class labels are recomputed."
        ),
    }
    return scores, provenance


def _validate_builder_provenance(
    index_path: str | Path,
    *,
    run_name: str,
    qrange: tuple[int, int],
) -> dict:
    index_path = Path(index_path)
    context = f"build_native_index_{run_name.lower()}_{qrange_tag(qrange)}"
    environment_path = index_path.parent / f"environment_{context}.json"
    if not environment_path.exists():
        raise RuntimeError(
            f"Builder environment record missing: {environment_path}"
        )
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    if environment.get("context") != context:
        raise RuntimeError("Builder environment context mismatch")
    if index_path.name not in str(environment.get("note", "")):
        raise RuntimeError(
            "Builder environment note does not identify the index artifact"
        )

    snapshot_path = None
    snapshot_sha256 = None
    if environment.get("git_dirty"):
        snapshot_value = environment.get("dirty_source_snapshot")
        snapshot_sha256 = environment.get("dirty_source_snapshot_sha256")
        if not snapshot_value or not snapshot_sha256:
            raise RuntimeError(
                "Dirty builder run lacks a complete source snapshot"
            )
        snapshot_path = Path(snapshot_value)
        if not snapshot_path.exists():
            raise RuntimeError(
                f"Dirty source snapshot is missing: {snapshot_path}"
            )
        actual = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        if actual != snapshot_sha256:
            raise RuntimeError(
                "Dirty source snapshot SHA256 does not match environment record"
            )

    return {
        "environment_path": str(environment_path),
        "git_commit": environment.get("git_commit"),
        "git_dirty": environment.get("git_dirty"),
        "python": environment.get("python"),
        "gwpy": environment.get("packages", {}).get("gwpy"),
        "torch": environment.get("torch", {}).get("version"),
        "dirty_source_snapshot": (
            str(snapshot_path) if snapshot_path is not None else None
        ),
        "dirty_source_snapshot_sha256": snapshot_sha256,
    }


def run(
    *,
    run_name: str = "O4a",
    production_dir: str | Path = "data/production",
    native_index_path: str | Path,
    candidate_window_offset: float = 4.0,
) -> dict:
    production_dir = Path(production_dir)
    aggregated = production_dir / "aggregated"
    taxonomy_path = aggregated / f"Master_Taxonomy_{run_name}.csv"
    if not taxonomy_path.exists():
        taxonomy_path = aggregated / f"Master_Taxonomy_{run_name.lower()}.csv"
    if not taxonomy_path.exists():
        raise FileNotFoundError(f"Master taxonomy not found: {taxonomy_path}")

    taxonomy = pd.read_csv(taxonomy_path)
    required = {"gps_start", "detector"}
    missing = required.difference(taxonomy.columns)
    if missing:
        raise RuntimeError(
            f"Master taxonomy lacks required columns: {sorted(missing)}"
        )

    expected_qrange = tuple(
        int(value) for value in load_config()["preprocessing"]["qrange"]
    )
    index_validation = validate_native_index(
        native_index_path,
        expected_qrange=expected_qrange,
        expected_k=1216,
        expected_detector="both",
    )
    builder_provenance = _validate_builder_provenance(
        native_index_path,
        run_name=run_name,
        qrange=expected_qrange,
    )
    representation = (
        f"idx{qrange_tag(index_validation['qrange'])}_"
        f"query{qrange_tag(expected_qrange)}"
    )
    protected_outputs = [
        aggregated
        / f"Master_Taxonomy_{run_name}_{representation}.csv",
        aggregated / f"dsd_scores_{run_name.lower()}_{representation}.csv",
        aggregated / f"dsd_thresholds_{run_name.lower()}_{representation}.json",
        aggregated
        / f"dsd_transition_audit_{run_name.lower()}_{representation}.json",
    ]
    existing = [path for path in protected_outputs if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite DSD transition artifacts: "
            + ", ".join(str(path) for path in existing)
        )

    reporter = AggregateReporter(
        production_dir=production_dir,
        run=run_name,
        native_index_path=native_index_path,
        allow_legacy_cross_representation=False,
        candidate_window_offset=candidate_window_offset,
    )
    metrics = reporter._run_domain_shift_defense(taxonomy)
    if not metrics.get("experiment_run"):
        raise RuntimeError("DSD transition audit did not complete")
    metrics["index_validation"] = index_validation
    metrics["builder_provenance"] = builder_provenance

    representation = metrics["representation"]["variant"]
    destination = aggregated / (
        f"dsd_transition_audit_{run_name.lower()}_{representation}.json"
    )
    destination.write_text(
        json.dumps(metrics, indent=2),
        encoding="utf-8",
    )
    record_environment(
        aggregated,
        f"dsd_transition_{run_name.lower()}_{representation}",
        note=(
            f"native_index={native_index_path}; "
            f"candidate_window_offset={candidate_window_offset}"
        ),
    )
    logger.info("Wrote %s", destination)
    return metrics


def reclassify_verified_scores(
    *,
    run_name: str = "O4a",
    production_dir: str | Path = "data/production",
    native_index_path: str | Path,
    verified_score_csv: str | Path,
    verified_score_audit: str | Path,
    candidate_window_offset: float = 4.0,
) -> dict:
    """Recompute thresholds/classes from an exactly verified score population.

    Native candidate scoring is deterministic and independent of the bootstrap
    replicate count. Reusing the complete score population avoids repeating
    strain retrieval, whitening, Q-transform rendering and encoder inference,
    while every threshold-derived label is regenerated from the current
    production bootstrap implementation.
    """
    production_dir = Path(production_dir)
    aggregated = production_dir / "aggregated"
    taxonomy_path = aggregated / f"Master_Taxonomy_{run_name}.csv"
    if not taxonomy_path.exists():
        taxonomy_path = aggregated / f"Master_Taxonomy_{run_name.lower()}.csv"
    if not taxonomy_path.exists():
        raise FileNotFoundError(f"Master taxonomy not found: {taxonomy_path}")

    taxonomy = pd.read_csv(taxonomy_path)
    required = {"gps_start", "detector"}
    missing = required.difference(taxonomy.columns)
    if missing:
        raise RuntimeError(
            f"Master taxonomy lacks required columns: {sorted(missing)}"
        )

    expected_qrange = tuple(
        int(value) for value in load_config()["preprocessing"]["qrange"]
    )
    index_validation = validate_native_index(
        native_index_path,
        expected_qrange=expected_qrange,
        expected_k=1216,
        expected_detector="both",
    )
    index_contract = load_index_contract(native_index_path)
    builder_provenance = _validate_builder_provenance(
        native_index_path,
        run_name=run_name,
        qrange=expected_qrange,
    )
    representation = (
        f"idx{qrange_tag(index_validation['qrange'])}_"
        f"query{qrange_tag(expected_qrange)}"
    )
    variant_column = representation.replace("-", "_")
    class_column = f"robustness_class_{variant_column}"
    score_column = f"native_score_{variant_column}"

    taxonomy_destination = aggregated / (
        f"Master_Taxonomy_{run_name}_{representation}.csv"
    )
    score_destination = aggregated / (
        f"dsd_scores_{run_name.lower()}_{representation}.csv"
    )
    threshold_destination = aggregated / (
        f"dsd_thresholds_{run_name.lower()}_{representation}.json"
    )
    audit_destination = aggregated / (
        f"dsd_transition_audit_{run_name.lower()}_{representation}.json"
    )
    protected_outputs = [
        taxonomy_destination,
        score_destination,
        threshold_destination,
        audit_destination,
    ]
    existing = [path for path in protected_outputs if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite DSD transition artifacts: "
            + ", ".join(str(path) for path in existing)
        )

    scores, score_provenance = _validate_reusable_candidate_scores(
        taxonomy,
        verified_score_csv,
        verified_score_audit,
        representation=representation,
        index_sha256=index_contract.sha256,
        candidate_window_offset=candidate_window_offset,
    )

    reporter = AggregateReporter(
        production_dir=production_dir,
        run=run_name,
        native_index_path=native_index_path,
        allow_legacy_cross_representation=False,
        candidate_window_offset=candidate_window_offset,
    )
    threshold_dict = reporter._calibrate_native_threshold(
        None,
        index_contract=index_contract,
        query_qrange=expected_qrange,
        candidate_frame=taxonomy,
        detectors=tuple(
            detector
            for detector in ("H1", "L1")
            if detector in set(taxonomy["detector"].astype(str))
        ),
    )
    expected_detectors = set(taxonomy["detector"].astype(str))
    if not expected_detectors.issubset(threshold_dict):
        raise RuntimeError(
            "Threshold calibration did not cover every taxonomy detector"
        )

    score_lookup = {
        (float(row.gps_start), str(row.detector)): float(row.score)
        for row in scores.itertuples(index=False)
    }
    output_taxonomy = taxonomy.copy()
    output_taxonomy[score_column] = [
        score_lookup[key] for key in _candidate_keys(output_taxonomy)
    ]
    output_taxonomy[class_column] = [
        _classify_score(
            float(score),
            float(threshold_dict[str(detector)]["ci_lower"]),
            float(threshold_dict[str(detector)]["ci_upper"]),
        )
        for score, detector in zip(
            output_taxonomy[score_column],
            output_taxonomy["detector"],
        )
    ]
    if "robustness_class" not in output_taxonomy.columns:
        output_taxonomy["robustness_class"] = output_taxonomy[class_column]
    if "native_o4a_score" not in output_taxonomy.columns:
        output_taxonomy["native_o4a_score"] = output_taxonomy[score_column]

    score_rows = pd.DataFrame(
        {
            "candidate_id": [
                f"{float(gps)}_{detector}"
                for gps, detector in _candidate_keys(output_taxonomy)
            ],
            "gps_start": output_taxonomy["gps_start"].astype(float),
            "detector": output_taxonomy["detector"].astype(str),
            "legacy_class": output_taxonomy.get(
                "robustness_class",
                pd.Series([None] * len(output_taxonomy)),
            ),
            "score": output_taxonomy[score_column].astype(float),
            "class": output_taxonomy[class_column].astype(str),
            "variant": representation,
        }
    )

    per_detector = {}
    for detector in sorted(expected_detectors):
        subset = score_rows[score_rows["detector"] == detector]
        counts = subset["class"].value_counts()
        per_detector[detector] = {
            "robust": int(counts.get("ROBUST", 0)),
            "ambiguous": int(counts.get("AMBIGUOUS", 0)),
            "background": int(counts.get("BACKGROUND", 0)),
            "total": int(len(subset)),
        }
    transition = pd.crosstab(
        score_rows["legacy_class"],
        score_rows["class"],
    )
    transition_record = {
        str(old): {str(new): int(value) for new, value in row.items()}
        for old, row in transition.to_dict(orient="index").items()
    }
    robust_total = sum(item["robust"] for item in per_detector.values())
    ambiguous_total = sum(item["ambiguous"] for item in per_detector.values())
    background_total = sum(item["background"] for item in per_detector.values())
    total = len(score_rows)

    representation_record = {
        "mode": "coherent",
        "coherent": True,
        "variant": representation,
        "index_path": str(native_index_path),
        "index_sha256": index_contract.sha256,
        "index_qrange": list(index_contract.qrange),
        "query_qrange": list(expected_qrange),
        "index_qrange_declared": index_contract.declared,
        "legacy_qrange_inferred": index_contract.legacy_inferred,
        "catalog_gps_to_analysis_window_offset_s": float(
            candidate_window_offset
        ),
    }
    threshold_record = {
        "run": run_name,
        "representation": representation_record,
        "thresholds": threshold_dict,
    }
    metrics = {
        "experiment_run": True,
        "execution_mode": "verified_candidate_score_reclassification",
        "survival_rate": float(robust_total / total),
        "family_cohesion": {},
        "family_cohesion_status": (
            "NOT_RECOMPUTED: per-candidate MIL vectors are not stored in the "
            "score artifact; use the dedicated background-cohesion experiment."
        ),
        **per_detector,
        "representation": representation_record,
        "taxonomy_artifact": str(taxonomy_destination),
        "long_form_scores": str(score_destination),
        "transition_from_existing_class": transition_record,
        "total_requested": int(total),
        "total_evaluated": int(total),
        "total_failed": 0,
        "survived_native_threshold": int(robust_total),
        "robust_count": int(robust_total),
        "ambiguous_count": int(ambiguous_total),
        "background_count": int(background_total),
        "threshold_artifact": str(threshold_destination),
        "candidate_score_reuse": score_provenance,
        "index_validation": index_validation,
        "builder_provenance": builder_provenance,
    }

    temporary_outputs = {
        taxonomy_destination: taxonomy_destination.with_suffix(".csv.tmp"),
        score_destination: score_destination.with_suffix(".csv.tmp"),
        threshold_destination: threshold_destination.with_suffix(".json.tmp"),
        audit_destination: audit_destination.with_suffix(".json.tmp"),
    }
    output_taxonomy.to_csv(
        temporary_outputs[taxonomy_destination],
        index=False,
    )
    score_rows.to_csv(temporary_outputs[score_destination], index=False)
    temporary_outputs[threshold_destination].write_text(
        json.dumps(threshold_record, indent=2),
        encoding="utf-8",
    )
    temporary_outputs[audit_destination].write_text(
        json.dumps(metrics, indent=2),
        encoding="utf-8",
    )
    for destination, temporary in temporary_outputs.items():
        temporary.replace(destination)

    record_environment(
        aggregated,
        f"dsd_transition_{run_name.lower()}_{representation}",
        note=(
            f"native_index={native_index_path}; "
            f"candidate_window_offset={candidate_window_offset}; "
            f"verified_scores={verified_score_csv}; "
            f"verified_score_audit={verified_score_audit}"
        ),
    )
    logger.info("Wrote %s", audit_destination)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="O4a")
    parser.add_argument("--production-dir", type=Path, default=Path("data/production"))
    parser.add_argument("--native-index", type=Path, required=True)
    parser.add_argument(
        "--candidate-window-offset",
        type=float,
        default=4.0,
        help="Use 4 for the historical O4a catalogue and 0 after label fix.",
    )
    parser.add_argument(
        "--verified-score-csv",
        type=Path,
        help=(
            "Complete prior candidate scores to reuse after source-audit "
            "validation. Requires --verified-score-audit."
        ),
    )
    parser.add_argument(
        "--verified-score-audit",
        type=Path,
        help="Audit JSON certifying --verified-score-csv.",
    )
    args = parser.parse_args()
    if (args.verified_score_csv is None) != (
        args.verified_score_audit is None
    ):
        parser.error(
            "--verified-score-csv and --verified-score-audit are required "
            "together"
        )
    if args.verified_score_csv is not None:
        reclassify_verified_scores(
            run_name=args.run,
            production_dir=args.production_dir,
            native_index_path=args.native_index,
            verified_score_csv=args.verified_score_csv,
            verified_score_audit=args.verified_score_audit,
            candidate_window_offset=args.candidate_window_offset,
        )
    else:
        run(
            run_name=args.run,
            production_dir=args.production_dir,
            native_index_path=args.native_index,
            candidate_window_offset=args.candidate_window_offset,
        )


if __name__ == "__main__":
    main()
