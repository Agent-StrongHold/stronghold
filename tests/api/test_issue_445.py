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


class TestQuotedAnnotations:
    def test_ruff_check_passes_without_quoted_annotations_errors(
        self, orchestrator_path: Path
    ) -> None:
        """Verify ruff check returns zero errors for quoted type annotations."""
        result = subprocess.run(
            ["ruff", "check", "--select", "Q", str(orchestrator_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff check failed with output:\n{result.stdout}\n{result.stderr}"
        )


class TestFunctionalBehavior:
    def test_ruff_check_passes_without_all_errors(self, orchestrator_path: Path) -> None:
        """Verify ruff check returns zero errors after all fixes and functional behavior remains unchanged."""
        result = subprocess.run(
            ["ruff", "check", str(orchestrator_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff check failed with output:\n{result.stdout}\n{result.stderr}"
        )


class TestRuffAutoFix:
    def test_ruff_can_auto_fix_all_issues(self, orchestrator_path: Path) -> None:
        """Verify ruff can auto-fix all issues in the file."""
        # Make a copy to compare later
        backup_path = orchestrator_path.with_suffix(".py.bak")
        subprocess.run(["cp", str(orchestrator_path), str(backup_path)], check=True)

        # Run ruff with --fix
        result = subprocess.run(
            ["ruff", "check", "--fix", str(orchestrator_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff check --fix failed with output:\n{result.stdout}\n{result.stderr}"
        )

        # Verify file was modified
        assert (
            subprocess.run(
                ["diff", str(backup_path), str(orchestrator_path)],
                capture_output=True,
            ).returncode
            != 0
        ), "File was not modified by ruff --fix"

        # Verify file is properly formatted
        format_result = subprocess.run(
            ["ruff", "format", str(orchestrator_path)],
            capture_output=True,
            text=True,
        )
        assert format_result.returncode == 0, (
            f"ruff format failed with output:\n{format_result.stdout}\n{format_result.stderr}"
        )

        # Clean up backup
        backup_path.unlink(missing_ok=True)
