from __future__ import annotations

import typer

app = typer.Typer(name="athena", help="Athena management CLI.")


@app.callback()
def root() -> None:
    """Run Athena management commands."""


def main() -> None:
    app()
