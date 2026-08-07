"""SQLAlchemy replay download query repositoryのvisibilityとreplay metadata contractを検証する."""

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
    """Replay download repository integration test用engineを提供する.

    Yields:
        AsyncEngine: 接続確認済みのPostgreSQL engine.

    Raises:
        pytest.skip: DATABASE_URLが未設定またはdatabase serviceが利用不能な場合.

    Notes:
        fixture終了時にengine poolをdisposeする.
    """
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
    """Visibility fixture rowを隔離するPostgreSQL session factoryを提供する.

    Args:
        engine (AsyncEngine): 接続確認済みのPostgreSQL engine.

    Yields:
        async_sessionmaker[AsyncSession]: replay download query用session factory.

    Notes:
        fixture前後でtest prefixを持つrowをcleanupする.
    """
    factory = create_session_factory(engine)
    await _cleanup_rows(factory)
    yield factory
    try:
        await _cleanup_rows(factory)
    except OSError, SQLAlchemyError:
        return


async def test_get_candidate_uses_real_role_visibility_and_replay_metadata(
    session_factory: async_sessionmaker[AsyncSession],
    query_budget: QueryBudget,
) -> None:
    """Role visibilityに従いavailable replayとhidden scoreを返すcontractを検証する.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): seeded rowを読むsession factory.
        query_budget (QueryBudget): query countとduplicate queryを検査するbudget helper.

    Returns:
        None: visible candidateのreplay metadataとhidden candidate kindを確認して完了する.
    """
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
        score_id=visible_score_id,
        score_owner_user_id=_VISIBLE_USER_ID,
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
    """Visible/hidden user, score, blob, replay rowをPostgreSQLへseedする.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): seed transactionを開くsession factory.

    Returns:
        tuple[int, int, int, str]: visible score ID, hidden score ID, blob ID, visible checksum.
    """
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
    """Replay download visibility test用のscore persistence rowを構築する.

    Args:
        score_id (int): inserted scoreのprimary key.
        user_id (int): scoreを所有するvisibleまたはhidden user ID.
        online_checksum (str): test cleanupとscore identityに使うonline checksum.

    Returns:
        dict[str, object]: ScoreModel insertへ渡すcomplete row mapping.
    """
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
    """Replay download visibility test用のblob persistence rowを構築する.

    Args:
        label (str): storage keyとchecksumを区別するvisible/hidden label.
        blob_id (int): inserted blobのprimary key.

    Returns:
        dict[str, object]: BlobModel insertへ渡すcomplete row mapping.
    """
    return {
        "id": blob_id,
        "sha256": _checksum(f"blob-{label}"),
        "byte_size": 1024,
        "content_type": "application/octet-stream",
        "storage_backend": "local",
        "storage_key": f"{_BLOB_STORAGE_PREFIX}{label}.osr",
    }


def _checksum(label: str) -> str:
    """Test labelからdeterministic SHA-256 checksumを生成する.

    Args:
        label (str): hash inputとして使用するASCII test label.

    Returns:
        str: lower-case hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(label.encode()).hexdigest()


async def _cleanup_rows(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Replay download visibility testが作成したrowをdependency順に削除する.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): cleanup用session factory.

    Returns:
        None: replay, score, role, user, blob rowのdeletionをcommitして完了する.
    """
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
