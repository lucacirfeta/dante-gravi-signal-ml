"""Packaging-boundary checks; no scientific stages are executed."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.smoke


def _run_module(*args: str, pythonpath: Path | None = None) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    if pythonpath is not None:
        environment["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        (sys.executable, *args),
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_pyproject_packages_only_the_workflow_boundary() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "dante-workflow"
    assert metadata["project"]["version"] == "3.8.0"
    assert metadata["project"]["license"] == "GPL-3.0-only"
    assert metadata["project"]["dependencies"] == []
    assert metadata["project"]["scripts"] == {
        "dante-workflow": "dante_workflow.cli:main",
        "dante-workflow-ui": "dante_workflow.ui.cli:main",
    }
    assert metadata["tool"]["setuptools"]["include-package-data"] is False
    assert metadata["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "dante_workflow",
        "dante_workflow.*",
    ]


def test_release_metadata_is_consistent_and_does_not_relabel_old_doi() -> None:
    package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))

    assert citation["version"] == package["project"]["version"] == "3.8.0"
    assert citation["date-released"] == "2026-09-10"
    assert citation["license"] == package["project"]["license"] == "GPL-3.0-only"
    assert citation["doi"] == "10.5281/zenodo.22681395"
    historical = [
        item
        for item in citation["references"]
        if item.get("type") == "software" and item.get("version") == "3.7.0"
    ]
    assert len(historical) == 1
    assert historical[0]["doi"] == "10.5281/zenodo.21912589"


def test_checkout_wrapper_and_package_module_have_identical_plan(tmp_path: Path) -> None:
    common = (
        "plan",
        "--repository-root",
        str(ROOT),
        "--raw-root",
        str(tmp_path / "raw"),
        "--cache-root",
        str(tmp_path / "cache"),
        "--workflow-root",
        str(tmp_path / "workflow"),
    )
    wrapper = _run_module("scripts/run_dante_workflow.py", *common)
    package = _run_module(
        "-m", "dante_workflow.cli", *common, pythonpath=ROOT / "src"
    )

    wrapper_plan = json.loads(wrapper.stdout)
    package_plan = json.loads(package.stdout)
    assert wrapper_plan == package_plan
    assert wrapper_plan["run_key"] == package_plan["run_key"]


def test_base_package_does_not_import_optional_ui_runtime() -> None:
    completed = _run_module(
        "-c",
        "import dante_workflow, dante_workflow.ui; "
        "assert 'flask' not in __import__('sys').modules",
        pythonpath=ROOT / "src",
    )

    assert completed.returncode == 0


def test_ui_package_data_is_declared_and_present() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = metadata["tool"]["setuptools"]["package-data"]["dante_workflow.ui"]

    assert declared == ["static/*.css", "static/*.js", "templates/*.html"]
    assert (ROOT / "src/dante_workflow/ui/static/app.css").is_file()
    assert (ROOT / "src/dante_workflow/ui/static/app.js").is_file()
    assert (ROOT / "src/dante_workflow/ui/templates/base.html").is_file()
