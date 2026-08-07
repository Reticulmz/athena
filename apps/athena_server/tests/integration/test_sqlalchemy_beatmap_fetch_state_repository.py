"""PostgreSQL beatmap fetch state repositoryのenum persistence contractを検証する."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFetchTargetKind,
)
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.sqlalchemy.models.beatmap import BeatmapFetchStateModel
from osu_server.repositories.sqlalchemy.queries.beatmaps import (
    SQLAlchemyBeatmapQueryRepository,
)
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
_TEST_BEATMAP_IDS = (2_147_400_001, 2_147_400_002)


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
    """実PostgreSQLへ接続するtest engineを提供する.

    Yields:
        AsyncEngine: 接続確認済みのtest engine.

    Raises:
        pytest.skip: DATABASE_URLが未設定または接続不能な場合.

    Notes:
        fixture終了時にengineをdisposeする.
    """
    engine = create_engine(_get_database_url())
    try:
        async with engine.connect() as connection:
            _ = await connection.execute(select(1))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"DATABASE_URL is set but database is unavailable: {exc}")
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    """Fetch state test用session factoryを提供する.

    Args:
        engine (AsyncEngine): 実PostgreSQLへ接続するtest engine.

    Yields:
        async_sessionmaker[AsyncSession]: 専用rowを分離するsession factory.

    Notes:
        他testのfetch state rowは削除しない.
    """
    factory = create_session_factory(engine)
    await _delete_test_fetch_state(factory)
    yield factory
    try:
        await _delete_test_fetch_state(factory)
    except OSError, SQLAlchemyError:
        return


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> SQLAlchemyUnitOfWorkFactory:
    """実session factoryからUnit of Work factoryを作成する.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): test専用session factory.

    Returns:
        SQLAlchemyUnitOfWorkFactory: SQLAlchemy repositoryを解決するfactory.
    """
    return SQLAlchemyUnitOfWorkFactory(session_factory)


async def _delete_test_fetch_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Test専用beatmap IDに紐づくfetch state rowを削除する.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): cleanup用のPostgreSQL session factory.

    Returns:
        None: test target keyのfetch state deletionをcommitして完了する.
    """
    async with session_factory() as session:
        _ = await session.execute(
            delete(BeatmapFetchStateModel).where(
                BeatmapFetchStateModel.target_key.in_(
                    tuple(str(beatmap_id) for beatmap_id in _TEST_BEATMAP_IDS)
                )
            )
        )
        await session.commit()


async def test_postgresql_fetch_state_persists_enum_values(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Fetch target enumがcommand/query境界でchecked stringとして永続化されるcontractを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): 実PostgreSQL用のUoW factory.
        session_factory (async_sessionmaker[AsyncSession]): query用session factory.

    Returns:
        None: pending取得とcompleted stateの再読込を確認して完了する.

    Raises:
        AssertionError: fetch stateまたは保存されたenum valueがexpected valueと異なる場合.

    Notes:
        Command/query repository, SQLAlchemy enum validation, DB CHECKを通過させる.
    """
    target = BeatmapFetchTarget.metadata_by_beatmap_id(_TEST_BEATMAP_IDS[0])

    async with uow_factory() as uow:
        assert await uow.beatmaps.get_fetch_state(target) is None
        assert await uow.beatmaps.try_mark_fetch_pending(target, now=_NOW) is True
        pending = await uow.beatmaps.get_fetch_state(target)
        await uow.commit()

    assert pending is not None
    assert pending.target.kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID
    assert pending.status is BeatmapFetchState.PENDING_FETCH
    assert pending.attempt_count == 1
    assert pending.pending_since == _NOW

    completed_at = _NOW + timedelta(seconds=1)
    async with uow_factory() as uow:
        assert await uow.beatmaps.try_mark_fetch_pending(target, now=completed_at) is False
        await uow.beatmaps.mark_fetch_succeeded(target, now=completed_at)
        await uow.commit()

    query_repository = SQLAlchemyBeatmapQueryRepository(session_factory)
    completed = await query_repository.get_fetch_state(target)

    assert completed is not None
    assert completed.target.kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID
    assert completed.status is BeatmapFetchState.FRESH
    assert completed.attempt_count == 1
    assert completed.last_error is None
    assert completed.pending_since is None
    assert completed.last_attempted_at == completed_at

    completion_only_target = BeatmapFetchTarget.file_by_beatmap_id(_TEST_BEATMAP_IDS[1])
    async with uow_factory() as uow:
        await uow.beatmaps.mark_fetch_succeeded(
            completion_only_target,
            now=completed_at,
        )
        await uow.commit()

    completion_only = await query_repository.get_fetch_state(completion_only_target)
    assert completion_only is not None
    assert completion_only.target.kind is BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID
    assert completion_only.status is BeatmapFetchState.FRESH
    assert completion_only.attempt_count == 0
