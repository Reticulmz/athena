"""Integration tests for SQLAlchemyReplayRepository.

Tests CRUD operations and unique constraint handling against real PostgreSQL.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.score.replay import Replay
from osu_server.domain.score.score import Grade, Playstyle, Ruleset, Score
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.sqlalchemy.replay_repository import SQLAlchemyReplayRepository
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
                text("DELETE FROM replays WHERE checksum_sha256 LIKE 'test_checksum_%'")
            )
            _ = await session.execute(
                text("DELETE FROM scores WHERE online_checksum LIKE 'test_replay_score_%'")
            )
            await session.commit()
    except (OSError, SQLAlchemyError):
        return


def _make_score(
    *,
    online_checksum: str = "test_replay_score_001",
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


def _make_replay(
    *,
    checksum: str = "test_checksum_001",
    score_id: int = 1,
) -> Replay:
    """Create a valid Replay for testing."""
    return Replay(
        id=None,
        score_id=score_id,
        blob_key=f"replays/{checksum}.osr",
        checksum_sha256=checksum,
        byte_size=1024,
    )


async def test_sqlalchemy_replay_repository_creates_replay(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    score_repo = SQLAlchemyScoreRepository(session_factory)
    replay_repo = SQLAlchemyReplayRepository(session_factory)

    score = _make_score(online_checksum="test_replay_score_001")
    created_score = await score_repo.create(score)

    replay = _make_replay(checksum="test_checksum_001", score_id=created_score.id)  # pyright: ignore[reportArgumentType]
    created = await replay_repo.create(replay)

    assert created.id is not None
    assert created.score_id == replay.score_id
    assert created.checksum_sha256 == replay.checksum_sha256
    assert created.blob_key == replay.blob_key
    assert created.byte_size == replay.byte_size


async def test_sqlalchemy_replay_repository_exists_by_checksum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    score_repo = SQLAlchemyScoreRepository(session_factory)
    replay_repo = SQLAlchemyReplayRepository(session_factory)

    score = _make_score(online_checksum="test_replay_score_002")
    created_score = await score_repo.create(score)

    replay = _make_replay(checksum="test_checksum_002", score_id=created_score.id)  # pyright: ignore[reportArgumentType]
    created = await replay_repo.create(replay)

    assert await replay_repo.exists_by_checksum(created.checksum_sha256) is True
    assert await replay_repo.exists_by_checksum("nonexistent_checksum") is False


async def test_sqlalchemy_replay_repository_rejects_duplicate_checksum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    score_repo = SQLAlchemyScoreRepository(session_factory)
    replay_repo = SQLAlchemyReplayRepository(session_factory)

    score1 = _make_score(online_checksum="test_replay_score_003")
    created_score1 = await score_repo.create(score1)

    score2 = _make_score(online_checksum="test_replay_score_004")
    created_score2 = await score_repo.create(score2)

    replay1 = _make_replay(checksum="test_checksum_003", score_id=created_score1.id)  # pyright: ignore[reportArgumentType]
    _ = await replay_repo.create(replay1)

    replay2 = _make_replay(checksum="test_checksum_003", score_id=created_score2.id)  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError, match="checksum_sha256 already exists"):
        _ = await replay_repo.create(replay2)
