"""Integration tests for ScoreSubmissionService with real PostgreSQL.

Tests E2E flow: multipart → decrypt → validate → persist → response.
Requirements: R1-R12 (all Wave 1 requirements)
"""

# pyright: reportUnknownParameterType=false, reportMissingParameterType=false
# pyright: reportUnknownMemberType=false, reportUnusedParameter=false
# pyright: reportArgumentType=false, reportOperatorIssue=false

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.beatmap import (
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)
from osu_server.domain.score.score import Grade, Playstyle, Ruleset
from osu_server.infrastructure.auth.score_authorization import ScoreAuthorizationService
from osu_server.infrastructure.crypto.score_crypto import DecryptedPayload
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.sqlalchemy.replay_repository import SQLAlchemyReplayRepository
from osu_server.repositories.sqlalchemy.score_repository import SQLAlchemyScoreRepository
from osu_server.repositories.sqlalchemy.submission_repository import (
    SQLAlchemyScoreSubmissionRepository,
)
from osu_server.services.score_submission_service import (
    ParsedSubmissionInput,
    ScoreSubmissionService,
    SubmissionOutcome,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _eligible_beatmap() -> BeatmapEligibility:
    return BeatmapEligibility(
        accepts_scores=True,
        has_leaderboard=True,
        awards_ranked_pp=True,
        awards_loved_pp=False,
        requires_osu_file_for_pp=True,
        is_officially_verified=True,
        is_mirror_derived=False,
        accepts_failed_scores=True,
        failed_scores_have_leaderboard=False,
        failed_scores_update_best_score=False,
        failed_scores_award_ranked_pp=False,
        failed_scores_award_loved_pp=False,
        denial_reason=None,
    )


@dataclass(slots=True)
class FakeBeatmapResolver:
    eligibility: BeatmapEligibility | None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,  # noqa: ARG002
        options: BeatmapResolveOptions | None = None,  # noqa: ARG002
    ) -> BeatmapResolveResult:
        return BeatmapResolveResult(
            beatmap=None,
            beatmapset=None,
            eligibility=self.eligibility,
            metadata_status=BeatmapFetchState.FRESH,
            file_status=BeatmapFileState.MISSING,
            source=BeatmapMetadataSource.OFFICIAL,
            verified=True,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=None,
        )


async def _cleanup_score_submission_rows(session: AsyncSession) -> None:
    test_score_filter = """
        online_checksum LIKE 'integration_test_%'
        OR online_checksum LIKE 'int_test_%'
    """
    _ = await session.execute(
        text(
            f"""
            DELETE FROM replays
            WHERE score_id IN (
                SELECT id FROM scores WHERE {test_score_filter}
            )
            """
        )
    )
    _ = await session.execute(text(f"DELETE FROM scores WHERE {test_score_filter}"))
    _ = await session.execute(
        text(
            """
            DELETE FROM score_submissions
            WHERE user_id = 1000 AND beatmap_checksum = 'abc123'
            """
        )
    )


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
    # Cleanup before test
    try:
        async with factory() as session:
            await _cleanup_score_submission_rows(session)
            await session.commit()
    except (OSError, SQLAlchemyError):
        pass

    yield factory

    # Cleanup after test
    try:
        async with factory() as session:
            await _cleanup_score_submission_rows(session)
            await session.commit()
    except (OSError, SQLAlchemyError):
        return


@pytest.fixture
def service(
    session_factory: async_sessionmaker[AsyncSession],
) -> ScoreSubmissionService:
    """Create ScoreSubmissionService with SQLAlchemy repositories."""
    score_repo = SQLAlchemyScoreRepository(session_factory)
    submission_repo = SQLAlchemyScoreSubmissionRepository(session_factory)
    replay_repo = SQLAlchemyReplayRepository(session_factory)
    auth_service = ScoreAuthorizationService()
    beatmap_resolver = FakeBeatmapResolver(_eligible_beatmap())
    return ScoreSubmissionService(
        score_repo, submission_repo, replay_repo, auth_service, beatmap_resolver
    )


