"""Run only the versioned DSD representation-transition audit.

This entry point avoids rerunning unrelated aggregate-report phases. It loads
the frozen master taxonomy, rescales every candidate with an explicit native
index contract, calibrates representation-matched detector backgrounds, and
writes a legacy-to-new transition artifact without overwriting legacy columns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from src.core.index_contract import qrange_tag, validate_native_index
from src.core.utils import load_config, record_environment, setup_logger
from src.pipeline_v2_production.aggregate_report import AggregateReporter

logger = setup_logger(__name__)


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
    args = parser.parse_args()
    run(
        run_name=args.run,
        production_dir=args.production_dir,
        native_index_path=args.native_index,
        candidate_window_offset=args.candidate_window_offset,
    )


if __name__ == "__main__":
    main()
