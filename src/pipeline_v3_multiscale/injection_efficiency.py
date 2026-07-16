"""Per-scale detection efficiency curves via synthetic injections (post-audit).

Injects synthetic glitches of known morphology and duration into clean O4a
background strain, then scores them with the V3 multiscale patch dictionaries
and the block-bootstrap p99 thresholds. Produces recall-vs-SNR curves per
(glitch duration, analysis scale) with Wilson confidence intervals.

Scientific conventions enforced:
- Injection happens in RAW strain, before whitening (physical).
- Whitening via whiten_context(pad=4.0) + extract_clean_subwindow only.
- Thresholds consumed through assert_threshold_run() (same-run application).
- SNR is matched-filter SNR against the local PSD; amplitudes are rescaled
  per-segment so the target SNR is achieved regardless of noise level.
"""

import json
import argparse
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from pathlib import Path
from tqdm import tqdm
from PIL import Image
from gwosc.timeline import get_segments

from src.core.data_loader import fetch_strain_data, _DATA_DIRECTORIES
from src.core.preprocessor import whiten_context, extract_clean_subwindow, generate_qtransform
from src.core.encoder import build_dinov2_transform
from src.core.injection import SyntheticGlitchGenerator, InjectionEngine
from src.core.utils import setup_logger
from src.pipeline_v3_multiscale.micro_mdc_multiscale import excess_power_veto
from src.pipeline_v3_multiscale.sampling import assert_threshold_run

logger = setup_logger(__name__)

SCALES = [0.5, 1, 2, 4]
STRIDE = 96  # guard-time compliant spacing between background centers

# Glitch types with their effective time-domain support (seconds). The
# generator's `duration` argument is the array length; the effective support
# is set by each morphology's internal envelope.
GLITCH_SET = {
    "Blip": {"duration_arg": 1.0, "effective_s": 0.04},
    "NarrowChirp": {"duration_arg": 1.0, "effective_s": 0.5},
    "Whistle": {"duration_arg": 1.0, "effective_s": 0.6},
    "ScatteredLight": {"duration_arg": 2.0, "effective_s": 1.5},
    "NoiseBlob": {"duration_arg": 4.0, "effective_s": 4.0},
    # DSD-falsifiability morphologies (mirrors dsd_injection_test.py's
    # native-index recovery test, run here at all four V3 scales instead
    # of only the legacy single 32s / K=68 pathway). HarmonicComb and
    # WallOfLines are persistent (no time-envelope) over their generated
    # duration_arg window, so injecting them at 4.0s makes them span the
    # full range of tested analysis scales, exactly like NoiseBlob.
    "HarmonicComb": {"duration_arg": 4.0, "effective_s": 4.0},
    "WallOfLines": {"duration_arg": 4.0, "effective_s": 4.0},
    "KoiFish": {"duration_arg": 1.0, "effective_s": 0.15},
}

