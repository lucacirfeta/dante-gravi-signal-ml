"""Run the Domain Shift Defense phase POST-HOC on an existing aggregate.

The full aggregate-report pass costs ~24 h at 10k candidates; when the
native index becomes available afterwards (or is rebuilt), this runner
executes ONLY the DSD phase and regenerates the final markdown report,
without re-running ingestion/dedup/veto.

Reads:  data/production/aggregated/{aggregate_summary.json, master_candidates.csv}
        data/reference/patch_compressed_index_{run}_ex.npz
Writes: updated Master_Taxonomy_{run}.csv (robustness_class, native score),
        updated aggregate_summary.json (domain_shift_defense block),
        regenerated Final_Discovery_Report.md (completeness gate re-evaluated).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.core.utils import setup_logger
from src.pipeline_v2_production.aggregate_report import AggregateReporter

logger = setup_logger(__name__)


def run_dsd(run: str = "O4a", production_dir: str = "data/production"):
    rep = AggregateReporter(production_dir=production_dir, run=run)
    agg = rep.output_dir / "aggregate_summary.json"
    master_csv = rep.output_dir / "master_candidates.csv"
    if not agg.exists() or not master_csv.exists():
        raise FileNotFoundError(
            f"Missing {agg} or {master_csv}: run aggregate-report first.")

    master = pd.read_csv(master_csv)
    logger.info(f"Running standalone DSD on {len(master)} candidates ({run})...")
    dsd_metrics = rep._run_domain_shift_defense(master)

    with open(agg) as f:
        report = json.load(f)
    report["domain_shift_defense"] = dsd_metrics
    with open(agg, "w") as f:
        json.dump(report, f, indent=4, default=str)
    logger.info("aggregate_summary.json updated with DSD metrics.")

    rep._generate_markdown_report(report)
    logger.info("Final_Discovery_Report.md regenerated (completeness gate "
                "re-evaluated with DSD present).")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=str, default="O4a")
    p.add_argument("--production-dir", type=str, default="data/production")
    a = p.parse_args()
    run_dsd(run=a.run, production_dir=a.production_dir)
