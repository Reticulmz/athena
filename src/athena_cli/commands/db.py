from __future__ import annotations

import typer

app = typer.Typer(help="Database management commands.")


@app.callback()
def db() -> None:
    """Manage Athena databases and migrations."""
