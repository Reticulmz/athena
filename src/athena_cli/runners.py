from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int


class CommandExecutor(Protocol):
    def run(self, argv: Sequence[str], environment: Mapping[str, str]) -> int: ...


class SubprocessCommandExecutor:
    def run(self, argv: Sequence[str], environment: Mapping[str, str]) -> int:
        completed = subprocess.run(
            list(argv),
            env=dict(environment),
            check=False,
        )
        return completed.returncode


@dataclass(frozen=True, slots=True)
class ProcessRunner:
    executor: CommandExecutor = field(default_factory=SubprocessCommandExecutor)

    def run_alembic_upgrade(self, *, environment: Mapping[str, str]) -> CommandResult:
        argv = ("alembic", "upgrade", "head")
        exit_code = self.executor.run(argv, environment)
        return CommandResult(argv=argv, exit_code=exit_code)

    def run_pytest(
        self,
        *,
        paths: Sequence[str],
        environment: Mapping[str, str],
    ) -> CommandResult:
        argv = ("pytest", *paths)
        exit_code = self.executor.run(argv, environment)
        return CommandResult(argv=argv, exit_code=exit_code)
