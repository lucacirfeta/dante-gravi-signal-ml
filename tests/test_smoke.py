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
