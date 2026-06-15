from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from athena_cli.commands import dev as dev_command
from athena_cli.main import app
from osu_server.services.commands.identity import (
    ChangeUserPasswordCommandInput,
    ChangeUserPasswordCommandResult,
    ChangeUserPasswordStatus,
)

if TYPE_CHECKING:
    import pytest


runner = CliRunner()


@dataclass(frozen=True, slots=True)
class FakeConfig:
    database_url: str = "postgresql+asyncpg://athena:password@localhost:5432/athena"
    banned_passwords: list[str] | None = None


@dataclass(frozen=True, slots=True)
class StubPromptAdapter:
    password: str

    def collect_confirmed_secret(
        self,
        *,
        message: str,
        confirmation_message: str,
    ) -> str:
        _ = message
        _ = confirmation_message
        return self.password


def test_dev_change_password_changes_password_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[ChangeUserPasswordCommandInput] = []

    def fake_load_config() -> FakeConfig:
        assert os.environ["ENVIRONMENT"] == "test"
        return FakeConfig()

    async def fake_change_user_password(
        config: FakeConfig,
        input_data: ChangeUserPasswordCommandInput,
    ) -> ChangeUserPasswordCommandResult:
        _ = config
        calls.append(input_data)
        return ChangeUserPasswordCommandResult(
            status=ChangeUserPasswordStatus.CHANGED,
            username="TargetUser",
            user_id=42,
        )

    monkeypatch.setattr(dev_command, "load_config", fake_load_config)
    monkeypatch.setattr(
        dev_command,
        "create_prompt_adapter",
        lambda: StubPromptAdapter(password="NewPass1234"),
    )
    monkeypatch.setattr(
        dev_command,
        "run_change_user_password",
        fake_change_user_password,
    )

    result = runner.invoke(app, ["dev", "change-password", "TargetUser", "--env", "test"])

    assert result.exit_code == 0
    assert "Password changed for TargetUser (id=42)." in result.output
    assert calls == [
        ChangeUserPasswordCommandInput(
            username="TargetUser",
            plain_password="NewPass1234",
        )
    ]


def test_dev_change_password_rejects_production_before_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_prompt() -> StubPromptAdapter:
        raise AssertionError("production rejection must happen before prompting")

    monkeypatch.setattr(dev_command, "create_prompt_adapter", forbidden_prompt)

    result = runner.invoke(
        app,
        ["dev", "change-password", "TargetUser", "--env", "production"],
    )

    assert result.exit_code != 0
    assert "only available for development and test" in result.output


def test_dev_change_password_reports_missing_user(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_load_config() -> FakeConfig:
        return FakeConfig()

    async def fake_change_user_password(
        config: FakeConfig,
        input_data: ChangeUserPasswordCommandInput,
    ) -> ChangeUserPasswordCommandResult:
        _ = config
        return ChangeUserPasswordCommandResult(
            status=ChangeUserPasswordStatus.USER_NOT_FOUND,
            username=input_data.username,
        )

    monkeypatch.setattr(dev_command, "load_config", fake_load_config)
    monkeypatch.setattr(
        dev_command,
        "create_prompt_adapter",
        lambda: StubPromptAdapter(password="NewPass1234"),
    )
    monkeypatch.setattr(
        dev_command,
        "run_change_user_password",
        fake_change_user_password,
    )

    result = runner.invoke(app, ["dev", "change-password", "MissingUser", "--env", "test"])

    assert result.exit_code != 0
    assert "User not found: MissingUser" in result.output
