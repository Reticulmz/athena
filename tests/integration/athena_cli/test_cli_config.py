from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from athena_cli.commands import config as config_command
from athena_cli.env.production import ProductionSafetyError
from athena_cli.main import app
from osu_server.config import AppConfig

if TYPE_CHECKING:
    import pytest


runner = CliRunner()


@dataclass(frozen=True, slots=True)
class FakeConfig:
    environment: str


def test_config_check_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    safety_checks: list[str] = []

    def fake_load_config() -> FakeConfig:
        assert os.environ["ENVIRONMENT"] == "test"
        return FakeConfig(environment="test")

    def fake_assert_production_safe(config: FakeConfig) -> None:
        safety_checks.append(config.environment)

    monkeypatch.setattr(config_command, "load_config", fake_load_config)
    monkeypatch.setattr(
        config_command,
        "assert_production_safe",
        fake_assert_production_safe,
    )

    result = runner.invoke(app, ["config", "check", "--env", "test"])

    assert result.exit_code == 0
    assert "Configuration is valid." in result.output
    assert safety_checks == ["test"]


def test_config_check_reports_validation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_load_config() -> AppConfig:
        return AppConfig.model_validate(
            {
                "database_url": "not-a-dsn",
                "valkey_url": "redis://localhost:6379/0",
                "environment": "test",
            }
        )

    monkeypatch.setattr(config_command, "load_config", fake_load_config)

    result = runner.invoke(app, ["config", "check", "--env", "test"])

    assert result.exit_code != 0
    assert "Invalid configuration: database_url" in result.output


def test_config_check_rejects_unsafe_production_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_load_config() -> FakeConfig:
        assert os.environ["ENVIRONMENT"] == "production"
        return FakeConfig(environment="production")

    def fake_assert_production_safe(config: FakeConfig) -> None:
        _ = config
        raise ProductionSafetyError(("DATABASE_URL", "VALKEY_URL"))

    monkeypatch.setattr(config_command, "load_config", fake_load_config)
    monkeypatch.setattr(
        config_command,
        "assert_production_safe",
        fake_assert_production_safe,
    )

    result = runner.invoke(app, ["config", "check", "--env", "production"])

    assert result.exit_code != 0
    assert "Unsafe production settings: DATABASE_URL, VALKEY_URL" in result.output
