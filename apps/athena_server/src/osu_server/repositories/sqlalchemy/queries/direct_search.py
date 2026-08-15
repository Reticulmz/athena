"""PostgreSQL系osu!direct search backendとauto fallbackを提供する."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, cast

import structlog
from paradedb.sqlalchemy import pdb, search
from sqlalchemy import (
    String,
    Text,
    case,
    column,
    func,
    literal,
    literal_column,
    or_,
    select,
    table,
    union_all,
)

from osu_server.domain.beatmaps.direct import (
    DirectSearchBackend,
    DirectSearchBackendResult,
    DirectSearchBackendUnavailableError,
    DirectSearchCandidate,
    DirectSearchListing,
    DirectSearchRequest,
)
from osu_server.repositories.sqlalchemy.models.beatmap import BeatmapModel, BeatmapSetModel

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from sqlalchemy.sql.base import Executable
    from sqlalchemy.sql.elements import ColumnElement

    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

_BM25_INDEX_NAME: Final = "idx_beatmapsets_direct_search_bm25"
_PG_SEARCH_EXTENSION: Final = "pg_search"
_DIFFICULTY_NAME_EXACT_SCORE: Final = 1_000_000.0
_FALLBACK_SCORE: Final = 0.0
_POSTGRES_TEXT_SEARCH_CONFIG: Final = "simple"
_SEARCH_DOCUMENT_TABLE_NAME: Final = "beatmapsets"
_DIRECT_SEARCH_TEXT_FIELD: Final = "direct_search_text"
_INACTIVE_STATUS_VALUES: Final = ("not_submitted", "unknown")
_PG_AVAILABLE_EXTENSIONS = table("pg_available_extensions", column("name", String))
_PG_EXTENSION = table("pg_extension", column("extname", String))
_PG_INDEXES = table(
    "pg_indexes",
    column("indexname", String),
    column("indexdef", Text),
)
_INFORMATION_SCHEMA_COLUMNS = table(
    "columns",
    column("table_schema", String),
    column("table_name", String),
    column("column_name", String),
    schema="information_schema",
)
_PARADEDB_SCORE = cast("Callable[[ColumnElement[object]], ColumnElement[float]]", pdb.score)
_PARADEDB_MATCH_ANY = cast(
    "Callable[[ColumnElement[object], str], ColumnElement[bool]]",
    search.match_any,
)
_REQUIRED_BM25_FIELDS: Final = ("id", _DIRECT_SEARCH_TEXT_FIELD)
_REQUIRED_TSVECTOR_FIELDS: Final = (
    "id",
    "official_status",
    "official_last_updated_at",
    _DIRECT_SEARCH_TEXT_FIELD,
)

logger: structlog.stdlib.BoundLogger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)


class ParadeDBSearchBackendUnavailableError(DirectSearchBackendUnavailableError):
    """ParadeDB search backendの必須capability不足を表す例外."""


class TsvectorSearchBackendUnavailableError(DirectSearchBackendUnavailableError):
    """PostgreSQL tsvector search backendの必須capability不足を表す例外."""


class AutoDirectSearchBackend:
    """利用可能なsearch backendを起動時または初回検索時に固定選択する.

    Attributes:
        _backends (tuple[tuple[str, DirectSearchBackend], ...]): 優先順付きbackend列.
        _selected_backend (DirectSearchBackend | None): 検証後に固定したbackend.
        _selected_backend_name (str | None): 検証後に固定したbackend名.
    """

    _backends: tuple[tuple[str, DirectSearchBackend], ...]
    _selected_backend: DirectSearchBackend | None
    _selected_backend_name: str | None

    def __init__(
        self,
        *,
        backends: Sequence[tuple[str, DirectSearchBackend]],
    ) -> None:
        """Auto選択に使うbackend候補を優先順で保持する.

        Args:
            backends (Sequence[tuple[str, DirectSearchBackend]]): 優先順付きbackend列.

        Raises:
            ValueError: backend候補が空の場合.
        """
        if not backends:
            msg = "auto direct search backend requires at least one backend"
            raise ValueError(msg)
        self._backends = tuple(backends)
        self._selected_backend = None
        self._selected_backend_name = None

    async def search(self, request: DirectSearchRequest) -> DirectSearchBackendResult:
        """固定選択済みまたは初回選択したbackendへ検索を委譲する.

        Args:
            request (DirectSearchRequest): stable inputから導出された検索条件.

        Returns:
            DirectSearchBackendResult: 選択backendから返された候補IDとscore.
        """
        backend = await self._backend()
        return await backend.search(request)

    async def validate(self) -> None:
        """利用可能なsearch backendを検証して固定する.

        Returns:
            None: 優先順の最初に利用可能なbackendを固定したことを示す.

        Raises:
            DirectSearchBackendUnavailableError: すべてのbackendが利用できない場合.
            SQLAlchemyError: backend検証queryの予期しない失敗が伝播した場合.
        """
        _ = await self._backend()

    async def _backend(self) -> DirectSearchBackend:
        """固定済みbackendを返し、未選択なら検証して選ぶ.

        Returns:
            DirectSearchBackend: このprocessで使うsearch backend.

        Raises:
            DirectSearchBackendUnavailableError: すべてのbackendが利用できない場合.
            SQLAlchemyError: backend検証queryの予期しない失敗が伝播した場合.
        """
        if self._selected_backend is not None:
            return self._selected_backend

        unavailable_reasons: dict[str, str] = {}
        for backend_name, backend in self._backends:
            try:
                await backend.validate()
            except DirectSearchBackendUnavailableError as exc:
                unavailable_reasons[backend_name] = str(exc)
                continue
            self._selected_backend = backend
            self._selected_backend_name = backend_name
            if unavailable_reasons:
                logger.warning(
                    "osu_direct_search_backend_fallback",
                    selected_backend=backend_name,
                    unavailable_backends=tuple(unavailable_reasons),
                    reasons=unavailable_reasons,
                    impact=_fallback_impact(backend_name),
                    remediation=_fallback_remediation(backend_name),
                )
            else:
                logger.info(
                    "osu_direct_search_backend_selected",
                    selected_backend=backend_name,
                )
            return self._selected_backend

        msg = "No osu!direct search backend is available: " + "; ".join(
            f"{backend_name}: {reason}" for backend_name, reason in unavailable_reasons.items()
        )
        raise DirectSearchBackendUnavailableError(msg)


class ParadeDBSearchBackend:
    """ParadeDB BM25 indexからosu!direct候補IDとscoreを取得するbackend.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread session factory.
    """

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """読み取り用session factoryを保持してbackendを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.
        """
        self._session_factory = session_factory

    async def search(self, request: DirectSearchRequest) -> DirectSearchBackendResult:
        """Beatmapset検索入力から検索候補IDとscoreだけを返す.

        Args:
            request (DirectSearchRequest): stable inputから導出された検索条件.

        Returns:
            DirectSearchBackendResult: page内候補と次page有無.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            KeyError: SQL result rowに必須fieldがない場合.
            TypeError: SQL result rowの必須field型が期待値と異なる場合.
        """
        return await _execute_search(
            self._session_factory,
            request,
            _search_statement,
        )

    async def validate(self) -> None:
        """ParadeDB extensionとBM25 index fieldが利用可能か検証する.

        Returns:
            None: extensionとindexが必要fieldを満たすことを示す.

        Raises:
            ParadeDBSearchBackendUnavailableError: extension, index, またはfieldが不足する場合.
            SQLAlchemyError: validation queryの実行に失敗した場合.
        """
        async with self._session_factory() as session:
            row = cast(
                "Mapping[str, object] | None",
                (await session.execute(_validation_statement())).mappings().one_or_none(),
            )

        if row is None or _bool_field(row, "has_available_extension") is not True:
            msg = "ParadeDB pg_search extension is not installed in PostgreSQL"
            raise ParadeDBSearchBackendUnavailableError(msg)

        if _bool_field(row, "has_created_extension") is not True:
            msg = "ParadeDB pg_search extension has not been created in this database"
            raise ParadeDBSearchBackendUnavailableError(msg)

        index_definition = _optional_str_field(row, "index_definition")
        if index_definition is None:
            msg = f"ParadeDB BM25 index is not available: {_BM25_INDEX_NAME}"
            raise ParadeDBSearchBackendUnavailableError(msg)

        missing_fields = tuple(
            field
            for field in _REQUIRED_BM25_FIELDS
            if not _index_definition_contains_field(index_definition, field)
        )
        if missing_fields:
            msg = (
                f"ParadeDB BM25 index {_BM25_INDEX_NAME} is missing fields: "
                f"{', '.join(missing_fields)}"
            )
            raise ParadeDBSearchBackendUnavailableError(msg)


class TsvectorSearchBackend:
    """PostgreSQL組み込み全文検索でosu!direct候補IDとscoreを取得するbackend.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread session factory.
    """

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """読み取り用session factoryを保持してbackendを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.
        """
        self._session_factory = session_factory

    async def search(self, request: DirectSearchRequest) -> DirectSearchBackendResult:
        """Beatmapset検索入力からtsvector検索候補IDとscoreだけを返す.

        Args:
            request (DirectSearchRequest): stable inputから導出された検索条件.

        Returns:
            DirectSearchBackendResult: page内候補と次page有無.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            KeyError: SQL result rowに必須fieldがない場合.
            TypeError: SQL result rowの必須field型が期待値と異なる場合.
        """
        return await _execute_search(
            self._session_factory,
            request,
            _tsvector_search_statement,
        )

    async def validate(self) -> None:
        """Beatmapsets tableがtsvector backendに必要な列を持つか検証する.

        Returns:
            None: beatmapsets tableが必要fieldを満たすことを示す.

        Raises:
            TsvectorSearchBackendUnavailableError: beatmapsets tableまたはfieldが不足する場合.
            SQLAlchemyError: validation queryの実行に失敗した場合.
        """
        async with self._session_factory() as session:
            rows = cast(
                "Sequence[Mapping[str, object]]",
                (await session.execute(_tsvector_validation_statement())).mappings().all(),
            )

        existing_fields = {_str_field(row, "column_name") for row in rows}
        missing_fields = tuple(
            field for field in _REQUIRED_TSVECTOR_FIELDS if field not in existing_fields
        )
        if missing_fields:
            msg = (
                f"PostgreSQL tsvector search backend is missing beatmapset fields: "
                f"{', '.join(missing_fields)}"
            )
            raise TsvectorSearchBackendUnavailableError(msg)


async def _execute_search(
    session_factory: SQLAlchemyQuerySessionFactory,
    request: DirectSearchRequest,
    statement_factory: Callable[[DirectSearchRequest], Executable],
) -> DirectSearchBackendResult:
    """Backend固有statementを実行して共通のpage結果へ変換する.

    Args:
        session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread session factory.
        request (DirectSearchRequest): page sizeを含む検索条件.
        statement_factory (Callable[[DirectSearchRequest], Executable]): backend固有SELECT builder.

    Returns:
        DirectSearchBackendResult: page内候補と次page有無.

    Raises:
        SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
        KeyError: SQL result rowに必須fieldがない場合.
        TypeError: SQL result rowの必須field型が期待値と異なる場合.
    """
    async with session_factory() as session:
        rows = cast(
            "Sequence[Mapping[str, object]]",
            (await session.execute(statement_factory(request))).mappings().all(),
        )

    candidate_rows = rows[: request.page_size]
    return DirectSearchBackendResult(
        candidates=tuple(_candidate_from_mapping(row) for row in candidate_rows),
        has_more=len(rows) > request.page_size,
    )


def _search_statement(request: DirectSearchRequest) -> Executable:
    """Direct search requestをParadeDB検索SELECTへ変換する.

    Args:
        request (DirectSearchRequest): backendへ渡された検索条件.

    Returns:
        Executable: 候補IDとscoreだけを返すSELECT.
    """
    uses_text_search = _uses_text_search(request)
    query_text = request.query_text.strip()
    mode = request.mode.value if request.mode is not None else None
    if uses_text_search:
        return _paradedb_text_search_statement(request, query_text, mode=mode)
    return _fallback_search_statement(request, mode=mode)


def _paradedb_text_search_statement(
    request: DirectSearchRequest,
    query_text: str,
    *,
    mode: str | None,
) -> Executable:
    """ParadeDB text検索とdifficulty名補完を分離したSELECTへ変換する.

    Args:
        request (DirectSearchRequest): backendへ渡された検索条件.
        query_text (str): 空白除去済みの検索文字列.
        mode (str | None): 絞り込むmode. Noneならmodeを問わない.

    Returns:
        Executable: 候補IDと最大scoreを返すSELECT.
    """
    score = _PARADEDB_SCORE(
        cast(
            "ColumnElement[object]",
            cast("object", BeatmapSetModel.id),
        )
    ).label("score")
    scope_filters = _search_scope_filters(request, mode=mode)
    candidate_scores = union_all(
        select(
            BeatmapSetModel.id.label("beatmapset_id"),
            score,
        ).where(*scope_filters, _text_search_filter(query_text)),
        select(
            BeatmapSetModel.id.label("beatmapset_id"),
            literal(_DIFFICULTY_NAME_EXACT_SCORE).label("score"),
        ).where(*scope_filters, _difficulty_name_search_filter(query_text, mode=mode)),
    ).subquery()

    beatmapset_id = cast("ColumnElement[int]", candidate_scores.c.beatmapset_id)
    max_score = func.max(candidate_scores.c.score).label("score")
    last_update_at = _last_update_at_expression(beatmapset_id)
    return (
        select(
            candidate_scores.c.beatmapset_id,
            max_score,
        )
        .group_by(candidate_scores.c.beatmapset_id)
        .order_by(
            max_score.desc(),
            last_update_at.desc().nulls_last(),
            candidate_scores.c.beatmapset_id.desc(),
        )
        .offset(request.page * request.page_size)
        .limit(request.page_size + 1)
    )


def _tsvector_search_statement(request: DirectSearchRequest) -> Executable:
    """Direct search requestをPostgreSQL tsvector検索SELECTへ変換する.

    Args:
        request (DirectSearchRequest): backendへ渡された検索条件.

    Returns:
        Executable: 候補IDとscoreだけを返すSELECT.
    """
    uses_text_search = _uses_text_search(request)
    query_text = request.query_text.strip()
    mode = request.mode.value if request.mode is not None else None
    if not uses_text_search:
        return _fallback_search_statement(request, mode=mode)

    score = _tsvector_score_expression(query_text, mode=mode).label("score")
    statement = select(
        BeatmapSetModel.id.label("beatmapset_id"),
        score,
    ).where(
        *_search_scope_filters(request, mode=mode),
        _text_or_difficulty_search_filter(
            _tsvector_text_search_filter(query_text),
            query_text,
            mode=mode,
        ),
    )

    last_update_at = _last_update_at_expression()
    statement = statement.order_by(
        score.desc(),
        last_update_at.desc().nulls_last(),
        BeatmapSetModel.id.desc(),
    )

    return statement.offset(request.page * request.page_size).limit(request.page_size + 1)


def _fallback_search_statement(
    request: DirectSearchRequest,
    *,
    mode: str | None,
) -> Executable:
    """Backend非依存のlisting SELECTとfallback順を構築する.

    Args:
        request (DirectSearchRequest): filterとpageを持つ検索条件.
        mode (str | None): 絞り込むmode. Noneならmodeを問わない.

    Returns:
        Executable: fallback scoreと更新日時順を持つ候補SELECT.
    """
    score = literal(_FALLBACK_SCORE).label("score")
    statement = (
        select(
            BeatmapSetModel.id.label("beatmapset_id"),
            score,
        )
        .where(*_search_scope_filters(request, mode=mode))
        .order_by(
            _last_update_at_expression().desc().nulls_last(),
            BeatmapSetModel.id.desc(),
        )
    )
    return statement.offset(request.page * request.page_size).limit(request.page_size + 1)


def _validation_statement() -> Executable:
    """ParadeDB backendの必須DB capabilityを読むSELECTを構築する.

    Returns:
        Executable: pg_searchの導入/作成有無とBM25 index定義を返すSELECT.
    """
    has_available_extension = (
        select(literal(True))
        .select_from(_PG_AVAILABLE_EXTENSIONS)
        .where(_PG_AVAILABLE_EXTENSIONS.c.name == _PG_SEARCH_EXTENSION)
        .exists()
        .label("has_available_extension")
    )
    has_created_extension = (
        select(literal(True))
        .select_from(_PG_EXTENSION)
        .where(_PG_EXTENSION.c.extname == _PG_SEARCH_EXTENSION)
        .exists()
        .label("has_created_extension")
    )
    index_definition = (
        select(_PG_INDEXES.c.indexdef)
        .select_from(_PG_INDEXES)
        .where(_PG_INDEXES.c.indexname == _BM25_INDEX_NAME)
        .limit(1)
        .scalar_subquery()
        .label("index_definition")
    )
    return select(has_available_extension, has_created_extension, index_definition)


def _tsvector_validation_statement() -> Executable:
    """Tsvector backendが必要とするprojection column一覧を読むSELECTを構築する.

    Returns:
        Executable: information_schemaから既存column名を返すSELECT.
    """
    return select(_INFORMATION_SCHEMA_COLUMNS.c.column_name).where(
        _INFORMATION_SCHEMA_COLUMNS.c.table_schema == "public",
        _INFORMATION_SCHEMA_COLUMNS.c.table_name == _SEARCH_DOCUMENT_TABLE_NAME,
        _INFORMATION_SCHEMA_COLUMNS.c.column_name.in_(_REQUIRED_TSVECTOR_FIELDS),
    )


def _fallback_impact(selected_backend: str) -> str:
    """Fallback選択時にoperatorへ出す影響説明を返す.

    Args:
        selected_backend (str): auto選択で固定したbackend名.

    Returns:
        str: structured logへ記録する検索体験への影響.
    """
    if selected_backend == "tsvector":
        missing_search_quality = "ParadeDB BM25 or Meilisearch typo-tolerant search"
        return f"osu!direct search quality is degraded without {missing_search_quality}"
    return (
        "osu!direct search is using a fallback backend because a preferred backend is unavailable"
    )


def _fallback_remediation(selected_backend: str) -> str:
    """Fallback選択時にoperatorへ出す復旧案内を返す.

    Args:
        selected_backend (str): auto選択で固定したbackend名.

    Returns:
        str: structured logへ記録する復旧案内.
    """
    if selected_backend == "tsvector":
        return "install pg_search or configure Meilisearch to restore higher-quality search"
    return "restore the preferred backend or set OSU_DIRECT_SEARCH_BACKEND explicitly"


def _uses_text_search(request: DirectSearchRequest) -> bool:
    """RequestがBM25 text検索を必要とするか判定する.

    Args:
        request (DirectSearchRequest): backendへ渡された検索条件.

    Returns:
        bool: 通常検索listingで空ではないquery_textを持つ場合はTrue.
    """
    return request.listing is DirectSearchListing.SEARCH and bool(request.query_text.strip())


def _search_scope_filters(
    request: DirectSearchRequest,
    *,
    mode: str | None,
) -> tuple[ColumnElement[bool], ...]:
    """検索種別に依存しないbeatmapsetの絞り込み条件を返す.

    Args:
        request (DirectSearchRequest): backendへ渡された検索条件.
        mode (str | None): 絞り込むmode. Noneならmodeを問わない.

    Returns:
        tuple[ColumnElement[bool], ...]: active/status/mode条件.
    """
    filters = [_active_beatmapset_filter()]
    if request.statuses:
        filters.append(
            BeatmapSetModel.official_status.in_([status.value for status in request.statuses])
        )
    if mode is not None:
        filters.append(_usable_child_exists(mode=mode))
    return tuple(filters)


def _text_or_difficulty_search_filter(
    text_search_filter: ColumnElement[bool],
    query_text: str,
    *,
    mode: str | None,
) -> ColumnElement[bool]:
    """検索index一致またはlocal difficulty名の完全一致条件を返す.

    Args:
        text_search_filter (ColumnElement[bool]): backend固有の全文検索条件.
        query_text (str): 空白除去済みの検索文字列.
        mode (str | None): 絞り込むmode. Noneならmodeを問わない.

    Returns:
        ColumnElement[bool]: 検索indexまたはchild difficulty名へ一致する条件.
    """
    return or_(text_search_filter, _difficulty_name_search_filter(query_text, mode=mode))


def _text_search_filter(query_text: str) -> ColumnElement[bool]:
    """Materialized検索入力へParadeDB text検索条件を適用する.

    Args:
        query_text (str): 空白除去済みの検索文字列.

    Returns:
        ColumnElement[bool]: direct_search_textが一致する条件.
    """
    return _PARADEDB_MATCH_ANY(
        cast("ColumnElement[object]", cast("object", BeatmapSetModel.direct_search_text)),
        query_text,
    )


def _tsvector_score_expression(
    query_text: str,
    *,
    mode: str | None,
) -> ColumnElement[float]:
    """Tsvector一致とdifficulty名完全一致を比較するscore式を返す.

    Args:
        query_text (str): 空白除去済みの検索文字列.
        mode (str | None): 絞り込むmode. Noneならmodeを問わない.

    Returns:
        ColumnElement[float]: difficulty名一致を優先するts_rank_cd score expression.
    """
    return cast(
        "ColumnElement[float]",
        case(
            (
                _difficulty_name_search_filter(query_text, mode=mode),
                literal(_DIFFICULTY_NAME_EXACT_SCORE),
            ),
            (
                _tsvector_text_search_filter(query_text),
                func.ts_rank_cd(_tsvector_document(), _tsquery_expression(query_text)),
            ),
            else_=literal(_FALLBACK_SCORE),
        ),
    )


def _tsvector_text_search_filter(query_text: str) -> ColumnElement[bool]:
    """宣言済みsearchable fieldへPostgreSQL full-text検索条件を適用する.

    Args:
        query_text (str): 空白除去済みの検索文字列.

    Returns:
        ColumnElement[bool]: tsvector documentがqueryに一致する条件.
    """
    return cast(
        "ColumnElement[bool]",
        _tsvector_document().op("@@")(_tsquery_expression(query_text)),
    )


def _tsvector_document() -> ColumnElement[object]:
    """Materialized検索入力からPostgreSQL tsvector documentを返す.

    Returns:
        ColumnElement[object]: `simple`辞書で構築したtsvector expression.
    """
    return cast(
        "ColumnElement[object]",
        func.to_tsvector(
            literal_column(f"'{_POSTGRES_TEXT_SEARCH_CONFIG}'"),
            BeatmapSetModel.direct_search_text,
        ),
    )


def _tsquery_expression(query_text: str) -> ColumnElement[object]:
    """User query textをPostgreSQL tsquery expressionへ変換する.

    Args:
        query_text (str): 空白除去済みの検索文字列.

    Returns:
        ColumnElement[object]: `simple`辞書のwebsearch tsquery expression.
    """
    return cast(
        "ColumnElement[object]",
        func.websearch_to_tsquery(literal_column(f"'{_POSTGRES_TEXT_SEARCH_CONFIG}'"), query_text),
    )


def _active_beatmapset_filter() -> ColumnElement[bool]:
    """検索対象として有効なbeatmapset条件を返す.

    Returns:
        ColumnElement[bool]: set statusがactiveでusable childを持つ条件.
    """
    return cast(
        "ColumnElement[bool]",
        BeatmapSetModel.official_status.not_in(_INACTIVE_STATUS_VALUES)
        & _usable_child_exists(mode=None),
    )


def _usable_child_exists(*, mode: str | None) -> ColumnElement[bool]:
    """Usable child beatmapが存在する条件を返す.

    Args:
        mode (str | None): 絞り込むmode. Noneならmodeを問わない.

    Returns:
        ColumnElement[bool]: effective statusがactiveなchildのEXISTS条件.
    """
    conditions = [
        BeatmapModel.beatmapset_id == BeatmapSetModel.id,
        func.coalesce(BeatmapModel.local_status_override, BeatmapModel.official_status).not_in(
            _INACTIVE_STATUS_VALUES
        ),
    ]
    if mode is not None:
        conditions.append(BeatmapModel.mode == mode)
    return cast(
        "ColumnElement[bool]",
        select(literal(True)).where(*conditions).exists(),
    )


def _difficulty_name_search_filter(query_text: str, *, mode: str | None) -> ColumnElement[bool]:
    """Local child difficulty名がqueryと完全一致する条件を返す.

    Args:
        query_text (str): 空白除去済みの検索文字列.
        mode (str | None): 絞り込むmode. Noneならmodeを問わない.

    Returns:
        ColumnElement[bool]: usable childのversionがqueryと一致するEXISTS条件.
    """
    conditions = [
        BeatmapModel.beatmapset_id == BeatmapSetModel.id,
        func.coalesce(BeatmapModel.local_status_override, BeatmapModel.official_status).not_in(
            _INACTIVE_STATUS_VALUES
        ),
        func.lower(BeatmapModel.version) == query_text.lower(),
    ]
    if mode is not None:
        conditions.append(BeatmapModel.mode == mode)
    return cast(
        "ColumnElement[bool]",
        select(literal(True)).where(*conditions).exists(),
    )


def _last_update_at_expression(
    beatmapset_id: ColumnElement[int] | None = None,
) -> ColumnElement[object]:
    """Beatmapsetのofficial更新時刻をset-level優先で返す式を構築する.

    Args:
        beatmapset_id (ColumnElement[int] | None): 更新時刻を読むbeatmapset ID式.
            Noneなら外側のBeatmapSetModel.idへ相関する.

    Returns:
        ColumnElement[object]: set-level official_last_updated_atまたはchild max日時.
    """
    target_beatmapset_id = (
        beatmapset_id
        if beatmapset_id is not None
        else cast("ColumnElement[int]", cast("object", BeatmapSetModel.id))
    )
    set_last_updated_at = (
        BeatmapSetModel.official_last_updated_at
        if beatmapset_id is None
        else select(BeatmapSetModel.official_last_updated_at)
        .where(BeatmapSetModel.id == target_beatmapset_id)
        .scalar_subquery()
    )
    child_last_updated_at = (
        select(func.max(BeatmapModel.official_last_updated_at))
        .where(BeatmapModel.beatmapset_id == target_beatmapset_id)
        .scalar_subquery()
    )
    return cast(
        "ColumnElement[object]",
        func.coalesce(set_last_updated_at, child_last_updated_at),
    )


def _index_definition_contains_field(index_definition: str, field: str) -> bool:
    """Index定義文字列が指定fieldをidentifier境界付きで含むか判定する.

    Args:
        index_definition (str): PostgreSQL `pg_indexes.indexdef`の値.
        field (str): 検証対象のfield名.

    Returns:
        bool: fieldが別identifierの部分文字列ではなく単独identifierとして存在する場合はTrue.
    """
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(field)}(?![A-Za-z0-9_])"
    return re.search(pattern, index_definition) is not None


def _candidate_from_mapping(row: Mapping[str, object]) -> DirectSearchCandidate:
    """SQL mapping rowを検索候補valueへ変換する.

    Args:
        row (Mapping[str, object]): `beatmapset_id`と`score`を含むSQL result row.

    Returns:
        DirectSearchCandidate: hydration前の候補IDとscore.

    Raises:
        KeyError: 必須fieldがrowにない場合.
        TypeError: 必須field型が期待値と異なる場合.
    """
    return DirectSearchCandidate(
        beatmapset_id=_int_field(row, "beatmapset_id"),
        score=_float_field(row, "score"),
    )


def _int_field(row: Mapping[str, object], field: str) -> int:
    """Mapping rowからboolではないint fieldを取り出す.

    Args:
        row (Mapping[str, object]): SQL result mapping.
        field (str): 取得するfield名.

    Returns:
        int: row内のint値.

    Raises:
        KeyError: fieldがrowにない場合.
        TypeError: field値がintでない場合.
    """
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{field} must be int"
        raise TypeError(msg)
    return value


def _float_field(row: Mapping[str, object], field: str) -> float:
    """Mapping rowからfloat化できる数値fieldを取り出す.

    Args:
        row (Mapping[str, object]): SQL result mapping.
        field (str): 取得するfield名.

    Returns:
        float: row内のscore値.

    Raises:
        KeyError: fieldがrowにない場合.
        TypeError: field値が数値でない場合.
    """
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{field} must be numeric"
        raise TypeError(msg)
    return float(value)


def _bool_field(row: Mapping[str, object], field: str) -> bool:
    """Mapping rowからbool fieldを取り出す.

    Args:
        row (Mapping[str, object]): SQL result mapping.
        field (str): 取得するfield名.

    Returns:
        bool: row内のbool値.

    Raises:
        KeyError: fieldがrowにない場合.
        TypeError: field値がboolでない場合.
    """
    value = row[field]
    if not isinstance(value, bool):
        msg = f"{field} must be bool"
        raise TypeError(msg)
    return value


def _str_field(row: Mapping[str, object], field: str) -> str:
    """Mapping rowからstr fieldを取り出す.

    Args:
        row (Mapping[str, object]): SQL result mapping.
        field (str): 取得するfield名.

    Returns:
        str: row内のstr値.

    Raises:
        KeyError: fieldがrowにない場合.
        TypeError: field値がstrでない場合.
    """
    value = row[field]
    if not isinstance(value, str):
        msg = f"{field} must be str"
        raise TypeError(msg)
    return value


def _optional_str_field(row: Mapping[str, object], field: str) -> str | None:
    """Mapping rowからoptional str fieldを取り出す.

    Args:
        row (Mapping[str, object]): SQL result mapping.
        field (str): 取得するfield名.

    Returns:
        str | None: row内のstr値. NULLならNone.

    Raises:
        KeyError: fieldがrowにない場合.
        TypeError: field値がstrまたはNoneでない場合.
    """
    value = row[field]
    if value is None or isinstance(value, str):
        return value
    msg = f"{field} must be str or None"
    raise TypeError(msg)


__all__ = [
    "AutoDirectSearchBackend",
    "ParadeDBSearchBackend",
    "ParadeDBSearchBackendUnavailableError",
    "TsvectorSearchBackend",
    "TsvectorSearchBackendUnavailableError",
]
