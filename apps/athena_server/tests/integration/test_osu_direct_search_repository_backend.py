"""osu!direct検索repositoryとbackendのintegration contractを検証する."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
    DirectCoverageKind,
    DirectCoverageRecord,
    DirectCoverageStatusScope,
    DirectExternalIndexBackend,
    DirectExternalIndexStatus,
    DirectSearchListing,
    DirectSearchRequest,
)
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapDirectCoverageModel,
    BeatmapDirectExternalIndexStateModel,
    BeatmapModel,
    BeatmapSetModel,
    BeatmapSetSearchDocumentModel,
)
from osu_server.repositories.sqlalchemy.queries.beatmaps import (
    SQLAlchemyBeatmapQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.direct_search import ParadeDBSearchBackend
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory
from osu_server.services.commands.beatmaps.direct_indexing import (
    DirectExternalIndexUpdateOutcome,
    DirectIndexingCommands,
)
from osu_server.services.queries.beatmaps.direct_search import DirectSearchQuery

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from osu_server.domain.beatmaps import BeatmapSetSearchDocument

_BEATMAPSET_ID = 2_147_460_201
_BEATMAP_ID = 2_147_460_202
_CHECKSUM_MD5 = "21474602010000000000000000000000"
_NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
_FUTURE_LAST_UPDATED = datetime(2099, 1, 1, tzinfo=UTC)
_COVERAGE_SORT_KEYS = (
    "kiro-osu-direct-feed",
    "kiro-osu-direct-range",
)


class FailingExternalIndexBackend:
    """External index失敗後もSQL searchが使えることを検証するwriter double.

    Attributes:
        indexed_documents (list[BeatmapSetSearchDocument]): 同期要求を受けたprojection列.
    """

    indexed_documents: list[BeatmapSetSearchDocument]

    def __init__(self) -> None:
        """空の呼出履歴を持つwriter doubleを初期化する."""
        self.indexed_documents = []

    async def index_document(self, document: BeatmapSetSearchDocument) -> None:
        """Projection同期要求を記録してretry可能な失敗を送出する.

        Args:
            document (BeatmapSetSearchDocument): external indexへ同期するprojection.

        Returns:
            None: 正常系では値を返さないが、このdoubleは常に失敗する.

        Raises:
            RuntimeError: sanitized failure state記録を検証するため常に送出する.
        """
        self.indexed_documents.append(document)
        raise RuntimeError("raw provider failure details")


def _get_database_url() -> str:
    """Integration testで使用するPostgreSQL connection URLを取得する.

    Returns:
        str: DATABASE_URL environment variableのPostgreSQL URL.

    Raises:
        pytest.skip: DATABASE_URLが未設定の場合.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    """osu!direct integration test用engineを提供する.

    Yields:
        AsyncEngine: 接続確認済みのPostgreSQL engine.

    Raises:
        pytest.skip: DATABASE_URLが未設定または接続不能な場合.

    Notes:
        fixture終了時にengine poolをdisposeする.
    """
    eng = create_engine(_get_database_url())
    try:
        async with eng.connect() as connection:
            _ = await connection.execute(select(1))
    except Exception as exc:
        await eng.dispose()
        pytest.skip(f"DATABASE_URL is set but database is unavailable: {exc}")
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    """osu!direct integration rowを隔離するPostgreSQL session factoryを提供する.

    Args:
        engine (AsyncEngine): 接続確認済みのPostgreSQL engine.

    Yields:
        async_sessionmaker[AsyncSession]: command/query repositoryへ渡すsession factory.

    Notes:
        fixture前後でこのtest専用IDとcoverage sort keyのrowだけをcleanupする.
    """
    factory = create_session_factory(engine)
    await _cleanup_rows(factory)
    yield factory
    try:
        await _cleanup_rows(factory)
    except OSError, SQLAlchemyError:
        return


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> SQLAlchemyUnitOfWorkFactory:
    """実PostgreSQL session factoryからUnit of Work factoryを作る.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): test専用session factory.

    Returns:
        SQLAlchemyUnitOfWorkFactory: SQLAlchemy command repositoryを解決するfactory.
    """
    return SQLAlchemyUnitOfWorkFactory(session_factory)


