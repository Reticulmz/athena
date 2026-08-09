"""ParadeDBを使うosu!direct SQL search backendを提供する."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, cast

from sqlalchemy import String, Text, column, func, literal, or_, select, table

from osu_server.domain.beatmaps.direct import (
    DirectSearchBackendResult,
    DirectSearchCandidate,
    DirectSearchListing,
    DirectSearchRequest,
)
from osu_server.infrastructure.search import DIRECT_SEARCH_INDEX_DEFINITION
from osu_server.repositories.sqlalchemy.models.beatmap import BeatmapSetSearchDocumentModel

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.sql.base import Executable
    from sqlalchemy.sql.elements import ColumnElement

    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

_BM25_INDEX_NAME: Final = "idx_beatmapset_search_documents_bm25"
_PG_SEARCH_EXTENSION: Final = "pg_search"
_FALLBACK_SCORE: Final = 0.0
_PG_EXTENSION = table("pg_extension", column("extname", String))
_PG_INDEXES = table(
    "pg_indexes",
    column("indexname", String),
    column("indexdef", Text),
)
_REQUIRED_BM25_FIELDS: Final = tuple(
    dict.fromkeys(
        (
            *DIRECT_SEARCH_INDEX_DEFINITION.searchable_fields,
            *DIRECT_SEARCH_INDEX_DEFINITION.filterable_fields,
            *DIRECT_SEARCH_INDEX_DEFINITION.sortable_fields,
        )
    )
)


class ParadeDBSearchBackendUnavailableError(RuntimeError):
    """ParadeDB search backendの必須capability不足を表す例外."""


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
        """Active projection documentから検索候補IDとscoreだけを返す.

        Args:
            request (DirectSearchRequest): stable inputから導出された検索条件.

        Returns:
            DirectSearchBackendResult: page内候補と次page有無.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            KeyError: SQL result rowに必須fieldがない場合.
            TypeError: SQL result rowの必須field型が期待値と異なる場合.
        """
        async with self._session_factory() as session:
            rows = cast(
                "Sequence[Mapping[str, object]]",
                (await session.execute(_search_statement(request))).mappings().all(),
            )

        candidate_rows = rows[: request.page_size]
        return DirectSearchBackendResult(
            candidates=tuple(_candidate_from_mapping(row) for row in candidate_rows),
            has_more=len(rows) > request.page_size,
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

        if row is None or _bool_field(row, "has_extension") is not True:
            msg = "ParadeDB pg_search extension is not available"
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


def _search_statement(request: DirectSearchRequest) -> Executable:
    """Direct search requestをParadeDB検索SELECTへ変換する.

    Args:
        request (DirectSearchRequest): backendへ渡された検索条件.

    Returns:
        Executable: 候補IDとscoreだけを返すSELECT.
    """
    uses_text_search = _uses_text_search(request)
    score = _score_expression(uses_text_search).label("score")
    statement = select(
        BeatmapSetSearchDocumentModel.beatmapset_id.label("beatmapset_id"),
        score,
    ).where(BeatmapSetSearchDocumentModel.is_active.is_(True))

    if request.statuses:
        statement = statement.where(
            BeatmapSetSearchDocumentModel.status.in_([status.value for status in request.statuses])
        )
    if request.mode is not None:
        statement = statement.where(
            BeatmapSetSearchDocumentModel.modes.contains([request.mode.value])
        )
    if uses_text_search:
        statement = statement.where(_text_search_filter(request.query_text.strip()))

    if uses_text_search:
        statement = statement.order_by(
            score.desc(),
            BeatmapSetSearchDocumentModel.last_update_at.desc().nulls_last(),
            BeatmapSetSearchDocumentModel.beatmapset_id.desc(),
        )
    else:
        statement = statement.order_by(
            BeatmapSetSearchDocumentModel.last_update_at.desc().nulls_last(),
            BeatmapSetSearchDocumentModel.beatmapset_id.desc(),
        )

    return statement.offset(request.page * request.page_size).limit(request.page_size + 1)


def _validation_statement() -> Executable:
    """ParadeDB backendの必須DB capabilityを読むSELECTを構築する.

    Returns:
        Executable: pg_search extension有無とBM25 index定義を返すSELECT.
    """
    has_extension = (
        select(literal(True))
        .select_from(_PG_EXTENSION)
        .where(_PG_EXTENSION.c.extname == _PG_SEARCH_EXTENSION)
        .exists()
        .label("has_extension")
    )
    index_definition = (
        select(_PG_INDEXES.c.indexdef)
        .select_from(_PG_INDEXES)
        .where(_PG_INDEXES.c.indexname == _BM25_INDEX_NAME)
        .limit(1)
        .scalar_subquery()
        .label("index_definition")
    )
    return select(has_extension, index_definition)


def _uses_text_search(request: DirectSearchRequest) -> bool:
    """RequestがBM25 text検索を必要とするか判定する.

    Args:
        request (DirectSearchRequest): backendへ渡された検索条件.

    Returns:
        bool: 通常検索listingで空ではないquery_textを持つ場合はTrue.
    """
    return request.listing is DirectSearchListing.SEARCH and bool(request.query_text.strip())


def _score_expression(uses_text_search: bool) -> ColumnElement[float]:
    """検索種別に応じたscore式を返す.

    Args:
        uses_text_search (bool): BM25 text検索を行う場合はTrue.

    Returns:
        ColumnElement[float]: BM25 scoreまたはfallback scoreのSQL expression.
    """
    if uses_text_search:
        return cast(
            "ColumnElement[float]",
            func.pdb.score(BeatmapSetSearchDocumentModel.beatmapset_id),
        )
    return literal(_FALLBACK_SCORE)


def _text_search_filter(query_text: str) -> ColumnElement[bool]:
    """宣言済みsearchable fieldへParadeDB text検索条件を適用する.

    Args:
        query_text (str): 空白除去済みの検索文字列.

    Returns:
        ColumnElement[bool]: いずれかのsearchable fieldが一致するOR条件.
    """
    return or_(
        *(
            _searchable_column(field).op("|||")(query_text)
            for field in DIRECT_SEARCH_INDEX_DEFINITION.searchable_fields
        )
    )


def _searchable_column(field: str) -> ColumnElement[object]:
    """宣言済みsearchable field名に対応するSQLAlchemy columnを返す.

    Args:
        field (str): Search index declaration上のfield名.

    Returns:
        ColumnElement[object]: search document model上の同名column.

    Raises:
        AttributeError: fieldに対応するmodel columnが存在しない場合.
    """
    return cast("ColumnElement[object]", getattr(BeatmapSetSearchDocumentModel, field))


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
    "ParadeDBSearchBackend",
    "ParadeDBSearchBackendUnavailableError",
]
