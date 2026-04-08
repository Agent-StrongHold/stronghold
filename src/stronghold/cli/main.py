"""CLI entry point for Stronghold."""

import typer

app = typer.Typer()


@app.command()
def main() -> None:
    """Main CLI command."""
    print("Stronghold CLI is working!")


@app.command()
def version() -> None:
    """Show version information."""
    print("Stronghold version 0.1.0")


if __name__ == "__main__":
    app()
