"""Athena管理CLIのroot commandを定義する."""

from __future__ import annotations

from typing import Annotated

import typer

from athena_cli.commands import config, db, dev, env, pp, test

app = typer.Typer(name="athena", help="Athena management CLI.")
app.add_typer(env.app, name="env")
app.add_typer(db.app, name="db")
app.add_typer(config.app, name="config")
app.add_typer(dev.app, name="dev")
app.add_typer(pp.app, name="pp")


@app.callback()
def root() -> None:
    """Athena管理commandのroot callbackを実行する.

    Returns:
        None: command groupのmetadataを登録し値を返さずに完了する.
    """


@app.command(name="test", help="")
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
    """Test databaseを準備してpytestを実行する.

    Args:
        environment (str | None):
            subprocessへ渡すtarget environment. 未指定時はprocess environmentを使用する.
        paths (list[str] | None):
            pytestへ渡すtest pathの反復指定. 未指定時は既定のapps/athena_server/tests/を使用する.

    Returns:
        None: test commandを実行し値を返さずに完了する.

    Raises:
        typer.Exit: database準備またはpytestが失敗した場合.
    """
    test.run_tests(environment=environment, paths=tuple(paths or ()))


def main() -> None:
    """Console script entry pointからTyper applicationを実行する.

    Returns:
        None: processのcommand line処理を開始し値を返さずに完了する.
    """
    app()
