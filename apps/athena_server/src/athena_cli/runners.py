"""外部processをCLI commandから実行するadapterを提供する."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class CommandResult:
    """外部commandのargumentと終了結果を表す.

    Attributes:
        argv (tuple[str, ...]): 実行したcommandとargument.
        exit_code (int): 外部processが返した終了code.
    """

    argv: tuple[str, ...]
    exit_code: int


class CommandExecutor(Protocol):
    """外部commandを実行する抽象boundaryを定義する."""

    def run(self, argv: Sequence[str], environment: Mapping[str, str]) -> int:
        """外部commandを指定環境で実行して終了codeを返す.

        Args:
            argv (Sequence[str]): 実行するcommandとargument.
            environment (Mapping[str, str]): 外部processへ渡す環境変数.

        Returns:
            int: 外部processが返した終了code.
        """
        ...


class SubprocessCommandExecutor:
    """標準library subprocessで外部commandを実行するexecutorを提供する."""

    def run(self, argv: Sequence[str], environment: Mapping[str, str]) -> int:
        """指定した環境変数で外部commandを実行して終了codeを返す.

        Args:
            argv (Sequence[str]): 実行するcommandとargument.
            environment (Mapping[str, str]): 外部processへ渡す環境変数.

        Returns:
            int: 外部processが返した終了code.

        Raises:
            OSError: commandを起動できない場合.
        """
        completed = subprocess.run(
            list(argv),
            env=dict(environment),
            check=False,
        )
        return completed.returncode


def _resolve_alembic_config_path() -> Path:
    """実行中のserver artifactに対応するAlembic config pathを解決する.

    Returns:
        Path: source checkoutまたはinstalled wheelが所有する`alembic.ini` path.

    Raises:
        FileNotFoundError: server workspaceまたはinstalled artifactにconfigがない場合.
    """
    module_path = Path(__file__).resolve()
    candidate_paths = (
        module_path.parents[2] / "alembic.ini",
        module_path.parents[1] / "alembic.ini",
    )
    for candidate_path in candidate_paths:
        if candidate_path.is_file():
            return candidate_path
    message = "Server-owned Alembic config was not found"
    raise FileNotFoundError(message)


@dataclass(frozen=True, slots=True)
class ProcessRunner:
    """Athena CLIが使う外部process commandを組み立てて実行する.

    Attributes:
        executor (CommandExecutor): command実行を委譲するadapter.
    """

    executor: CommandExecutor = field(default_factory=SubprocessCommandExecutor)

    def run_alembic_upgrade(self, *, environment: Mapping[str, str]) -> CommandResult:
        """Alembic upgrade headを実行する.

        Args:
            environment (Mapping[str, str]): alembic processへ渡す環境変数.

        Returns:
            CommandResult: 実行したargumentと終了code.

        Raises:
            OSError: alembic commandを起動できない場合.
        """
        argv = (
            "alembic",
            "-c",
            str(_resolve_alembic_config_path()),
            "upgrade",
            "head",
        )
        exit_code = self.executor.run(argv, environment)
        return CommandResult(argv=argv, exit_code=exit_code)

    def run_pytest(
        self,
        *,
        paths: Sequence[str],
        environment: Mapping[str, str],
    ) -> CommandResult:
        """指定pathを引数にpytestを実行する.

        Args:
            paths (Sequence[str]): pytestへ渡すtest path.
            environment (Mapping[str, str]): pytest processへ渡す環境変数.

        Returns:
            CommandResult: 実行したargumentと終了code.

        Raises:
            OSError: pytest commandを起動できない場合.
        """
        argv = ("pytest", *paths)
        exit_code = self.executor.run(argv, environment)
        return CommandResult(argv=argv, exit_code=exit_code)
