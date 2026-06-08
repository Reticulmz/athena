from __future__ import annotations

from typer.testing import CliRunner

from athena_cli.main import app

runner = CliRunner()


def test_root_help_shows_only_in_scope_management_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "env" in result.output
    assert "db" in result.output
    assert "config" in result.output
    assert "test" in result.output
    assert "server" not in result.output
    assert "worker" not in result.output
    assert "drop" not in result.output
    assert "reset" not in result.output
    assert "seed" not in result.output


def test_unknown_command_fails_with_usage_error() -> None:
    result = runner.invoke(app, ["unknown-command"])

    assert result.exit_code != 0
    assert "Usage:" in result.output
    assert "No such command" in result.output
