"""Integration tests for the SQLAlchemy replay download query repository."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from sqlalchemy import delete, insert, or_, select
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.identity.leaderboard_visibility import (
    LEADERBOARD_VISIBLE_PERMISSION_MASK,
)
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadAvailableReplayCandidate,
    ReplayDownloadCandidateKind,
    ReplayDownloadCandidateQuery,
    ReplayDownloadHiddenScoreCandidate,
)
from osu_server.repositories.sqlalchemy.models.blob import BlobModel
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel
from osu_server.repositories.sqlalchemy.models.score import ReplayModel, ScoreModel
from osu_server.repositories.sqlalchemy.models.user import UserModel
from osu_server.repositories.sqlalchemy.queries.replay_download import (
    SQLAlchemyReplayDownloadQueryRepository,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from tests.conftest import QueryBudget


_TEST_PREFIX: Final = "trdq_"
_BLOB_STORAGE_PREFIX: Final = "test/replay-download-query/"
_NOW: Final = datetime.now(UTC)
_VISIBLE_USER_ID: Final = 910_001
_HIDDEN_USER_ID: Final = 910_002
_VISIBLE_ROLE_ID: Final = 910_001
_VISIBLE_SCORE_ID: Final = 910_001
_HIDDEN_SCORE_ID: Final = 910_002
_VISIBLE_BLOB_ID: Final = 910_001
_HIDDEN_BLOB_ID: Final = 910_002
_VISIBLE_REPLAY_ID: Final = 910_001
_HIDDEN_REPLAY_ID: Final = 910_002


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
            _ = await conn.execute(select(1))
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
    await _cleanup_rows(factory)
    yield factory
    try:
        await _cleanup_rows(factory)
    except (OSError, SQLAlchemyError):
        return


async def test_get_candidate_uses_real_role_visibility_and_replay_metadata(
    session_factory: async_sessionmaker[AsyncSession],
    query_budget: QueryBudget,
) -> None:
    visible_score_id, hidden_score_id, blob_id, checksum = await _seed_visibility_rows(
        session_factory
    )
    repository = SQLAlchemyReplayDownloadQueryRepository(session_factory)

    with query_budget(
        max_queries=2,
        name="replay-download-candidate-visible",
        duplicate_threshold=1,
    ):
        visible = await repository.get_candidate(
            ReplayDownloadCandidateQuery(score_id=visible_score_id, ruleset=Ruleset.OSU)
        )
    with query_budget(
        max_queries=2,
        name="replay-download-candidate-hidden",
        duplicate_threshold=1,
    ):
        hidden = await repository.get_candidate(
            ReplayDownloadCandidateQuery(score_id=hidden_score_id, ruleset=Ruleset.OSU)
        )

    assert visible == ReplayDownloadAvailableReplayCandidate(
        blob_id=blob_id,
        checksum=checksum,
        byte_size=1024,
    )
    assert visible.kind is ReplayDownloadCandidateKind.AVAILABLE_REPLAY
    assert isinstance(hidden, ReplayDownloadHiddenScoreCandidate)
    assert hidden.kind is ReplayDownloadCandidateKind.HIDDEN_SCORE


async def _seed_visibility_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, int, str]:
    visible_checksum = _checksum("visible-replay")
    async with session_factory() as session:
        _ = await session.execute(
            insert(UserModel).values(
                [
                    {
                        "id": _VISIBLE_USER_ID,
                        "username": f"{_TEST_PREFIX}visible",
                        "safe_username": f"{_TEST_PREFIX}visible",
                        "email": f"{_TEST_PREFIX}visible@example.invalid",
                        "password_hash": "test-hash",
                    },
                    {
                        "id": _HIDDEN_USER_ID,
                        "username": f"{_TEST_PREFIX}hidden",
                        "safe_username": f"{_TEST_PREFIX}hidden",
                        "email": f"{_TEST_PREFIX}hidden@example.invalid",
                        "password_hash": "test-hash",
                    },
                ]
            )
        )
        _ = await session.execute(
            insert(RoleModel).values(
                {
                    "id": _VISIBLE_ROLE_ID,
                    "name": f"{_TEST_PREFIX}visible",
                    "permissions": LEADERBOARD_VISIBLE_PERMISSION_MASK,
                    "position": 0,
                }
            )
        )
        _ = await session.execute(
            insert(UserRoleModel).values(
                {
                    "user_id": _VISIBLE_USER_ID,
                    "role_id": _VISIBLE_ROLE_ID,
                }
            )
        )
        _ = await session.execute(
            insert(ScoreModel).values(
                [
                    _score_row(
                        score_id=_VISIBLE_SCORE_ID,
                        user_id=_VISIBLE_USER_ID,
                        online_checksum=f"{_TEST_PREFIX}score_visible",
                    ),
                    _score_row(
                        score_id=_HIDDEN_SCORE_ID,
                        user_id=_HIDDEN_USER_ID,
                        online_checksum=f"{_TEST_PREFIX}score_hidden",
                    ),
                ]
            )
        )
        _ = await session.execute(
            insert(BlobModel).values(
                [
                    _blob_row(label="visible", blob_id=_VISIBLE_BLOB_ID),
                    _blob_row(label="hidden", blob_id=_HIDDEN_BLOB_ID),
                ]
            )
        )
        _ = await session.execute(
            insert(ReplayModel).values(
                [
                    {
                        "id": _VISIBLE_REPLAY_ID,
                        "score_id": _VISIBLE_SCORE_ID,
                        "blob_id": _VISIBLE_BLOB_ID,
                        "checksum_sha256": visible_checksum,
                        "byte_size": 1024,
                    },
                    {
                        "id": _HIDDEN_REPLAY_ID,
                        "score_id": _HIDDEN_SCORE_ID,
                        "blob_id": _HIDDEN_BLOB_ID,
                        "checksum_sha256": _checksum("hidden-replay"),
                        "byte_size": 1024,
                    },
                ]
            )
        )
        await session.commit()

    return _VISIBLE_SCORE_ID, _HIDDEN_SCORE_ID, _VISIBLE_BLOB_ID, visible_checksum


def _score_row(*, score_id: int, user_id: int, online_checksum: str) -> dict[str, object]:
    return {
        "id": score_id,
        "user_id": user_id,
        "beatmap_id": 2000,
        "beatmap_checksum": "8119fb28af74b9445f4a685f8b09eec2",
        "online_checksum": online_checksum,
        "ruleset": Ruleset.OSU.value,
        "playstyle": Playstyle.VANILLA.value,
        "mods": 0,
        "n300": 100,
        "n100": 10,
        "n50": 5,
        "geki": 20,
        "katu": 5,
        "miss": 0,
        "score": 1000000,
        "max_combo": 150,
        "accuracy": 0.95,
        "grade": Grade.A.value,
        "passed": True,
        "perfect": False,
        "client_version": "b20240101",
        "submitted_at": _NOW,
        "leaderboard_eligible_at_submission": True,
    }


def _blob_row(*, label: str, blob_id: int) -> dict[str, object]:
    return {
        "id": blob_id,
        "sha256": _checksum(f"blob-{label}"),
        "byte_size": 1024,
        "content_type": "application/octet-stream",
        "storage_backend": "local",
        "storage_key": f"{_BLOB_STORAGE_PREFIX}{label}.osr",
    }


def _checksum(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


async def _cleanup_rows(session_factory: async_sessionmaker[AsyncSession]) -> None:
    score_ids = select(ScoreModel.id).where(ScoreModel.online_checksum.like(f"{_TEST_PREFIX}%"))
    user_ids = select(UserModel.id).where(UserModel.safe_username.like(f"{_TEST_PREFIX}%"))
    role_ids = select(RoleModel.id).where(RoleModel.name.like(f"{_TEST_PREFIX}%"))

    async with session_factory() as session:
        _ = await session.execute(delete(ReplayModel).where(ReplayModel.score_id.in_(score_ids)))
        _ = await session.execute(
            delete(ScoreModel).where(ScoreModel.online_checksum.like(f"{_TEST_PREFIX}%"))
        )
        _ = await session.execute(
            delete(UserRoleModel).where(
                or_(
                    UserRoleModel.user_id.in_(user_ids),
                    UserRoleModel.role_id.in_(role_ids),
                )
            )
        )
        _ = await session.execute(delete(RoleModel).where(RoleModel.name.like(f"{_TEST_PREFIX}%")))
        _ = await session.execute(
            delete(UserModel).where(UserModel.safe_username.like(f"{_TEST_PREFIX}%"))
        )
        _ = await session.execute(
            delete(BlobModel).where(BlobModel.storage_key.like(f"{_BLOB_STORAGE_PREFIX}%"))
        )
        await session.commit()
