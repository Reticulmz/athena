"""development CLI commandがtest環境だけで安全に管理操作する契約を検証する."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from athena_cli.commands import dev as dev_command
from athena_cli.main import app
from osu_server.domain.identity.sessions import AuthorizationRefreshStatus
from osu_server.services.commands.identity import (
    ChangeUserPasswordCommandInput,
    ChangeUserPasswordCommandResult,
    ChangeUserPasswordStatus,
    ChangeUserRoleCommandInput,
    ChangeUserRoleCommandResult,
    ChangeUserRoleStatus,
)

if TYPE_CHECKING:
    import pytest


runner = CliRunner()


@dataclass(frozen=True, slots=True)
class FakeConfig:
    """development commandへ渡す最小のapplication設定fakeを表す.

    Attributes:
        database_url (str): command compositionが参照可能なdatabase DSN.
        banned_passwords (list[str] | None): password policyへ渡すoptionalな禁止password list.
    """

    database_url: str = "postgresql+asyncpg://athena:password@localhost:5432/athena"
    banned_passwords: list[str] | None = None


@dataclass(frozen=True, slots=True)
class StubPromptAdapter:
    """password変更時に確認済みsecretを固定で返すprompt adapter stubを提供する.

    Attributes:
        password (str): collect_confirmed_secretで返すpassword.
    """

    password: str

    def collect_confirmed_secret(
        self,
        *,
        message: str,
        confirmation_message: str,
    ) -> str:
        """表示messageを検証せず固定passwordを返す.

        Args:
            message (str): 最初のsecret入力に使う表示message.
            confirmation_message (str): secret再入力に使う表示message.

        Returns:
            str: construction時に指定した確認済みpassword.
        """
        _ = message
        _ = confirmation_message
        return self.password


def test_dev_change_password_changes_password_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """test環境でpassword変更がcommand inputへ変換され成功messageを表示することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとpromptとpassword use-caseをfakeへ
            置き換えるfixture.

    Returns:
        None: CLI出力とuse-case inputを検証して完了する. 呼び出し側へ値を返さない.
    """
    calls: list[ChangeUserPasswordCommandInput] = []

    def fake_load_config() -> FakeConfig:
        """Test environmentを観測して最小設定fakeを返す.

        Returns:
            FakeConfig: test command用の設定fake.
        """
        assert os.environ["ENVIRONMENT"] == "test"
        return FakeConfig()

    async def fake_change_user_password(
        config: FakeConfig,
        input_data: ChangeUserPasswordCommandInput,
    ) -> ChangeUserPasswordCommandResult:
        """password変更inputを記録して成功結果を返す.

        Args:
            config (FakeConfig): commandが読み込んだ設定fake.
            input_data (ChangeUserPasswordCommandInput): password変更use-caseへ渡すinput.

        Returns:
            ChangeUserPasswordCommandResult: 対象userを変更した成功結果.
        """
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
    """productionのpassword変更がprompt生成前に拒否されることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): 呼び出されると失敗するprompt factoryを設定するfixture.

    Returns:
        None: production拒否messageを検証して完了する. 呼び出し側へ値を返さない.
    """

    def forbidden_prompt() -> StubPromptAdapter:
        """production拒否より先にpromptが作成された場合だけ失敗する.

        Returns:
            StubPromptAdapter: このhelperは正常値を返さずに例外を送出する.

        Raises:
            AssertionError: prompt生成がproduction拒否より先に起きた場合.
        """
        raise AssertionError("production rejection must happen before prompting")

    monkeypatch.setattr(dev_command, "create_prompt_adapter", forbidden_prompt)

    result = runner.invoke(
        app,
        ["dev", "change-password", "TargetUser", "--env", "production"],
    )

    assert result.exit_code != 0
    assert "only available for development and test" in result.output


def test_dev_change_password_reports_missing_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """存在しないuserのpassword変更がCLIのnot-found messageになることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとpromptとpassword use-caseをnot-found
            fakeへ置き換えるfixture.

    Returns:
        None: user not found出力を検証して完了する. 呼び出し側へ値を返さない.
    """

    def fake_load_config() -> FakeConfig:
        """最小設定fakeを返す.

        Returns:
            FakeConfig: development command用の設定fake.
        """
        return FakeConfig()

    async def fake_change_user_password(
        config: FakeConfig,
        input_data: ChangeUserPasswordCommandInput,
    ) -> ChangeUserPasswordCommandResult:
        """対象usernameを持つuser-not-found結果を返す.

        Args:
            config (FakeConfig): commandが読み込んだ設定fake.
            input_data (ChangeUserPasswordCommandInput): usernameを含むpassword変更input.

        Returns:
            ChangeUserPasswordCommandResult: user未検出を表す結果.
        """
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


def test_dev_change_role_changes_role_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """test環境でrole変更がcommand inputへ変換されsession refreshを表示することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとrole use-caseをsuccess fakeへ
            置き換えるfixture.

    Returns:
        None: CLI出力とuse-case inputを検証して完了する. 呼び出し側へ値を返さない.
    """
    calls: list[ChangeUserRoleCommandInput] = []

    def fake_load_config() -> FakeConfig:
        """Test environmentを観測して最小設定fakeを返す.

        Returns:
            FakeConfig: test command用の設定fake.
        """
        assert os.environ["ENVIRONMENT"] == "test"
        return FakeConfig()

    async def fake_change_user_role(
        config: FakeConfig,
        input_data: ChangeUserRoleCommandInput,
    ) -> ChangeUserRoleCommandResult:
        """role変更inputを記録してsession refresh済みの成功結果を返す.

        Args:
            config (FakeConfig): commandが読み込んだ設定fake.
            input_data (ChangeUserRoleCommandInput): role変更use-caseへ渡すinput.

        Returns:
            ChangeUserRoleCommandResult: role変更とsession refreshを表す成功結果.
        """
        _ = config
        calls.append(input_data)
        return ChangeUserRoleCommandResult(
            status=ChangeUserRoleStatus.CHANGED,
            username="TargetUser",
            user_id=42,
            role_name="Admin",
            role_id=3,
            authorization_refresh_status=AuthorizationRefreshStatus.REFRESHED,
        )

    monkeypatch.setattr(dev_command, "load_config", fake_load_config)
    monkeypatch.setattr(dev_command, "run_change_user_role", fake_change_user_role)

    result = runner.invoke(
        app,
        ["dev", "change-role", "TargetUser", "Admin", "--env", "test"],
    )

    assert result.exit_code == 0
    assert "Role changed for TargetUser (id=42) to Admin (id=3)." in result.output
    assert "Active session authorization refreshed." in result.output
    assert calls == [
        ChangeUserRoleCommandInput(
            username="TargetUser",
            role_name="Admin",
        )
    ]


def test_dev_change_role_rejects_production_before_loading_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """productionのrole変更が設定読み込み前に拒否されることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): 呼び出されると失敗するconfig loaderを設定するfixture.

    Returns:
        None: production拒否messageを検証して完了する. 呼び出し側へ値を返さない.
    """

    def forbidden_load_config() -> FakeConfig:
        """production拒否より先に設定を読んだ場合だけ失敗する.

        Returns:
            FakeConfig: このhelperは正常値を返さずに例外を送出する.

        Raises:
            AssertionError: config読み込みがproduction拒否より先に起きた場合.
        """
        raise AssertionError("production rejection must happen before config loading")

    monkeypatch.setattr(dev_command, "load_config", forbidden_load_config)

    result = runner.invoke(
        app,
        ["dev", "change-role", "TargetUser", "Admin", "--env", "production"],
    )

    assert result.exit_code != 0
    assert "only available for development and test" in result.output


def test_dev_change_role_reports_missing_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """存在しないroleの変更がCLIのnot-found messageになることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとrole use-caseをnot-found fakeへ
            置き換えるfixture.

    Returns:
        None: role not found出力を検証して完了する. 呼び出し側へ値を返さない.
    """

    def fake_load_config() -> FakeConfig:
        """最小設定fakeを返す.

        Returns:
            FakeConfig: development command用の設定fake.
        """
        return FakeConfig()

    async def fake_change_user_role(
        config: FakeConfig,
        input_data: ChangeUserRoleCommandInput,
    ) -> ChangeUserRoleCommandResult:
        """対象role名を持つrole-not-found結果を返す.

        Args:
            config (FakeConfig): commandが読み込んだ設定fake.
            input_data (ChangeUserRoleCommandInput): usernameとrole名を含む変更input.

        Returns:
            ChangeUserRoleCommandResult: role未検出を表す結果.
        """
        _ = config
        return ChangeUserRoleCommandResult(
            status=ChangeUserRoleStatus.ROLE_NOT_FOUND,
            username=input_data.username,
            role_name=input_data.role_name,
            user_id=42,
        )

    monkeypatch.setattr(dev_command, "load_config", fake_load_config)
    monkeypatch.setattr(dev_command, "run_change_user_role", fake_change_user_role)

    result = runner.invoke(
        app,
        ["dev", "change-role", "TargetUser", "MissingRole", "--env", "test"],
    )

    assert result.exit_code != 0
    assert "Role not found: MissingRole" in result.output
