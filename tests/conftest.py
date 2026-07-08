"""Shared test fixtures and configuration for gh-blast-radius tests."""

from __future__ import annotations

from pathlib import Path

import pytest

# Path to the fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the test fixtures directory."""
    return FIXTURES_DIR
