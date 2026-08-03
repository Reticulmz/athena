"""SQL query diagnostics collectorのredactionとbudget契約を検証するmodule."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import pytest
from sqlalchemy import event as sqlalchemy_event

from osu_server.infrastructure.database.query_diagnostics import (
    install_query_diagnostics,
)
from osu_server.shared.query_diagnostics import (
    query_diagnostic_scope,
    query_diagnostics_warning_fields,
    record_query,
)

if TYPE_CHECKING:
    from contextlib import AbstractContextManager


class QueryBudget(Protocol):
    """query_budget fixtureが提供するcontext manager factoryの型contractを表す."""

    def __call__(
        self,
        *,
        max_queries: int,
        name: str,
        duplicate_threshold: int = 2,
    ) -> AbstractContextManager[None]:
        """指定budgetを持つquery diagnostics scopeを生成する.

        Args:
            max_queries (int): scope内で許容する最大query数.
            name (str): failure messageへ表示するscope名.
            duplicate_threshold (int): duplicateとして報告する最小同一template数.

        Returns:
            AbstractContextManager[None]: query数を収集してbudgetを検証するcontext manager.
        """
        ...


class _SyncEngine:
    """SQLAlchemy sync engineを表すattributeなしの最小test double."""


class _AsyncEngine:
    """AsyncEngine.sync_engineを公開する最小test double.

    Attributes:
        sync_engine (_SyncEngine): listenerを登録する同期engine fake.
    """

    def __init__(self) -> None:
        """listener登録先として使う同期engine fakeを初期化する."""
        self.sync_engine: _SyncEngine = _SyncEngine()


def test_scope_records_duplicate_templates_without_parameters() -> None:
    """SQL parameterとliteralを保存せずredacted templateでduplicateを集計することを検証する.

    Returns:
        None: redacted summaryとsecret非出力を検証して完了する.
    """
    with query_diagnostic_scope(
        scope_kind="test",
        scope_name="score submission",
        duplicate_threshold=2,
    ) as collector:
        record_query(
            " SELECT  *\nFROM users WHERE email = 'secret@example.invalid' AND id = 123 ",
            parameters={"password": "secret-password", "email": "user@example.invalid"},
        )
        record_query(
            "SELECT * FROM users WHERE email = 'other@example.invalid' AND id = 456",
            parameters={"password": "other-secret", "email": "other@example.invalid"},
        )
        record_query("UPDATE scores SET pp = $1 WHERE id = $2", parameters=(123, 1))

    summary = collector.summary()

    assert summary.scope_kind == "test"
    assert summary.scope_name == "score submission"
    assert summary.total_queries == 3
    assert summary.duplicate_templates_total == 1
    assert summary.duplicates_truncated is False
    assert len(summary.duplicate_queries) == 1
    duplicate = summary.duplicate_queries[0]
    assert duplicate.count == 2
    assert duplicate.sql_prefix == "SELECT * FROM users WHERE email = ? AND id = ?"
    assert duplicate.fingerprint
    assert "secret-password" not in repr(summary)
    assert "secret@example.invalid" not in repr(summary)
    assert "user@example.invalid" not in repr(summary)
    assert "other-secret" not in repr(summary)


def test_scope_redacts_matching_dollar_quoted_literal_tag() -> None:
    """Dollar-quoted literalを同一tagの終端までまとめてredactすることを検証する.

    Returns:
        None: redacted SQL prefixとliteral非出力を検証して完了する.
    """
    with query_diagnostic_scope(
        scope_kind="test",
        scope_name="dollar quoted",
        duplicate_threshold=1,
    ) as collector:
        record_query(
            "SELECT $tag$secret $other$inner$other$ still secret$tag$ AS value",
        )

    summary = collector.summary()

    assert len(summary.duplicate_queries) == 1
    assert summary.duplicate_queries[0].sql_prefix == "SELECT ? AS value"
    assert "secret" not in repr(summary)
    assert "inner" not in repr(summary)


def test_record_query_without_scope_is_noop() -> None:
    """Active scopeがないSQL eventが記録されないことを検証する.

    Returns:
        None: 空scopeのquery countを検証して完了する.
    """
    record_query("SELECT $1", parameters={"token": "secret-token"})

    with query_diagnostic_scope(
        scope_kind="test",
        scope_name="empty",
        duplicate_threshold=2,
    ) as collector:
        pass

    assert collector.summary().total_queries == 0


def test_scope_reset_prevents_query_leakage_between_scopes() -> None:
    """ContextVar resetにより別scope間でqueryが混ざらないことを検証する.

    Returns:
        None: 独立scopeごとのquery countを検証して完了する.
    """
    with query_diagnostic_scope(
        scope_kind="test",
        scope_name="first",
        duplicate_threshold=2,
    ) as first:
        record_query("SELECT 1")

    with query_diagnostic_scope(
        scope_kind="test",
        scope_name="second",
        duplicate_threshold=2,
    ) as second:
        record_query("SELECT 2")
        record_query("SELECT 3")

    assert first.summary().total_queries == 1
    assert second.summary().total_queries == 2


def test_install_query_diagnostics_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """同じengineへquery diagnostics listenerを二重登録しないことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): SQLAlchemy listener関数をrecording fakeへ置換するfixture.

    Returns:
        None: listener登録回数とtarget engineを検証して完了する.
    """
    listened: list[tuple[object, str, object]] = []

    def listen(engine: object, event_name: str, callback: object) -> None:
        """Listener登録requestを記録してidempotency assertionへ渡す.

        Args:
            engine (object): listener登録対象のsync engine.
            event_name (str): SQLAlchemy event名.
            callback (object): event発生時に呼び出すcallback.

        Returns:
            None: 登録requestを記録して値を返さず完了する.
        """
        listened.append((engine, event_name, callback))

    monkeypatch.setattr(sqlalchemy_event, "listen", listen)
    engine = _AsyncEngine()

    install_query_diagnostics(engine)
    install_query_diagnostics(engine)

    assert len(listened) == 1
    listened_engine, event_name, callback = listened[0]
    assert listened_engine is engine.sync_engine
    assert event_name == "before_cursor_execute"
    assert callable(callback)


def test_duplicate_summary_is_bounded_and_reports_truncation() -> None:
    """Duplicate summaryが上位件数へ制限されtruncationを示すことを検証する.

    Returns:
        None: total数とtruncation flagおよびreported件数を検証して完了する.
    """
    with query_diagnostic_scope(
        scope_kind="test",
        scope_name="many duplicates",
        duplicate_threshold=1,
    ) as collector:
        for index in range(12):
            record_query(f"SELECT * FROM table_{index} WHERE id = {index}")

    summary = collector.summary()
    fields = query_diagnostics_warning_fields(summary, max_queries=1)

    assert summary.duplicate_templates_total == 12
    assert summary.duplicates_truncated is True
    assert len(summary.duplicate_queries) == 10
    assert fields["duplicate_templates_total"] == 12
    assert fields["duplicates_truncated"] is True


def test_query_budget_fixture_allows_within_limit(query_budget: QueryBudget) -> None:
    """budget内のquery countではquery_budget fixtureがfailureにしないことを検証する.

    Args:
        query_budget (QueryBudget): query数を計測してbudgetを検証するfixture.

    Returns:
        None: 許容queryを実行して例外なく完了する.
    """
    with query_budget(max_queries=1, name="unit budget"):
        record_query("SELECT 1")


def test_query_budget_fixture_fails_with_redacted_summary(
    query_budget: QueryBudget,
) -> None:
    """budget超過時にparameterを出さないquery summaryでfailureになることを検証する.

    Args:
        query_budget (QueryBudget): query数を計測してbudgetを検証するfixture.

    Returns:
        None: redacted failure messageの内容とsecret非出力を検証して完了する.
    """
    with (
        pytest.raises(AssertionError) as exc_info,
        query_budget(max_queries=0, name="secret-free", duplicate_threshold=1),
    ):
        record_query(
            "SELECT * FROM users WHERE email = 'secret@example.invalid' AND id = 123",
            parameters={"email": "secret@example.invalid", "token": "secret-token"},
        )

    message = str(exc_info.value)
    assert "SQL query budget exceeded" in message
    assert "scope=test:secret-free" in message
    assert "actual=1" in message
    assert "allowed=0" in message
    assert "duplicate_templates_total=1" in message
    assert "duplicates_truncated=False" in message
    assert "SELECT * FROM users WHERE email = ? AND id = ?" in message
    assert "secret@example.invalid" not in message
    assert "secret-token" not in message
