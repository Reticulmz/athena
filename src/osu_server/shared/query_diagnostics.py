"""SQL query diagnostics shared scope primitives."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Generator

_SQL_BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
_SQL_DOLLAR_QUOTED_LITERAL_PATTERN = re.compile(
    r"\$([A-Za-z_][A-Za-z0-9_]*)\$.*?\$\1\$|\$\$.*?\$\$",
    re.DOTALL,
)
_SQL_LINE_COMMENT_PATTERN = re.compile(r"--[^\r\n]*")
_SQL_NUMERIC_LITERAL_PATTERN = re.compile(r"(?<![\w$])-?(?:\d+\.\d+|\d+)(?![\w$])")
_SQL_SINGLE_QUOTED_LITERAL_PATTERN = re.compile(r"'(?:''|[^'])*'")
_SQL_WHITESPACE_PATTERN = re.compile(r"\s+")
_SQL_PREFIX_MAX_LENGTH = 160
_FINGERPRINT_LENGTH = 16
_DUPLICATE_SUMMARY_LIMIT = 10
_current_collector: ContextVar[QueryDiagnosticCollector | None] = ContextVar(
    "query_diagnostic_collector",
    default=None,
)


class _AsyncDiagnosticLogger(Protocol):
    async def awarning(self, event: str, **event_kw: object) -> object: ...

    async def adebug(self, event: str, **event_kw: object) -> object: ...


@dataclass(slots=True, frozen=True)
class DuplicateQuerySummary:
    """重複 SQL template の redacted summary.

    Attributes:
        fingerprint: Redacted SQL template から算出した短縮 fingerprint.
        count: この template が scope 内で観測された回数.
        sql_prefix: Literal 値を ? に置換した SQL template の先頭部分.
    """

    fingerprint: str
    count: int
    sql_prefix: str


@dataclass(slots=True, frozen=True)
class QueryDiagnosticSummary:
    """1 つの diagnostic scope で観測した SQL 発行数 summary.

    Attributes:
        scope_kind: `http_request`, `taskiq_job`, `test` などの scope 種別.
        scope_name: Path や task name などの redacted scope 名.
        total_queries: Scope 内で観測した SQL query 数.
        duplicate_queries: 上位 duplicate SQL template の redacted summary.
        duplicate_templates_total: Duplicate threshold を満たした template 総数.
        duplicates_truncated: duplicate_queries が上限で切り詰められた場合は true.
    """

    scope_kind: str
    scope_name: str
    total_queries: int
    duplicate_queries: tuple[DuplicateQuerySummary, ...]
    duplicate_templates_total: int
    duplicates_truncated: bool


@dataclass(slots=True)
class QueryDiagnosticCollector:
    """Active scope 内の SQL template を記録する collector.

    Attributes:
        scope_kind: Scope 種別.
        scope_name: Redacted scope 名.
        duplicate_threshold: Duplicate として扱う同一 template の最小回数.
    """

    scope_kind: str
    scope_name: str
    duplicate_threshold: int
    _query_count: int = 0
    _template_counts: Counter[str] = field(default_factory=Counter)

    def record(self, statement: str) -> None:
        """SQL statement を redacted template として記録する.

        Args:
            statement: SQLAlchemy cursor execute が受け取った SQL statement.

        Returns:
            なし. Active collector 内の query count と template count を更新する.

        Constraints:
            SQL params は受け取らず, SQL text 内の literal 値も ? に置換する.
        """
        template = _normalize_sql(statement)
        if not template:
            return
        self._query_count += 1
        self._template_counts[template] += 1

    def summary(self) -> QueryDiagnosticSummary:
        """現在の記録内容から redacted summary を返す.

        Returns:
            Query count, duplicate template 数, 上位 duplicate summary を持つ
            QueryDiagnosticSummary.

        Constraints:
            duplicate_queries は上位 10 件に制限し, SQL params と literal 値は含めない.
        """
        duplicate_templates = [
            (template, count)
            for template, count in self._template_counts.items()
            if count >= self.duplicate_threshold
        ]
        duplicate_templates.sort(key=_duplicate_sort_key)
        retained_templates = duplicate_templates[:_DUPLICATE_SUMMARY_LIMIT]
        duplicates = tuple(
            DuplicateQuerySummary(
                fingerprint=_fingerprint_sql(template),
                count=count,
                sql_prefix=_sql_prefix(template),
            )
            for template, count in retained_templates
        )
        duplicate_templates_total = len(duplicate_templates)
        return QueryDiagnosticSummary(
            scope_kind=self.scope_kind,
            scope_name=self.scope_name,
            total_queries=self._query_count,
            duplicate_queries=duplicates,
            duplicate_templates_total=duplicate_templates_total,
            duplicates_truncated=duplicate_templates_total > len(duplicates),
        )


def query_diagnostics_exceeded(summary: QueryDiagnosticSummary, *, max_queries: int) -> bool:
    """Summary が runtime warning threshold を超えたかを返す.

    Args:
        summary: Query diagnostic scope の summary.
        max_queries: 許容する最大 SQL query 数.

    Returns:
        Query count 超過または duplicate query がある場合は true.
    """
    return summary.total_queries > max_queries or summary.duplicate_templates_total > 0


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
        SQL params と SQL literal 値を含まない structlog 用 fields.
    """
    return {
        "scope_kind": summary.scope_kind,
        "scope_name": summary.scope_name,
        "total_queries": summary.total_queries,
        "max_queries": max_queries,
        "duplicate_templates_total": summary.duplicate_templates_total,
        "duplicates_truncated": summary.duplicates_truncated,
        "duplicates": tuple(
            {
                "fingerprint": duplicate.fingerprint,
                "count": duplicate.count,
                "sql_prefix": duplicate.sql_prefix,
            }
            for duplicate in summary.duplicate_queries
        ),
    }


