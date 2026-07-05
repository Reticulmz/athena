"""SQL query diagnostics for tests and development runtime scopes."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from weakref import WeakSet

from sqlalchemy import event

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy.engine import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine

_SQL_WHITESPACE_PATTERN = re.compile(r"\s+")
_SQL_PREFIX_MAX_LENGTH = 160
_FINGERPRINT_LENGTH = 16
_current_collector: ContextVar[QueryDiagnosticCollector | None] = ContextVar(
    "query_diagnostic_collector",
    default=None,
)
_installed_sync_engines: WeakSet[Engine] = WeakSet()


@dataclass(slots=True, frozen=True)
class DuplicateQuerySummary:
    """重複 SQL template の redacted summary."""

    fingerprint: str
    count: int
    sql_prefix: str


@dataclass(slots=True, frozen=True)
class QueryDiagnosticSummary:
    """1 つの diagnostic scope で観測した SQL 発行数 summary."""

    scope_kind: str
    scope_name: str
    total_queries: int
    duplicate_queries: tuple[DuplicateQuerySummary, ...]


@dataclass(slots=True)
class QueryDiagnosticCollector:
    """Active scope 内の SQL template を記録する collector."""

    scope_kind: str
    scope_name: str
    duplicate_threshold: int
    _query_count: int = 0
    _template_counts: Counter[str] = field(default_factory=Counter)

    def record(self, statement: str) -> None:
        """SQL statement を params なしで正規化して記録する."""
        template = _normalize_sql(statement)
        if not template:
            return
        self._query_count += 1
        self._template_counts[template] += 1

    def summary(self) -> QueryDiagnosticSummary:
        """現在の記録内容から redacted summary を返す."""
        duplicates = tuple(
            DuplicateQuerySummary(
                fingerprint=_fingerprint_sql(template),
                count=count,
                sql_prefix=_sql_prefix(template),
            )
            for template, count in self._template_counts.items()
            if count >= self.duplicate_threshold
        )
        return QueryDiagnosticSummary(
            scope_kind=self.scope_kind,
            scope_name=self.scope_name,
            total_queries=self._query_count,
            duplicate_queries=duplicates,
        )


def query_diagnostics_exceeded(summary: QueryDiagnosticSummary, *, max_queries: int) -> bool:
    """Summary が runtime warning threshold を超えたかを返す.

    Args:
        summary: Query diagnostic scope の summary.
        max_queries: 許容する最大 SQL query 数.

    Returns:
        Query count 超過または duplicate query がある場合は true.
    """
    return summary.total_queries > max_queries or bool(summary.duplicate_queries)


def query_diagnostics_warning_fields(
    summary: QueryDiagnosticSummary,
    *,
    max_queries: int,
) -> dict[str, object]:
    """Warning log に渡す redacted fields を返す.

    Args:
        summary: Query diagnostic scope の summary.
        max_queries: 許容する最大 SQL query 数.

    Returns:
        SQL params を含まない structlog 用 fields.
    """
    return {
        "scope_kind": summary.scope_kind,
        "scope_name": summary.scope_name,
        "total_queries": summary.total_queries,
        "max_queries": max_queries,
        "duplicates": tuple(
            {
                "fingerprint": duplicate.fingerprint,
                "count": duplicate.count,
                "sql_prefix": duplicate.sql_prefix,
            }
            for duplicate in summary.duplicate_queries
        ),
    }


@contextmanager
def query_diagnostic_scope(
    *,
    scope_kind: str,
    scope_name: str,
    duplicate_threshold: int,
) -> Generator[QueryDiagnosticCollector]:
    """Query diagnostic scope を開き exit 時に active collector を reset する.

    Args:
        scope_kind: `http_request` や `taskiq_job` などの scope 種別.
        scope_name: method/path や task name などの redacted scope 名.
        duplicate_threshold: duplicate として扱う同一 SQL template の最小回数.

    Yields:
        Scope 内で記録された SQL を保持する collector.

    Raises:
        ValueError: duplicate_threshold が 1 未満の場合.
    """
    if duplicate_threshold < 1:
        msg = "duplicate_threshold must be greater than or equal to 1"
        raise ValueError(msg)

    collector = QueryDiagnosticCollector(
        scope_kind=scope_kind,
        scope_name=scope_name,
        duplicate_threshold=duplicate_threshold,
    )
    token = _current_collector.set(collector)
    try:
        yield collector
    finally:
        _current_collector.reset(token)


def record_query(statement: str, *, parameters: object | None = None) -> None:
    """Active collector がある場合だけ SQL statement を記録する.

    Args:
        statement: SQLAlchemy cursor execute が受け取った SQL template.
        parameters: DBAPI に渡される params. 記録せず破棄する.
    """
    _ = parameters
    collector = _current_collector.get()
    if collector is None:
        return
    collector.record(statement)


def install_query_diagnostics(engine: AsyncEngine) -> None:
    """AsyncEngine の sync engine に SQLAlchemy cursor event listener を登録する.

    Args:
        engine: SQLAlchemy async engine.
    """
    sync_engine = engine.sync_engine
    if sync_engine in _installed_sync_engines:
        return
    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    _installed_sync_engines.add(sync_engine)


def _before_cursor_execute(
    _conn: object,
    _cursor: object,
    statement: str,
    parameters: object,
    _context: object,
    _executemany: bool,
) -> None:
    record_query(statement, parameters=parameters)


def _normalize_sql(statement: str) -> str:
    return _SQL_WHITESPACE_PATTERN.sub(" ", statement).strip()


def _fingerprint_sql(template: str) -> str:
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:_FINGERPRINT_LENGTH]


def _sql_prefix(template: str) -> str:
    if len(template) <= _SQL_PREFIX_MAX_LENGTH:
        return template
    return f"{template[: _SQL_PREFIX_MAX_LENGTH - 3]}..."
