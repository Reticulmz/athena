"""CLI process runnerがexecutorへ渡すcommandと環境変数を検証する."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from athena_cli.runners import ProcessRunner

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(slots=True)
class StubExecutor:
    """呼び出しを記録して固定exit codeを返すprocess executor stubを提供する.

    Attributes:
        exit_code (int): 各run呼び出しで返すprocess終了code.
        calls (list[tuple[tuple[str, ...], dict[str, str]]]): argvと環境変数の呼び出し履歴.
    """

    exit_code: int
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = field(default_factory=list)

    def run(self, argv: Sequence[str], environment: Mapping[str, str]) -> int:
        """argvと環境変数をcopyして記録し固定exit codeを返す.

        Args:
            argv (Sequence[str]): 実行要求された外部commandとargument.
            environment (Mapping[str, str]): 外部processへ渡す環境変数.

        Returns:
            int: construction時に指定したexit code.
        """
        self.calls.append((tuple(argv), dict(environment)))
        return self.exit_code


def test_run_alembic_upgrade_uses_selected_environment() -> None:
    """Alembic upgrade commandが選択済みenvironmentをexecutorへ渡すことを検証する.

    Returns:
        None: argvとexit codeと環境変数の記録を検証して完了する. 呼び出し側へ値を返さない.
    """
    executor = StubExecutor(exit_code=0)
    runner = ProcessRunner(executor=executor)

    result = runner.run_alembic_upgrade(environment={"ENVIRONMENT": "test"})

    assert result.argv == ("alembic", "upgrade", "head")
    assert result.exit_code == 0
    assert executor.calls == [(("alembic", "upgrade", "head"), {"ENVIRONMENT": "test"})]


def test_run_pytest_uses_paths_and_propagates_exit_code() -> None:
    """Pytest commandが指定pathと外部exit codeを保持することを検証する.

    Returns:
        None: argvとexit codeと環境変数の記録を検証して完了する. 呼び出し側へ値を返さない.
    """
    executor = StubExecutor(exit_code=5)
    runner = ProcessRunner(executor=executor)

    result = runner.run_pytest(
        paths=("tests/unit", "tests/integration"),
        environment={"ENVIRONMENT": "test", "DATABASE_URL": "postgresql://example/db"},
    )

    assert result.argv == ("pytest", "tests/unit", "tests/integration")
    assert result.exit_code == 5
    assert executor.calls == [
        (
            ("pytest", "tests/unit", "tests/integration"),
            {"ENVIRONMENT": "test", "DATABASE_URL": "postgresql://example/db"},
        )
    ]
