"""CLI entry point for Stronghold."""

import typer

app = typer.Typer()


@app.command()
def main() -> None:
    """Main CLI command."""
    print("Stronghold CLI is working!")


if __name__ == "__main__":
    app()
