"""Generate the v6 manuscript figures from representation-versioned artifacts.

The script reads only coherent Q64/Q64 outputs.  It intentionally does not
fall back to legacy filenames, so a missing coherent artifact fails loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
AGG = ROOT / "data" / "production" / "aggregated"
OUT = ROOT / "paper_draft" / "v6_paper" / "figures"
OUTPUT_DIRS = [
    OUT,
    ROOT / "paper_draft" / "v6_paper" / "arxiv_v6" / "img",
    ROOT / "paper_draft" / "v6_paper" / "cqg_v6" / "img",
]
for output_dir in OUTPUT_DIRS:
    output_dir.mkdir(parents=True, exist_ok=True)

BLUE = "#2f6f9f"
ORANGE = "#e07a2d"
GREEN = "#3a8d5d"
RED = "#b44b4b"
GREY = "#6b7280"


def load_json(name: str) -> dict:
    path = AGG / name
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def load_final_json(name: str) -> dict:
    if "pilot" in name.lower():
        raise ValueError(f"pilot artifact is not eligible for paper figures: {name}")
    value = load_json(name)
    if value.get("status") not in {"complete", "final"}:
        raise ValueError(f"artifact is not complete/final: {name}")
    if "source_sha256" not in value and name != "cqg_known_glitch_controls.json":
        raise ValueError(f"artifact lacks source provenance: {name}")
    if name == "cqg_known_glitch_controls.json":
        detectors = value.get("detectors", {})
        if not detectors or any(
            "manifest_sha256" not in record for record in detectors.values()
        ):
            raise ValueError(f"known-glitch artifact lacks manifest provenance: {name}")
    return value


def save(fig: plt.Figure, name: str) -> None:
    for output_dir in OUTPUT_DIRS:
        fig.savefig(output_dir / name, dpi=220, bbox_inches="tight")
    plt.close(fig)


def figure_funnel() -> None:
    audit = load_json("dsd_transition_audit_o4a_idxq4-64_queryq4-64.json")
    labels = ["H1", "L1", "Combined"]
    robust = [audit["H1"]["robust"], audit["L1"]["robust"], audit["robust_count"]]
    ambiguous = [
        audit["H1"]["ambiguous"],
        audit["L1"]["ambiguous"],
        audit["ambiguous_count"],
    ]
    background = [
        audit["H1"]["background"],
        audit["L1"]["background"],
        audit["background_count"],
    ]
    totals = np.array(robust) + np.array(ambiguous) + np.array(background)
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(6.5, 4.1))
    ax.bar(x, np.array(background) / totals, color=GREY, label="BACKGROUND")
    ax.bar(
        x,
        np.array(ambiguous) / totals,
        bottom=np.array(background) / totals,
        color=ORANGE,
        label="AMBIGUOUS",
    )
    ax.bar(
        x,
        np.array(robust) / totals,
        bottom=(np.array(background) + np.array(ambiguous)) / totals,
        color=GREEN,
        label="ROBUST",
    )
    for i, total in enumerate(totals):
        ax.text(i, 1.025, f"N={total:,}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 1.10)
    ax.set_ylabel("Fraction of coherent Q64/Q64 taxonomy")
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.18))
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "fig_funnel_q64.png")


def figure_robustness() -> None:
    p5 = load_json("dsd_index_stability_o4a_idxq4-64_queryq4-64.json")
    p4 = load_json("dsd_k_sensitivity_o4a_idxq4-64_queryq4-64.json")
    p10 = load_json("pca_baseline_o4a_idxq4-64_queryq4-64.json")
    autoencoder = load_json(
        "gw_autoencoder_baseline_o4a_idxq4-64_queryq4-64.json"
    )
    white = load_json(
        "whitening_context_sensitivity_o4a_idxq4-64_queryq4-64.json"
    )
    fig, axes = plt.subplots(2, 2, figsize=(8.3, 6.2))

    ax = axes[0, 0]
    vals = [
        p5["score_rank_correlation_mean"],
        p5["score_rank_correlation_min"],
    ]
    ax.bar(["mean", "minimum"], vals, color=[BLUE, GREY])
    ax.set_ylim(0, 1)
    ax.set_ylabel("Pairwise Spearman $\\rho$")
    ax.set_title("(a) Background-draw stability")

    ax = axes[0, 1]
    ks = [512, 1024, 2048]
    corrs = [
        p4["rank_correlation_vs_production_k"][str(value)] for value in ks
    ]
    ax.plot(ks, corrs, marker="o", color=BLUE)
    ax.axhline(1, color=GREY, lw=1, ls=":")
    ax.axvline(1216, color=ORANGE, lw=1, ls="--", label="production K")
    ax.set_ylim(0.6, 1.02)
    ax.set_xlabel("Dictionary size K")
    ax.set_ylabel("$\\rho$ vs K=1216")
    ax.set_title("(b) Dictionary-size sensitivity")
    ax.legend(frameon=False, fontsize=8)

    ax = axes[1, 0]
    auc = [
        p10["pca_reconstruction_residual"]["auc_robust_vs_rejected"],
        p10["spectral_energy"]["auc_robust_vs_rejected"],
        autoencoder["metrics"]["pooled"]["auc_robust_vs_ambiguous"],
    ]
    ax.bar(
        ["PCA residual", "Energy", "GW autoencoder"],
        auc,
        color=[BLUE, ORANGE, GREEN],
    )
    ax.axhline(0.5, color=GREY, lw=1, ls="--")
    ax.set_ylim(0.35, 0.65)
    ax.set_ylabel("AUC: ROBUST vs AMBIGUOUS")
    ax.set_title("(c) Representation comparators")

    ax = axes[1, 1]
    pads = [16.0, 64.0, 128.0]
    fixed = [
        white["fixed_pad4_threshold_flips"][str(value)]["flip_rate"] for value in pads
    ]
    recal = [
        white["pad_recalibrated_pipeline_flips"][str(value)]["flip_rate"]
        for value in pads
    ]
    x = np.arange(len(pads))
    width = 0.36
    ax.bar(x - width / 2, fixed, width, color=BLUE, label="fixed pad-4 threshold")
    ax.bar(x + width / 2, recal, width, color=ORANGE, label="recalibrated")
    ax.set_xticks(x, [f"{int(value)} s" for value in pads])
    ax.set_ylim(0, 0.75)
    ax.set_ylabel("Disposition-flip fraction")
    ax.set_title("(d) Whitening context, boundary sample")
    ax.legend(frameon=False, fontsize=7)

    for ax in axes.flat:
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    save(fig, "fig_robustness_q64.png")


def figure_absorption() -> None:
    data = load_json("dsd_absorption_blip_q4-64.json")
    rows = data["rows"]
    x = np.array([row["prevalence"] for row in rows]) * 100
    flagged = np.array([row["flagged_fraction"] for row in rows]) * 100
    z = np.array([row["z_injected_vs_background"] for row in rows])
    control = np.array([row["z_control_same_size_all_background"] for row in rows])
    fig, ax1 = plt.subplots(figsize=(6.6, 4.1))
    ax1.plot(x, flagged, marker="o", color=BLUE, label="fraction above background P99")
    ax1.set_xlabel("Injected prevalence in native-index training set (%)")
    ax1.set_ylabel("Held-out Blip fraction above P99 (%)", color=BLUE)
    ax1.tick_params(axis="y", labelcolor=BLUE)
    ax1.set_ylim(0, 100)
    ax2 = ax1.twinx()
    ax2.plot(x, z, marker="s", color=ORANGE, label="injection/background separation")
    ax2.plot(x, control, marker="^", color=GREY, ls="--", label="same-size control")
    ax2.set_ylabel("Standardized separation $z$", color=ORANGE)
    ax2.tick_params(axis="y", labelcolor=ORANGE)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(
        lines,
        [line.get_label() for line in lines],
        loc="center right",
        bbox_to_anchor=(0.98, 0.58),
        frameon=True,
        facecolor="white",
        edgecolor="none",
        framealpha=0.92,
        fontsize=8,
    )
    ax1.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)
    save(fig, "fig_absorption_q64.png")


def figure_domain_known() -> None:
    domain = load_final_json("cqg_cross_run_domain_shift.json")
    known = load_final_json("cqg_known_glitch_controls.json")
    detectors = ["H1", "L1"]
    colors = [BLUE, ORANGE]
    fig, axes = plt.subplots(2, 2, figsize=(8.4, 6.2))

    ax = axes[0, 0]
    for index, (detector, color) in enumerate(zip(detectors, colors)):
        result = domain["detectors"][detector]["direct_shift_same_o3b_index"]
        point = result["mean_difference"]["difference"]
        low, high = result["mean_difference"]["ci95"]
        ax.errorbar(
            point,
            index,
            xerr=[[point - low], [high - point]],
            fmt="o",
            capsize=4,
            color=color,
        )
    ax.axvline(0, color=GREY, lw=1, ls="--")
    ax.set_yticks(range(2), detectors)
    ax.set_xlabel("O4a minus O3b mean score (95% CI)")
    ax.set_title("(a) Same O3b-index domain shift")

    ax = axes[0, 1]
    for index, (detector, color) in enumerate(zip(detectors, colors)):
        result = domain["detectors"][detector]["native_adaptation"]
        point = result["paired_native_minus_cross_mean"]
        low, high = result["paired_native_minus_cross_ci95"]
        ax.errorbar(
            point,
            index,
            xerr=[[point - low], [high - point]],
            fmt="o",
            capsize=4,
            color=color,
        )
    ax.axvline(0, color=GREY, lw=1, ls="--")
    ax.set_yticks(range(2), detectors)
    ax.set_xlabel("Native minus cross-index score (95% CI)")
    ax.set_title("(b) Effect of native adaptation")

    ax = axes[1, 0]
    for index, (detector, color) in enumerate(zip(detectors, colors)):
        result = domain["detectors"][detector]["run_probe"]
        point = result["auc_oof"]
        low, high = result["auc_oof_bootstrap_ci95"]
        ax.errorbar(
            point,
            index,
            xerr=[[point - low], [high - point]],
            fmt="o",
            capsize=4,
            color=color,
        )
        shuffle_low, shuffle_high = result["shuffle_auc_interval_95"]
        ax.plot([shuffle_low, shuffle_high], [index, index], color=GREY, lw=5, alpha=0.35)
    ax.axvline(0.5, color=GREY, lw=1, ls="--")
    ax.set_xlim(0.35, 1.0)
    ax.set_yticks(range(2), detectors)
    ax.set_xlabel("Out-of-fold run-probe AUC (95% CI)")
    ax.set_title("(c) Representation-level run probe")

    ax = axes[1, 1]
    labels = ["Blip", "Scattered_Light", "Koi_Fish"]
    display = ["Blip", "Scattered Light", "Koi Fish"]
    values = np.array(
        [
            [
                known["detectors"][detector]["metrics"][label]["dante_topk"]["auc"]
                for label in labels
            ]
            for detector in detectors
        ]
    )
    image = ax.imshow(values, vmin=0.5, vmax=1.0, cmap="cividis", aspect="auto")
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            color = "white" if values[row, column] < 0.75 else "black"
            ax.text(
                column,
                row,
                f"{values[row, column]:.3f}",
                ha="center",
                va="center",
                color=color,
                fontsize=9,
            )
    ax.set_xticks(range(3), display, rotation=20, ha="right")
    ax.set_yticks(range(2), detectors)
    ax.set_title("(d) O3b known-glitch ranking AUC")
    cbar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("AUC vs held-out clean")

    for ax in axes.flat:
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    save(fig, "fig_domain_known_q64.png")


def figure_robustness_replicates() -> None:
    data = load_final_json("cqg_robustness_replicates.json")
    axes_spec = [
        ("background_draw", "Background draw", 8),
        ("kmeans_seed", "K-means seed", 5),
        ("k_value", "Dictionary size K", 4),
    ]
    populations = [
        ("near_boundary", "near-boundary", BLUE),
        ("unconditioned", "unconditioned", ORANGE),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(9.4, 3.6), sharey=True)
    for ax, (axis_key, title, n_models) in zip(axes, axes_spec):
        for index, (population, label, color) in enumerate(populations):
            result = data["axes"][axis_key]["populations"][population]
            point = result["pairwise_spearman_mean"]
            low, high = result["bootstrap_ci95"]["pairwise_spearman_mean"]
            ax.errorbar(
                index,
                point,
                yerr=[[point - low], [high - point]],
                fmt="o",
                capsize=4,
                color=color,
                label=label,
            )
            ax.scatter(
                index,
                result["pairwise_spearman_min"],
                marker="v",
                color=color,
                s=36,
                alpha=0.8,
            )
        ax.set_xticks([0, 1], ["near", "uncond."])
        ax.set_ylim(0.75, 1.005)
        ax.set_title(f"{title}\n({n_models} models)")
        ax.axhline(1, color=GREY, lw=1, ls=":")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Pairwise Spearman $\\rho$")
    axes[-1].legend(
        frameon=False,
        fontsize=8,
        loc="lower right",
        title="circles: mean (95% CI)\ntriangles: minimum",
        title_fontsize=7,
    )
    fig.tight_layout()
    save(fig, "fig_robustness_replicates_q64.png")


def figure_absorption_matrix() -> None:
    data = load_final_json("cqg_absorption_matrix.json")
    morphologies = ["Blip", "KoiFish", "ScatteredLight"]
    display = ["Blip", "Koi Fish", "Scattered Light"]
    colors = [BLUE, ORANGE, GREEN]
    fig, axes = plt.subplots(2, 3, figsize=(9.6, 5.8), sharex=True)
    for column, (morphology, label, color) in enumerate(
        zip(morphologies, display, colors)
    ):
        rows = data["summary"][morphology]["rows"]
        prevalence = np.array([row["prevalence"] for row in rows]) * 100
        z_median = np.array([row["z_median"] for row in rows])
        z_low = np.array([row["z_range"][0] for row in rows])
        z_high = np.array([row["z_range"][1] for row in rows])
        flag_median = np.array([row["flagged_fraction_median"] for row in rows])
        flag_low = np.array([row["flagged_fraction_range"][0] for row in rows])
        flag_high = np.array([row["flagged_fraction_range"][1] for row in rows])

        ax = axes[0, column]
        ax.plot(prevalence, z_median, marker="o", color=color)
        ax.fill_between(prevalence, z_low, z_high, color=color, alpha=0.18)
        ax.axhline(3, color=GREY, lw=1, ls="--")
        ax.set_title(label)
        ax.spines[["top", "right"]].set_visible(False)

        ax = axes[1, column]
        ax.plot(prevalence, flag_median, marker="o", color=color)
        ax.fill_between(prevalence, flag_low, flag_high, color=color, alpha=0.18)
        ax.axhline(0.5, color=GREY, lw=1, ls="--")
        crossing = data["summary"][morphology]["crossing_range"]
        if crossing[0] == crossing[1]:
            crossing_label = f"{100 * crossing[0]:g}%"
        else:
            crossing_label = (
                f"{100 * crossing[0]:g}--{100 * crossing[1]:g}%"
            )
        ax.text(
            0.98,
            0.92,
            f"crossing: {crossing_label}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=8,
        )
        ax.set_xlabel("Index contamination prevalence (%)")
        ax.set_ylim(-0.03, 1.03)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0, 0].set_ylabel("Injection/background separation $z$")
    axes[1, 0].set_ylabel("Fraction above background P99")
    fig.tight_layout()
    save(fig, "fig_absorption_matrix_q64.png")


def figure_blind_spot() -> None:
    data = load_json("blind_spot_map_centered_q64_v3_o4a.json")
    frame = pd.DataFrame(data["cells"])
    pivot = frame.pivot(index="q", columns="f0", values="flag_rate").sort_index()
    fig, ax = plt.subplots(figsize=(6.6, 4.5))
    image = ax.imshow(
        pivot.values,
        origin="lower",
        aspect="auto",
        vmin=0,
        vmax=1,
        cmap="viridis",
    )
    ax.set_xticks(np.arange(len(pivot.columns)), [f"{v:g}" for v in pivot.columns])
    ax.set_yticks(np.arange(len(pivot.index)), [f"{v:g}" for v in pivot.index])
    ax.set_xlabel("Sine-Gaussian central frequency $f_0$ (Hz)")
    ax.set_ylabel("Quality factor Q")
    ax.axhline(
        np.where(pivot.index.to_numpy() == 64)[0][0] + 0.5,
        color="white",
        lw=1.2,
        ls="--",
    )
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Primary flag fraction (n=8 per cell)")
    save(fig, "fig_blind_spot_q64.png")


def figure_pem() -> None:
    data = load_json("pem/idxq4-64_queryq4-64/pem_class_association.json")
    endpoint = data["endpoints"]["zero_lag_confirmed"]["by_class"]
    labels = ["ROBUST", "AMBIGUOUS", "BACKGROUND"]
    rates = np.array([endpoint[label]["rate"] for label in labels])
    low = np.array([endpoint[label]["wilson_ci95"][0] for label in labels])
    high = np.array([endpoint[label]["wilson_ci95"][1] for label in labels])
    yerr = np.vstack([rates - low, high - rates])
    fig, ax = plt.subplots(figsize=(6.4, 4.1))
    x = np.arange(len(labels))
    ax.errorbar(
        x,
        rates,
        yerr=yerr,
        fmt="o",
        ms=7,
        capsize=4,
        color=BLUE,
        ecolor=GREY,
    )
    for i, label in enumerate(labels):
        row = endpoint[label]
        ax.text(
            i,
            min(0.48, high[i] + 0.03),
            f"{row['n_positive']}/{row['n_calibrated']}",
            ha="center",
            fontsize=9,
        )
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 0.5)
    ax.set_ylabel("Zero-lag-confirmed coupling fraction")
    ax.set_title("Family-wise PEM calibration; Wilson 95% intervals")
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "fig_pem_q64.png")


def figure_cbc_controls() -> None:
    data = load_json("astrophysical_injection_o4a_idxq4-64_queryq4-64.json")
    frame = pd.DataFrame(data["rows"])
    systems = ["BBH_30_30", "BBH_10_10", "NSBH_10_1.4"]
    colors = [BLUE, ORANGE, GREEN]
    fig, axes = plt.subplots(1, 3, figsize=(10.2, 3.5), sharex=True, sharey=True)
    metrics = [
        ("flag_either", "Primary flag"),
        ("coincidence_recovery", "End-to-end coincidence"),
        (None, "Native ROBUST"),
    ]
    for ax, (metric, title) in zip(axes, metrics):
        for system, color in zip(systems, colors):
            subset = frame[frame["system"] == system].sort_values("distance_mpc")
            records = subset["binomial_endpoints"].tolist()
            if metric is None:
                selected_records = [
                    max(
                        (
                            record["dsd_robust_H1"],
                            record["dsd_robust_L1"],
                        ),
                        key=lambda item: item["rate"],
                    )
                    for record in records
                ]
            else:
                selected_records = [record[metric] for record in records]
            values = np.array([record["rate"] for record in selected_records])
            low = np.array(
                [record["wilson_ci95"][0] for record in selected_records]
            )
            high = np.array(
                [record["wilson_ci95"][1] for record in selected_records]
            )
            ax.errorbar(
                subset["distance_mpc"],
                values,
                yerr=np.vstack([values - low, high - values]),
                fmt="o",
                linestyle="none",
                capsize=2.5,
                color=color,
                ecolor=color,
                label=system.replace("_", " "),
            )
        ax.set_xscale("log", base=2)
        ax.set_xticks([100, 200, 400, 800, 1600])
        ax.set_xticklabels(["100", "200", "400", "800", "1600"], rotation=35)
        ax.set_title(title)
        ax.set_xlabel("Distance (Mpc)")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Fraction of 25 injections")
    axes[0].set_ylim(-0.03, 1.0)
    axes[-1].legend(frameon=False, fontsize=8, loc="upper right")
    fig.tight_layout()
    save(fig, "fig_cbc_controls_q64.png")


def figure_catalog_null() -> None:
    path = (
        AGG
        / "catalog_cross_match_null_circular_shift_v2_idxq4-64_queryq4-64_o4a.csv"
    )
    frame = pd.read_csv(path)
    candidates = [
        column for column in frame.columns if "overlap_any" in column.lower()
    ]
    if not candidates:
        raise KeyError(f"Cannot locate overlap-any column in {list(frame.columns)}")
    values = frame[candidates[0]].to_numpy()
    fig, ax = plt.subplots(figsize=(6.3, 4.0))
    bins = np.arange(values.min() - 0.5, values.max() + 1.5, 1)
    ax.hist(values, bins=bins, density=True, color=BLUE, alpha=0.8)
    ax.axvline(2, color=RED, lw=2, label="observed = 2")
    ax.set_xlabel("Catalogue-window overlaps after circular shift")
    ax.set_ylabel("Probability")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "fig_catalog_null_q64.png")


if __name__ == "__main__":
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.titlesize": 10,
            "axes.labelsize": 10,
            "figure.facecolor": "white",
        }
    )
    figure_funnel()
    figure_robustness()
    figure_absorption()
    figure_domain_known()
    figure_robustness_replicates()
    figure_absorption_matrix()
    figure_blind_spot()
    figure_pem()
    figure_cbc_controls()
    figure_catalog_null()
    print(f"Wrote v6 figures to {OUT}")