TARGET_SNRS = [8, 12, 16, 24, 32, 48]


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z ** 2 / n
    centre = (p + z ** 2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def load_thresholds(detector: str, target_run: str) -> dict:
    path = Path("results/micro_mdc/multiscale") / f"{detector}_thresholds.json"
    with open(path) as f:
        thresholds = json.load(f)
    assert_threshold_run(thresholds, target_run)
    return thresholds


def find_background_centers(detector: str, n_needed: int, seed: int) -> list[tuple[int, int, int]]:
    """Return (block_start, block_end, t_bg) triples of DQ-clean, quiet centers."""
    rng = np.random.default_rng(seed)
    local_blocks = []
    for directory in _DATA_DIRECTORIES:
        if directory.exists():
            for file in directory.rglob(f"{detector}_*.hdf5"):
                parts = file.stem.split("_")
                if len(parts) >= 3:
                    try:
                        local_blocks.append((int(parts[1]), int(parts[2])))
                    except ValueError:
                        pass
    local_blocks = sorted(set(local_blocks))
    rng.shuffle(local_blocks)

    centers = []
    pbar = tqdm(total=n_needed, desc="Background centers")
    for block_start, block_end in local_blocks:
        if len(centers) >= n_needed:
            break
        try:
            burst_segs = get_segments(f"{detector}_BURST_CAT1", block_start, block_end)
        except Exception:
            continue
        try:
            ts_clean = fetch_strain_data(detector, block_start, block_end, cache_raw=False)
            ts_w_padded, _ = whiten_context(ts_clean, block_start, block_end, pad=4.0)
            ts_bp = extract_clean_subwindow(ts_w_padded, block_start, block_end)
        except Exception:
            continue
        for t_bg in np.arange(block_start + 64, block_end - 64, STRIDE):
            if len(centers) >= n_needed:
                break
            win_start, win_end = t_bg - 16, t_bg + 16
            if not any(s[0] <= win_start and s[1] >= win_end for s in burst_segs):
                continue
            if excess_power_veto(ts_bp.crop(win_start, win_end)):
                continue
            centers.append((int(block_start), int(block_end), int(t_bg)))
            pbar.update(1)
    pbar.close()
    if len(centers) < n_needed:
        logger.warning(f"Only {len(centers)}/{n_needed} background centers found.")
    return centers


def run_injection_efficiency(detector: str, n_per_cell: int, seed: int, target_run: str,
                             morphologies: list[str] | None = None, tag: str = ""):
    np.random.seed(seed)
    output_dir = Path("results/micro_mdc/multiscale")
    temp_dir = output_dir / "temp_injection_eff"
    temp_dir.mkdir(parents=True, exist_ok=True)

    glitch_set = {k: GLITCH_SET[k] for k in (morphologies or GLITCH_SET)}
    suffix = f"_{tag}" if tag else ""

    thresholds = load_thresholds(detector, target_run)

    dicts = {}
    for scale in SCALES:
        data = np.load(output_dir / f"{detector}_patch_dict_{scale}s.npz")
        dicts[scale] = torch.tensor(data["embeddings"], dtype=torch.float32)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    for scale in SCALES:
        dicts[scale] = dicts[scale].to(device)
    model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14_reg").to(device)
    model.eval()
    for p in model.parameters():
        p.requires_grad = False
    transform = build_dinov2_transform()

    gen = SyntheticGlitchGenerator(sample_rate=4096)
    injector = InjectionEngine(sample_rate=4096)

    n_cells = len(glitch_set) * len(TARGET_SNRS)
    n_injections = n_cells * n_per_cell
    centers = find_background_centers(detector, n_injections, seed)

    tasks = []
    for gtype in glitch_set:
        for snr in TARGET_SNRS:
            for _ in range(n_per_cell):
                tasks.append((gtype, snr))
    rng = np.random.default_rng(seed)
    rng.shuffle(tasks)

    results = []
    resume_path = output_dir / f"{detector}_injection_efficiency{suffix}_raw.csv"
    done = 0
    if resume_path.exists():
        prev = pd.read_csv(resume_path)
        results = prev.to_dict("records")
        done = prev["injection_id"].nunique()
        logger.info(f"Resuming: {done} injections already scored.")

    block_cache = {}  # (start, end) -> raw TimeSeries; keep only last block

    for i, (gtype, target_snr) in enumerate(tqdm(tasks, desc=f"Injections {detector}")):
        if i < done:
            continue
        if i >= len(centers):
            break
        block_start, block_end, t_bg = centers[i]

        try:
            key = (block_start, block_end)
            if key not in block_cache:
                block_cache.clear()
                block_cache[key] = fetch_strain_data(
                    detector, block_start, block_end, cache_raw=False)
            ts_raw = block_cache[key]

            spec = glitch_set[gtype]
            glitch = gen.generate(gtype, amplitude=1.0, duration=spec["duration_arg"])
            # Rescale to target matched-filter SNR against the local PSD
            snr_unit = injector.compute_snr(ts_raw.crop(t_bg - 16, t_bg + 16), glitch)
            if snr_unit <= 0:
                continue
            glitch = glitch * (target_snr / snr_unit)

            ts_injected = injector.inject(ts_raw.copy(), glitch, float(t_bg))
            win_start, win_end = t_bg - 16, t_bg + 16
            ts_w_padded, _ = whiten_context(ts_injected, win_start, win_end, pad=4.0)
            ts_bp = extract_clean_subwindow(ts_w_padded, win_start, win_end)

            for scale in SCALES:
                ts_crop = ts_bp.crop(t_bg - scale / 2.0, t_bg + scale / 2.0)
                if np.any(~np.isfinite(ts_crop.value)):
                    continue
                temp_path = temp_dir / f"inj_{scale}.png"
                try:
                    generate_qtransform(ts_crop, qrange=(4, 32), save_path=temp_path)
                    img = Image.open(temp_path)
                    tensor = transform(img).unsqueeze(0).to(device)
                    with torch.inference_mode():
                        features = model.forward_features(tensor)
                        patch_tokens = F.normalize(
                            features["x_norm_patchtokens"].squeeze(0), p=2, dim=-1)
                    sims = torch.matmul(patch_tokens, dicts[scale].T)
                    max_sims, _ = sims.max(dim=1)
                    top_k, _ = torch.topk(1.0 - max_sims, k=68)
                    score = top_k.mean().item()
                finally:
                    if temp_path.exists():
                        temp_path.unlink()

                thr = thresholds[f"{scale}s"]["p99_mean"]
                results.append({
                    "injection_id": i,
                    "glitch_type": gtype,
                    "effective_duration_s": spec["effective_s"],
                    "target_snr": target_snr,
                    "gps_center": t_bg,
                    "scale_s": scale,
                    "score": score,
                    "threshold_p99": thr,
                    "detected": bool(score > thr),
                })
        except Exception as e:
            logger.warning(f"Injection {i} ({gtype}, SNR {target_snr}) failed: {e}")
            continue

        if (i + 1) % 50 == 0:
            pd.DataFrame(results).to_csv(resume_path, index=False)

    df = pd.DataFrame(results)
    df.to_csv(resume_path, index=False)

    # Summary: recall per (glitch_type, scale, snr) with Wilson CI
    rows = []
    for (gtype, scale, snr), g in df.groupby(["glitch_type", "scale_s", "target_snr"]):
        k, n = int(g["detected"].sum()), len(g)
        lo, hi = wilson_ci(k, n)
        rows.append({
            "glitch_type": gtype,
            "effective_duration_s": glitch_set[gtype]["effective_s"],
            "scale_s": scale,
            "target_snr": snr,
            "n": n,
            "n_detected": k,
            "recall": k / n if n else 0.0,
            "ci_low": lo,
            "ci_high": hi,
        })
    summary = pd.DataFrame(rows).sort_values(
        ["effective_duration_s", "scale_s", "target_snr"])
    summary_path = output_dir / f"{detector}_injection_efficiency{suffix}_summary.csv"
    summary.to_csv(summary_path, index=False)
    logger.info(f"Summary written to {summary_path}")

    plot_efficiency(summary, detector, output_dir, glitch_set, suffix)


def plot_efficiency(summary: pd.DataFrame, detector: str, output_dir: Path,
                    glitch_set: dict | None = None, suffix: str = ""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    glitch_set = glitch_set or GLITCH_SET
    # Derive plotted types from the data actually present, in glitch_set's
    # order, so a partial/custom run only plots what it ran.
    gtypes = [g for g in glitch_set if g in set(summary["glitch_type"])]
    fig, axes = plt.subplots(1, len(gtypes), figsize=(4 * len(gtypes), 4),
                             sharey=True)
    if len(gtypes) == 1:
        axes = [axes]
    for ax, gtype in zip(axes, gtypes):
        sub = summary[summary["glitch_type"] == gtype]
        for scale in SCALES:
            s = sub[sub["scale_s"] == scale].sort_values("target_snr")
            if s.empty:
                continue
            ax.plot(s["target_snr"], s["recall"], marker="o",
                    label=f"{scale}s")
            ax.fill_between(s["target_snr"], s["ci_low"], s["ci_high"],
                            alpha=0.15)
        dur = glitch_set[gtype]["effective_s"]
        ax.set_title(f"{gtype} (~{dur}s)")
        ax.set_xlabel("Matched-filter SNR")
        ax.set_xscale("log")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Detection efficiency (recall)")
    axes[0].legend(title="Analysis scale")
    fig.suptitle(f"{detector} per-scale detection efficiency (post-audit V3)")
    fig.tight_layout()
    out = output_dir / f"fig_{detector}_injection_efficiency{suffix}_postaudit.png"
    fig.savefig(out, dpi=150)
    logger.info(f"Figure written to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector", type=str, default="L1")
    parser.add_argument("--n-per-cell", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run", type=str, default="O4a")
    parser.add_argument("--morphologies", nargs="+", default=None,
                        help="Subset of GLITCH_SET keys to run (default: all).")
    parser.add_argument("--tag", type=str, default="",
                        help="Suffix for output filenames, to avoid "
                             "clobbering a prior run with a different "
                             "morphology subset.")
    args = parser.parse_args()
    run_injection_efficiency(args.detector, args.n_per_cell, args.seed, args.run,
                             morphologies=args.morphologies, tag=args.tag)
