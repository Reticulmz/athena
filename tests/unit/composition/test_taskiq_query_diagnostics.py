"""Taskiq SQL query diagnostics integration tests."""

from __future__ import annotations

import pytest
import structlog.testing
from taskiq import InMemoryBroker, TaskiqMessage, TaskiqResult
from tests.factories.config import make_app_config

from osu_server.composition.taskiq_integration import (
    SQLQueryDiagnosticsTaskiqMiddleware,
    setup_taskiq_query_diagnostics,
)
from osu_server.infrastructure.database.query_diagnostics import record_query


def _make_message(
    *,
    task_id: str = "job-1",
    task_name: str = "calculate_score_performance",
) -> TaskiqMessage:
    return TaskiqMessage(
        task_id=task_id,
        task_name=task_name,
        labels={},
        args=[],
        kwargs={},
    )


def _make_result(*, is_err: bool = False) -> TaskiqResult[object]:
    return TaskiqResult[object](
        is_err=is_err,
        return_value=None,
        execution_time=0.1,
    )


def _diagnostics_middlewares(
    broker: InMemoryBroker,
) -> list[SQLQueryDiagnosticsTaskiqMiddleware]:
    return [
        middleware
        for middleware in broker.middlewares
        if isinstance(middleware, SQLQueryDiagnosticsTaskiqMiddleware)
    ]


@pytest.mark.asyncio
async def test_taskiq_sql_query_diagnostics_warns_in_development() -> None:
    """Development job で threshold 超過時に redacted warning を出す."""
    config = make_app_config(
        environment="development",
        query_diagnostics_max_queries=1,
        query_diagnostics_duplicate_threshold=2,
    )
    middleware = SQLQueryDiagnosticsTaskiqMiddleware(config)
    message = _make_message()

    with structlog.testing.capture_logs() as logs:
        returned = middleware.pre_execute(message)
        record_query(
            "SELECT * FROM scores WHERE user_id = $1",
            parameters={"user_id": 1, "token": "secret-token"},
        )
        record_query(
            "SELECT * FROM scores WHERE user_id = $1",
            parameters={"user_id": 1, "token": "secret-token"},
        )
        await middleware.post_execute(message, _make_result())

    assert returned is message
    warnings = [log for log in logs if log["event"] == "sql_query_diagnostics_warning"]
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["scope_kind"] == "taskiq_job"
    assert warning["scope_name"] == "calculate_score_performance"
    assert warning["total_queries"] == 2
    assert warning["max_queries"] == 1
    assert "secret-token" not in repr(warning)
    assert "SELECT * FROM scores WHERE user_id = $1" in repr(warning)


@pytest.mark.asyncio
async def test_taskiq_sql_query_diagnostics_skips_non_development_default() -> None:
    """Production default では Taskiq runtime warning を出さない."""
    config = make_app_config(
        environment="production",
        query_diagnostics_max_queries=1,
        query_diagnostics_duplicate_threshold=2,
    )
    middleware = SQLQueryDiagnosticsTaskiqMiddleware(config)
    message = _make_message()

    with structlog.testing.capture_logs() as logs:
        returned = middleware.pre_execute(message)
        record_query("SELECT * FROM scores WHERE user_id = $1", parameters={"token": "secret"})
        await middleware.post_execute(message, _make_result())

    assert returned is message
    assert not [log for log in logs if log["event"] == "sql_query_diagnostics_warning"]


@pytest.mark.asyncio
async def test_taskiq_sql_query_diagnostics_closes_scope_on_error_once() -> None:
    """Job 失敗時も scope を閉じ, 二重 warning を出さない."""
    config = make_app_config(
        environment="development",
        query_diagnostics_max_queries=1,
        query_diagnostics_duplicate_threshold=2,
    )
    middleware = SQLQueryDiagnosticsTaskiqMiddleware(config)
    message = _make_message()
    exception = RuntimeError("task failed")

    with structlog.testing.capture_logs() as logs:
        _ = middleware.pre_execute(message)
        record_query("SELECT * FROM scores WHERE id = $1", parameters={"id": 1})
        record_query("SELECT * FROM scores WHERE id = $1", parameters={"id": 1})
        await middleware.on_error(message, _make_result(is_err=True), exception)
        await middleware.post_execute(message, _make_result())

    warnings = [log for log in logs if log["event"] == "sql_query_diagnostics_warning"]
    assert len(warnings) == 1
    assert warnings[0]["scope_kind"] == "taskiq_job"


def test_setup_taskiq_query_diagnostics_installs_once_in_development() -> None:
    """Development broker に diagnostics middleware を一度だけ登録する."""
    broker = InMemoryBroker()
    config = make_app_config(environment="development")

    setup_taskiq_query_diagnostics(config, broker)
    setup_taskiq_query_diagnostics(config, broker)

    assert len(_diagnostics_middlewares(broker)) == 1


def test_setup_taskiq_query_diagnostics_removes_existing_when_disabled() -> None:
    """Disabled config では既存 diagnostics middleware を取り除く."""
    broker = InMemoryBroker()
    setup_taskiq_query_diagnostics(make_app_config(environment="development"), broker)

    setup_taskiq_query_diagnostics(make_app_config(environment="production"), broker)

    assert _diagnostics_middlewares(broker) == []
