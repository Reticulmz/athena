"""Integration tests for SQLAlchemyScoreRepository.

Tests CRUD operations and unique constraint handling against real PostgreSQL.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.score.score import Grade, Playstyle, Ruleset, Score
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.sqlalchemy.score_repository import SQLAlchemyScoreRepository

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    eng = create_engine(_get_database_url())
    try:
        async with eng.connect() as conn:
            _ = await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await eng.dispose()
        pytest.skip(f"DATABASE_URL is set but database is unavailable: {exc}")
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    factory = create_session_factory(engine)
    yield factory
    try:
        async with factory() as session:
            _ = await session.execute(
                text("DELETE FROM scores WHERE online_checksum LIKE 'test_checksum_%'")
            )
            await session.commit()
    except (OSError, SQLAlchemyError):
        return


def _make_score(
    *,
    online_checksum: str = "test_checksum_001",
    user_id: int = 1000,
    beatmap_id: int = 2000,
) -> Score:
    """Create a valid Score for testing."""
    return Score(
        id=None,
        user_id=user_id,
        beatmap_id=beatmap_id,
        beatmap_checksum="8119fb28af74b9445f4a685f8b09eec2",
        online_checksum=online_checksum,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=0,
        n300=100,
        n100=10,
        n50=5,
        geki=20,
        katu=5,
        miss=0,
        score=1000000,
        max_combo=150,
        accuracy=0.95,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="b20240101",
        submitted_at=datetime.now(UTC),
    )


async def test_sqlalchemy_score_repository_creates_and_retrieves_score(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = SQLAlchemyScoreRepository(session_factory)

    score = _make_score(online_checksum="test_checksum_001")
    created = await repo.create(score)

    assert created.id is not None
    assert created.user_id == score.user_id
    assert created.online_checksum == score.online_checksum

    retrieved = await repo.get_by_id(created.id)
    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.online_checksum == created.online_checksum


async def test_sqlalchemy_score_repository_exists_by_online_checksum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = SQLAlchemyScoreRepository(session_factory)

    score = _make_score(online_checksum="test_checksum_002")
    created = await repo.create(score)

    assert await repo.exists_by_online_checksum(created.online_checksum) is True
    assert await repo.exists_by_online_checksum("nonexistent_checksum") is False


async def test_sqlalchemy_score_repository_rejects_duplicate_online_checksum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = SQLAlchemyScoreRepository(session_factory)

    score1 = _make_score(online_checksum="test_checksum_003", user_id=1000)
    _ = await repo.create(score1)

    score2 = _make_score(online_checksum="test_checksum_003", user_id=2000)
    with pytest.raises(ValueError, match="online_checksum already exists"):
        _ = await repo.create(score2)


async def test_sqlalchemy_score_repository_handles_failed_scores(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = SQLAlchemyScoreRepository(session_factory)

    score = _make_score(online_checksum="test_checksum_004")
    score.passed = False
    score.score = 50000
    score.accuracy = 0.65
    score.grade = Grade.D

    created = await repo.create(score)

    assert created.id is not None
    assert created.passed is False

    retrieved = await repo.get_by_id(created.id)
    assert retrieved is not None
    assert retrieved.passed is False
    assert retrieved.score == 50000


async def test_sqlalchemy_score_repository_preserves_all_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = SQLAlchemyScoreRepository(session_factory)

    score = _make_score(online_checksum="test_checksum_005")
    score.ruleset = Ruleset.TAIKO
    score.mods = 72  # HD+DT
    score.perfect = True

    created = await repo.create(score)

    assert created.id is not None
    retrieved = await repo.get_by_id(created.id)

    assert retrieved is not None
    assert retrieved.ruleset == Ruleset.TAIKO
    assert retrieved.mods == 72
    assert retrieved.perfect is True
    assert retrieved.n300 == score.n300
    assert retrieved.n100 == score.n100
    assert retrieved.n50 == score.n50
    assert retrieved.geki == score.geki
    assert retrieved.katu == score.katu
    assert retrieved.miss == score.miss
