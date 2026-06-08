from __future__ import annotations

import typer

app = typer.Typer(help="Configuration management commands.")


@app.callback()
def config() -> None:
    """Manage and validate Athena configuration."""
