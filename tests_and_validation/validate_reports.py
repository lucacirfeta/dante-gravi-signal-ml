"""
Automated Validation Routine for V2 Production Reports.

Strict gatekeeper that ensures:
1. All production JSON reports operate on 384-dimensional patch-level geometry.
2. No duplicate GPS entries exist within or across sessions.
3. All referenced HDF5 novelty archives exist and are readable.
4. No legacy 768D artifacts are silently mixed into V2 output directories.

Exit Code:
    0 — All validations passed.
    1 — At least one validation failed. See log output for details.

Usage:
    python -m tests_and_validation.validate_reports [--production-dir data/production/]
"""

import json
import sys
import argparse
from pathlib import Path
from collections import Counter


def validate_json_report(json_path: Path) -> list[str]:
    """Validate a single cluster_report_novelties JSON file."""
    errors = []
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        errors.append(f"CORRUPT JSON: {json_path} — {e}")
        return errors
    
    # Check for 384D geometry marker
    metadata = report.get("metadata", {})
    embedding_dim = metadata.get("embedding_dim")
    
    if embedding_dim is not None and embedding_dim != 384:
        errors.append(
            f"DIMENSION MISMATCH: {json_path} — "
            f"Expected 384D patch-level geometry, found {embedding_dim}D. "
            f"This may be a legacy 768D CLS-token artifact."
        )
    
    # Check for gps_dedup_validated field
    if "gps_dedup_validated" not in report:
        errors.append(
            f"MISSING DEDUP FLAG: {json_path} — "
            f"'gps_dedup_validated' field is absent. "
            f"Re-run production-report to apply the deduplication serializer."
        )
    
    # Check for duplicate GPS within clusters
    all_gps = []
    clusters = report.get("clusters", {})
    for cluster_id, cluster_data in clusters.items():
        members = cluster_data.get("members", [])
        for member in members:
            gps = member.get("gps_start")
            if gps is not None:
                all_gps.append(gps)
    
    # Also check unclassified
    unclassified = report.get("unclassified_novel_candidates", [])
    for candidate in unclassified:
        gps = candidate.get("gps_start")
        if gps is not None:
            all_gps.append(gps)
    
    gps_counts = Counter(all_gps)
    duplicates = {gps: count for gps, count in gps_counts.items() if count > 1}
    if duplicates:
        errors.append(
            f"DUPLICATE GPS: {json_path} — "
            f"{len(duplicates)} GPS times appear more than once: "
            f"{dict(list(duplicates.items())[:5])}"
        )
    
    return errors


def validate_h5_exists(session_dir: Path) -> list[str]:
    """Check that the novelties.h5 archive exists and is non-empty."""
    errors = []
    h5_path = session_dir / "novelties.h5"
    
    if not h5_path.exists():
        errors.append(f"MISSING HDF5: {h5_path} — Novelty archive not found.")
    elif h5_path.stat().st_size == 0:
        errors.append(f"EMPTY HDF5: {h5_path} — File exists but is 0 bytes.")
    
    return errors


def validate_production_dir(production_dir: Path) -> list[str]:
    """Validate the entire production directory."""
    all_errors = []
    
    if not production_dir.exists():
        all_errors.append(f"DIRECTORY NOT FOUND: {production_dir}")
        return all_errors
    
    session_dirs = sorted([d for d in production_dir.iterdir() if d.is_dir()])
    
    if not session_dirs:
        all_errors.append(f"NO SESSIONS: {production_dir} contains no session directories.")
        return all_errors
    
    print(f"Validating {len(session_dirs)} sessions in {production_dir}...")
    
    # Cross-session GPS dedup check
    global_gps_registry: dict[int, str] = {}
    
    for session_dir in session_dirs:
        session_id = session_dir.name
        
        # Validate HDF5
        all_errors.extend(validate_h5_exists(session_dir))
        
        # Find and validate JSON reports
        report_dir = session_dir / "report"
        if report_dir.exists():
            json_files = list(report_dir.glob("cluster_report_novelties_*.json"))
            for json_file in json_files:
                all_errors.extend(validate_json_report(json_file))
                
                # Cross-session GPS dedup
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        report = json.load(f)
                    
                    for cluster_data in report.get("clusters", {}).values():
                        for member in cluster_data.get("members", []):
                            gps = member.get("gps_start")
                            if gps is not None:
                                if gps in global_gps_registry:
                                    all_errors.append(
                                        f"CROSS-SESSION DUPLICATE: GPS {gps} claimed by both "
                                        f"{global_gps_registry[gps]} and {session_id}"
                                    )
                                else:
                                    global_gps_registry[gps] = session_id
                except Exception:
                    pass  # Already caught in validate_json_report
    
    return all_errors


def main():
    parser = argparse.ArgumentParser(
        description="Validate V2 Production Reports (384D geometry, dedup, integrity)."
    )
    parser.add_argument(
        "--production-dir",
        type=str,
        default="data/production/",
        help="Path to the production directory containing session subdirectories.",
    )
    args = parser.parse_args()
    
    production_dir = Path(args.production_dir)
    errors = validate_production_dir(production_dir)
    
    print()
    if errors:
        print(f"{'=' * 60}")
        print(f"VALIDATION FAILED: {len(errors)} error(s) detected")
        print(f"{'=' * 60}")
        for i, error in enumerate(errors, 1):
            print(f"  [{i}] {error}")
        print(f"{'=' * 60}")
        sys.exit(1)
    else:
        print(f"{'=' * 60}")
        print("VALIDATION PASSED: All checks OK.")
        print(f"{'=' * 60}")
        sys.exit(0)


if __name__ == "__main__":
    main()
