"""Taskiq SQL query diagnostics middleware の契約を検証する."""

from __future__ import annotations

import pytest
import structlog.testing
from taskiq import InMemoryBroker, TaskiqMessage, TaskiqResult
from tests.factories.config import make_app_config

from osu_server.composition.taskiq_integration import (
    SQLQueryDiagnosticsTaskiqMiddleware,
    setup_taskiq_query_diagnostics,
)
from osu_server.shared.query_diagnostics import record_query


def _make_message(
    *,
    task_id: str = "job-1",
    task_name: str = "calculate_score_performance",
) -> TaskiqMessage:
    """診断 middleware に渡す最小の Taskiq message を作る.

    Args:
        task_id (str): task 実行を識別する id.
        task_name (str): 診断 log へ出す task 名.

    Returns:
        TaskiqMessage: 引数なし job を表す message.
    """
    return TaskiqMessage(
        task_id=task_id,
        task_name=task_name,
        labels={},
        args=[],
        kwargs={},
    )


def _make_result(*, is_err: bool = False) -> TaskiqResult[object]:
    """診断 middleware の完了 hook に渡す Taskiq result を作る.

    Args:
        is_err (bool): job 実行が失敗した結果として扱うか.

    Returns:
        TaskiqResult[object]: 固定実行時間と値なしを持つ result.
    """
    return TaskiqResult[object](
        is_err=is_err,
        return_value=None,
        execution_time=0.1,
    )


def _diagnostics_middlewares(
    broker: InMemoryBroker,
) -> list[SQLQueryDiagnosticsTaskiqMiddleware]:
    """Broker に登録済みの SQL query diagnostics middleware だけを抽出する.

    Args:
        broker (InMemoryBroker): middleware 登録を調べる broker.

    Returns:
        list[SQLQueryDiagnosticsTaskiqMiddleware]: 診断 middleware の登録順 list.
    """
    return [
        middleware
        for middleware in broker.middlewares
        if isinstance(middleware, SQLQueryDiagnosticsTaskiqMiddleware)
    ]


@pytest.mark.asyncio
async def test_taskiq_sql_query_diagnostics_warns_in_development() -> None:
    """開発 job の query 数超過時に秘密値を伏せた warning を一件出す契約を検証する.

    Returns:
        None: warning の scope, 集計値, redaction 後の query template を検証して完了する.
    """
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
            "SELECT * FROM scores WHERE user_id = 1 AND token = 'secret-token'",
            parameters={"user_id": 1, "token": "secret-token"},
        )
        record_query(
            "SELECT * FROM scores WHERE user_id = 2 AND token = 'other-secret'",
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
    assert warning["duplicate_templates_total"] == 1
    assert warning["duplicates_truncated"] is False
    assert "secret-token" not in repr(warning)
    assert "SELECT * FROM scores WHERE user_id = ? AND token = ?" in repr(warning)


@pytest.mark.asyncio
async def test_taskiq_sql_query_diagnostics_skips_non_development_default() -> None:
    """本番既定では query を記録しても Taskiq runtime warning を出さない契約を検証する.

    Returns:
        None: middleware が同じ message を返し warning がないことを検証して完了する.
    """
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
    """Job error 後の post execute が scope を再閉鎖せず warning を一件に保つ契約を検証する.

    Returns:
        None: error hook と post execute 後の warning 数と scope 種別を検証して完了する.
    """
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
    """開発brokerへのdiagnostics setupを二回呼んでもmiddlewareを一つだけ登録する.

    この契約を検証する.

    Returns:
        None: diagnostics middleware の登録数を検証して完了する.
    """
    broker = InMemoryBroker()
    config = make_app_config(environment="development")

    setup_taskiq_query_diagnostics(config, broker)
    setup_taskiq_query_diagnostics(config, broker)

    assert len(_diagnostics_middlewares(broker)) == 1


def test_setup_taskiq_query_diagnostics_mutates_existing_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diagnostics setup が with_middlewares を使わず既存 broker を直接変更する契約を検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): 禁止 API を失敗関数へ差し替える fixture.

    Returns:
        None: 例外なく middleware が既存 broker に登録されることを検証して完了する.
    """
    broker = InMemoryBroker()

    def fail_with_middlewares(*args: object, **kwargs: object) -> object:
        """禁止された broker API が使われたことを失敗として通知する.

        Args:
            *args (object): 呼出し側が渡した位置引数.
            **kwargs (object): 呼出し側が渡した keyword 引数.

        Raises:
            AssertionError: setup が with_middlewares に依存した場合.
        """
        _ = (args, kwargs)
        msg = "with_middlewares must not be used for diagnostics setup"
        raise AssertionError(msg)

    monkeypatch.setattr(broker, "with_middlewares", fail_with_middlewares)

    setup_taskiq_query_diagnostics(make_app_config(environment="development"), broker)

    assert len(_diagnostics_middlewares(broker)) == 1


def test_setup_taskiq_query_diagnostics_removes_existing_when_disabled() -> None:
    """診断を無効化した設定が既存 diagnostics middleware を取り除く契約を検証する.

    Returns:
        None: 開発設定で登録後, 本番設定で登録 list が空になることを検証して完了する.
    """
    broker = InMemoryBroker()
    setup_taskiq_query_diagnostics(make_app_config(environment="development"), broker)

    setup_taskiq_query_diagnostics(make_app_config(environment="production"), broker)

    assert _diagnostics_middlewares(broker) == []