@pytest.fixture
def valid_input() -> ParsedSubmissionInput:
    """Valid submission input."""
    return ParsedSubmissionInput(
        encrypted_payload=b"encrypted_data",
        iv=b"0" * 32,
        replay_data=b"replay_binary_data_integration",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # "password"
        client_hash="integration_test_hash",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_e2e_valid_submission_persists_to_database(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    """E2E: Valid submission creates score, replay, and submission records in DB."""

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        payload = (
            "1000:test_user:abc123:integration_test_checksum_001:0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None

    # Verify score persisted in DB
    score_repo = SQLAlchemyScoreRepository(session_factory)
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.user_id == 1000
    assert score.online_checksum == "integration_test_checksum_001"
    assert score.passed is True
    assert score.ruleset == Ruleset.OSU
    assert score.playstyle == Playstyle.VANILLA

    # Verify replay persisted in DB
    replay_repo = SQLAlchemyReplayRepository(session_factory)
    assert valid_input.replay_data is not None
    replay_checksum = hashlib.sha256(valid_input.replay_data).hexdigest()
    assert await replay_repo.exists_by_checksum(replay_checksum)

    # Verify submission record persisted in DB
    submission_repo = SQLAlchemyScoreSubmissionRepository(session_factory)
    fingerprint = hashlib.sha256(
        (
            f"{valid_input.beatmap_id}:"
            f"{valid_input.client_hash}:"
            f"{valid_input.submitted_at.isoformat()}"
        ).encode()
    ).hexdigest()
    submission = await submission_repo.get_by_fingerprint(fingerprint)
    assert submission is not None
    assert submission.state == "completed"
    assert submission.result_snapshot is not None
    assert submission.result_snapshot["score_id"] == result.score_id


@pytest.mark.asyncio
async def test_e2e_database_transaction_handling(
    service: ScoreSubmissionService,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    """E2E: Database transactions are handled correctly."""

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        payload = (
            "1000:test_user:abc123:integration_test_checksum_002:0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    input_data = ParsedSubmissionInput(
        encrypted_payload=b"encrypted_data",
        iv=b"0" * 32,
        replay_data=b"replay_data_tx_test",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        client_hash="tx_test_hash",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )

    result = await service.submit_score(input_data)
    assert result.outcome == SubmissionOutcome.COMPLETED

    # Verify all records are committed
    score_repo = SQLAlchemyScoreRepository(session_factory)
    assert result.score_id is not None
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None

    replay_repo = SQLAlchemyReplayRepository(session_factory)
    assert input_data.replay_data is not None
    replay_checksum = hashlib.sha256(input_data.replay_data).hexdigest()
    assert await replay_repo.exists_by_checksum(replay_checksum)


@pytest.mark.asyncio
async def test_e2e_concurrent_submission_handling(
    service: ScoreSubmissionService,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    """E2E: Concurrent submissions with different checksums are handled correctly."""
    call_count = 0

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        payload = (
            f"1000:test_user:abc123:int_test_cc_{call_count}:0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    # Create 3 concurrent submissions with different fingerprints
    inputs = [
        ParsedSubmissionInput(
            encrypted_payload=f"encrypted_data_{i}".encode(),
            iv=b"0" * 32,
            replay_data=f"replay_data_concurrent_{i}".encode(),
            password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            client_hash=f"concurrent_hash_{i}",
            fail_time_ms=None,
            osu_version="20240101",
            beatmap_id=1,
            submitted_at=datetime.now(UTC),
        )
        for i in range(3)
    ]

    results = await asyncio.gather(*[service.submit_score(inp) for inp in inputs])

    # All submissions should succeed
    assert all(r.outcome == SubmissionOutcome.COMPLETED for r in results)
    assert all(r.score_id is not None for r in results)

    # All score IDs should be unique
    score_ids = [r.score_id for r in results]
    assert len(set(score_ids)) == 3

    # Verify all scores persisted
    score_repo = SQLAlchemyScoreRepository(session_factory)
    for score_id in score_ids:
        assert score_id is not None
        score = await score_repo.get_by_id(score_id)
        assert score is not None


@pytest.mark.asyncio
async def test_e2e_duplicate_online_checksum_rejected_in_db(
    service: ScoreSubmissionService,
    monkeypatch,
) -> None:
    """E2E: Duplicate online checksum is rejected at database level."""

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        payload = "1000:test_user:abc123:int_test_dup:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    # First submission
    input1 = ParsedSubmissionInput(
        encrypted_payload=b"encrypted_data_1",
        iv=b"0" * 32,
        replay_data=b"replay_data_1",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        client_hash="duplicate_test_hash_1",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )
    result1 = await service.submit_score(input1)
    assert result1.outcome == SubmissionOutcome.COMPLETED

    # Second submission (different fingerprint, same online checksum)
    input2 = ParsedSubmissionInput(
        encrypted_payload=b"encrypted_data_2",
        iv=b"0" * 32,
        replay_data=b"replay_data_2",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        client_hash="duplicate_test_hash_2",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )
    result2 = await service.submit_score(input2)
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.error_reason is not None
    assert "duplicate_online_checksum" in result2.error_reason


@pytest.mark.asyncio
async def test_e2e_failed_play_persists_to_database(
    service: ScoreSubmissionService,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    """E2E: Failed play (passed=0) is stored in database."""

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        # passed=0 (last field)
        payload = "1000:test_user:abc123:int_test_failed:0:0:50:10:5:0:0:10:200000:40:0:0"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    input_data = ParsedSubmissionInput(
        encrypted_payload=b"encrypted_data",
        iv=b"0" * 32,
        replay_data=b"replay_data_failed",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        client_hash="failed_test_hash",
        fail_time_ms=30000,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )

    result = await service.submit_score(input_data)
    assert result.outcome == SubmissionOutcome.COMPLETED

    # Verify failed score persisted in DB
    score_repo = SQLAlchemyScoreRepository(session_factory)
    assert result.score_id is not None
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.passed is False
    assert score.score == 200000
    assert score.grade == Grade.B


@pytest.mark.asyncio
async def test_e2e_idempotent_retry_returns_cached_result(
    service: ScoreSubmissionService,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    """E2E: Idempotent retry returns cached result from database."""

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        payload = "1000:test_user:abc123:int_test_idem:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    input_data = ParsedSubmissionInput(
        encrypted_payload=b"encrypted_data",
        iv=b"0" * 32,
        replay_data=b"replay_data_idempotent",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        client_hash="idempotent_test_hash",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.fromisoformat("2024-01-01T12:00:00+00:00"),
    )

    # First submission
    result1 = await service.submit_score(input_data)
    assert result1.outcome == SubmissionOutcome.COMPLETED
    score_id1 = result1.score_id

    # Second submission (same fingerprint)
    result2 = await service.submit_score(input_data)
    assert result2.outcome == SubmissionOutcome.COMPLETED
    assert result2.score_id == score_id1

    # Verify only one score record exists
    async with session_factory() as session:
        query_result = await session.execute(
            text("SELECT COUNT(*) FROM scores WHERE online_checksum = :checksum"),
            {"checksum": "int_test_idem"},
        )
        count = query_result.scalar()
        assert count == 1
