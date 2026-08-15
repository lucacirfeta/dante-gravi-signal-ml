"""Run the predeclared CQG native-adaptation absorption matrix.

The matrix uses one held-out protocol, Q=(4, 64), three representative
morphologies and multiple seeds.  A cell is admissible only when all encoded
sample counts are complete, index/query GPS groups are disjoint, every score is
finite and the same-size all-background control is present.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline_v2_production.dsd_absorption_threshold import (  # noqa: E402
    _artifact_stem,
    _experiment_identity,
    run,
)


OUT = ROOT / "data" / "production" / "aggregated"
QRANGE = (4, 64)
FULL_SEEDS = (42, 314159, 271828)
PILOT_SEEDS = (42, 43)
PREVALENCES = (0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40)
PILOT_PREVALENCES = (0.0, 0.10, 0.40)
MORPHOLOGIES = (
    {"morphology": "Blip", "amplitude": 12.0, "duration": 1.0},
    {"morphology": "ScatteredLight", "amplitude": 12.0, "duration": 1.5},
    {"morphology": "KoiFish", "amplitude": 12.0, "duration": 1.0},
)

# This operational endpoint is fixed before looking at the multi-seed matrix.
# It is a measurement convention, not a universal physical detection limit.
ABSORPTION_RULE = {
    "z_at_or_below": 3.0,
    "flagged_fraction_at_or_below": 0.5,
    "crossing": "first tested prevalence satisfying both conditions",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_cell(cell: dict) -> None:
    """Fail closed on partial, non-finite, or non-disjoint experiment cells."""
    if cell.get("qrange") != list(QRANGE):
        raise ValueError(f"inadmissible qrange: {cell.get('qrange')}")
    groups = cell.get("gps_groups", {})
    required_groups = {
        "background",
        "holdout_background",
        "holdout_injected_source",
        "index_injected_source",
    }
    if set(groups) != required_groups:
        raise ValueError(f"incomplete GPS ledger: {sorted(groups)}")
    group_sets = {name: set(values) for name, values in groups.items()}
    names = sorted(group_sets)
    for i, left in enumerate(names):
        if len(group_sets[left]) != len(groups[left]):
            raise ValueError(f"duplicate GPS within {left}")
        for right in names[i + 1 :]:
            overlap = group_sets[left] & group_sets[right]
            if overlap:
                raise ValueError(f"GPS leakage between {left} and {right}: {overlap}")
    if not cell.get("rows"):
        raise ValueError("cell contains no prevalence rows")
    required_finite = {
        "prevalence",
        "score_injected_mean",
        "score_background_mean",
        "score_background_std",
        "z_injected_vs_background",
        "z_control_same_size_all_background",
        "flagged_fraction",
    }
    for row in cell["rows"]:
        missing = required_finite - set(row)
        if missing:
            raise ValueError(f"row missing fields: {sorted(missing)}")
        if not all(np.isfinite(float(row[name])) for name in required_finite):
            raise ValueError(f"non-finite absorption row: {row}")
        if len(row.get("z_injected_vs_background_ci95", [])) != 2:
            raise ValueError("missing z-score uncertainty")
        if len(row.get("flagged_fraction_wilson95", [])) != 2:
            raise ValueError("missing binomial uncertainty")
        if row.get("flagged_total") != cell.get("n_holdout_inj"):
            raise ValueError("flagged denominator differs from held-out injections")
        raw = row.get("raw_scores", {})
        required_raw = {
            "injected_mixed_index",
            "background_mixed_index",
            "injected_same_size_control",
            "background_same_size_control",
        }
        if set(raw) != required_raw:
            raise ValueError("missing raw absorption score populations")
        arrays = {
            name: np.asarray(values, dtype=float)
            for name, values in raw.items()
        }
        if (
            len(arrays["injected_mixed_index"]) != cell["n_holdout_inj"]
            or len(arrays["injected_same_size_control"])
            != cell["n_holdout_inj"]
            or len(arrays["background_mixed_index"])
            != cell["n_holdout_bg"]
            or len(arrays["background_same_size_control"])
            != cell["n_holdout_bg"]
            or not all(np.all(np.isfinite(values)) for values in arrays.values())
        ):
            raise ValueError("invalid raw absorption score populations")
        inj = arrays["injected_mixed_index"]
        bg = arrays["background_mixed_index"]
        ctrl_inj = arrays["injected_same_size_control"]
        ctrl_bg = arrays["background_same_size_control"]
        recomputed_z = (inj.mean() - bg.mean()) / (bg.std(ddof=1) + 1e-12)
        recomputed_ctrl = (
            (ctrl_inj.mean() - ctrl_bg.mean())
            / (ctrl_bg.std(ddof=1) + 1e-12)
        )
        threshold = np.percentile(bg, 99)
        recomputed_flagged = int(np.sum(inj > threshold))
        if not np.isclose(recomputed_z, row["z_injected_vs_background"]):
            raise ValueError("raw scores do not reproduce mixed-index z")
        if not np.isclose(
            recomputed_ctrl, row["z_control_same_size_all_background"]
        ):
            raise ValueError("raw scores do not reproduce same-size control z")
        if recomputed_flagged != row["flagged_count"]:
            raise ValueError("raw scores do not reproduce flagged count")
        if not np.isclose(
            recomputed_flagged / len(inj), row["flagged_fraction"]
        ):
            raise ValueError("raw scores do not reproduce flagged fraction")
        if not np.isclose(inj.mean(), row["score_injected_mean"]):
            raise ValueError("raw scores do not reproduce injected mean")
        if not np.isclose(bg.mean(), row["score_background_mean"]):
            raise ValueError("raw scores do not reproduce background mean")
        if not np.isclose(bg.std(ddof=1), row["score_background_std"]):
            raise ValueError("raw scores do not reproduce background std")


def cell_crossing(cell: dict) -> float | None:
    for row in sorted(cell["rows"], key=lambda value: value["prevalence"]):
        if (
            row["z_injected_vs_background"] <= ABSORPTION_RULE["z_at_or_below"]
            and row["flagged_fraction"]
            <= ABSORPTION_RULE["flagged_fraction_at_or_below"]
        ):
            return float(row["prevalence"])
    return None


def summarize_cells(cells: list[dict]) -> dict:
    by_morphology: dict[str, list[dict]] = {}
    for cell in cells:
        by_morphology.setdefault(cell["morphology"], []).append(cell)
    summary: dict[str, dict] = {}
    for morphology, morph_cells in sorted(by_morphology.items()):
        crossings = [cell_crossing(cell) for cell in morph_cells]
        finite_crossings = [value for value in crossings if value is not None]
        prevalences = sorted(
            set.intersection(
                *[
                    {float(row["prevalence"]) for row in cell["rows"]}
                    for cell in morph_cells
                ]
            )
        )
        rows = []
        for prevalence in prevalences:
            matched = [
                next(
                    row
                    for row in cell["rows"]
                    if float(row["prevalence"]) == prevalence
                )
                for cell in morph_cells
            ]
            z_values = np.asarray(
                [row["z_injected_vs_background"] for row in matched], dtype=float
            )
            flagged = np.asarray(
                [row["flagged_fraction"] for row in matched], dtype=float
            )
            controls = np.asarray(
                [row["z_control_same_size_all_background"] for row in matched],
                dtype=float,
            )
            rows.append(
                {
                    "prevalence": prevalence,
                    "n_seeds": len(matched),
                    "z_median": float(np.median(z_values)),
                    "z_range": [float(z_values.min()), float(z_values.max())],
                    "z_sample_sd": (
                        float(z_values.std(ddof=1)) if len(z_values) > 1 else None
                    ),
                    "flagged_fraction_median": float(np.median(flagged)),
                    "flagged_fraction_range": [
                        float(flagged.min()),
                        float(flagged.max()),
                    ],
                    "same_size_control_z_median": float(np.median(controls)),
                    "same_size_control_z_range": [
                        float(controls.min()),
                        float(controls.max()),
                    ],
                }
            )
        summary[morphology] = {
            "n_seeds": len(morph_cells),
            "seed_crossings": crossings,
            "crossing_range": (
                [float(min(finite_crossings)), float(max(finite_crossings))]
                if finite_crossings
                else None
            ),
            "rows": rows,
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--run", default="O4a")
    parser.add_argument("--detector", default="L1")
    args = parser.parse_args()

    seeds = PILOT_SEEDS if args.pilot else FULL_SEEDS
    prevalences = PILOT_PREVALENCES if args.pilot else PREVALENCES
    n_background = 40 if args.pilot else 300
    n_holdout_bg = 12 if args.pilot else 150
    n_holdout_inj = 12 if args.pilot else 60
    cells: list[dict] = []
    artifacts: list[dict] = []
    for spec in MORPHOLOGIES:
        for seed in seeds:
            cell = run(
                **spec,
                n_background=n_background,
                n_holdout_bg=n_holdout_bg,
                n_holdout_inj=n_holdout_inj,
                prevalences=prevalences,
                run_name=args.run,
                detector=args.detector,
                seed=seed,
                qrange=QRANGE,
            )
            validate_cell(cell)
            identity = _experiment_identity(
                run_name=args.run,
                detector=args.detector,
                n_background=n_background,
                n_holdout_bg=n_holdout_bg,
                n_holdout_inj=n_holdout_inj,
                prevalences=prevalences,
                seed=seed,
                qrange=QRANGE,
                **spec,
            )
            path = OUT / f"{_artifact_stem(identity)}.json"
            token_caches = {
                role: Path(cache_path)
                for role, cache_path in cell["token_caches"].items()
            }
            artifacts.append(
                {
                    "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "sha256": sha256(path),
                    "token_caches": {
                        role: {
                            "path": str(
                                cache_path.resolve().relative_to(ROOT)
                            ).replace("\\", "/"),
                            "sha256": sha256(cache_path),
                        }
                        for role, cache_path in token_caches.items()
                    },
                    "whitened_segment_cache": {
                        "path": str(
                            Path(cell["whitened_segment_cache"])
                            .resolve()
                            .relative_to(ROOT)
                        ).replace("\\", "/"),
                        "sha256": sha256(
                            Path(cell["whitened_segment_cache"])
                        ),
                    },
                }
            )
            cells.append(cell)

    source = Path(__file__).resolve()
    module = (
        ROOT
        / "src"
        / "pipeline_v2_production"
        / "dsd_absorption_threshold.py"
    )
    result = {
        "schema_version": 1,
        "status": "complete",
        "experiment": "cqg_native_adaptation_absorption_matrix",
        "scope": (
            "Synthetic proof of mechanism under the stated amplitude, duration, "
            "representation and O4a L1 background; not a population recall limit."
        ),
        "representation": "idxq4-64_queryq4-64",
        "run": args.run,
        "detector": args.detector,
        "seeds": list(seeds),
        "prevalences": list(prevalences),
        "absorption_rule": ABSORPTION_RULE,
        "source_sha256": {
            str(source.relative_to(ROOT)).replace("\\", "/"): sha256(source),
            str(module.relative_to(ROOT)).replace("\\", "/"): sha256(module),
        },
        "cell_artifacts": artifacts,
        "cells": cells,
        "summary": summarize_cells(cells),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = "_pilot" if args.pilot else ""
    destination = OUT / f"cqg_absorption_matrix{suffix}.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"WROTE {destination} SHA256={sha256(destination)}")


if __name__ == "__main__":
    main()
