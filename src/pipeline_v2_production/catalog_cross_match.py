"""Catalogue-window overlap test with an empirical circular-shift null.

This is an astrophysical *control*, not a recovery-efficiency measurement.
Coverage, candidate-window overlap, and confirmed recovery are distinct:

* coverage comes from the exact successfully-scored window ledger when
  available; historical proxies are labelled explicitly;
* overlap means that a catalogue GPS falls inside a DANTE candidate window;
* no event is called recovered without an excess above the circular-shift null.

The null applies one common random circular offset to the complete catalogue,
preserving the event-event temporal structure while breaking alignment with
DANTE candidate windows. Per-shift counts are saved long-form.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

import numpy as np
import pandas as pd

from src.core.index_contract import load_taxonomy_view
from src.core.utils import load_config, record_environment, setup_logger
from src.pipeline_v2_production.processed_window_ledger import (
    merge_intervals,
    resolve_coverage,
)

logger = setup_logger(__name__)

PROD = Path("data/production")
AGG = PROD / "aggregated"
WINDOW_OFFSET = 4.0
WINDOW_LENGTH = 32.0
CATALOGS = ("GWTC-4.0", "GWTC-4.1")
O4A_LO, O4A_HI = 1368975618, 1389456018
ANALYSIS_VERSION = "circular_shift_v2"


def _fetch_events(cache: Path, refresh: bool) -> pd.DataFrame:
    """Confirmed O4a events with GPS, SNR, distance, and source masses."""
    if cache.exists() and not refresh:
        logger.info("loading cached catalogue from %s", cache.name)
        return pd.read_json(cache)

    merged: dict[str, dict] = {}
    for catalog in CATALOGS:
        url = f"https://gwosc.org/eventapi/json/{catalog}/"
        logger.info("fetching %s from GWOSC", catalog)
        with urllib.request.urlopen(url, timeout=120) as response:
            events = json.load(response)["events"]
        for name, values in events.items():
            gps = values.get("GPS")
            if not gps or not (O4A_LO <= gps <= O4A_HI):
                continue
            base = name.split("-")[0]
            merged[base] = {
                "name": base,
                "gps": float(gps),
                "catalog": catalog,
                "snr": values.get("network_matched_filter_snr"),
                "dl": values.get("luminosity_distance"),
                "m1": values.get("mass_1_source"),
                "m2": values.get("mass_2_source"),
            }
    frame = pd.DataFrame(list(merged.values()))
    for column in ("snr", "dl", "m1", "m2"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.to_json(cache)
    logger.info("cached %d O4a events to %s", len(frame), cache.name)
    return frame


def _run_bounds(run_name: str) -> tuple[float, float]:
    if run_name.lower() == "o4a":
        return float(O4A_LO), float(O4A_HI)
    config = load_config()
    entry = config.get("run_config", {}).get(run_name, {})
    if "gps_start" not in entry or "gps_end" not in entry:
        raise ValueError(
            f"Run {run_name!r} needs explicit gps_start/gps_end in config.yaml"
        )
    return float(entry["gps_start"]), float(entry["gps_end"])


def _intervals(record: dict) -> list[tuple[float, float]]:
    return [(float(start), float(end)) for start, end in record["intervals"]]


def _contains_many(
    times: np.ndarray,
    intervals: list[tuple[float, float]],
) -> np.ndarray:
    """Vectorized membership in sorted disjoint intervals."""
    values = np.asarray(times, dtype=np.float64)
    if not intervals:
        return np.zeros(values.shape, dtype=bool)
    merged = merge_intervals(intervals)
    starts = np.asarray([start for start, _ in merged], dtype=np.float64)
    ends = np.asarray([end for _, end in merged], dtype=np.float64)
    indices = np.searchsorted(starts, values, side="right") - 1
    valid = indices >= 0
    result = np.zeros(values.shape, dtype=bool)
    result[valid] = values[valid] <= ends[indices[valid]]
    return result


def _candidate_intervals(detector_taxonomy: pd.DataFrame) -> list[tuple[float, float]]:
    starts = detector_taxonomy.gps_start.to_numpy(dtype=np.float64) + WINDOW_OFFSET
    return merge_intervals(
        [(start, start + WINDOW_LENGTH) for start in starts]
    )


def _evaluate(
    times: np.ndarray,
    coverage: dict[str, list[tuple[float, float]]],
    candidates: dict[str, list[tuple[float, float]]],
) -> dict:
    covered = {
        detector: _contains_many(times, coverage[detector])
        for detector in ("H1", "L1")
    }
    flagged = {
        detector: (
            _contains_many(times, candidates[detector]) & covered[detector]
        )
        for detector in ("H1", "L1")
    }
    covered_any = covered["H1"] | covered["L1"]
    covered_both = covered["H1"] & covered["L1"]
    flagged_any = flagged["H1"] | flagged["L1"]
    flagged_both = flagged["H1"] & flagged["L1"]
    return {
        "covered": covered,
        "flagged": flagged,
        "covered_any": covered_any,
        "covered_both": covered_both,
        "flagged_any": flagged_any,
        "flagged_both": flagged_both,
        "counts": {
            "covered_any": int(covered_any.sum()),
            "covered_both": int(covered_both.sum()),
            "overlap_any": int(flagged_any.sum()),
            "overlap_both": int(flagged_both.sum()),
        },
    }


def _circular_shift_null(
    event_times: np.ndarray,
    coverage: dict[str, list[tuple[float, float]]],
    candidates: dict[str, list[tuple[float, float]]],
    *,
    run_bounds: tuple[float, float],
    observed_any: int,
    observed_both: int,
    n_shifts: int,
    seed: int,
    minimum_shift_s: float,
) -> tuple[pd.DataFrame, dict]:
    if n_shifts < 1:
        raise ValueError("n_shifts must be at least 1")
    run_start, run_end = run_bounds
    duration = run_end - run_start
    if not 0 <= minimum_shift_s < duration / 2:
        raise ValueError("minimum_shift_s must be in [0, run_duration/2)")

    rng = np.random.default_rng(seed)
    offsets = rng.uniform(minimum_shift_s, duration - minimum_shift_s, n_shifts)
    rows = []
    for index, offset in enumerate(offsets):
        shifted = run_start + np.mod(event_times - run_start + offset, duration)
        evaluated = _evaluate(shifted, coverage, candidates)
        counts = evaluated["counts"]
        rows.append(
            {
                "shift_id": index,
                "offset_s": float(offset),
                "covered_any": counts["covered_any"],
                "covered_both": counts["covered_both"],
                "overlap_any": counts["overlap_any"],
                "overlap_both": counts["overlap_both"],
            }
        )
    frame = pd.DataFrame(rows)

    def summarize(column: str, observed: int) -> dict:
        values = frame[column].to_numpy(dtype=np.int64)
        return {
            "observed": int(observed),
            "null_mean": float(values.mean()),
            "null_std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
            "null_median": float(np.median(values)),
            "null_interval_95": [
                float(np.quantile(values, 0.025)),
                float(np.quantile(values, 0.975)),
            ],
            "empirical_p_ge_observed": float(
                (1 + np.count_nonzero(values >= observed)) / (len(values) + 1)
            ),
        }

    summary = {
        "method": "common-offset circular shifts of complete catalogue",
        "n_shifts": int(n_shifts),
        "seed": int(seed),
        "minimum_shift_s": float(minimum_shift_s),
        "run_bounds_gps": [run_start, run_end],
        "overlap_any": summarize("overlap_any", observed_any),
        "overlap_both": summarize("overlap_both", observed_both),
    }
    return frame, summary


def _flag_detail(
    event_time: float,
    detector_taxonomy: pd.DataFrame,
) -> tuple[str, float] | None:
    gps = detector_taxonomy.gps_start.to_numpy(dtype=np.float64)
    mask = (
        (gps + WINDOW_OFFSET <= event_time)
        & (event_time <= gps + WINDOW_OFFSET + WINDOW_LENGTH)
    )
    if not mask.any():
        return None
    row = detector_taxonomy[mask].iloc[0]
    return str(row.dsd_class), float(row.dsd_score)


def _json_number(value):
    try:
        return (
            None
            if value is None
            or (isinstance(value, float) and np.isnan(value))
            else float(value)
        )
    except (TypeError, ValueError):
        return value


def _write_manifest(
    destination: Path,
    *,
    run_name: str,
    analysis_tag: str = ANALYSIS_VERSION,
    inputs: list[Path],
    outputs: list[Path],
) -> Path:
    """Write a non-circular SHA256 manifest for P11 inputs and outputs."""
    records = []
    for role, paths in (("input", inputs), ("output", outputs)):
        for path in paths:
            path = Path(path)
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(
                    f"Cannot manifest missing {role} artifact: {path}"
                )
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            records.append(
                {
                    "role": role,
                    "path": str(path),
                    "bytes": int(path.stat().st_size),
                    "sha256": digest,
                }
            )
    manifest = destination.with_name(
        f"catalog_cross_match_manifest_{analysis_tag}_"
        f"{run_name.lower()}.json"
    )
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run": run_name,
                "files": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest


def run(
    run_name: str = "O4a",
    refresh: bool = False,
    *,
    coverage_source: str = "auto",
    n_shifts: int = 10000,
    seed: int = 42,
    minimum_shift_s: float = 86400.0,
    production_dir: str | Path = PROD,
    aggregated_dir: str | Path | None = None,
) -> dict:
    production_dir = Path(production_dir)
    aggregated_dir = (
        Path(aggregated_dir)
        if aggregated_dir is not None
        else production_dir / "aggregated"
    )
    aggregated_dir.mkdir(parents=True, exist_ok=True)

    events = _fetch_events(
        aggregated_dir / f"gwtc_{run_name.lower()}_events.json",
        refresh,
    )
    event_times = events.gps.to_numpy(dtype=np.float64)
    logger.info("%d confirmed events in the %s window", len(events), run_name)

    coverage_records = {
        detector: resolve_coverage(
            production_dir,
            detector,
            source=coverage_source,
        )
        for detector in ("H1", "L1")
    }
    coverage = {
        detector: _intervals(coverage_records[detector])
        for detector in ("H1", "L1")
    }
    taxonomy, taxonomy_contract = load_taxonomy_view(
        aggregated_dir,
        run_name,
    )
    analysis_tag = (
        f"{ANALYSIS_VERSION}_{taxonomy_contract.representation}"
    )
    coverage_artifact = aggregated_dir / (
        f"processed_coverage_{analysis_tag}_{run_name.lower()}.json"
    )
    coverage_artifact.write_text(
        json.dumps(
            {
                "run": run_name,
                "requested_source": coverage_source,
                "detectors": coverage_records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    taxonomy["gps_start"] = taxonomy.gps_start.astype(float)
    detector_taxonomy = {
        detector: taxonomy[taxonomy.detector == detector]
        for detector in ("H1", "L1")
    }
    candidates = {
        detector: _candidate_intervals(detector_taxonomy[detector])
        for detector in ("H1", "L1")
    }

    observed = _evaluate(event_times, coverage, candidates)
    counts = observed["counts"]
    null_frame, null_summary = _circular_shift_null(
        event_times,
        coverage,
        candidates,
        run_bounds=_run_bounds(run_name),
        observed_any=counts["overlap_any"],
        observed_both=counts["overlap_both"],
        n_shifts=n_shifts,
        seed=seed,
        minimum_shift_s=minimum_shift_s,
    )
    null_path = aggregated_dir / (
        f"catalog_cross_match_null_{analysis_tag}_"
        f"{run_name.lower()}.csv"
    )
    null_frame.to_csv(null_path, index=False)
    null_summary["long_form_path"] = str(null_path)

    event_rows = []
    flagged_events = []
    for index, event in events.reset_index(drop=True).iterrows():
        details = {
            detector: _flag_detail(
                float(event.gps),
                detector_taxonomy[detector],
            )
            for detector in ("H1", "L1")
        }
        row = {
            "name": event["name"],
            "gps": float(event.gps),
            "snr": _json_number(event.snr),
            "dl_mpc": _json_number(event.dl),
            "cov_H1": bool(observed["covered"]["H1"][index]),
            "cov_L1": bool(observed["covered"]["L1"][index]),
            "overlap_H1": bool(observed["flagged"]["H1"][index]),
            "overlap_L1": bool(observed["flagged"]["L1"][index]),
            "class_H1": details["H1"][0] if details["H1"] else None,
            "score_H1": details["H1"][1] if details["H1"] else None,
            "class_L1": details["L1"][0] if details["L1"] else None,
            "score_L1": details["L1"][1] if details["L1"] else None,
        }
        event_rows.append(row)
        if row["overlap_H1"] or row["overlap_L1"]:
            flagged_events.append(row)

    event_ledger_path = aggregated_dir / (
        f"catalog_cross_match_events_{analysis_tag}_"
        f"{run_name.lower()}.csv"
    )
    pd.DataFrame(event_rows).to_csv(event_ledger_path, index=False)

    exact_coverage = all(
        record["quality"] == "exact_successfully_scored_windows"
        for record in coverage_records.values()
    )
    p_any = null_summary["overlap_any"]["empirical_p_ge_observed"]
    conclusion = (
        "No excess of catalogue-window overlaps above the circular-shift null "
        f"is resolved (empirical p={p_any:.4g}). This is not a recall estimate."
    )
    if not exact_coverage:
        conclusion += (
            " Historical coverage is proxy-level, so coverage fractions remain "
            "non-paper-grade until an exact processed-window ledger is available."
        )

    out = {
        "run": run_name,
        "representation": taxonomy_contract.representation,
        "taxonomy_path": str(taxonomy_contract.path),
        "catalogs": list(CATALOGS),
        "n_events_in_window": int(len(events)),
        "coverage": {
            detector: {
                key: value
                for key, value in coverage_records[detector].items()
                if key not in {"intervals", "files"}
            }
            for detector in ("H1", "L1")
        },
        "coverage_exact_for_all_detectors": exact_coverage,
        "coverage_artifact": str(coverage_artifact),
        "observed": counts,
        "flagged_events": flagged_events,
        "event_ledger": str(event_ledger_path),
        "circular_shift_null": null_summary,
        "interpretation_note": conclusion,
    }
    destination = aggregated_dir / (
        f"catalog_cross_match_{analysis_tag}_{run_name.lower()}.json"
    )
    destination.write_text(json.dumps(out, indent=2), encoding="utf-8")
    logger.info(
        "observed overlap any=%d, null mean=%.3f, p=%.4g; "
        "coverage exact=%s",
        counts["overlap_any"],
        null_summary["overlap_any"]["null_mean"],
        p_any,
        exact_coverage,
    )
    logger.info("wrote %s", destination)
    environment_path = record_environment(
        aggregated_dir,
        f"catalog_cross_match_{analysis_tag}_{run_name.lower()}",
        note=(
            f"coverage_source={coverage_source}; n_shifts={n_shifts}; "
            f"seed={seed}"
        ),
    )
    manifest_outputs = [
        coverage_artifact,
        null_path,
        event_ledger_path,
        destination,
    ]
    if environment_path is not None:
        manifest_outputs.append(environment_path)
        try:
            environment = json.loads(
                environment_path.read_text(encoding="utf-8")
            )
            snapshot = environment.get("dirty_source_snapshot")
            if snapshot:
                manifest_outputs.append(Path(snapshot))
        except (OSError, json.JSONDecodeError):
            pass
    manifest_path = _write_manifest(
        destination,
        run_name=run_name,
        analysis_tag=analysis_tag,
        inputs=[
            aggregated_dir / f"gwtc_{run_name.lower()}_events.json",
            taxonomy_contract.path,
        ],
        outputs=manifest_outputs,
    )
    logger.info("wrote manifest %s", manifest_path)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="O4a")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--coverage-source",
        choices=("auto", "exact", "raw-blocks", "legacy-spans"),
        default="auto",
    )
    parser.add_argument("--n-shifts", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--minimum-shift-s", type=float, default=86400.0)
    parser.add_argument("--production-dir", type=Path, default=PROD)
    args = parser.parse_args()
    run(
        args.run,
        refresh=args.refresh,
        coverage_source=args.coverage_source,
        n_shifts=args.n_shifts,
        seed=args.seed,
        minimum_shift_s=args.minimum_shift_s,
        production_dir=args.production_dir,
    )


if __name__ == "__main__":
    main()
