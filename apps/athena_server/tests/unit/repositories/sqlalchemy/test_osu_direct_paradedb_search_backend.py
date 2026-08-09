"""osu!direct ParadeDB search backendのSQL contractを検証する."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, cast, override

import pytest
from sqlalchemy.dialects import postgresql

from osu_server.domain.beatmaps import BeatmapMode, BeatmapRankStatus
from osu_server.domain.beatmaps.direct import DirectSearchListing, DirectSearchRequest
from osu_server.repositories.sqlalchemy.queries.direct_search import (
    ParadeDBSearchBackend,
    ParadeDBSearchBackendUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from types import TracebackType

    from sqlalchemy.sql.elements import ClauseElement

    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory


class FakeMappingResult:
    """SQLAlchemy mapping resultとして必要なread APIだけを提供する.

    Attributes:
        _rows (tuple[Mapping[str, object], ...]): `all()`と`one_or_none()`が返すrow列.
    """

    _rows: tuple[Mapping[str, object], ...]

    def __init__(self, rows: Iterable[Mapping[str, object]]) -> None:
        """結果row列を保持する.

        Args:
            rows (Iterable[Mapping[str, object]]): repositoryへ返すmapping row列.
        """
        self._rows = tuple(rows)

    def mappings(self) -> FakeMappingResult:
        """Mapping result viewを返す.

        Returns:
            FakeMappingResult: すでにmapping rowを保持する同じresult.
        """
        return self

    def all(self) -> tuple[Mapping[str, object], ...]:
        """全rowを順序付きで返す.

        Returns:
            tuple[Mapping[str, object], ...]: 設定済みrow列.
        """
        return self._rows

    def one_or_none(self) -> Mapping[str, object] | None:
        """単一rowまたは未存在を返す.

        Returns:
            Mapping[str, object] | None: 1件ならそのrow, 0件ならNone.

        Raises:
            AssertionError: 複数rowを単一rowとして読もうとした場合.
        """
        if len(self._rows) > 1:
            msg = "expected at most one row"
            raise AssertionError(msg)
        return self._rows[0] if self._rows else None


class FakeSearchSession(AbstractAsyncContextManager["FakeSearchSession"]):
    """ParadeDB backendが発行するSQL statementを記録するfake session.

    Attributes:
        statements (list[ClauseElement]): executeで受け取ったstatement列.
        closed (bool): context manager終了時にTrueになる状態.
        _results (list[FakeMappingResult]): execute順に返すresult列.
    """

    statements: list[ClauseElement]
    closed: bool
    _results: list[FakeMappingResult]

    def __init__(self, results: Iterable[FakeMappingResult]) -> None:
        """返却result列を持つfake sessionを初期化する.

        Args:
            results (Iterable[FakeMappingResult]): execute呼び出し順に返すresult列.
        """
        self.statements = []
        self.closed = False
        self._results = list(results)

    @override
    async def __aenter__(self) -> FakeSearchSession:
        """Context内で使うsession自身を返す.

        Returns:
            FakeSearchSession: statement記録を保持するこのsession.
        """
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Context終了時にclosed状態へする.

        Args:
            exc_type (type[BaseException] | None): 終了exception型. 正常終了ならNone.
            exc (BaseException | None): 終了exception. 正常終了ならNone.
            traceback (TracebackType | None): 終了exception traceback. 正常終了ならNone.

        Returns:
            None: sessionをclosed状態へして値を返さず完了する.
        """
        _ = exc_type
        _ = exc
        _ = traceback
        self.closed = True

    async def execute(self, statement: ClauseElement) -> FakeMappingResult:
        """Statementを記録し次のfake resultを返す.

        Args:
            statement (ClauseElement): backendが実行しようとしたSQLAlchemy statement.

        Returns:
            FakeMappingResult: 呼び出し順に設定されたfake result.
        """
        self.statements.append(statement)
        return self._results.pop(0)


def _session_factory(session: FakeSearchSession) -> SQLAlchemyQuerySessionFactory:
    """Fake sessionをSQLAlchemy query session factory型として返す.

    Args:
        session (FakeSearchSession): backendへ渡すtest用session.

    Returns:
        SQLAlchemyQuerySessionFactory: backend constructorへ渡せるfactory.
    """
    return cast("SQLAlchemyQuerySessionFactory", lambda: session)


