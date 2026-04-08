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


def test_pyproject_toml_has_correct_scripts_entry() -> None:
    pyproject_path = Path("pyproject.toml")
    assert pyproject_path.exists(), "pyproject.toml should exist"

    content = pyproject_path.read_text()
    assert "[project.scripts]" in content, "pyproject.toml should contain [project.scripts] section"

    scripts_section = "[project.scripts]"
    start = content.find(scripts_section)
    assert start != -1, "Could not find [project.scripts] section"

    end = content.find("\n[", start + 1)
    if end == -1:
        end = len(content)

    scripts_content = content[start:end]
    assert "stronghold = 'src.stronghold.cli.main:app'" in scripts_content, (
        "Scripts section should include 'stronghold = 'src.stronghold.cli.main:app''"
    )


def test_stronghold_cli_help_output() -> None:
    import subprocess

    result = subprocess.run(
        ["stronghold", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "stronghold --help should exit with code 0"
    assert "Usage:" in result.stdout, "Output should contain 'Usage:'"
    assert "Options:" in result.stdout, "Output should contain 'Options:'"
