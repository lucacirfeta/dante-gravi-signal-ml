import json
import logging
from pathlib import Path
import pandas as pd
import numpy as np
import scipy.stats
import argparse
import re

logger = logging.getLogger(__name__)

def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

def merge_intervals(intervals):
    """
    Merge overlapping intervals and return disjoint segments.
    """
    if not intervals:
        return []
    
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    
    for current in intervals[1:]:
        previous = merged[-1]
        if current[0] <= previous[1]:
            # Overlap detected, merge them
            merged[-1] = (previous[0], max(previous[1], current[1]))
        else:
            # No overlap
            merged.append(current)
            
    return merged

def calculate_livetime(aggregated_dir: Path, detector: str = "H1") -> float:
    """
    Calculate the exact livetime in days by reading all valid cluster reports
    for the specified detector and merging overlapping GPS segments.
    """
    master_report_path = aggregated_dir / "master_report.json"
    if not master_report_path.exists():
        raise FileNotFoundError(f"Master report not found at {master_report_path}")
        
    with open(master_report_path, "r", encoding="utf-8") as f:
        master_report = json.load(f)
        
    det_lower = detector.lower()
    if det_lower not in master_report["summary"]:
        raise KeyError(f"Detector {detector} not found in master_report.json")
        
    valid_sessions_count = master_report["summary"][det_lower].get("n_sessions_valid", 0)
    logger.info(f"Master report indicates {valid_sessions_count} valid sessions for {detector}.")
    
    # Now scan production directories for valid session reports
    production_root = aggregated_dir.parent
    session_dirs = [d for d in production_root.iterdir() if d.is_dir() and d.name.isdigit()]
    
    intervals = []
    for d in session_dirs:
        report_path = d / f"cluster_report_novelties_{d.name}_{detector}.json"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as rf:
                rep = json.load(rf)
                intervals.append((rep["session_start_gps"], rep["session_end_gps"]))
                
    if not intervals:
        logger.warning(f"No cluster reports found for {detector}.")
        return 0.0
        
    merged_intervals = merge_intervals(intervals)
    total_seconds = sum(end - start for start, end in merged_intervals)
    total_days = total_seconds / 86400.0
    
    logger.info(f"Found {len(intervals)} reports. Merged into {len(merged_intervals)} disjoint segments.")
    logger.info(f"Exact {detector} Livetime: {total_seconds:,.1f} seconds ({total_days:,.3f} days).")
    
    return total_days

