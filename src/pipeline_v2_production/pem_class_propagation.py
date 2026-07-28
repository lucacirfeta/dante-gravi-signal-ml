"""Audit the effect of coherent DSD classes on an existing PEM sample.

This module does not pretend that relabelling a legacy-selected sample is a
replacement for resampling PEM targets.  It answers the narrower, reproducible
question: if the already measured events are joined to the coherent
Q-range-matched taxonomy, does the published class-enrichment result survive?

The output is deliberately representation-versioned and preserves both class
labels.  A full PEM rerun must use :mod:`pem_coherence_analysis` to draw targets
from the coherent taxonomy directly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from scipy.stats import fisher_exact

from src.core.index_contract import load_taxonomy_view, sha256_file
from src.core.utils import record_environment, setup_logger

logger = setup_logger(__name__)


def _class_summary(
    frame: pd.DataFrame,
    class_column: str,
    coupled_column: str,
) -> dict:
    counts = {}
    for label in ("ROBUST", "AMBIGUOUS", "BACKGROUND"):
        group = frame[frame[class_column].eq(label)]
        n_total = int(len(group))
        n_coupled = int(group[coupled_column].sum())
        counts[label] = {
            "n_total": n_total,
            "n_coupled": n_coupled,
            "coupled_fraction": (
                n_coupled / n_total if n_total else None
            ),
        }

    robust = counts["ROBUST"]
    background = counts["BACKGROUND"]
    table = [
        [
            robust["n_coupled"],
            robust["n_total"] - robust["n_coupled"],
        ],
        [
            background["n_coupled"],
            background["n_total"] - background["n_coupled"],
        ],
    ]
    odds_ratio, pvalue = fisher_exact(table, alternative="two-sided")
    return {
        "counts": counts,
        "comparison": "ROBUST versus BACKGROUND",
        "contingency_table": table,
        "fisher_alternative": "two-sided",
        "odds_ratio": float(odds_ratio),
        "pvalue": float(pvalue),
    }


def run(
    run_name: str = "O4a",
    aggregated_dir: Path = Path("data/production/aggregated"),
    legacy_verdicts: Path | None = None,
) -> dict:
    """Relabel an existing PEM sample and persist the exact transition audit."""
    aggregated_dir = Path(aggregated_dir)
    taxonomy, contract = load_taxonomy_view(aggregated_dir, run_name)
    if "robustness_class" not in taxonomy.columns:
        raise RuntimeError(
            "The coherent taxonomy does not preserve the historical "
            "robustness_class required for the propagation comparison"
        )

    legacy_verdicts = (
        aggregated_dir / "pem" / "pem_family_wise_verdicts.csv"
        if legacy_verdicts is None
        else Path(legacy_verdicts)
    )
    verdicts = pd.read_csv(legacy_verdicts)
    required = {
        "detector",
        "gps_start",
        "verdict_tier",
    }
    missing = required.difference(verdicts.columns)
    if missing:
        raise RuntimeError(
            f"Legacy PEM verdicts lack columns: {sorted(missing)}"
        )

    taxonomy_columns = [
        "detector",
        "gps_start",
        "robustness_class",
        "dsd_class",
        "dsd_score",
    ]
    joined = verdicts.merge(
        taxonomy[taxonomy_columns],
        on=["detector", "gps_start"],
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    unmatched = joined["_merge"].ne("both")
    if unmatched.any():
        examples = joined.loc[
            unmatched,
            ["detector", "gps_start"],
        ].head(5).to_dict("records")
        raise RuntimeError(
            f"{int(unmatched.sum())} PEM events did not match the coherent "
            f"taxonomy; examples={examples}"
        )
    joined = joined.drop(columns="_merge").rename(
        columns={
            "robustness_class": "legacy_dsd_class",
            "dsd_class": "coherent_dsd_class",
            "dsd_score": "coherent_dsd_score",
        }
    )
    joined["is_coupled"] = joined["verdict_tier"].eq("COUPLED")
    joined["class_changed"] = joined["legacy_dsd_class"].ne(
        joined["coherent_dsd_class"]
    )
    joined["taxonomy_representation"] = contract.representation

    legacy = _class_summary(
        joined,
        "legacy_dsd_class",
        "is_coupled",
    )
    coherent = _class_summary(
        joined,
        "coherent_dsd_class",
        "is_coupled",
    )
    transition = pd.crosstab(
        joined["legacy_dsd_class"],
        joined["coherent_dsd_class"],
        dropna=False,
    )

    output_dir = aggregated_dir / "pem" / contract.representation
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / "pem_existing_sample_reclassified.csv"
    joined.to_csv(rows_path, index=False)
    transition_path = output_dir / "pem_class_transition.csv"
    transition.to_csv(transition_path)

    result = {
        "run": run_name,
        "analysis": "existing measured sample reclassification",
        "interpretation_limit": (
            "This is not a replacement for coherent-taxonomy target "
            "resampling; it only propagates new labels onto the old sample."
        ),
        "taxonomy_path": str(contract.path),
        "taxonomy_sha256": sha256_file(contract.path),
        "taxonomy_representation": contract.representation,
        "taxonomy_audit_path": str(contract.audit_path),
        "legacy_verdicts_path": str(legacy_verdicts),
        "legacy_verdicts_sha256": sha256_file(legacy_verdicts),
        "n_events": int(len(joined)),
        "n_matched": int(len(joined)),
        "n_class_changed": int(joined["class_changed"].sum()),
        "class_changed_fraction": float(joined["class_changed"].mean()),
        "legacy_class_result": legacy,
        "coherent_class_result": coherent,
        "rows_path": str(rows_path),
        "transition_path": str(transition_path),
    }
    result_path = output_dir / "pem_class_propagation.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    record_environment(
        output_dir,
        f"pem_class_propagation_{run_name.lower()}_"
        f"{contract.representation}",
    )
    logger.info("Wrote %s", result_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="O4a")
    parser.add_argument(
        "--aggregated-dir",
        type=Path,
        default=Path("data/production/aggregated"),
    )
    parser.add_argument("--legacy-verdicts", type=Path, default=None)
    args = parser.parse_args()
    run(args.run, args.aggregated_dir, args.legacy_verdicts)


if __name__ == "__main__":
    main()
