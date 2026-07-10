"""Integration tests for the SQLAlchemy replay command repository.

Tests CRUD operations and unique constraint handling against real PostgreSQL.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.replay import Replay
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.domain.storage.blobs import NewBlob
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory

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
                text("DELETE FROM replay_file_attachments WHERE checksum_sha256 LIKE :prefix"),
                {"prefix": "test_checksum_%"},
            )
            _ = await session.execute(
                text("DELETE FROM scores WHERE online_checksum LIKE 'test_replay_score_%'")
            )
            _ = await session.execute(
                text("DELETE FROM blobs WHERE storage_key LIKE 'test/replay/%'")
            )
            await session.commit()
    except (OSError, SQLAlchemyError):
        return


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> SQLAlchemyUnitOfWorkFactory:
    return SQLAlchemyUnitOfWorkFactory(session_factory)


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
        mods=ModCombination.none(),
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
    blob_id: int = 1,
) -> Replay:
    """Create a valid Replay for testing."""
    return Replay(
        id=None,
        score_id=score_id,
        blob_id=blob_id,
        checksum_sha256=checksum,
        byte_size=1024,
    )


async def _create_blob(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
    *,
    checksum: str,
) -> int:
    sha256 = hashlib.sha256(checksum.encode()).hexdigest()
    async with uow_factory() as uow:
        blob = await uow.blobs.create(
            NewBlob(
                sha256=sha256,
                byte_size=1024,
                content_type="application/octet-stream",
                storage_backend="local",
                storage_key=f"test/replay/{checksum}.osr",
            )
        )
        await uow.commit()
    return blob.id


async def test_sqlalchemy_replay_repository_creates_replay(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    score = _make_score(online_checksum="test_replay_score_001")
    async with uow_factory() as uow:
        created_score = await uow.scores.create(score)
        await uow.commit()
    assert created_score.id is not None
    blob_id = await _create_blob(uow_factory, checksum="test_checksum_001")

    replay = _make_replay(
        checksum="test_checksum_001",
        score_id=created_score.id,
        blob_id=blob_id,
    )
    async with uow_factory() as uow:
        created = await uow.replays.create(replay)
        await uow.commit()

    assert created.id is not None
    assert created.score_id == replay.score_id
    assert created.checksum_sha256 == replay.checksum_sha256
    assert created.blob_id == replay.blob_id
    assert created.byte_size == replay.byte_size


async def test_sqlalchemy_replay_repository_exists_by_checksum(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    score = _make_score(online_checksum="test_replay_score_002")
    async with uow_factory() as uow:
        created_score = await uow.scores.create(score)
        await uow.commit()
    assert created_score.id is not None
    blob_id = await _create_blob(uow_factory, checksum="test_checksum_002")

    replay = _make_replay(
        checksum="test_checksum_002",
        score_id=created_score.id,
        blob_id=blob_id,
    )
    async with uow_factory() as uow:
        created = await uow.replays.create(replay)
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.replays.exists_by_checksum(created.checksum_sha256) is True
        assert await uow.replays.exists_by_checksum("nonexistent_checksum") is False


async def test_sqlalchemy_replay_repository_rejects_duplicate_checksum(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    score1 = _make_score(online_checksum="test_replay_score_003")
    async with uow_factory() as uow:
        created_score1 = await uow.scores.create(score1)
        await uow.commit()
    assert created_score1.id is not None

    score2 = _make_score(online_checksum="test_replay_score_004")
    async with uow_factory() as uow:
        created_score2 = await uow.scores.create(score2)
        await uow.commit()
    assert created_score2.id is not None
    blob_id1 = await _create_blob(uow_factory, checksum="test_checksum_003")
    blob_id2 = await _create_blob(uow_factory, checksum="test_checksum_004")

    replay1 = _make_replay(
        checksum="test_checksum_003",
        score_id=created_score1.id,
        blob_id=blob_id1,
    )
    async with uow_factory() as uow:
        _ = await uow.replays.create(replay1)
        await uow.commit()

    replay2 = _make_replay(
        checksum="test_checksum_003",
        score_id=created_score2.id,
        blob_id=blob_id2,
    )
    with pytest.raises(ValueError, match="checksum_sha256 already exists"):
        async with uow_factory() as uow:
            _ = await uow.replays.create(replay2)
