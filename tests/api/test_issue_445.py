"""Tests for unused imports in orchestrator.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ORCHESTRATOR_PATH = Path("src/stronghold/builders/orchestrator.py")


@pytest.fixture
def orchestrator_path() -> Path:
    """Path to the orchestrator.py file."""
    return ORCHESTRATOR_PATH


class TestUnusedImports:
    def test_ruff_check_passes_without_unused_imports(self, orchestrator_path: Path) -> None:
        """Verify ruff check returns zero errors for unused imports."""
        result = subprocess.run(
            ["ruff", "check", str(orchestrator_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff check failed with output:\n{result.stdout}\n{result.stderr}"
        )


class TestImportSorting:
    def test_ruff_check_passes_without_import_sorting_errors(self, orchestrator_path: Path) -> None:
        """Verify ruff check returns zero errors for import sorting."""
        result = subprocess.run(
            ["ruff", "check", "--select", "I", str(orchestrator_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff check failed with output:\n{result.stdout}\n{result.stderr}"
        )
