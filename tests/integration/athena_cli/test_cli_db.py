from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from athena_cli.commands import db as db_command
from athena_cli.errors import DatabaseOperationError
from athena_cli.main import app
from athena_cli.runners import CommandResult

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pytest


runner = CliRunner()
_DATABASE_URL = "postgresql+asyncpg://athena:password@localhost:5432/athena"


@dataclass(frozen=True, slots=True)
class FakeConfig:
    database_url: str


@dataclass(slots=True)
class StubProcessRunner:
    exit_code: int = 0
    calls: list[dict[str, str]] = field(default_factory=list)

    def run_alembic_upgrade(self, *, environment: Mapping[str, str]) -> CommandResult:
        self.calls.append(dict(environment))
        return CommandResult(argv=("alembic", "upgrade", "head"), exit_code=self.exit_code)


@dataclass(frozen=True, slots=True)
class StubPromptAdapter:
    confirmed: bool

    def confirm(self, message: str, *, default: bool = False) -> bool:
        _ = message
        _ = default
        return self.confirmed


def test_db_create_reports_created_database(monkeypatch: pytest.MonkeyPatch) -> None:
    create_calls: list[str] = []

    def fake_load_config() -> FakeConfig:
        assert os.environ["ENVIRONMENT"] == "test"
        return FakeConfig(database_url=_DATABASE_URL)

    async def fake_create_database_if_missing(database_url: str) -> bool:
        create_calls.append(database_url)
        return True

    monkeypatch.setattr(db_command, "load_config", fake_load_config)
    monkeypatch.setattr(
        db_command,
        "create_database_if_missing",
        fake_create_database_if_missing,
    )

    result = runner.invoke(app, ["db", "create", "--env", "test"])

    assert result.exit_code == 0
    assert "Database created." in result.output
    assert create_calls == [_DATABASE_URL]


def test_db_create_reports_existing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create_database_if_missing(database_url: str) -> bool:
        _ = database_url
        return False

    monkeypatch.setattr(
        db_command,
        "load_config",
        lambda: FakeConfig(database_url=_DATABASE_URL),
    )
    monkeypatch.setattr(
        db_command,
        "create_database_if_missing",
        fake_create_database_if_missing,
    )

    result = runner.invoke(app, ["db", "create", "--env", "test"])

    assert result.exit_code == 0
    assert "Database already exists." in result.output


def test_db_create_requires_production_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    create_calls: list[str] = []

    async def fake_create_database_if_missing(database_url: str) -> bool:
        create_calls.append(database_url)
        return True

    monkeypatch.setattr(
        db_command,
        "load_config",
        lambda: FakeConfig(database_url=_DATABASE_URL),
    )
    monkeypatch.setattr(
        db_command,
        "create_database_if_missing",
        fake_create_database_if_missing,
    )
    monkeypatch.setattr(
        db_command,
        "create_prompt_adapter",
        lambda: StubPromptAdapter(confirmed=False),
    )

    result = runner.invoke(app, ["db", "create", "--env", "production"])

    assert result.exit_code != 0
    assert "Target environment: production" in result.output
    assert "Production database creation requires explicit confirmation." in result.output
    assert create_calls == []


def test_db_create_reports_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create_database_if_missing(database_url: str) -> bool:
        _ = database_url
        raise DatabaseOperationError("connection refused")

    monkeypatch.setattr(
        db_command,
        "load_config",
        lambda: FakeConfig(database_url=_DATABASE_URL),
    )
    monkeypatch.setattr(
        db_command,
        "create_database_if_missing",
        fake_create_database_if_missing,
    )

    result = runner.invoke(app, ["db", "create", "--env", "test"])

    assert result.exit_code != 0
    assert "Database operation failed: connection refused" in result.output


def test_db_migrate_propagates_migration_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    process_runner = StubProcessRunner(exit_code=7)
    monkeypatch.setattr(db_command, "create_process_runner", lambda: process_runner)

    result = runner.invoke(app, ["db", "migrate", "--env", "test"])

    assert result.exit_code == 7
    assert "Command failed with exit code 7: alembic upgrade head" in result.output
    assert process_runner.calls[0]["ENVIRONMENT"] == "test"


def test_db_setup_runs_create_then_migrate(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    process_runner = StubProcessRunner(exit_code=0)

    async def fake_create_database_if_missing(database_url: str) -> bool:
        _ = database_url
        order.append("create")
        return True

    def fake_create_process_runner() -> StubProcessRunner:
        order.append("migrate")
        return process_runner

    monkeypatch.setattr(
        db_command,
        "load_config",
        lambda: FakeConfig(database_url=_DATABASE_URL),
    )
    monkeypatch.setattr(
        db_command,
        "create_database_if_missing",
        fake_create_database_if_missing,
    )
    monkeypatch.setattr(db_command, "create_process_runner", fake_create_process_runner)

    result = runner.invoke(app, ["db", "setup", "--env", "test"])

    assert result.exit_code == 0
    assert "Database created." in result.output
    assert "Database migrated." in result.output
    assert "Database setup complete." in result.output
    assert order == ["create", "migrate"]