async def test_direct_search_repository_backend_and_index_state_share_source_of_truth(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Projection永続化, SQL候補, metadata hydration, index失敗stateを統合検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): 実DBへcommitするcommand UoW factory.
        session_factory (async_sessionmaker[AsyncSession]): raw readとquery repository用factory.

    Returns:
        None: osu!direct検索永続化境界とsource of truth分離を検証して完了する.
    """
    request = DirectSearchRequest(
        authenticated_user_id=42,
        query_text="Newest",
        statuses=(BeatmapRankStatus.RANKED,),
        mode=BeatmapMode.OSU,
        page_size=1,
        listing=DirectSearchListing.NEWEST,
    )

    async with uow_factory() as uow:
        await uow.beatmaps.save_beatmapset_snapshot(_beatmapset())
        assert await uow.beatmaps.get_search_document(_BEATMAPSET_ID) is not None
        assert await _get_search_document_model(session_factory) is None
        await uow.commit()

    document = await _get_search_document_model(session_factory)
    assert document is not None
    assert document.beatmapset_id == _BEATMAPSET_ID
    assert document.title == "Metadata Title"
    assert document.difficulty_names == "Integration"
    assert document.is_active is True
    assert document.document_version == 1

    await _replace_projection_title(session_factory, "Projection Shadow Title")

    backend = ParadeDBSearchBackend(session_factory)
    backend_result = await backend.search(request)
    assert [candidate.beatmapset_id for candidate in backend_result.candidates] == [_BEATMAPSET_ID]
    assert [candidate.score for candidate in backend_result.candidates] == [0.0]

    result = await DirectSearchQuery(
        SQLAlchemyBeatmapQueryRepository(session_factory),
        backend,
    ).execute(request)
    assert [beatmapset.title for beatmapset in result.beatmapsets] == ["Metadata Title"]
    assert result.stable_result_count == 1

    external_index = FailingExternalIndexBackend()
    indexing = DirectIndexingCommands(
        unit_of_work_factory=uow_factory,
        external_index_backend=external_index,
    )
    update_result = await indexing.update_external_index(_BEATMAPSET_ID)

    assert update_result.outcome is DirectExternalIndexUpdateOutcome.FAILED
    assert [document.beatmapset_id for document in external_index.indexed_documents] == [
        _BEATMAPSET_ID
    ]
    index_state = await _get_index_state_model(session_factory)
    assert index_state is not None
    assert index_state.status == DirectExternalIndexStatus.FAILED.value
    assert index_state.document_version == 1
    assert index_state.failure_reason == "RuntimeError: external index update failed"

    still_available = await DirectSearchQuery(
        SQLAlchemyBeatmapQueryRepository(session_factory),
        backend,
    ).execute(request)
    assert [beatmapset.id for beatmapset in still_available.beatmapsets] == [_BEATMAPSET_ID]


async def test_direct_coverage_records_completed_failed_feed_and_range_scopes(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Coverage recordが完了/失敗とfeed/range scopeを区別して永続化されることを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): coverage stateをcommitするUoW factory.
        session_factory (async_sessionmaker[AsyncSession]): 保存済みcoverageを読むsession factory.

    Returns:
        None: coverage kindと完了/失敗timestampが混ざらないことを確認して完了する.
    """
    completed_feed = DirectCoverageRecord(
        coverage_kind=DirectCoverageKind.FEED_WINDOW,
        source=BeatmapMetadataSource.OFFICIAL,
        status_scope=DirectCoverageStatusScope.RANKED,
        sort_key=_COVERAGE_SORT_KEYS[0],
        window_key="page-1",
        from_beatmapset_id=_BEATMAPSET_ID,
        to_beatmapset_id=_BEATMAPSET_ID,
        cursor="cursor-next",
        completed_at=_NOW,
        failed_at=None,
        failure_reason=None,
    )
    failed_feed = DirectCoverageRecord(
        coverage_kind=DirectCoverageKind.FEED_WINDOW,
        source=BeatmapMetadataSource.OFFICIAL,
        status_scope=DirectCoverageStatusScope.RANKED,
        sort_key=_COVERAGE_SORT_KEYS[0],
        window_key="page-failed",
        from_beatmapset_id=0,
        to_beatmapset_id=0,
        cursor=None,
        completed_at=None,
        failed_at=_NOW + timedelta(seconds=1),
        failure_reason="upstream timeout",
    )
    completed_range = DirectCoverageRecord(
        coverage_kind=DirectCoverageKind.ID_RANGE,
        source=BeatmapMetadataSource.OFFICIAL,
        status_scope=DirectCoverageStatusScope.ALL,
        sort_key=_COVERAGE_SORT_KEYS[1],
        window_key="",
        from_beatmapset_id=_BEATMAPSET_ID,
        to_beatmapset_id=_BEATMAPSET_ID,
        cursor=None,
        completed_at=_NOW + timedelta(seconds=2),
        failed_at=None,
        failure_reason=None,
    )

    async with uow_factory() as uow:
        await uow.beatmaps.record_direct_coverage(completed_feed)
        await uow.beatmaps.record_direct_coverage(failed_feed)
        await uow.beatmaps.record_direct_coverage(completed_range)
        await uow.commit()

    rows = await _get_coverage_models(session_factory)
    by_scope = {(row.coverage_kind, row.window_key): row for row in rows}

    assert len(rows) == 3
    assert by_scope[(DirectCoverageKind.FEED_WINDOW.value, "page-1")].completed_at == _NOW
    assert by_scope[(DirectCoverageKind.FEED_WINDOW.value, "page-1")].failed_at is None
    assert by_scope[(DirectCoverageKind.FEED_WINDOW.value, "page-failed")].completed_at is None
    assert by_scope[(DirectCoverageKind.FEED_WINDOW.value, "page-failed")].failed_at == (
        _NOW + timedelta(seconds=1)
    )
    assert by_scope[(DirectCoverageKind.FEED_WINDOW.value, "page-failed")].failure_reason == (
        "upstream timeout"
    )
    assert by_scope[(DirectCoverageKind.ID_RANGE.value, "")].completed_at == (
        _NOW + timedelta(seconds=2)
    )
    assert by_scope[(DirectCoverageKind.ID_RANGE.value, "")].status_scope == (
        DirectCoverageStatusScope.ALL.value
    )


