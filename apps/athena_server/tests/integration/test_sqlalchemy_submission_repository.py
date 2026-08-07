"""SQLAlchemy score submission repositoryのidempotencyとfingerprint uniquenessを検証する.

Notes:
    各testは実PostgreSQLへ接続し, score submission persistenceを検証する.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _get_database_url() -> str:
    """Integration testで使用するPostgreSQL connection URLを取得する.

    Returns:
        str: DATABASE_URL environment variableで指定されたPostgreSQL URL.

    Raises:
        pytest.skip: DATABASE_URLが未設定の場合.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    """Score submission repository integration test用engineを提供する.

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
    """Score submission rowをcleanupするPostgreSQL session factoryを提供する.

    Args:
        engine (AsyncEngine): 接続確認済みのPostgreSQL engine.

    Yields:
        async_sessionmaker[AsyncSession]: score submission repository用session factory.

    Notes:
        fixture終了時にtest_fp_ prefixを持つscore submission rowを削除する.
    """
    factory = create_session_factory(engine)
    yield factory
    try:
        async with factory() as session:
            _ = await session.execute(
                text("DELETE FROM score_submissions WHERE fingerprint LIKE 'test_fp_%'")
            )
            await session.commit()
    except OSError, SQLAlchemyError:
        return


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> SQLAlchemyUnitOfWorkFactory:
    """Score submission command repositoryを解決するSQLAlchemy Unit of Work factoryを構築する.

    Args:
        session_factory (async_sessionmaker[AsyncSession]): test用PostgreSQL session factory.

    Returns:
        SQLAlchemyUnitOfWorkFactory: score submission command repositoryを持つfactory.
    """
    return SQLAlchemyUnitOfWorkFactory(session_factory)


def _make_submission(
    *,
    fingerprint: str = "test_fp_001",
    user_id: int = 1000,
    state: ScoreSubmissionState = ScoreSubmissionState.RECEIVED,
) -> ScoreSubmission:
    """Score submission repositoryへ保存するvalid ScoreSubmission domain objectを構築する.

    Args:
        fingerprint (str): idempotencyとuniquenessを検証するsubmission fingerprint.
        user_id (int): submissionを所有するtest user ID.
        state (ScoreSubmissionState): 作成時に保存するsubmission lifecycle state.

    Returns:
        ScoreSubmission: current timestampとempty result snapshotを持つpersistable submission.
    """
    return ScoreSubmission(
        id=None,
        fingerprint=fingerprint,
        user_id=user_id,
        beatmap_checksum="8119fb28af74b9445f4a685f8b09eec2",
        submitted_at=datetime.now(UTC),
        state=state,
        result_snapshot=None,
    )


async def test_sqlalchemy_submission_repository_creates_and_retrieves_by_fingerprint(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """Submission repositoryがfingerprintでcreated submissionをretrieveするcontractを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): score submission repository用factory.

    Returns:
        None: persisted identity, fingerprint, user IDの再読込を確認して完了する.
    """
    submission = _make_submission(fingerprint="test_fp_001")
    async with uow_factory() as uow:
        created = await uow.submissions.create(submission)
        await uow.commit()

    assert created.id is not None
    assert created.fingerprint == submission.fingerprint
    assert created.user_id == submission.user_id

    async with uow_factory() as uow:
        retrieved = await uow.submissions.get_by_fingerprint(created.fingerprint)
    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.fingerprint == created.fingerprint


async def test_sqlalchemy_submission_repository_returns_none_for_nonexistent_fingerprint(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """Submission repositoryがmissing fingerprintに対してNoneを返すcontractを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): score submission repository用factory.

    Returns:
        None: 未保存fingerprintのquery resultがNoneであることを確認して完了する.
    """
    async with uow_factory() as uow:
        retrieved = await uow.submissions.get_by_fingerprint("nonexistent_fingerprint")
    assert retrieved is None


async def test_sqlalchemy_submission_repository_rejects_duplicate_fingerprint(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """Submission repositoryがduplicate fingerprintをValueErrorで拒否するcontractを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): score submission repository用factory.

    Returns:
        None: second createがfingerprint uniqueness errorとなることを確認して完了する.
    """
    submission1 = _make_submission(fingerprint="test_fp_002", user_id=1000)
    async with uow_factory() as uow:
        _ = await uow.submissions.create(submission1)
        await uow.commit()

    submission2 = _make_submission(fingerprint="test_fp_002", user_id=2000)
    with pytest.raises(ValueError, match="fingerprint already exists"):
        async with uow_factory() as uow:
            _ = await uow.submissions.create(submission2)


async def test_sqlalchemy_submission_repository_idempotent_retrieval(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """Submission repositoryが同じfingerprintのrepeated retrievalで同一rowを返すcontractを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): score submission repository用factory.

    Returns:
        None: two retrievalが同一identityとfingerprintを返すことを確認して完了する.
    """
    submission = _make_submission(fingerprint="test_fp_003")
    async with uow_factory() as uow:
        created = await uow.submissions.create(submission)
        await uow.commit()

    async with uow_factory() as uow:
        first_retrieval = await uow.submissions.get_by_fingerprint(created.fingerprint)
        second_retrieval = await uow.submissions.get_by_fingerprint(created.fingerprint)

    assert first_retrieval is not None
    assert second_retrieval is not None
    assert first_retrieval.id == second_retrieval.id
    assert first_retrieval.fingerprint == second_retrieval.fingerprint


async def test_sqlalchemy_submission_repository_updates_state(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """Submission repositoryがpersisted submission stateを更新するcontractを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): score submission repository用factory.

    Returns:
        None: received stateがcompleted stateへ更新されることを確認して完了する.
    """
    submission = _make_submission(
        fingerprint="test_fp_004",
        state=ScoreSubmissionState.RECEIVED,
    )
    async with uow_factory() as uow:
        created = await uow.submissions.create(submission)
        await uow.commit()

    assert created.id is not None
    assert created.state == ScoreSubmissionState.RECEIVED

    async with uow_factory() as uow:
        await uow.submissions.update_state(created.id, ScoreSubmissionState.COMPLETED)
        await uow.commit()

    async with uow_factory() as uow:
        retrieved = await uow.submissions.get_by_fingerprint(created.fingerprint)
    assert retrieved is not None
    assert retrieved.state == ScoreSubmissionState.COMPLETED


async def test_sqlalchemy_submission_repository_update_state_raises_for_nonexistent_id(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """Submission repositoryが未保存IDのstate updateをValueErrorで拒否するcontractを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): score submission repository用factory.

    Returns:
        None: 未保存IDのstate updateがnot-found errorとなることを確認して完了する.
    """
    with pytest.raises(ValueError, match="Submission not found"):
        async with uow_factory() as uow:
            await uow.submissions.update_state(999999, ScoreSubmissionState.COMPLETED)


async def test_sqlalchemy_submission_repository_preserves_result_snapshot(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """Submission repositoryがresult snapshot JSON mappingを保持するcontractを検証する.

    Args:
        uow_factory (SQLAlchemyUnitOfWorkFactory): score submission repository用factory.

    Returns:
        None: persisted snapshotのstatusとscore IDを再読込できることを確認して完了する.
    """
    submission = _make_submission(fingerprint="test_fp_005")
    submission.result_snapshot = {"status": "completed", "score_id": 12345}
    async with uow_factory() as uow:
        created = await uow.submissions.create(submission)
        await uow.commit()

    assert created.id is not None
    async with uow_factory() as uow:
        retrieved = await uow.submissions.get_by_fingerprint(created.fingerprint)

    assert retrieved is not None
    assert retrieved.result_snapshot is not None
    assert retrieved.result_snapshot["status"] == "completed"
    assert retrieved.result_snapshot["score_id"] == 12345