async def test_text_search_returns_candidates_and_compiles_declared_filters() -> None:
    """Text検索がactive projectionへ宣言済みfield/filter/pageを適用することを検証する.

    Returns:
        None: 候補ID,score,has_moreとPostgreSQL SQL shapeを検証して完了する.
    """
    session = FakeSearchSession(
        [
            FakeMappingResult(
                (
                    {"beatmapset_id": 11, "score": 8.5},
                    {"beatmapset_id": 12, "score": 6.25},
                    {"beatmapset_id": 13, "score": 1.0},
                )
            )
        ]
    )
    backend = ParadeDBSearchBackend(_session_factory(session))

    result = await backend.search(
        DirectSearchRequest(
            query_text="camellia exit",
            status=BeatmapRankStatus.RANKED,
            mode=BeatmapMode.OSU,
            page=2,
            page_size=2,
        )
    )

    assert [candidate.beatmapset_id for candidate in result.candidates] == [11, 12]
    assert [candidate.score for candidate in result.candidates] == [8.5, 6.25]
    assert result.has_more is True
    sql = _compile_sql(session.statements[0])
    assert "FROM beatmapset_search_documents" in sql
    assert "beatmapset_search_documents.is_active IS true" in sql
    assert "pdb.score(beatmapset_search_documents.beatmapset_id) AS score" in sql
    for field in (
        "artist",
        "title",
        "creator",
        "source",
        "tags",
        "difficulty_names",
        "artist_unicode",
        "title_unicode",
    ):
        assert f"beatmapset_search_documents.{field} ||| 'camellia exit'" in sql
    assert "@@@" not in sql
    assert "beatmapset_search_documents.status = 'ranked'" in sql
    assert "beatmapset_search_documents.modes @> ARRAY['osu']" in sql
    assert "ORDER BY score DESC" in sql
    assert "last_update_at DESC NULLS LAST" in sql
    assert "beatmapset_id DESC" in sql
    assert "LIMIT 3" in sql
    assert "OFFSET 4" in sql


@pytest.mark.parametrize(
    "listing",
    [
        DirectSearchListing.NEWEST,
        DirectSearchListing.TOP_RATED,
        DirectSearchListing.MOST_PLAYED,
    ],
)
async def test_special_listing_uses_fallback_order_without_text_predicate(
    listing: DirectSearchListing,
) -> None:
    """Special listingがliteral text検索を行わずfallback順だけを使うことを検証する.

    Args:
        listing (DirectSearchListing): stable special queryから導出されるlisting種別.

    Returns:
        None: special listing用SQLのsort/predicate contractを検証して完了する.
    """
    session = FakeSearchSession([FakeMappingResult(({"beatmapset_id": 21, "score": 0.0},))])
    backend = ParadeDBSearchBackend(_session_factory(session))

    result = await backend.search(
        DirectSearchRequest(
            query_text=listing.value,
            page=0,
            page_size=100,
            listing=listing,
        )
    )

    assert result.candidates[0].beatmapset_id == 21
    assert result.candidates[0].score == 0.0
    assert result.has_more is False
    sql = _compile_sql(session.statements[0])
    assert "@@@" not in sql
    assert "|||" not in sql
    assert "0.0 AS score" in sql
    assert "ORDER BY beatmapset_search_documents.last_update_at DESC NULLS LAST" in sql
    assert "beatmapset_search_documents.beatmapset_id DESC" in sql


async def test_validate_rejects_missing_extension_or_stale_index_fields() -> None:
    """Startup検証用validateがpg_searchとBM25 index field不足を拒否することを検証する.

    Returns:
        None: capability不足がconfiguration errorとして表面化することを確認して完了する.
    """
    session = FakeSearchSession(
        [
            FakeMappingResult(
                (
                    {
                        "has_extension": True,
                        "index_definition": (
                            "CREATE INDEX idx_beatmapset_search_documents_bm25 "
                            "ON beatmapset_search_documents USING bm25 "
                            "(beatmapset_id, artist, title_unicode, creator, "
                            "source, tags, difficulty_names, artist_unicode, "
                            "status, modes, last_update_at)"
                        ),
                    },
                )
            )
        ]
    )
    backend = ParadeDBSearchBackend(_session_factory(session))

    with pytest.raises(ParadeDBSearchBackendUnavailableError, match="title"):
        await backend.validate()


def _compile_sql(statement: ClauseElement) -> str:
    """PostgreSQL dialectでliteral付きSQL文字列へ変換する.

    Args:
        statement (ClauseElement): compile対象のSQLAlchemy statement.

    Returns:
        str: test assertion向けのPostgreSQL SQL文字列.
    """
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
