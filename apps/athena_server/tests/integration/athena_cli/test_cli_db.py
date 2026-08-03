"""database CLI commandの作成とmigration workflowを検証する."""

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
    """database URLだけを持つconfig command用設定fakeを表す.

    Attributes:
        database_url (str): database作成へ渡すDSN.
    """

    database_url: str


@dataclass(slots=True)
class StubProcessRunner:
    """alembic実行要求を記録して固定exit codeを返すprocess runner stubを提供する.

    Attributes:
        exit_code (int): migration結果として返すexit code.
        calls (list[dict[str, str]]): migrationごとに受け取った環境変数のcopy.
    """

    exit_code: int = 0
    calls: list[dict[str, str]] = field(default_factory=list)

    def run_alembic_upgrade(self, *, environment: Mapping[str, str]) -> CommandResult:
        """migration環境を記録して固定exit codeのalembic結果を返す.

        Args:
            environment (Mapping[str, str]): alembic subprocessへ渡す環境変数.

        Returns:
            CommandResult: Alembic upgrade headのargvと固定exit codeを持つ結果.
        """
        self.calls.append(dict(environment))
        return CommandResult(argv=("alembic", "upgrade", "head"), exit_code=self.exit_code)


@dataclass(frozen=True, slots=True)
class StubPromptAdapter:
    """production作成confirmationを固定値で返すprompt adapter stubを提供する.

    Attributes:
        confirmed (bool): confirm呼び出しで返すuser confirmation値.
    """

    confirmed: bool

    def confirm(self, message: str, *, default: bool = False) -> bool:
        """表示messageとdefaultを検証せずに固定confirmation値を返す.

        Args:
            message (str): commandが表示するconfirmation message.
            default (bool): commandが渡す既定confirmation値.

        Returns:
            bool: construction時に指定したconfirmation値.
        """
        _ = message
        _ = default
        return self.confirmed


def test_db_create_reports_created_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """存在しないdatabaseの作成成功がCLIへ表示されDSNへ実行されることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとdatabase作成をfakeへ置き換えるfixture.

    Returns:
        None: 成功出力とcreate requestのDSNを検証して完了する. 呼び出し側へ値を返さない.
    """
    create_calls: list[str] = []

    def fake_load_config() -> FakeConfig:
        """Test environmentを観測してdatabase URL設定fakeを返す.

        Returns:
            FakeConfig: test environment用のdatabase URLを持つ設定fake.
        """
        assert os.environ["ENVIRONMENT"] == "test"
        return FakeConfig(database_url=_DATABASE_URL)

    async def fake_create_database_if_missing(database_url: str) -> bool:
        """作成要求のDSNを記録して新規作成成功を返す.

        Args:
            database_url (str): database作成を要求されたDSN.

        Returns:
            bool: databaseを新規作成したことを示すTrue.
        """
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
    """既存databaseが作成不要messageとしてCLIへ表示されることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとdatabase作成を既存結果へ置き換えるfixture.

    Returns:
        None: 既存database出力を検証して完了する. 呼び出し側へ値を返さない.
    """

    async def fake_create_database_if_missing(database_url: str) -> bool:
        """受け取ったDSNを使わず既存databaseを表すFalseを返す.

        Args:
            database_url (str): database作成を要求されたDSN.

        Returns:
            bool: databaseがすでに存在することを示すFalse.
        """
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
    """Production database作成が明示confirmationなしでは実行されないことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとdatabase作成とpromptをstubへ
            置き換えるfixture.

    Returns:
        None: warningとconfirmation errorとcreate未実行を検証して完了する.
            呼び出し側へ値を返さない.
    """
    create_calls: list[str] = []

    async def fake_create_database_if_missing(database_url: str) -> bool:
        """呼び出された場合だけDSNを記録して作成成功を返す.

        Args:
            database_url (str): database作成を要求されたDSN.

        Returns:
            bool: database作成成功を表すTrue.
        """
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
    """database接続failureがCLIのoperation error messageになることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとdatabase作成をfailure fakeへ
            置き換えるfixture.

    Returns:
        None: CLI失敗messageを検証して完了する. 呼び出し側へ値を返さない.
    """

    async def fake_create_database_if_missing(database_url: str) -> bool:
        """受け取ったDSNを使わずDatabaseOperationErrorを送出する.

        Args:
            database_url (str): database作成を要求されたDSN.

        Returns:
            bool: このstubは正常値を返さずに例外を送出する.

        Raises:
            DatabaseOperationError: database接続拒否を表す場合.
        """
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
    """alembicのnon-zero exit codeがCLIのmigration failureとして伝播することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): process runner factoryをfailure stubへ置き換えるfixture.

    Returns:
        None: exit codeとCLI failure messageとenvironmentを検証して完了する.
            呼び出し側へ値を返さない.
    """
    process_runner = StubProcessRunner(exit_code=7)
    monkeypatch.setattr(db_command, "create_process_runner", lambda: process_runner)

    result = runner.invoke(app, ["db", "migrate", "--env", "test"])

    assert result.exit_code == 7
    assert "Command failed with exit code 7: alembic upgrade head" in result.output
    assert process_runner.calls[0]["ENVIRONMENT"] == "test"


def test_db_setup_runs_create_then_migrate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Database setupが作成後にmigrationを実行し順序を完了messageへ反映することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): config loadとcreateとrunner factoryをstubへ
            置き換えるfixture.

    Returns:
        None: CLI成功出力とcreateからmigrateへの順序を検証して完了する. 呼び出し側へ値を返さない.
    """
    order: list[str] = []
    process_runner = StubProcessRunner(exit_code=0)

    async def fake_create_database_if_missing(database_url: str) -> bool:
        """作成stepを記録してdatabase新規作成成功を返す.

        Args:
            database_url (str): database作成を要求されたDSN.

        Returns:
            bool: database作成成功を表すTrue.
        """
        _ = database_url
        order.append("create")
        return True

    def fake_create_process_runner() -> StubProcessRunner:
        """Migration stepを記録して共有process runner stubを返す.

        Returns:
            StubProcessRunner: migrationに使用する固定結果のrunner.
        """
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
