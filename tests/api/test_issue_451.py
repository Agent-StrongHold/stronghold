"""Tests for removing quoted type annotations in services.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SERVICES_PATH = Path("src/stronghold/builders/services.py")


@pytest.fixture
def services_file() -> Path:
    """Fixture providing the services.py file path."""
    return SERVICES_PATH


class TestQuotedTypeAnnotations:
    def test_no_up037_errors_in_services(self, services_file: Path) -> None:
        """Test that no UP037 errors exist in services.py after removing quoted annotations."""
        result = subprocess.run(
            ["ruff", "check", str(services_file)],
            capture_output=True,
            text=True,
        )
        assert "UP037" not in result.stdout, "UP037 errors found in services.py"
        assert "UP037" not in result.stderr, "UP037 errors found in services.py"

        # Verify line 63 doesn't contain quoted type annotation
        lines = services_file.read_text().splitlines()
        line_63 = lines[62]  # 0-indexed
        assert not line_63.strip().startswith(("status: str =", "status: 'str' =")), (
            "Line 63 still contains quoted type annotation"
        )
