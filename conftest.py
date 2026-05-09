"""Pytest configuration — shared markers and CLI options."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register --run-slow CLI flag for tests requiring model downloads."""
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow tests that download models (~90 MB).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Auto-skip @pytest.mark.slow tests unless --run-slow is provided."""
    if config.getoption("--run-slow"):
        return
    skip_slow = pytest.mark.skip(
        reason="Requires model download. Use --run-slow."
    )
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)
