#!/usr/bin/env python3
"""Generate the v6 candidate and method figures from canonical artefacts.

The candidate panel is accepted only if the score recomputed through the
production Q64/cividis/DINOv2/VQ path reproduces the detector-aware taxonomy.
The script also writes a compact provenance JSON used by manuscript checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.core.data_loader import fetch_local_or_remote_strain
from src.core.patch_scorer import PatchScorer
from src.core.preprocessor import extract_clean_subwindow, generate_qtransform, whiten_context
from src.pipeline_v2_production.saliency_map import EFFECTIVE_FRANGE, generate_saliency_map

CANDIDATE_GPS = 1382955228.0
ANALYSIS_GPS = CANDIDATE_GPS + 4.0
DETECTOR = "L1"
REPRESENTATION = "idxq4-64_queryq4-64"
EXPECTED_INDEX_SHA256 = "0241b2a1ea2a460334f2c7ae0ab1bb62052706ea05c48443af32ae60a2488744"

AGG = ROOT / "data" / "production" / "aggregated"
TAXONOMY = AGG / "Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"
MULTISCALE = AGG / "Multiscale_Profile_O4a_idxq4-64_queryq4-64.csv"
PEM = AGG / "pem" / REPRESENTATION / "pem_family_wise_verdicts.csv"
CHARACTERIZE = AGG / "characterize_L1_1382955232.json"
INDEX = ROOT / "data" / "reference" / "patch_compressed_index_o4a_q4-64_ex.npz"
FIGURES = ROOT / "paper_draft" / "v6_paper" / "figures"
PAPER_DIRS = [
    ROOT / "paper_draft" / "v6_paper" / "arxiv_v6" / "img",
    ROOT / "paper_draft" / "v6_paper" / "cqg_v6" / "img",
]
PROVENANCE = AGG / "candidate_case_L1_1382955228_idxq4-64_queryq4-64.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_candidate_evidence() -> dict:
    taxonomy = pd.read_csv(TAXONOMY)
    # GPS values are integral catalogue keys.  ``np.isclose`` is unsafe at
    # O(1e9) because its default relative tolerance merges nearby windows.
    row = taxonomy[(taxonomy.detector == DETECTOR) & (taxonomy.gps_start == CANDIDATE_GPS)]
    if len(row) != 1:
        raise RuntimeError(f"expected one detector--GPS taxonomy row, found {len(row)}")
    tax = row.iloc[0]
    if tax.robustness_class != "ROBUST":
        raise RuntimeError(f"unexpected current disposition: {tax.robustness_class}")

    multiscale = pd.read_csv(MULTISCALE)
    ms = multiscale[(multiscale.detector == DETECTOR) & (multiscale.gps_start == CANDIDATE_GPS)]
    if len(ms) != 4 or set(ms.scale_s.astype(float)) != {0.5, 1.0, 2.0, 4.0}:
        raise RuntimeError("candidate multiscale profile is incomplete")
    if not bool(ms.exceeds.all()):
        raise RuntimeError("candidate does not exceed every recorded multiscale threshold")

    pem = pd.read_csv(PEM)
    pem_row = pem[(pem.detector == DETECTOR) & (pem.gps_start == CANDIDATE_GPS)]
    if len(pem_row) != 1:
        raise RuntimeError(f"expected one PEM row, found {len(pem_row)}")
    pem_value = pem_row.iloc[0]
    if pem_value.verdict != "NO_CORRELATION" or pem_value.taxonomy_representation != REPRESENTATION:
        raise RuntimeError("candidate PEM result is stale or unexpected")

    characterize = json.loads(CHARACTERIZE.read_text(encoding="utf-8"))
    if characterize["window"] != [ANALYSIS_GPS, ANALYSIS_GPS + 32.0]:
        raise RuntimeError("characterization window does not match the historical +4 s contract")
    if characterize["production_coincidence"]["gps"] != CANDIDATE_GPS:
        raise RuntimeError("candidate coincidence join is inconsistent")

    return {
        "taxonomy": tax.to_dict(),
        "multiscale": ms.sort_values("scale_s").to_dict(orient="records"),
        "pem": pem_value.to_dict(),
        "characterize": characterize,
    }


def _copy_figure(source: Path) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    if source.parent != FIGURES:
        shutil.copy2(source, FIGURES / source.name)
    for directory in PAPER_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, directory / source.name)


def generate_pipeline_overview() -> Path:
    stages = [
        ("Public O4a strain", "H1/L1, science-quality coverage"),
        ("Canonical representation", "pad 4 s, whiten, crop, Q64, cividis"),
        ("Historical novelty scan", "frozen DINOv2 patches + O3b VQ index"),
        ("Native DSD calibration", "candidate-vetoed O4a index + block bootstrap"),
        ("Statistical disposition", "ROBUST / AMBIGUOUS / BACKGROUND"),
        ("Physical follow-up", "strain null, PEM null, catalogues, injections"),
    ]
    fig, ax = plt.subplots(figsize=(10.5, 5.0), dpi=180)
    ax.set_xlim(0, 3)
    ax.set_ylim(-0.12, 2)
    ax.axis("off")
    colors = ["#355f8d", "#2a788e", "#21918c", "#22a884", "#7ad151", "#fde725"]
    positions = [(0.08, 1.16), (1.08, 1.16), (2.08, 1.16),
                 (2.08, 0.30), (1.08, 0.30), (0.08, 0.30)]
    for i, (((title, detail), color), (x, y0)) in enumerate(zip(zip(stages, colors), positions)):
        box = FancyBboxPatch((x, y0), 0.84, 0.56, boxstyle="round,pad=0.02",
                             facecolor=color, edgecolor="#24303a", linewidth=1.0)
        ax.add_patch(box)
        ax.text(x + 0.42, y0 + 0.38, title, ha="center", va="center", fontsize=9.0,
                fontweight="bold", color="white" if i < 4 else "#17202a")
        ax.text(x + 0.42, y0 + 0.17, detail.replace(", ", ",\n"),
                ha="center", va="center", fontsize=7.1,
                color="white" if i < 4 else "#17202a", wrap=True)
    for start, end in [((0.93, 1.44), (1.07, 1.44)),
                       ((1.93, 1.44), (2.07, 1.44)),
                       ((2.50, 1.15), (2.50, 0.88)),
                       ((2.07, 0.58), (1.93, 0.58)),
                       ((1.07, 0.58), (0.93, 0.58))]:
        ax.annotate("", xy=end, xytext=start,
                    arrowprops=dict(arrowstyle="->", color="#24303a", lw=1.5))
    ax.text(1.5, 0.02,
            "The outputs are triage evidence, not an astrophysical detection statistic or a glitch-class label.",
            ha="center", va="center", fontsize=8, color="#333333")
    fig.tight_layout()
    path = FIGURES / "fig_pipeline_overview.png"
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    _copy_figure(path)
    return path


def generate_representation_figure(spec: np.ndarray) -> Path:
    rgb = (plt.get_cmap("cividis")(spec)[:, :, :3] * 255.0).astype(np.uint8)
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 3.4), dpi=180)
    extent = [0, 32, 0, spec.shape[1]]
    y = np.linspace(0, spec.shape[1], 6)
    labels = [f"{EFFECTIVE_FRANGE[0] * (EFFECTIVE_FRANGE[1] / EFFECTIVE_FRANGE[0]) ** (v / spec.shape[1]):.0f}" for v in y]
    axes[0].imshow(spec.T, origin="lower", aspect="auto", extent=extent, cmap="cividis")
    axes[0].set_title("Normalized Q-transform")
    axes[0].set_xlabel("Time from window start (s)")
    axes[0].set_ylabel("Frequency (Hz, log-spaced)")
    axes[0].set_yticks(y, labels)
    axes[1].imshow(rgb.transpose(1, 0, 2), origin="lower", aspect="auto", extent=extent)
    axes[1].set_title("Exact cividis RGB encoder input")
    axes[1].set_xlabel("Time from window start (s)")
    axes[1].set_yticks([])
    axes[2].imshow(rgb.transpose(1, 0, 2), origin="lower", aspect="auto", extent=extent)
    for n in range(38):
        axes[2].axvline(n * 32 / 37, color="white", lw=0.25, alpha=0.5)
        axes[2].axhline(n * spec.shape[1] / 37, color="white", lw=0.25, alpha=0.5)
    axes[2].set_title("$37\\times37$ DINOv2 patch geometry")
    axes[2].set_xlabel("Time from window start (s)")
    axes[2].set_yticks([])
    fig.tight_layout()
    path = FIGURES / "fig_representation_examples.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    _copy_figure(path)
    return path


def generate_candidate_figure(device: str, evidence: dict) -> tuple[Path, dict]:
    if sha256(INDEX) != EXPECTED_INDEX_SHA256:
        raise RuntimeError("native Q64 index hash does not match the frozen contract")
    ts_context = fetch_local_or_remote_strain(DETECTOR, ANALYSIS_GPS - 4.0,
                                               ANALYSIS_GPS + 36.0, edge_tolerance=4.0)
    ts_white, _ = whiten_context(ts_context, ANALYSIS_GPS, ANALYSIS_GPS + 32.0, pad=4.0)
    ts_clean = extract_clean_subwindow(ts_white, ANALYSIS_GPS, ANALYSIS_GPS + 32.0)
    spec = generate_qtransform(ts_clean, qrange=(4, 64), output_size=(256, 256))
    # PatchScorer's built-in MD5 is the frozen historical O3b dictionary.
    # This run-native index is guarded immediately above by its contract SHA256.
    scorer = PatchScorer(reference_index_path=str(INDEX), device=device, verify_md5=False)
    prefix = FIGURES / "candidate_L1_1382955228_q64"
    result = generate_saliency_map(
        spectrogram_matrix=spec,
        output_path_prefix=str(prefix),
        model=scorer.model,
        k_highlight=68,
        device=device,
        scorer=scorer,
        score_source_label="native O4a Q64 VQ dictionary",
    )
    target = FIGURES / "fig_candidate_saliency_q64.png"
    Path(f"{prefix}_saliency.png").replace(target)
    Path(f"{prefix}_saliency.pdf").unlink(missing_ok=True)
    stored = float(evidence["taxonomy"]["native_o4a_score"])
    delta = abs(float(result["mean_topk_score"]) - stored)
    if delta > 1e-6:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"figure score does not reproduce taxonomy: delta={delta:.3g}")
    _copy_figure(target)
    generate_representation_figure(spec)
    return target, {
        "recomputed_score": float(result["mean_topk_score"]),
        "stored_score": stored,
        "absolute_delta": delta,
        "top_k_indices": [int(value) for value in result["top_k_indices"]],
        "spectrogram_shape": list(spec.shape),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    FIGURES.mkdir(parents=True, exist_ok=True)
    evidence = load_candidate_evidence()
    pipeline = generate_pipeline_overview()
    candidate, reproduction = generate_candidate_figure(args.device, evidence)
    representation = FIGURES / "fig_representation_examples.png"
    source_paths = [TAXONOMY, MULTISCALE, PEM, CHARACTERIZE, INDEX]
    provenance = {
        "schema_version": 1,
        "candidate_key": {"detector": DETECTOR, "catalog_gps": CANDIDATE_GPS},
        "analysis_window": [ANALYSIS_GPS, ANALYSIS_GPS + 32.0],
        "feature_gps": evidence["characterize"]["feature_gps"],
        "representation": REPRESENTATION,
        "source_artifacts": [
            {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path)}
            for path in source_paths
        ],
        "score_reproduction": reproduction,
        "candidate_evidence": evidence,
        "figures": [
            {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path)}
            for path in (candidate, representation, pipeline)
        ],
        "claim_boundary": (
            "Statistically ROBUST L1-local transient with no resolved H1 or tested-public-PEM "
            "counterpart; unclassified and not evidence for a new glitch class."
        ),
    }
    PROVENANCE.write_text(json.dumps(provenance, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"CANDIDATE_FIGURES=PASS score_delta={reproduction['absolute_delta']:.3g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
