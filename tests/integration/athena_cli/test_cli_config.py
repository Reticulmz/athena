"""config CLI commandのvalidation表示とproduction safety契約を検証する."""

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
    """config commandへ渡す最小の設定fakeを表す.

    Attributes:
        environment (str): validation対象として返すenvironment名.
    """

    environment: str


def test_config_check_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """有効なtest設定が成功messageを表示しproduction safetyへ渡されることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとsafety policyをfakeへ置き換えるfixture.

    Returns:
        None: CLI成功出力とsafety policyへの入力を検証して完了する. 呼び出し側へ値を返さない.
    """
    safety_checks: list[str] = []

    def fake_load_config() -> FakeConfig:
        """Test environmentを観測して最小の有効設定を返す.

        Returns:
            FakeConfig: test environmentを持つ設定fake.
        """
        assert os.environ["ENVIRONMENT"] == "test"
        return FakeConfig(environment="test")

    def fake_assert_production_safe(config: FakeConfig) -> None:
        """Safety policyに渡されたenvironmentを記録する.

        Args:
            config (FakeConfig): config commandが読み込んだ設定fake.

        Returns:
            None: environmentを記録して完了する. 値を返さない.
        """
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
    """不正なDSNの設定がusage errorとしてfield名を表示することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadをvalidation失敗するfakeへ置き換えるfixture.

    Returns:
        None: CLI失敗出力のfield名を検証して完了する. 呼び出し側へ値を返さない.
    """

    def fake_load_config() -> AppConfig:
        """不正なdatabase DSNでAppConfig validationを実行する.

        Returns:
            AppConfig: この実装ではValidationErrorにより返らない設定型.

        Raises:
            ValidationError: 不正なdatabase_urlがAppConfig validationに拒否される場合.
        """
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
    """unsafeなproduction設定が設定名を含む失敗messageになることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとsafety policyをfailure fakeへ
            置き換えるfixture.

    Returns:
        None: CLI失敗出力のunsafe setting名を検証して完了する. 呼び出し側へ値を返さない.
    """

    def fake_load_config() -> FakeConfig:
        """Production environmentを観測して最小のproduction設定を返す.

        Returns:
            FakeConfig: production environmentを持つ設定fake.
        """
        assert os.environ["ENVIRONMENT"] == "production"
        return FakeConfig(environment="production")

    def fake_assert_production_safe(config: FakeConfig) -> None:
        """Unsafe settingを持つProductionSafetyErrorを送出する.

        Args:
            config (FakeConfig): policy対象として渡される設定fake.

        Returns:
            None: このstubは正常値を返さずに例外を送出する.

        Raises:
            ProductionSafetyError: unsafeなdatabaseとValkey設定を表す場合.
        """
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
