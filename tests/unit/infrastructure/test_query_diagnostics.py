"""SQL query diagnostics collector tests."""

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
    """query_budget fixture の型 contract."""

    def __call__(
        self,
        *,
        max_queries: int,
        name: str,
        duplicate_threshold: int = 2,
    ) -> AbstractContextManager[None]: ...


class _SyncEngine:
    """SQLAlchemy sync engine の最小テストダブル."""


class _AsyncEngine:
    """AsyncEngine.sync_engine を持つ最小テストダブル."""

    def __init__(self) -> None:
        self.sync_engine: _SyncEngine = _SyncEngine()


def test_scope_records_duplicate_templates_without_parameters() -> None:
    """SQL params と literal を保存せず, redacted template で duplicate を集計する."""
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
    """Dollar-quoted literal は同一 tag の終端までまとめて redaction する."""
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
    """Active scope がない SQL event は記録されない."""
    record_query("SELECT $1", parameters={"token": "secret-token"})

    with query_diagnostic_scope(
        scope_kind="test",
        scope_name="empty",
        duplicate_threshold=2,
    ) as collector:
        pass

    assert collector.summary().total_queries == 0


def test_scope_reset_prevents_query_leakage_between_scopes() -> None:
    """Contextvar reset により別 scope の query が混ざらない."""
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
    """同じ engine への listener 二重登録を防ぐ."""
    listened: list[tuple[object, str, object]] = []

    def listen(engine: object, event_name: str, callback: object) -> None:
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
    """Duplicate summary は上位件数に制限し, truncation を明示する."""
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
    """Budget 内の query count は test failure にしない."""
    with query_budget(max_queries=1, name="unit budget"):
        record_query("SELECT 1")


def test_query_budget_fixture_fails_with_redacted_summary(
    query_budget: QueryBudget,
) -> None:
    """Budget 超過時は params を出さずに query summary を返す."""
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
