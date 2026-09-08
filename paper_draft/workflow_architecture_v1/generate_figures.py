"""Generate architecture-paper figures from the frozen workflow contract."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


PAPER_DIR = Path(__file__).resolve().parent
REPO_ROOT = PAPER_DIR.parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "dante_workflow_productization_v1.json"
FIGURE_DIR = PAPER_DIR / "figures"

NAVY = "#17324D"
BLUE = "#2B6F9F"
LIGHT_BLUE = "#DCEEF8"
GREEN = "#2D7D46"
LIGHT_GREEN = "#E3F3E7"
AMBER = "#A86500"
LIGHT_AMBER = "#FFF0D2"
RED = "#A33A32"
LIGHT_RED = "#F8E2DF"
GRAY = "#56616B"
LIGHT_GRAY = "#EEF1F3"


def load_contract() -> dict:
    contract = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    stages = contract["stages"]
    if len(stages) != 15:
        raise RuntimeError(f"expected frozen 15-stage graph, found {len(stages)}")
    names = {stage["name"] for stage in stages}
    for stage in stages:
        unknown = {item["stage"] for item in stage["dependencies"]} - names
        if unknown:
            raise RuntimeError(f"{stage['name']} has unknown dependencies: {unknown}")
    return contract


def add_box(
    ax: plt.Axes,
    center: tuple[float, float],
    text: str,
    *,
    width: float = 1.82,
    height: float = 0.58,
    facecolor: str = LIGHT_BLUE,
    edgecolor: str = BLUE,
    fontsize: float = 8.0,
) -> None:
    x, y = center
    patch = FancyBboxPatch(
        (x - width / 2, y - height / 2),
        width,
        height,
        boxstyle="round,pad=0.04,rounding_size=0.08",
        linewidth=1.15,
        edgecolor=edgecolor,
        facecolor=facecolor,
        zorder=3,
    )
    ax.add_patch(patch)
    ax.text(
        x, y, text, ha="center", va="center", fontsize=fontsize, color=NAVY, zorder=4
    )


def add_arrow(
    ax: plt.Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str = GRAY,
    style: str = "-",
    rad: float = 0.0,
    label: str | None = None,
    label_offset: tuple[float, float] = (0.0, 0.0),
) -> None:
    ax.annotate(
        "",
        xy=end,
        xytext=start,
        arrowprops={
            "arrowstyle": "-|>",
            "color": color,
            "lw": 1.2,
            "mutation_scale": 13,
            "linestyle": style,
            "connectionstyle": f"arc3,rad={rad}",
            "shrinkA": 17,
            "shrinkB": 17,
        },
        zorder=2,
    )
    if label:
        x = (start[0] + end[0]) / 2 + label_offset[0]
        y = (start[1] + end[1]) / 2 + label_offset[1]
        ax.text(
            x,
            y,
            label,
            ha="center",
            va="center",
            fontsize=7.1,
            color=color,
            bbox={
                "boxstyle": "round,pad=0.15",
                "facecolor": "white",
                "edgecolor": "none",
            },
            zorder=5,
        )


def save_figure(fig: plt.Figure, stem: str) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_DIR / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(FIGURE_DIR / f"{stem}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def workflow_dag(contract: dict) -> None:
    positions = {
        "PREFLIGHT": (0.8, 3.0),
        "ACQUIRE": (2.3, 3.0),
        "CALIBRATE": (3.8, 3.0),
        "SCAN": (5.3, 3.0),
        "COHORT": (6.8, 3.0),
        "INDEX": (8.3, 3.0),
        "NATIVE_CALIBRATION": (9.8, 3.0),
        "RESCORE": (11.3, 3.0),
        "THRESHOLDS": (0.8, 1.15),
        "CLASSIFY": (2.3, 1.15),
        "TAXONOMY": (3.8, 1.15),
        "COINCIDENCE": (5.3, 1.15),
        "PEM": (6.8, 1.15),
        "COMPARE": (8.3, 1.15),
        "REPORT": (9.8, 1.15),
    }
    labels = {
        "NATIVE_CALIBRATION": "07  NATIVE\nCALIBRATION",
        "COINCIDENCE": "12  COINCIDENCE",
    }
    stages = {stage["name"]: stage for stage in contract["stages"]}
    if set(positions) != set(stages):
        raise RuntimeError("figure layout and frozen stage set differ")

    stage_numbers = {
        stage["name"]: number for number, stage in enumerate(contract["stages"], 1)
    }

    fig, ax = plt.subplots(figsize=(12.8, 4.0))
    ax.set_xlim(-0.15, 12.55)
    ax.set_ylim(-0.05, 3.65)
    ax.axis("off")

    for name, center in positions.items():
        adaptive = name in {"INDEX", "NATIVE_CALIBRATION", "RESCORE"}
        terminal = name == "REPORT"
        add_box(
            ax,
            center,
            labels.get(name, f"{stage_numbers[name]:02d}  {name}"),
            width=1.35 if name == "NATIVE_CALIBRATION" else 1.28,
            height=0.58,
            facecolor=LIGHT_GREEN
            if adaptive
            else LIGHT_AMBER
            if terminal
            else LIGHT_BLUE,
            edgecolor=GREEN if adaptive else AMBER if terminal else BLUE,
            fontsize=6.0 if name in {"NATIVE_CALIBRATION", "COINCIDENCE"} else 6.5,
        )

    for destination, stage in stages.items():
        for dependency in stage["dependencies"]:
            source = dependency["stage"]
            artifact_edge = dependency.get("artifact") == "index_window_manifest"
            if (source, destination) == ("RESCORE", "THRESHOLDS"):
                continue
            add_arrow(
                ax,
                positions[source],
                positions[destination],
                color=GREEN if artifact_edge else GRAY,
                style="--" if artifact_edge else "-",
                rad=-0.18
                if artifact_edge
                else 0.28
                if (source, destination)
                in {("COHORT", "NATIVE_CALIBRATION"), ("INDEX", "RESCORE")}
                else 0.0,
                label="index-window manifest" if artifact_edge else None,
                label_offset=(0.0, -0.63),
            )

    # Keep every numbered row left-to-right.  The only row wrap is routed around
    # the boxes so the visual order cannot be mistaken for a reversed chain.
    ax.plot(
        [11.94, 12.3, 12.3, 0.08, 0.08],
        [3.0, 3.0, 0.35, 0.35, 1.15],
        color=GRAY,
        linewidth=1.2,
        zorder=1,
    )
    ax.annotate(
        "",
        xy=positions["THRESHOLDS"],
        xytext=(0.08, 1.15),
        arrowprops={
            "arrowstyle": "-|>",
            "color": GRAY,
            "lw": 1.2,
            "mutation_scale": 13,
            "shrinkA": 0,
            "shrinkB": 17,
        },
        zorder=2,
    )
    ax.text(
        11.88,
        0.55,
        "08 → 09",
        ha="right",
        va="center",
        fontsize=7.0,
        color=GRAY,
        weight="bold",
    )

    ax.text(
        0.18,
        3.5,
        "Read numbered nodes 01 → 15; every row runs left to right",
        ha="left",
        va="center",
        fontsize=9.5,
        color=NAVY,
        weight="bold",
    )
    ax.text(
        7.45,
        3.5,
        "Detector-aware native adaptation",
        ha="left",
        va="center",
        fontsize=9.5,
        color=GREEN,
        weight="bold",
    )
    ax.text(
        0.18,
        1.7,
        "Classification and diagnostic follow-up",
        ha="left",
        va="center",
        fontsize=9.5,
        color=NAVY,
        weight="bold",
    )
    ax.text(
        10.55,
        1.15,
        "Verified human-readable output",
        ha="left",
        va="center",
        fontsize=8.4,
        color=AMBER,
    )
    save_figure(fig, "fig_workflow_dag")


def runtime_boundary() -> None:
    fig, ax = plt.subplots(figsize=(10.8, 5.1))
    ax.set_xlim(-0.25, 10.95)
    ax.set_ylim(0, 5.3)
    ax.axis("off")

    add_box(ax, (0.9, 4.45), "Operator", facecolor=LIGHT_GRAY, edgecolor=GRAY)
    add_box(ax, (3.2, 4.75), "Command line")
    add_box(ax, (3.2, 3.85), "Browser")
    add_box(ax, (5.55, 3.85), "Loopback UI server", width=2.15)
    add_box(ax, (5.55, 4.75), "Shared orchestrator", width=2.15)
    add_box(ax, (8.05, 4.75), "Detached worker", facecolor=LIGHT_GREEN, edgecolor=GREEN)
    add_box(
        ax, (8.05, 3.55), "Mutable progress", facecolor=LIGHT_AMBER, edgecolor=AMBER
    )
    add_box(
        ax,
        (8.05, 2.35),
        "Attempt artifacts\nand logs",
        facecolor=LIGHT_GRAY,
        edgecolor=GRAY,
    )
    add_box(ax, (5.55, 1.35), "Stage verifier", facecolor=LIGHT_GREEN, edgecolor=GREEN)
    add_box(
        ax,
        (3.0, 1.35),
        "Immutable stage receipt",
        width=2.2,
        facecolor=LIGHT_GREEN,
        edgecolor=GREEN,
    )
    add_box(
        ax,
        (0.85, 1.35),
        "Final receipt\nand report",
        facecolor=LIGHT_AMBER,
        edgecolor=AMBER,
    )

    add_arrow(ax, (0.9, 4.45), (3.2, 4.75))
    add_arrow(ax, (0.9, 4.45), (3.2, 3.85))
    add_arrow(
        ax,
        (3.2, 3.85),
        (5.55, 3.85),
        label="HTTP on 127.0.0.1",
        label_offset=(0, 0.42),
    )
    add_arrow(ax, (5.55, 3.85), (5.55, 4.75))
    add_arrow(ax, (3.2, 4.75), (5.55, 4.75))
    add_arrow(ax, (5.55, 4.75), (8.05, 4.75))
    add_arrow(ax, (8.05, 4.75), (8.05, 3.55))
    add_arrow(ax, (8.05, 4.75), (8.05, 2.35), rad=0.12)
    add_arrow(ax, (8.05, 2.35), (5.55, 1.35))
    add_arrow(ax, (5.55, 1.35), (3.0, 1.35))
    add_arrow(ax, (3.0, 1.35), (0.85, 1.35))

    ax.text(
        5.45,
        3.25,
        "UI exit does not affect the worker lease",
        ha="center",
        fontsize=8.2,
        color=GRAY,
    )
    ax.text(
        8.05,
        2.96,
        "replaceable operational state",
        ha="center",
        fontsize=7.8,
        color=AMBER,
    )
    ax.text(
        4.25,
        0.65,
        "Scientific logic stays behind stage commands and verifiers",
        ha="center",
        fontsize=8.6,
        color=NAVY,
    )
    ax.text(
        9.25,
        1.25,
        "No scientific stage runs\nin an HTTP request",
        ha="center",
        fontsize=8.3,
        color=RED,
    )
    save_figure(fig, "fig_runtime_boundary")


def evidence_lifecycle() -> None:
    fig, ax = plt.subplots(figsize=(10.8, 4.4))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 4.5)
    ax.axis("off")

    nodes = [
        ((1.0, 3.45), "Frozen inputs", LIGHT_BLUE, BLUE),
        ((3.25, 3.45), "Content-addressed\nrun key", LIGHT_BLUE, BLUE),
        ((5.5, 3.45), "Unique attempt", LIGHT_GRAY, GRAY),
        ((7.75, 3.45), "Stage verification", LIGHT_GREEN, GREEN),
        ((10.0, 3.45), "Immutable evidence", LIGHT_GREEN, GREEN),
        ((7.75, 1.25), "New attempt under\nsame contract", LIGHT_AMBER, AMBER),
        ((10.0, 1.25), "Fail closed", LIGHT_RED, RED),
    ]
    for center, label, face, edge in nodes:
        add_box(
            ax, center, label, width=1.9, height=0.72, facecolor=face, edgecolor=edge
        )

    add_arrow(ax, (1.0, 3.45), (3.25, 3.45))
    add_arrow(ax, (3.25, 3.45), (5.5, 3.45))
    add_arrow(ax, (5.5, 3.45), (7.75, 3.45))
    add_arrow(ax, (7.75, 3.45), (10.0, 3.45), color=GREEN)
    add_arrow(ax, (7.75, 3.45), (7.75, 1.25), color=AMBER)
    add_arrow(ax, (7.75, 1.25), (5.5, 3.45), color=AMBER, rad=-0.22)
    add_arrow(ax, (7.75, 3.45), (10.0, 1.25), color=RED)

    ax.text(8.87, 3.78, "PASS", ha="center", fontsize=8.3, color=GREEN)
    ax.text(
        7.18, 2.62, "interrupted or incomplete", ha="right", fontsize=8.0, color=AMBER
    )
    ax.text(6.15, 1.86, "retry", ha="center", fontsize=8.0, color=AMBER)
    ax.text(
        9.58, 2.72, "digest or contract mismatch", ha="center", fontsize=8.0, color=RED
    )

    ax.text(
        5.5,
        4.18,
        "Outcomes remain hidden until the corresponding evidence verifies",
        ha="center",
        fontsize=10,
        color=NAVY,
        weight="bold",
    )
    ax.text(
        3.25,
        2.45,
        "Run identity binds code, config, data manifest, and environment",
        ha="center",
        fontsize=8.2,
        color=GRAY,
    )
    ax.text(
        9.0,
        0.45,
        "Divergent evidence is preserved, never overwritten",
        ha="center",
        fontsize=8.5,
        color=RED,
    )
    save_figure(fig, "fig_evidence_lifecycle")


def main() -> None:
    contract = load_contract()
    workflow_dag(contract)
    runtime_boundary()
    evidence_lifecycle()
    print(f"generated architecture figures in {FIGURE_DIR}")


if __name__ == "__main__":
    main()
