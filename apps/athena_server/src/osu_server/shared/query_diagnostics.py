"""SQL query diagnostics の共有 scope primitive を定義する."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from traceback import FrameSummary, extract_stack
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
_TRACEBACK_CAPTURE_LIMIT = 120
_TRACEBACK_SUMMARY_LIMIT = 8
_PROJECT_PATH_MARKERS = ("apps/athena_server/", "tests/", "/osu_server/")
_INTERNAL_TRACEBACK_SUFFIXES = (
    "/shared/query_diagnostics.py",
    "/infrastructure/database/query_diagnostics.py",
)
_current_collector: ContextVar[QueryDiagnosticCollector | None] = ContextVar(
    "query_diagnostic_collector",
    default=None,
)


class _AsyncDiagnosticLogger(Protocol):
    """診断 warning を非同期に記録できる logger の最小境界を表す."""

    async def awarning(self, event: str, **event_kw: object) -> object:
        """Warning event と redacted field を非同期に記録する.

        Args:
            event (str): warning を識別する event 名.
            **event_kw (object): event に関連付ける redacted field.

        Returns:
            object: logger 実装が返す記録結果.
        """
        ...

    async def adebug(self, event: str, **event_kw: object) -> object:
        """Diagnostics logging 失敗を示す debug event を非同期に記録する.

        Args:
            event (str): debug event を識別する event 名.
            **event_kw (object): event に関連付ける redacted field.

        Returns:
            object: logger 実装が返す記録結果.
        """
        ...


@dataclass(slots=True, frozen=True)
class DuplicateQuerySummary:
    """重複 SQL template の redacted summary を表す.

    Attributes:
        fingerprint (str): redacted SQL template から算出した短縮 fingerprint.
        count (int): この template が scope 内で観測された回数.
        sql_prefix (str): literal 値を ? に置換した SQL template の先頭部分.
        traceback (tuple[str, ...]): duplicate thresholdへ初めて到達した呼び出し元 stack.
    """

    fingerprint: str
    count: int
    sql_prefix: str
    traceback: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class QueryDiagnosticSummary:
    """1 つの diagnostic scope で観測した SQL 発行数 summary を表す.

    Attributes:
        scope_kind (str): `http_request` や `taskiq_job` などの scope 種別.
        scope_name (str): path や task name などの redacted scope 名.
        total_queries (int): scope 内で観測した SQL query 数.
        duplicate_queries (tuple[DuplicateQuerySummary, ...]): 上位 duplicate SQL template の
            redacted summary.
        duplicate_templates_total (int): duplicate threshold を満たした template 総数.
        duplicates_truncated (bool): duplicate_queries が上限で切り詰められたか.
    """

    scope_kind: str
    scope_name: str
    total_queries: int
    duplicate_queries: tuple[DuplicateQuerySummary, ...]
    duplicate_templates_total: int
    duplicates_truncated: bool


@dataclass(slots=True)
class QueryDiagnosticCollector:
    """active scope 内の SQL template を記録する collector を表す.

    Attributes:
        scope_kind (str): scope 種別.
        scope_name (str): redacted scope 名.
        duplicate_threshold (int): duplicate として扱う同一 template の最小回数.
        _query_count (int): scope 内で記録した SQL query 数.
        _template_counts (Counter[str]): redacted SQL template ごとの出現回数.
        _template_tracebacks (dict[str, tuple[str, ...]]): threshold到達時の呼び出し元 stack.
    """

    scope_kind: str
    scope_name: str
    duplicate_threshold: int
    _query_count: int = 0
    _template_counts: Counter[str] = field(default_factory=Counter)
    _template_tracebacks: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def record(self, statement: str) -> None:
        """SQL statement を redacted template として記録する.

        Args:
            statement (str): cursor execute が受け取った SQL statement.

        Returns:
            None: active collector 内の query count と template count を更新する.

        Notes:
            SQL params は受け取らず SQL text 内の literal 値も ? に置換する.
        """
        template = _normalize_sql(statement)
        if not template:
            return
        self._query_count += 1
        count = self._template_counts[template] + 1
        self._template_counts[template] = count
        if count == self.duplicate_threshold:
            self._template_tracebacks[template] = _query_traceback()

    def summary(self) -> QueryDiagnosticSummary:
        """現在の記録内容から redacted summary を返す.

        Returns:
            QueryDiagnosticSummary: query count と duplicate template 数と上位 summary を持つ値.

        Notes:
            duplicate_queries は上位 10 件に制限し SQL params と literal 値は含めない.
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
                traceback=self._template_tracebacks.get(template, ()),
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
        summary (QueryDiagnosticSummary): query diagnostic scope の summary.
        max_queries (int): 許容する最大 SQL query 数.

    Returns:
        bool: query count 超過または duplicate query がある場合は True.
    """
    return summary.total_queries > max_queries or summary.duplicate_templates_total > 0


def query_diagnostics_warning_fields(
    summary: QueryDiagnosticSummary,
    *,
    max_queries: int,
) -> dict[str, object]:
    """Warning log に渡す redacted field を返す.

    Args:
        summary (QueryDiagnosticSummary): query diagnostic scope の summary.
        max_queries (int): 許容する最大 SQL query 数.

    Returns:
        dict[str, object]: SQL params と SQL literal 値を含まない structlog 用 field.
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
                "traceback": duplicate.traceback,
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
        logger (_AsyncDiagnosticLogger): structlog 互換の async logger.
        summary (QueryDiagnosticSummary): query diagnostic scope の summary.
        max_queries (int): 許容する最大 SQL query 数.

    Returns:
        None: threshold 未超過時は何も記録せず 超過時は warning を記録する.

    Notes:
        diagnostics logging の失敗は request/job の結果を変えない.
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
        scope_kind (str): `http_request` や `taskiq_job` などの scope 種別.
        scope_name (str): method/path や task name などの redacted scope 名.
        duplicate_threshold (int): duplicate として扱う同一 SQL template の最小回数.

    Yields:
        QueryDiagnosticCollector: scope 内で記録された SQL を保持する collector.

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
        statement (str): cursor execute が受け取った SQL statement.
        parameters (object | None): DBAPI に渡される params. 記録せず破棄する.

    Returns:
        None: active collector がある場合だけ statement を記録する.

    Notes:
        parameters は diagnostics output へ含めず credential や個人情報の記録を防ぐ.
    """
    _ = parameters
    collector = _current_collector.get()
    if collector is None:
        return
    collector.record(statement)


def _duplicate_sort_key(item: tuple[str, int]) -> tuple[int, str]:
    """Duplicate template を出現回数の降順で並べる key を返す.

    Args:
        item (tuple[str, int]): redacted SQL template とその出現回数.

    Returns:
        tuple[int, str]: count の降順と template の昇順を表す sort key.
    """
    template, count = item
    return (-count, template)


def _normalize_sql(statement: str) -> str:
    """SQL statement を literal を含まない比較用 template に正規化する.

    Args:
        statement (str): cursor execute が受け取った SQL statement.

    Returns:
        str: comment を除去し literal を ? へ置換して空白を正規化した template.

    Notes:
        dollar quote と single quote と数値 literal を置換し値そのものを記録しない.
    """
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
    """Redacted SQL template の固定長 fingerprint を返す.

    Args:
        template (str): literal を除去済みの SQL template.

    Returns:
        str: SHA-256 digest の先頭 16 文字.
    """
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:_FINGERPRINT_LENGTH]


def _sql_prefix(template: str) -> str:
    """表示上限に収まる redacted SQL template の prefix を返す.

    Args:
        template (str): literal を除去済みの SQL template.

    Returns:
        str: 160 文字以下の template または末尾に ... を付けた prefix.
    """
    if len(template) <= _SQL_PREFIX_MAX_LENGTH:
        return template
    return f"{template[: _SQL_PREFIX_MAX_LENGTH - 3]}..."


def _query_traceback() -> tuple[str, ...]:
    """Query diagnostics に出す呼び出し元 stack を値なし形式で返す.

    Returns:
        tuple[str, ...]: project内frameだけを `path:line in function` 形式にしたstack.

    Notes:
        Source lineはSQL literalやparameterを含む可能性があるため記録しない.
    """
    frames = [
        _format_traceback_frame(frame)
        for frame in extract_stack(limit=_TRACEBACK_CAPTURE_LIMIT)
        if _is_query_traceback_frame(frame)
    ]
    return tuple(frames[-_TRACEBACK_SUMMARY_LIMIT:])


def _is_query_traceback_frame(frame: FrameSummary) -> bool:
    """SQL diagnostics の呼び出し元として表示するproject frameかを返す.

    Args:
        frame (FrameSummary): Python tracebackから抽出したframe.

    Returns:
        bool: Athenaのsource/test frameで内部diagnostics実装ではない場合はTrue.
    """
    filename = frame.filename.replace("\\", "/")
    if filename.endswith(_INTERNAL_TRACEBACK_SUFFIXES):
        return False
    return any(marker in filename for marker in _PROJECT_PATH_MARKERS)


def _format_traceback_frame(frame: FrameSummary) -> str:
    """Traceback frame を source lineなしの短い表示へ変換する.

    Args:
        frame (FrameSummary): Python tracebackから抽出したframe.

    Returns:
        str: `path:line in function` 形式のframe表示.
    """
    filename = frame.filename.replace("\\", "/")
    return f"{_display_traceback_path(filename)}:{frame.lineno} in {frame.name}"


def _display_traceback_path(filename: str) -> str:
    """Traceback用の絶対pathをrepository内pathへ短縮する.

    Args:
        filename (str): Python tracebackから得たsource file path.

    Returns:
        str: project marker以降のpath. markerがない場合は入力path.
    """
    for marker in _PROJECT_PATH_MARKERS:
        if marker in filename:
            return filename[filename.index(marker) :]
    return filename
