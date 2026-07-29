"""Dishka worker containerをTaskiqへ統合するhelperを提供する.

Taskiq jobごとのDishka scopeとSQL query diagnostics scopeをbroker middlewareとして構成する.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

import structlog
from dishka.integrations.taskiq import ContainerMiddleware, setup_dishka
from taskiq import TaskiqMiddleware

from osu_server.shared.query_diagnostics import (
    emit_sql_query_diagnostics_warning,
    query_diagnostic_scope,
)

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from dishka import AsyncContainer
    from taskiq import AsyncBroker, TaskiqMessage, TaskiqResult

    from osu_server.config import AppConfig
    from osu_server.shared.query_diagnostics import (
        QueryDiagnosticCollector,
    )

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


@dataclass(slots=True)
class _ActiveTaskiqDiagnosticScope:
    """実行中Taskiq jobのSQL query diagnostics scopeを保持する.

    Attributes:
        manager (AbstractContextManager[QueryDiagnosticCollector]): scopeの開始と終了を管理する
            context manager.
        collector (QueryDiagnosticCollector): job実行中にquery情報を収集するcollector.
    """

    manager: AbstractContextManager[QueryDiagnosticCollector]
    collector: QueryDiagnosticCollector


class SQLQueryDiagnosticsTaskiqMiddleware(TaskiqMiddleware):
    """Taskiq jobごとにSQL query diagnostics scopeを開くmiddlewareを表す.

    Attributes:
        _config (AppConfig): diagnosticsの有効状態と閾値を持つruntime設定.
        _active_scopes (dict[str, _ActiveTaskiqDiagnosticScope]): task IDごとに開始済みの
            diagnostics scopeを保持するmapping.
    """

    def __init__(self, config: AppConfig) -> None:
        """middlewareをruntime configurationで初期化する.

        Args:
            config (AppConfig): runtime SQL diagnosticsの有効状態とthresholds.
        """
        super().__init__()
        self._config: AppConfig = config
        self._active_scopes: dict[str, _ActiveTaskiqDiagnosticScope] = {}

    @override
    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """job実行前に有効なdiagnostics scopeを開始する.

        Args:
            message (TaskiqMessage): 実行されるTaskiq message.

        Returns:
            TaskiqMessage: Taskiqへ渡す元のmessage. Athenaでは変更しない.
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
        """job完了後にdiagnostics scopeを閉じて必要ならwarningを出す.

        Args:
            message (TaskiqMessage): 完了したTaskiq message.
            result (TaskiqResult[object]): Taskiqの実行結果. 診断では参照しない.

        Returns:
            None: 対応するscopeを終了し,必要なwarningを記録したことを示す.
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
        """job失敗時にdiagnostics scopeを閉じて必要ならwarningを出す.

        Args:
            message (TaskiqMessage): 失敗したTaskiq message.
            result (TaskiqResult[object]): Taskiqの実行結果. 診断では参照しない.
            exception (BaseException): 発生した例外. 診断では参照しない.

        Returns:
            None: 対応するscopeを終了し,必要なwarningを記録したことを示す.
        """
        _ = (result, exception)
        await self._finish_scope(message)

    async def _finish_scope(self, message: TaskiqMessage) -> None:
        """対象task IDに対応するdiagnostics scopeを終了してsummaryを記録する.

        Args:
            message (TaskiqMessage): 終了対象scopeのtask IDを持つTaskiq message.

        Returns:
            None: scopeがない場合は何もせず,存在した場合はwarning記録まで完了したことを示す.
        """
        active_scope = self._active_scopes.pop(message.task_id, None)
        if active_scope is None:
            return

        summary = active_scope.collector.summary()
        try:
            _ = active_scope.manager.__exit__(None, None, None)
        finally:
            await emit_sql_query_diagnostics_warning(
                logger,
                summary,
                max_queries=self._config.query_diagnostics_max_queries,
            )


def setup_taskiq_dishka(container: AsyncContainer, broker: AsyncBroker) -> None:
    """Taskiq brokerへDishka container middlewareを1個だけ登録する.

    Args:
        container (AsyncContainer): Taskiq job scopeで利用するDishka container.
        broker (AsyncBroker): middlewareを再構成するTaskiq broker.

    Returns:
        None: 既存ContainerMiddlewareを除去してDishka integrationを設定したことを示す.
    """
    broker.middlewares = [
        middleware
        for middleware in broker.middlewares
        if not isinstance(middleware, ContainerMiddleware)
    ]
    setup_dishka(container=container, broker=broker)


def setup_taskiq_query_diagnostics(config: AppConfig, broker: AsyncBroker) -> None:
    """Taskiq brokerにruntime SQL diagnostics middlewareを一度だけ登録する.

    Args:
        config (AppConfig): runtime SQL diagnosticsの有効状態とthresholds.
        broker (AsyncBroker): workerが利用するTaskiq broker.

    Returns:
        None: 既存diagnostics middlewareを除去し,有効時だけ新instanceを追加したことを示す.
    """
    broker.middlewares = [
        middleware
        for middleware in broker.middlewares
        if not isinstance(middleware, SQLQueryDiagnosticsTaskiqMiddleware)
    ]
    if not config.query_diagnostics_effective_enabled:
        return
    broker.middlewares.append(SQLQueryDiagnosticsTaskiqMiddleware(config))