async def _cleanup_rows(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """このtest専用のosu!direct integration rowを削除する.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): cleanup用session factory.

    Returns:
        None: 関連rowをFK順に削除してcommitする.
    """
    async with session_factory() as session:
        _ = await session.execute(
            delete(BeatmapDirectExternalIndexStateModel).where(
                BeatmapDirectExternalIndexStateModel.beatmapset_id == _BEATMAPSET_ID
            )
        )
        _ = await session.execute(
            delete(BeatmapSetSearchDocumentModel).where(
                BeatmapSetSearchDocumentModel.beatmapset_id == _BEATMAPSET_ID
            )
        )
        _ = await session.execute(
            delete(BeatmapModel).where(BeatmapModel.beatmapset_id == _BEATMAPSET_ID)
        )
        _ = await session.execute(
            delete(BeatmapSetModel).where(BeatmapSetModel.id == _BEATMAPSET_ID)
        )
        _ = await session.execute(
            delete(BeatmapDirectCoverageModel).where(
                BeatmapDirectCoverageModel.sort_key.in_(_COVERAGE_SORT_KEYS)
            )
        )
        await session.commit()


async def _get_search_document_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> BeatmapSetSearchDocumentModel | None:
    """保存済みsearch projection modelを直接読む.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): read用session factory.

    Returns:
        BeatmapSetSearchDocumentModel | None: test beatmapsetのprojection row.
    """
    async with session_factory() as session:
        model = await session.get(BeatmapSetSearchDocumentModel, _BEATMAPSET_ID)
        return model if isinstance(model, BeatmapSetSearchDocumentModel) else None


async def _replace_projection_title(
    session_factory: async_sessionmaker[AsyncSession],
    title: str,
) -> None:
    """Hydration source of truth検証用にprojection titleだけを差し替える.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): update用session factory.
        title (str): projection rowへ保存するmetadataと異なるtitle.

    Returns:
        None: projection titleを更新してcommitする.
    """
    async with session_factory() as session:
        _ = await session.execute(
            update(BeatmapSetSearchDocumentModel)
            .where(BeatmapSetSearchDocumentModel.beatmapset_id == _BEATMAPSET_ID)
            .values(title=title)
        )
        await session.commit()


async def _get_index_state_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> BeatmapDirectExternalIndexStateModel | None:
    """保存済みexternal index state modelを直接読む.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): read用session factory.

    Returns:
        BeatmapDirectExternalIndexStateModel | None: test beatmapsetのindex state row.
    """
    async with session_factory() as session:
        model = await session.get(
            BeatmapDirectExternalIndexStateModel,
            (DirectExternalIndexBackend.MEILISEARCH.value, _BEATMAPSET_ID),
        )
        return model if isinstance(model, BeatmapDirectExternalIndexStateModel) else None


async def _get_coverage_models(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[BeatmapDirectCoverageModel, ...]:
    """このtestが保存したcoverage model列を直接読む.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): read用session factory.

    Returns:
        tuple[BeatmapDirectCoverageModel, ...]: sort keyに一致するcoverage row列.
    """
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(BeatmapDirectCoverageModel).where(
                        BeatmapDirectCoverageModel.sort_key.in_(_COVERAGE_SORT_KEYS)
                    )
                )
            )
            .scalars()
            .all()
        )
        return tuple(rows)


def _beatmapset() -> BeatmapSet:
    """osu!direct integration test用beatmapset metadataを作る.

    Returns:
        BeatmapSet: direct検索可能なchildを1件持つmetadata snapshot.
    """
    return BeatmapSet(
        id=_BEATMAPSET_ID,
        artist="Integration Artist",
        title="Metadata Title",
        creator="Integration Mapper",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(_beatmap(),),
        last_fetched_at=_NOW,
        next_refresh_at=None,
    )


def _beatmap() -> Beatmap:
    """osu!direct integration test用child beatmap metadataを作る.

    Returns:
        Beatmap: direct検索projectionへ入るranked osu child beatmap.
    """
    return Beatmap(
        id=_BEATMAP_ID,
        beatmapset_id=_BEATMAPSET_ID,
        checksum_md5=_CHECKSUM_MD5,
        mode=BeatmapMode.OSU,
        version="Integration",
        total_length=120,
        hit_length=100,
        max_combo=500,
        bpm=180.0,
        cs=4.0,
        od=8.0,
        ar=9.0,
        hp=6.0,
        difficulty_rating=4.5,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=None,
        official_last_updated_at=_FUTURE_LAST_UPDATED,
    )
