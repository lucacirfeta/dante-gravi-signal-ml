from __future__ import annotations

import importlib.util
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "paper_draft" / "v6_paper" / "tools" / "generate_candidate_and_method_figures.py"
if not SCRIPT.is_file():
    pytest.skip(
        "private paper workspace is not included in the public checkout",
        allow_module_level=True,
    )
SPEC = importlib.util.spec_from_file_location("v6_candidate_figures", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_candidate_evidence_uses_detector_gps_and_current_taxonomy() -> None:
    evidence = module.load_candidate_evidence()
    assert evidence["taxonomy"]["detector"] == "L1"
    assert evidence["taxonomy"]["gps_start"] == 1382955228.0
    assert evidence["taxonomy"]["robustness_class"] == "ROBUST"
    assert abs(evidence["taxonomy"]["native_o4a_score"] - 0.5988767743110657) < 1e-12
    assert [row["scale_s"] for row in evidence["multiscale"]] == [0.5, 1.0, 2.0, 4.0]
    assert evidence["pem"]["verdict"] == "NO_CORRELATION"
    assert evidence["characterize"]["feature_gps"] == 1382955253.17


def test_pipeline_schematic_names_the_scientific_boundaries(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(module, "FIGURES", tmp_path)
    monkeypatch.setattr(module, "PAPER_DIRS", [])
    output = module.generate_pipeline_overview()
    assert output.is_file() and output.stat().st_size > 10_000


def test_frozen_native_index_hash() -> None:
    assert module.sha256(module.INDEX) == module.EXPECTED_INDEX_SHA256


def test_manuscripts_include_current_candidate_evidence() -> None:
    arxiv = (ROOT / "paper_draft" / "v6_paper" / "arxiv_v6" / "main.tex").read_text(encoding="utf-8")
    cqg = (ROOT / "paper_draft" / "v6_paper" / "cqg_v6" / "main.tex").read_text(encoding="utf-8")
    for text in (arxiv, cqg):
        assert "1382955228" in text
        assert "1382955253.17" in text
        assert "fig_candidate_saliency_q64.png" in text
        assert "fig_catalog_null_q64.png" in text
        assert "not evidence for a new glitch class" in text or "no new glitch class is claimed" in text
    assert "fig_pipeline_overview.png" not in arxiv
    assert "fig_pipeline_overview.png" in cqg
    assert "fig_representation_examples.png" in cqg
