from __future__ import annotations

from typing import Annotated

import typer

from athena_cli.commands import config, db, dev, env, test

app = typer.Typer(name="athena", help="Athena management CLI.")
app.add_typer(env.app, name="env")
app.add_typer(db.app, name="db")
app.add_typer(config.app, name="config")
app.add_typer(dev.app, name="dev")


@app.callback()
def root() -> None:
    """Run Athena management commands."""


@app.command(name="test")
def run_test_command(
    environment: Annotated[
        str | None,
        typer.Option("--env", help="Target environment."),
    ] = None,
    paths: Annotated[
        list[str] | None,
        typer.Option("--path", help="Test path to pass to pytest."),
    ] = None,
) -> None:
    test.run_tests(environment=environment, paths=tuple(paths or ()))


def main() -> None:
    app()