async def emit_sql_query_diagnostics_warning(
    logger: _AsyncDiagnosticLogger,
    summary: QueryDiagnosticSummary,
    *,
    max_queries: int,
) -> None:
    """Threshold 超過時に SQL diagnostics warning を出す.

    Args:
        logger: structlog 互換の async logger.
        summary: Query diagnostic scope の summary.
        max_queries: 許容する最大 SQL query 数.

    Returns:
        なし.

    Constraints:
        Diagnostics logging の失敗は request/job の結果を変えない.
    """
    if not query_diagnostics_exceeded(summary, max_queries=max_queries):
        return
    try:
        _ = await logger.awarning(
            "sql_query_diagnostics_warning",
            **query_diagnostics_warning_fields(summary, max_queries=max_queries),
        )
    except Exception as exc:  # noqa: BLE001, RUF100 - diagnostics logging must not mask request/job results.
        with suppress(Exception):
            _ = await logger.adebug(
                "sql_query_diagnostics_warning_failed",
                error_type=type(exc).__name__,
            )


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
        statement: SQLAlchemy cursor execute が受け取った SQL statement.
        parameters: DBAPI に渡される params. 記録せず破棄する.
    """
    _ = parameters
    collector = _current_collector.get()
    if collector is None:
        return
    collector.record(statement)


def _duplicate_sort_key(item: tuple[str, int]) -> tuple[int, str]:
    template, count = item
    return (-count, template)


def _normalize_sql(statement: str) -> str:
    without_block_comments = _SQL_BLOCK_COMMENT_PATTERN.sub(" ", statement)
    without_line_comments = _SQL_LINE_COMMENT_PATTERN.sub(" ", without_block_comments)
    without_dollar_literals = _SQL_DOLLAR_QUOTED_LITERAL_PATTERN.sub(
        "?",
        without_line_comments,
    )
    without_string_literals = _SQL_SINGLE_QUOTED_LITERAL_PATTERN.sub(
        "?",
        without_dollar_literals,
    )
    without_numeric_literals = _SQL_NUMERIC_LITERAL_PATTERN.sub(
        "?",
        without_string_literals,
    )
    return _SQL_WHITESPACE_PATTERN.sub(" ", without_numeric_literals).strip()


def _fingerprint_sql(template: str) -> str:
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:_FINGERPRINT_LENGTH]


def _sql_prefix(template: str) -> str:
    if len(template) <= _SQL_PREFIX_MAX_LENGTH:
        return template
    return f"{template[: _SQL_PREFIX_MAX_LENGTH - 3]}..."