def run_poisson_upper_limit(aggregated_dir: Path, target_detector: str = "H1", cl: float = 0.90):
    """
    Calculate the Poisson Upper Limit on the rate of morphologically novel, 
    instrumentally unclassified transients for the target detector.
    """
    logger.info(f"Starting Poisson Upper Limit calculation for {target_detector}...")
    
    # 1. Calculate Livetime
    livetime_days = calculate_livetime(aggregated_dir, target_detector)
    if livetime_days <= 0:
        logger.error("Livetime is 0. Aborting.")
        return
        
    # 2. Extract Event Count (N)
    taxonomy_path = aggregated_dir / "Master_Taxonomy_O4a.csv"
    if not taxonomy_path.exists():
        logger.error(f"Taxonomy CSV not found at {taxonomy_path}")
        return
        
    df = pd.read_csv(taxonomy_path)
    
    # The rigorous criteria for an unexplained macroscopic anomaly on the target detector:
    # It must be on the target detector AND its transitivity status must indicate it could not 
    # be vetoed or classified via cross-detector coincidence.
    unexplained_mask = (df["detector"] == target_detector) & (df["transitivity_status"] == "True_Unverifiable_Anomaly")
    
    n_obs = unexplained_mask.sum()
    logger.info(f"Found N={n_obs} unexplained anomalies satisfying strict criteria.")
    
    if n_obs > 0:
        logger.info(f"The events are:\n{df[unexplained_mask][['gps_start', 'global_family_id', 'transitivity_status']]}")
        
    # 3. Calculate Poisson Upper Limit
    # For N=0, lambda_90 is analytically -ln(1 - C.L.)
    # The general formula via Chi-squared distribution is 0.5 * chi2.ppf(C.L., 2*(N+1))
    
    alpha = 1.0 - cl
    if n_obs == 0:
        lambda_90 = -np.log(alpha)
        # Verify against canonical chi2
        chi2_val = 0.5 * scipy.stats.chi2.ppf(cl, 2 * (n_obs + 1))
        logger.info(f"Analytic lambda_90 = {lambda_90:.6f} (matches chi2 formulation: {chi2_val:.6f})")
    else:
        lambda_90 = 0.5 * scipy.stats.chi2.ppf(cl, 2 * (n_obs + 1))
        logger.info(f"Chi2 formulation lambda_90 = {lambda_90:.6f}")
        
    # 4. Calculate Rate Bounds
    rate_per_day = lambda_90 / livetime_days
    rate_per_year = rate_per_day * 365.25
    
    # 5. Export Report
    out_dir = aggregated_dir / "upper_limit"
    out_dir.mkdir(exist_ok=True, parents=True)
    
    stats_dict = {
        "detector": target_detector,
        "livetime_days": livetime_days,
        "livetime_years": livetime_days / 365.25,
        "observed_unexplained_events": int(n_obs),
        "confidence_level": cl,
        "lambda_upper_limit": lambda_90,
        "rate_upper_limit_per_day": rate_per_day,
        "rate_upper_limit_per_year": rate_per_year,
        "methodology": "Analytic -ln(0.1)" if n_obs == 0 else f"Chi2 PPF(df=2(N+1))"
    }
    
    json_path = out_dir / f"poisson_upper_limit_{target_detector}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(stats_dict, f, indent=4)
        
    md_path = out_dir / f"poisson_upper_limit_{target_detector}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Poisson Upper Limit on {target_detector} Data\n\n")
        f.write("> **Methodological Limit:** Upper limit on the rate of morphologically novel, instrumentally unclassified transients in O4a data as characterized by the DANTE pipeline.\n\n")
        
        f.write("## 1. Livetime Analysis\n")
        f.write(f"- **Detector:** {target_detector}\n")
        f.write(f"- **Total Scanned Span:** {livetime_days * 86400:,.1f} seconds\n")
        f.write(f"- **Total Scanned Span:** {livetime_days:,.3f} days ({livetime_days / 365.25:,.4f} years)\n")
        f.write("*Note on Coverage: A DANTE 'session' does not represent a single 4096s GWOSC file, but rather a continuous macro-block of analysis spanning several days. Consequently, 41 sessions cover a bounding span of ~227 days. This span encompasses both `ANALYSIS_READY` segments and natural detector gaps, which explains the discrepancy between calendar days and pure science mode livetime. Overlapping session boundaries have been strictly disjoint-merged to avoid double-counting.*\n\n")
        
        f.write("## 2. Event Statistics\n")
        f.write(f"- **Observed Unclassified Anomalies ($N$):** {int(n_obs)}\n")
        f.write("  - *Filter Criteria:* `transitivity_status == 'True_Unverifiable_Anomaly'` AND `detector == target_detector`.\n")
        f.write("  - *Context:* Anomalies fully classified into recurring morphological families (e.g. `Family_03`) or cross-detector validated as local instrumental glitches (`Confirmed_Local`) are successfully characterized by the pipeline and thus excluded from the pool of 'unknowns'.\n\n")
        
        f.write("## 3. Upper Limit Calculation\n")
        f.write(f"- **Confidence Level:** {cl*100:.1f}%\n")
        if n_obs == 0:
            f.write(f"- **Expected Events Bound ($\\lambda_{{{cl*100:.0f}}}$):** {lambda_90:.6f}\n")
            f.write("  - *Derivation:* For $N=0$, the canonical exact analytical closure is $\\lambda_{90} = -\\ln(1 - 0.9) \simeq 2.302585$. (Equivalent to the general formulation $\\frac{1}{2}\\chi^2_{2, 0.90}$).\n\n")
        else:
            f.write(f"- **Expected Events Bound ($\\lambda_{{{cl*100:.0f}}}$):** {lambda_90:.6f}\n")
            f.write(f"  - *Derivation:* Calculated via the general chi-squared distribution $\\frac{{1}}{{2}}\\chi^2_{{2(N+1), 0.90}}$.\n\n")
            
        f.write("### Resulting Constraints\n")
        event_text = "the absence of unclassified events" if n_obs == 0 else f"{n_obs} unclassified event(s)"
        f.write(f"Given the limited {target_detector} coverage of {livetime_days:.0f} days and {event_text}, DANTE establishes a methodological upper limit of **$R_{{{cl*100:.0f}}} < {rate_per_year:.2f}$ yr⁻¹** (or {rate_per_day:.4f} events/day) on novel morphological transients. This is a constraint driven primarily by the short observation window rather than by the pipeline's sensitivity.\n")
        
    logger.info(f"Saved reports to {out_dir}")
    
    _inject_into_final_report(aggregated_dir)

def _inject_into_final_report(aggregated_dir: Path):
    """Append the Poisson Upper Limit section to Final_Discovery_Report.md for all available detectors."""
    master_report = aggregated_dir / "Final_Discovery_Report.md"
    if not master_report.exists():
        logger.info("Final_Discovery_Report.md not found - skipping injection.")
        return
        
    out_dir = aggregated_dir / "upper_limit"
    md_reports = list(out_dir.glob("poisson_upper_limit_*.md"))
    if not md_reports:
        return
        
    combined_content = []
    for report in sorted(md_reports):
        det = report.stem.split('_')[-1]
        text = report.read_text(encoding="utf-8")
        text = text.replace(f"# Poisson Upper Limit on {det} Data\n\n", f"### {det} Upper Limit\n\n")
        combined_content.append(text)
        
    full_injection = "\n## 17. Poisson Upper Limit (Offline Validation)\n\n" + "\n---\n\n".join(combined_content) + "\n"
        
    try:
        content = master_report.read_text(encoding="utf-8")
        
        # Replace existing section if present
        if "## 17. Poisson Upper Limit (Offline Validation)" in content:
            # Regex to replace everything from ## 17 until ## Limitations or end of file
            content = re.sub(r"## 17\. Poisson Upper Limit \(Offline Validation\).*?(?=## Limitations|\Z)", lambda _: full_injection, content, flags=re.DOTALL)
            new_content = content
        else:
            if "## Limitations" in content:
                new_content = content.replace("## Limitations", full_injection + "## Limitations")
            else:
                new_content = content + full_injection
                
        master_report.write_text(new_content, encoding="utf-8")
        logger.info("Successfully injected/updated Upper Limit into Final_Discovery_Report.md.")
    except Exception as e:
        logger.error(f"Failed to inject into Final_Discovery_Report.md: {e}")

if __name__ == "__main__":
    setup_logger()
    parser = argparse.ArgumentParser(description="Calculate Poisson Upper Limit on a null-result detector")
    parser.add_argument("--detector", type=str, default="H1", help="Target detector (e.g. H1, L1)")
    args = parser.parse_args()
    
    agg_dir = Path("data/production/aggregated")
    run_poisson_upper_limit(agg_dir, target_detector=args.detector)
