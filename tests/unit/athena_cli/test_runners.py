from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from athena_cli.runners import ProcessRunner

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(slots=True)
class StubExecutor:
    exit_code: int
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = field(default_factory=list)

    def run(self, argv: Sequence[str], environment: Mapping[str, str]) -> int:
        self.calls.append((tuple(argv), dict(environment)))
        return self.exit_code


def test_run_alembic_upgrade_uses_selected_environment() -> None:
    executor = StubExecutor(exit_code=0)
    runner = ProcessRunner(executor=executor)

    result = runner.run_alembic_upgrade(environment={"ENVIRONMENT": "test"})

    assert result.argv == ("alembic", "upgrade", "head")
    assert result.exit_code == 0
    assert executor.calls == [(("alembic", "upgrade", "head"), {"ENVIRONMENT": "test"})]


def test_run_pytest_uses_paths_and_propagates_exit_code() -> None:
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
