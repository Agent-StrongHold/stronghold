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


def test_pyproject_toml_scripts_entry_format() -> None:
    pyproject_path = Path("pyproject.toml")
    content = pyproject_path.read_text()

    scripts_section = "[project.scripts]"
    start = content.find(scripts_section)
    assert start != -1, "Could not find [project.scripts] section"

    end = content.find("\n[", start + 1)
    if end == -1:
        end = len(content)

    scripts_content = content[start:end]
    assert "stronghold =" in scripts_content, (
        "Scripts section should contain 'stronghold =' assignment"
    )
    assert "src/stronghold/cli/main.py:app" in scripts_content, (
        "Scripts section should point to 'src/stronghold/cli/main.py:app'"
    )


def test_stronghold_cli_command_shows_version() -> None:
    import subprocess

    result = subprocess.run(
        ["stronghold", "--version"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "stronghold --version should exit with code 0"
    assert "version" in result.stdout.lower(), "Output should contain version information"


def test_stronghold_cli_invalid_arg_fails() -> None:
    import subprocess

    result = subprocess.run(
        ["stronghold", "--invalid-arg"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, "stronghold --invalid-arg should exit with non-zero code"
    assert "Error:" in result.stderr, "Output should contain 'Error:'"
    assert "no such option" in result.stderr.lower(), "Output should contain 'no such option'"


def test_stronghold_cli_version_output_contains_stronghold() -> None:
    import subprocess

    result = subprocess.run(
        ["stronghold", "--version"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "stronghold --version should exit with code 0"
    assert "stronghold" in result.stdout.lower(), "Output should contain 'stronghold'"
