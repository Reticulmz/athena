"""Taskiq integration helpers for the Dishka worker container."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

import structlog
from dishka.integrations.taskiq import ContainerMiddleware, setup_dishka
from taskiq import TaskiqMiddleware

from osu_server.infrastructure.database.query_diagnostics import (
    query_diagnostic_scope,
    query_diagnostics_exceeded,
    query_diagnostics_warning_fields,
)

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from dishka import AsyncContainer
    from taskiq import AsyncBroker, TaskiqMessage, TaskiqResult

    from osu_server.config import AppConfig
    from osu_server.infrastructure.database.query_diagnostics import (
        QueryDiagnosticCollector,
        QueryDiagnosticSummary,
    )

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


@dataclass(slots=True)
class _ActiveTaskiqDiagnosticScope:
    manager: AbstractContextManager[QueryDiagnosticCollector]
    collector: QueryDiagnosticCollector


class SQLQueryDiagnosticsTaskiqMiddleware(TaskiqMiddleware):
    """Taskiq job ごとに SQL query diagnostics scope を開く middleware."""

    def __init__(self, config: AppConfig) -> None:
        """Middleware を runtime config で初期化する.

        Args:
            config: Runtime SQL diagnostics の有効状態と thresholds.
        """
        super().__init__()
        self._config: AppConfig = config
        self._active_scopes: dict[str, _ActiveTaskiqDiagnosticScope] = {}

    @override
    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Job 実行前に diagnostics scope を開始する.

        Args:
            message: 実行される Taskiq message.

        Returns:
            Taskiq に渡す message. Athena では変更しない.
        """
        if not self._config.query_diagnostics_effective_enabled:
            return message

        manager = query_diagnostic_scope(
            scope_kind="taskiq_job",
            scope_name=message.task_name,
            duplicate_threshold=self._config.query_diagnostics_duplicate_threshold,
        )
        collector = manager.__enter__()
        self._active_scopes[message.task_id] = _ActiveTaskiqDiagnosticScope(
            manager=manager,
            collector=collector,
        )
        return message

    @override
    async def post_execute(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[object],
    ) -> None:
        """Job 完了後に scope を閉じて必要なら warning を出す.

        Args:
            message: 完了した Taskiq message.
            result: Taskiq の実行結果. 診断では参照しない.
        """
        _ = result
        await self._finish_scope(message)

    @override
    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[object],
        exception: BaseException,
    ) -> None:
        """Job 失敗時に scope を閉じて必要なら warning を出す.

        Args:
            message: 失敗した Taskiq message.
            result: Taskiq の実行結果. 診断では参照しない.
            exception: 発生した例外. 診断では参照しない.
        """
        _ = (result, exception)
        await self._finish_scope(message)

    async def _finish_scope(self, message: TaskiqMessage) -> None:
        active_scope = self._active_scopes.pop(message.task_id, None)
        if active_scope is None:
            return

        summary = active_scope.collector.summary()
        try:
            _ = active_scope.manager.__exit__(None, None, None)
        finally:
            await _emit_sql_query_diagnostics_warning(
                summary,
                max_queries=self._config.query_diagnostics_max_queries,
            )


def setup_taskiq_dishka(container: AsyncContainer, broker: AsyncBroker) -> None:
    """Install one Dishka middleware instance on the taskiq broker."""
    broker.middlewares = [
        middleware
        for middleware in broker.middlewares
        if not isinstance(middleware, ContainerMiddleware)
    ]
    setup_dishka(container=container, broker=broker)


def setup_taskiq_query_diagnostics(config: AppConfig, broker: AsyncBroker) -> None:
    """Taskiq broker に runtime SQL diagnostics middleware を一度だけ登録する.

    Args:
        config: Runtime SQL diagnostics の有効状態と thresholds.
        broker: Worker が利用する Taskiq broker.
    """
    broker.middlewares = [
        middleware
        for middleware in broker.middlewares
        if not isinstance(middleware, SQLQueryDiagnosticsTaskiqMiddleware)
    ]
    if not config.query_diagnostics_effective_enabled:
        return
    _ = broker.with_middlewares(SQLQueryDiagnosticsTaskiqMiddleware(config))


async def _emit_sql_query_diagnostics_warning(
    summary: QueryDiagnosticSummary,
    *,
    max_queries: int,
) -> None:
    if not query_diagnostics_exceeded(summary, max_queries=max_queries):
        return
    try:
        await logger.awarning(
            "sql_query_diagnostics_warning",
            **query_diagnostics_warning_fields(summary, max_queries=max_queries),
        )
    except Exception:
        return
