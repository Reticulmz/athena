from __future__ import annotations

import typer

app = typer.Typer(help="Environment file management commands.")


@app.callback()
def env() -> None:
    """Manage Athena environment files."""
