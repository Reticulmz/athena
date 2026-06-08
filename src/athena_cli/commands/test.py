from __future__ import annotations

import typer


def run_tests() -> None:
    typer.echo("The test command is not implemented yet.", err=True)
    raise typer.Exit(1)
