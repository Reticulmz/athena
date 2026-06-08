from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from athena_cli.commands import test as test_command
from athena_cli.errors import CliUserError
from athena_cli.main import app
from athena_cli.runners import CommandResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import pytest


runner = CliRunner()


@dataclass(slots=True)
class StubProcessRunner:
    exit_code: int = 0
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = field(default_factory=list)

    def run_pytest(
        self,
        *,
        paths: Sequence[str],
        environment: Mapping[str, str],
    ) -> CommandResult:
        argv = ("pytest", *paths)
        self.calls.append((argv, dict(environment)))
        return CommandResult(argv=argv, exit_code=self.exit_code)


def test_test_command_runs_setup_then_default_pytest_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    process_runner = StubProcessRunner()

    def fake_setup_database(*, environment: str | None) -> None:
        assert environment == "test"
        order.append("setup")

    def fake_create_process_runner() -> StubProcessRunner:
        order.append("pytest")
        return process_runner

    monkeypatch.setattr(test_command, "setup_database", fake_setup_database)
    monkeypatch.setattr(test_command, "create_process_runner", fake_create_process_runner)

    result = runner.invoke(app, ["test", "--env", "test"])

    assert result.exit_code == 0
    assert order == ["setup", "pytest"]
    assert process_runner.calls[0][0] == ("pytest", "tests/")
    assert process_runner.calls[0][1]["ENVIRONMENT"] == "test"


def test_test_command_passes_multiple_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    process_runner = StubProcessRunner()

    def fake_setup_database(*, environment: str | None) -> None:
        _ = environment

    monkeypatch.setattr(test_command, "setup_database", fake_setup_database)
    monkeypatch.setattr(test_command, "create_process_runner", lambda: process_runner)

    result = runner.invoke(
        app,
        ["test", "--env", "test", "--path", "tests/unit", "--path", "tests/integration"],
    )

    assert result.exit_code == 0
    assert process_runner.calls[0][0] == ("pytest", "tests/unit", "tests/integration")


def test_test_command_stops_when_setup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    process_runner = StubProcessRunner()

    def fake_setup_database(*, environment: str | None) -> None:
        _ = environment
        raise CliUserError("test database setup failed")

    monkeypatch.setattr(test_command, "setup_database", fake_setup_database)
    monkeypatch.setattr(test_command, "create_process_runner", lambda: process_runner)

    result = runner.invoke(app, ["test", "--env", "test"])

    assert result.exit_code != 0
    assert "test database setup failed" in result.output
    assert process_runner.calls == []


def test_test_command_propagates_pytest_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    process_runner = StubProcessRunner(exit_code=5)

    def fake_setup_database(*, environment: str | None) -> None:
        _ = environment

    monkeypatch.setattr(test_command, "setup_database", fake_setup_database)
    monkeypatch.setattr(test_command, "create_process_runner", lambda: process_runner)

    result = runner.invoke(app, ["test", "--env", "test"])

    assert result.exit_code == 5
    assert "Command failed with exit code 5: pytest tests/" in result.output
