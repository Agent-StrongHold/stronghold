"""Tests for CLI entry point module."""

from __future__ import annotations

from pathlib import Path

CLI_MAIN_PATH = Path("src/stronghold/cli/main.py")


def test_cli_main_py_exists() -> None:
    assert CLI_MAIN_PATH.exists(), "src/stronghold/cli/main.py should exist"


def test_cli_main_py_contains_typer_app() -> None:
    content = CLI_MAIN_PATH.read_text()
    assert "typer" in content.lower(), "File should import typer"
    assert "app" in content.lower(), "File should initialize a Typer app"
