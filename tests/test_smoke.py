"""Fast setup check for a freshly cloned repository.

Answers one question in under 30 seconds: *is this checkout usable?* It never
downloads the encoder and never touches the network, so a failure here is a
setup problem, not an analysis problem.

    pytest -m smoke

Deliberately asserts on things a newcomer gets wrong first: missing
dependencies, a missing reference index, an unregistered CLI command. Each
failure message says what to do next rather than only what broke.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

ROOT = Path(__file__).resolve().parents[1]

# Modules that must import without a model download or network access.
CORE_MODULES = [
    "src.core.utils",
    "src.core.preprocessor",
    "src.core.data_loader",
    "src.core.injection",
]

PRODUCTION_MODULES = [
    "src.pipeline_v2_production.aggregate_report",
    "src.pipeline_v2_production.coincidence_physical",
    "src.pipeline_v2_production.coincidence_physical_efficiency",
    "src.pipeline_v2_production.background_cohesion_test",
    "src.pipeline_v2_production.poisson_upper_limit",
]

# Commands the README and CLI_REFERENCE promise exist.
DOCUMENTED_COMMANDS = [
    "fetch-raw",
    "patch-analysis",
    "aggregate-report",
    "multiscale-analysis",
    "coincidence-physical",
    "coincidence-efficiency",
    "background-cohesion",
    "dsd-absorption",
    "inter-session-recurrence",
    "dsd-index-stability",
    "pem-coherence-analysis",
    "poisson-upper-limit",
]


@pytest.mark.parametrize("mod", CORE_MODULES + PRODUCTION_MODULES)
def test_module_imports(mod: str) -> None:
    """Every pipeline module imports cleanly."""
    try:
        importlib.import_module(mod)
    except ImportError as e:  # noqa: PERF203 - message matters more than speed
        pytest.fail(
            f"Cannot import {mod}: {e}\n"
            "Install dependencies with:  pip install -r requirements.txt"
        )


def test_third_party_stack_present() -> None:
    """The scientific stack the pipeline is built on is installed."""
    missing = []
    for pkg in ["numpy", "scipy", "pandas", "torch", "gwpy", "h5py",
                "sklearn", "matplotlib"]:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    assert not missing, (
        f"Missing packages: {', '.join(missing)}\n"
        "Install with:  pip install -r requirements.txt"
    )


def test_config_loads() -> None:
    """config.yaml parses and declares the detectors."""
    from src.core.utils import load_config

    cfg = load_config()
    assert isinstance(cfg, dict) and cfg, "config.yaml parsed to an empty config"
    detectors = cfg.get("detectors")
    assert detectors, "config.yaml declares no 'detectors' key"


def test_cli_registers_documented_commands() -> None:
    """Every command promised in the docs is actually wired into main.py.

    Guards the failure mode where a module exists but is unreachable, which is
    indistinguishable from a missing feature for anyone reading the docs.
    """
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    missing = [c for c in DOCUMENTED_COMMANDS if f'"{c}"' not in text]
    assert not missing, (
        f"Commands documented but not registered in main.py: {missing}"
    )


def test_reference_index_present_or_explains_itself() -> None:
    """The VQ reference index is required by every analysis command.

    Skips rather than fails when absent: a fresh clone legitimately does not
    have it yet, but the reader is told exactly where to get it.
    """
    ref_dir = ROOT / "data" / "reference"
    indices = sorted(ref_dir.glob("patch_compressed_index*.npz")) if ref_dir.is_dir() else []
    if not indices:
        pytest.skip(
            "No reference index in data/reference/. Nothing will run without it.\n"
            "Download it from the Zenodo record (DOI 10.5281/zenodo.21451803):\n"
            "  data/reference/patch_compressed_index_o4a_ex.npz  (native O4a, K=1216)\n"
            "  data/reference/patch_compressed_index_o3b.npz     (primary O3b, K=275)"
        )

    import numpy as np

    with np.load(indices[0], allow_pickle=True) as z:
        assert "embeddings" in z, (
            f"{indices[0].name} has no 'embeddings' array — file is corrupt or "
            "is not a DANTE reference index."
        )
        emb = z["embeddings"]
    assert emb.ndim == 2 and emb.shape[1] == 384, (
        f"Expected (K, 384) DINOv2 embeddings, got {emb.shape}"
    )


def test_saliency_callers_pass_the_production_scorer() -> None:
    """Published saliency panels must show the patches the pipeline pooled.

    `generate_saliency_map` falls back to a session-local spatial background
    when no `scorer` is given. That fallback ranks patches by a different
    quantity than the novelty score, so its boxes are not the production
    Top-k. Every call site that can produce a figure for publication therefore
    has to pass the scorer explicitly; this test exists because they all
    silently did not (see paper_draft/CORRECTIONS_2026-07-21.md, C2).
    """
    import re

    targets = [
        ROOT / "src" / "pipeline_v2_production" / "production_report.py",
        ROOT / "scripts" / "regenerate_singleton_saliency.py",
    ]
    offenders = []
    for path in targets:
        if not path.exists():
            continue  # scripts/ is gitignored, so a fresh clone has no copy
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"generate_saliency_map\(", text):
            if text[m.end()] == ")":
                continue  # prose mention like ``generate_saliency_map()``
            # Take the call's argument list by matching parentheses.
            depth, i = 1, m.end()
            while i < len(text) and depth:
                depth += (text[i] == "(") - (text[i] == ")")
                i += 1
            if "scorer=" not in text[m.end():i]:
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{path.name}:{line}")

    assert not offenders, (
        "generate_saliency_map called without scorer= at: "
        + ", ".join(offenders)
        + ". Pass the production PatchScorer, or the panel shows the "
        "diagnostic spatial-background ranking instead of the Top-k."
    )


def test_environment_is_recorded_with_artifacts(tmp_path) -> None:
    """A run that writes results must also write the versions that made them.

    The published O4a artifacts cannot be regenerated because the dependency
    set that produced them was never recorded and gwpy has since gone 3.x ->
    4.x, changing both the whitening and the Q-transform. Provenance is
    therefore a pipeline output, not a convenience.
    """
    import json

    from src.core.utils import record_environment

    dest = record_environment(tmp_path, "smoke")
    assert dest is not None and dest.exists(), "record_environment wrote nothing"

    record = json.loads(dest.read_text(encoding="utf-8"))
    assert "gwpy" in record["packages"], (
        "gwpy version missing from the provenance record — it supplies both "
        "whiten() and q_transform(), so its version is the one that matters most."
    )
    for key in ("git_commit", "python", "platform", "torch", "reference_index_md5"):
        assert key in record, f"provenance record has no '{key}'"


def test_artifact_writers_record_the_environment() -> None:
    """The three classes that write artifacts all call record_environment."""
    writers = {
        "production_writer.py": "src/pipeline_v2_production/production_writer.py",
        "production_report.py": "src/pipeline_v2_production/production_report.py",
        "aggregate_report.py": "src/pipeline_v2_production/aggregate_report.py",
    }
    missing = [
        name for name, rel in writers.items()
        if "record_environment(" not in (ROOT / rel).read_text(encoding="utf-8")
    ]
    assert not missing, (
        f"These write artifacts without recording the environment: {missing}"
    )


def test_pem_reports_a_missing_nds2_client_as_such() -> None:
    """A missing NDS2 client must not masquerade as absent auxiliary data.

    Without `nds2`, gwpy answers every auxiliary fetch with "no valid sources
    found", which reads as "this channel has no data here". That is how a
    whole PEM batch gets written off as a coverage gap when the real cause is
    a package that pip cannot install (conda-forge: nds2-client).
    """
    from src.pipeline_v2_production.pem_coherence_analysis import require_nds2

    available = require_nds2()
    assert isinstance(available, bool)
    if not available:
        pytest.skip(
            "nds2 not importable in this interpreter, so the PEM veto cannot "
            "run here. Use the conda environment that has it:\n"
            "  conda install -c conda-forge nds2-client python-nds2-client"
        )
