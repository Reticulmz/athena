from __future__ import annotations

import typer

from athena_cli.commands import config, db, env, test

app = typer.Typer(name="athena", help="Athena management CLI.")
app.add_typer(env.app, name="env")
app.add_typer(db.app, name="db")
app.add_typer(config.app, name="config")


@app.callback()
def root() -> None:
    """Run Athena management commands."""


@app.command(name="test")
def test_command() -> None:
    test.run_tests()


def main() -> None:
    app()
