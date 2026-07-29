"""test CLI commandのdatabase準備とpytest実行workflowを検証する."""

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
    """pytest実行requestを記録して固定exit codeを返すprocess runner stubを提供する.

    Attributes:
        exit_code (int): pytest実行結果として返すexit code.
        calls (list[tuple[tuple[str, ...], dict[str, str]]]): argvと環境変数の実行履歴.
    """

    exit_code: int = 0
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = field(default_factory=list)

    def run_pytest(
        self,
        *,
        paths: Sequence[str],
        environment: Mapping[str, str],
    ) -> CommandResult:
        """Pytest argvと環境変数を記録して固定exit codeの結果を返す.

        Args:
            paths (Sequence[str]): pytestへ渡すtest path列.
            environment (Mapping[str, str]): pytest subprocessへ渡す環境変数.

        Returns:
            CommandResult: pytest argvとconstruction時のexit codeを持つ結果.
        """
        argv = ("pytest", *paths)
        self.calls.append((argv, dict(environment)))
        return CommandResult(argv=argv, exit_code=self.exit_code)


def test_test_command_runs_setup_then_default_pytest_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test commandがdatabase setup後に既定tests/ pathでpytestを実行することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): setupとprocess runner factoryを記録stubへ
            置き換えるfixture.

    Returns:
        None: setupからpytestへの順序と既定pathとenvironmentを検証して完了する.
            呼び出し側へ値を返さない.
    """
    order: list[str] = []
    process_runner = StubProcessRunner()

    def fake_setup_database(*, environment: str | None) -> None:
        """Target environmentを検証してdatabase setup stepを記録する.

        Args:
            environment (str | None): test commandがsetupへ渡すtarget environment.

        Returns:
            None: setup stepを記録して完了する. 値を返さない.
        """
        assert environment == "test"
        order.append("setup")

    def fake_create_process_runner() -> StubProcessRunner:
        """Pytest stepを記録して共有process runner stubを返す.

        Returns:
            StubProcessRunner: pytest実行を記録するrunner.
        """
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
    """repeat可能な--path optionが指定順でpytest argvへ渡ることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): setupとprocess runner factoryをstubへ置き換えるfixture.

    Returns:
        None: 複数test pathを持つpytest argvを検証して完了する. 呼び出し側へ値を返さない.
    """
    process_runner = StubProcessRunner()

    def fake_setup_database(*, environment: str | None) -> None:
        """environmentを使わず成功するdatabase setup stubを提供する.

        Args:
            environment (str | None): test commandがsetupへ渡すtarget environment.

        Returns:
            None: setup成功として完了する. 値を返さない.
        """
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
    """Database setup failure時にpytestを起動せずerrorを表示することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): setupをfailure fakeへ置き換えprocess runnerをstubへ
            置き換えるfixture.

    Returns:
        None: setup error messageとpytest未実行を検証して完了する. 呼び出し側へ値を返さない.
    """
    process_runner = StubProcessRunner()

    def fake_setup_database(*, environment: str | None) -> None:
        """environmentを使わずtest database setup failureを送出する.

        Args:
            environment (str | None): test commandがsetupへ渡すtarget environment.

        Returns:
            None: このstubは正常値を返さずに例外を送出する.

        Raises:
            CliUserError: test database setup失敗を表す場合.
        """
        _ = environment
        raise CliUserError("test database setup failed")

    monkeypatch.setattr(test_command, "setup_database", fake_setup_database)
    monkeypatch.setattr(test_command, "create_process_runner", lambda: process_runner)

    result = runner.invoke(app, ["test", "--env", "test"])

    assert result.exit_code != 0
    assert "test database setup failed" in result.output
    assert process_runner.calls == []


def test_test_command_propagates_pytest_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """pytestのnon-zero exit codeがtest commandからそのまま返ることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): setupとprocess runner factoryをstubへ置き換えるfixture.

    Returns:
        None: pytest exit codeとfailure messageを検証して完了する. 呼び出し側へ値を返さない.
    """
    process_runner = StubProcessRunner(exit_code=5)

    def fake_setup_database(*, environment: str | None) -> None:
        """environmentを使わず成功するdatabase setup stubを提供する.

        Args:
            environment (str | None): test commandがsetupへ渡すtarget environment.

        Returns:
            None: setup成功として完了する. 値を返さない.
        """
        _ = environment

    monkeypatch.setattr(test_command, "setup_database", fake_setup_database)
    monkeypatch.setattr(test_command, "create_process_runner", lambda: process_runner)

    result = runner.invoke(app, ["test", "--env", "test"])

    assert result.exit_code == 5
    assert "Command failed with exit code 5: pytest tests/" in result.output
