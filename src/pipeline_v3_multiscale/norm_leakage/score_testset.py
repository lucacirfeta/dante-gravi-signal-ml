"""Score the shared test/calibration sets under all factorial cells.

Stage A (--stage calib): O4a calibration segments (DISJOINT segment seed
    from the dictionary builder) scored with the O4a dictionaries ->
    per-cell p99 thresholds, replicating the original cross-run FPR
    observation (O4a-calibrated threshold applied to O3a background).
Stage B (--stage test): the SHARED O3a test set (one GPS list, frozen to
    disk on first run) scored under every (dict_run, norm, kmeans_seed,
    scale) cell. Fully paired: every cell sees identical strain.

Output: long-format CSV, one row per (segment, cell).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from src.core.utils import setup_logger
from src.pipeline_v3_multiscale.norm_leakage.common import (
    DETECTOR, OUT_ROOT, SCALES, PatchEncoder, get_normalizer,
    iter_clean_segments, raw_qgram, spectrogram_to_rgb, topk_score,
)
from src.pipeline_v3_multiscale.norm_leakage.build_dictionaries import KMEANS_SEEDS

logger = setup_logger(__name__)

DICT_DIR = OUT_ROOT / "dictionaries"

# Segment seeds — MUST all be distinct (disjoint sampling):
SEED_DICT = 42     # used by build_dictionaries.py
SEED_CALIB = 1042  # O4a calibration split
SEED_TEST = 2042   # O3a shared test set


def _load_dicts(detector: str):
    dicts = {}
    for f in DICT_DIR.glob(f"{detector}_*_seed*_*s.npz"):
        with np.load(f, allow_pickle=True) as d:
            meta = json.loads(str(d["meta"]))
            key = (meta["run"], meta["norm"], meta["kmeans_seed"], meta["scale"])
            dicts[key] = d["embeddings"]
    if not dicts:
        raise FileNotFoundError(f"No dictionaries in {DICT_DIR} — run "
                                "build_dictionaries.py for both runs first.")
    return dicts


def _score_segments(run: str, n: int, seed: int, out_csv: Path,
                    detector: str, dict_runs: tuple[str, ...]):
    dicts = _load_dicts(detector)
    encoder = PatchEncoder()
    normalizers = {"minmax": get_normalizer("minmax"),
                   "fixed": get_normalizer("fixed")}

    write_header = not out_csv.exists()
    done_gps = set()
    if not write_header:  # resumable
        with open(out_csv) as f:
            done_gps = {float(r["gps"]) for r in csv.DictReader(f)}

    with open(out_csv, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["gps", "segment_run", "dict_run", "norm",
                             "kmeans_seed", "scale", "score"])
        for seg in iter_clean_segments(run, detector, n, seed=seed):
            if seg.t_bg in done_gps:
                continue
            for scale in SCALES:
                ts_crop = seg.ts_whitened.crop(seg.t_bg - scale / 2.0,
                                               seg.t_bg + scale / 2.0)
                try:
                    spec_raw = raw_qgram(ts_crop)
                except Exception:
                    continue
                for sch, norm in normalizers.items():
                    tokens = encoder.encode_rgb(spectrogram_to_rgb(norm(spec_raw)))
                    for dict_run in dict_runs:
                        for km_seed in KMEANS_SEEDS:
                            cents = dicts.get((dict_run, sch, km_seed, scale))
                            if cents is None:
                                continue
                            s = topk_score(tokens, cents)
                            writer.writerow([seg.t_bg, run, dict_run, sch,
                                             km_seed, scale, f"{s:.6f}"])
            f.flush()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["calib", "test"], required=True)
    p.add_argument("--n", type=int, default=None)
    p.add_argument("--detector", type=str, default=DETECTOR)
    a = p.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if a.stage == "calib":
        n = a.n or 500
        # calibration on O4a background, O4a dictionaries only
        _score_segments("o4a", n, SEED_CALIB,
                        OUT_ROOT / "scores_calib_o4a.csv", a.detector,
                        dict_runs=("o4a",))
    else:
        n = a.n or 2000
        # shared O3a test set, ALL dictionaries (fully paired design)
        _score_segments("o3a", n, SEED_TEST,
                        OUT_ROOT / "scores_test_o3a.csv", a.detector,
                        dict_runs=("o3a", "o4a"))


if __name__ == "__main__":
    main()
