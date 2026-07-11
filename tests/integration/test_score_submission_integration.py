"""安定版 score submission の PostgreSQL integration test。

Command workflow の validation、persistence、stable response construction を
SQLAlchemy repository と実 database transaction 越しに検証する。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import Mod
from osu_server.domain.scores.score import Grade, Playstyle, PlayTimeSource, Ruleset
from osu_server.domain.storage.blobs import BlobStorageBackendKind, BlobStored, NewBlob
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBest,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory
from osu_server.services.commands.scores import (
    ParsedSubmissionInput,
    ProcessScoreSubmissionUseCase,
    SubmissionOutcome,
    SubmitScoreUseCase,
    generate_submission_fingerprint,
)
from tests.support.fakes import (
    make_score_authorization_service,
    make_test_parsed_score,
    make_test_submission_input,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from tests.conftest import QueryBudget


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


def _resolved_beatmap(*, total_length: int | None = None) -> Beatmap:
    return Beatmap(
        id=1,
        beatmapset_id=10,
        checksum_md5="0123456789abcdef0123456789abcdef",
        mode=BeatmapMode.OSU,
        version="Integration",
        total_length=total_length,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )


def _resolved_beatmapset(*, total_length: int | None = None) -> BeatmapSet:
    return BeatmapSet(
        id=10,
        artist="Integration Artist",
        title="Integration Title",
        creator="Athena",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(_resolved_beatmap(total_length=total_length),),
        last_fetched_at=None,
        next_refresh_at=None,
    )


def _fingerprint_for(
    input_data: ParsedSubmissionInput,
    *,
    user_id: int = 1000,
    beatmap_checksum: str = "abc123",
    submitted_timestamp: str | None = None,
) -> str:
    return generate_submission_fingerprint(
        user_id=user_id,
        beatmap_checksum=beatmap_checksum,
        submitted_timestamp=submitted_timestamp,
        request_hash=input_data.request_hash,
    )


def _leaderboard_scope(
    *,
    user_id: int = 1000,
) -> BeatmapLeaderboardUserBestScope:
    return BeatmapLeaderboardUserBestScope(
        beatmap_id=1,
        beatmap_checksum="abc123",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=user_id,
    )


async def _get_leaderboard_best(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
    scope: BeatmapLeaderboardUserBestScope,
) -> BeatmapLeaderboardUserBest | None:
    async with uow_factory() as uow:
        return await uow.beatmap_leaderboards.get_user_best(scope)


async def _replace_user_projection_with_score(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
    *,
    user_id: int,
    score_id: int,
    score: int,
    submitted_at: datetime,
) -> None:
    async with uow_factory() as uow:
        await uow.beatmap_leaderboards.replace_projection_slice(
            BeatmapLeaderboardUserProjectionSlice(user_id=user_id),
            (
                UpsertBeatmapLeaderboardUserBest(
                    scope=_leaderboard_scope(user_id=user_id),
                    score_id=score_id,
                    rank_key=ScoreRankKey(
                        score=score,
                        submitted_at=submitted_at,
                        score_id=score_id,
                    ),
                ),
            ),
        )
        await uow.commit()


@dataclass(slots=True)
class FakeBeatmapResolver:
    eligibility: BeatmapEligibility | None
    beatmap_total_length: int | None = None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        _ = (beatmap_id, options)
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

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        _ = (checksum_md5, options)
        return BeatmapResolveResult(
            beatmap=_resolved_beatmap(total_length=self.beatmap_total_length),
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


class SQLAlchemyBlobStorageStub:
    """外部キー付き integration test 用に blob metadata を永続化する fake storage。"""

    _uow_factory: SQLAlchemyUnitOfWorkFactory

    def __init__(self, uow_factory: SQLAlchemyUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def put_bytes(self, data: bytes, *, content_type: str) -> BlobStored:
        digest = hashlib.sha256(data).hexdigest()
        async with self._uow_factory() as uow:
            existing = await uow.blobs.get_by_sha256(digest)
            if existing is not None:
                return BlobStored(existing)

            blob = await uow.blobs.create(
                NewBlob(
                    sha256=digest,
                    byte_size=len(data),
                    content_type=content_type,
                    storage_backend=BlobStorageBackendKind.LOCAL,
                    storage_key=f"test/replay/{digest}.osr",
                )
            )
            await uow.commit()
        return BlobStored(blob)


async def _cleanup_score_submission_rows(session: AsyncSession) -> None:
    test_score_filter = """
        online_checksum LIKE 'integration_test_%'
        OR online_checksum LIKE 'int_test_%'
    """
    _ = await session.execute(
        text(
            f"""
            DELETE FROM beatmap_leaderboard_user_bests
            WHERE score_id IN (
                SELECT id FROM scores WHERE {test_score_filter}
            )
            """
        )
    )
    _ = await session.execute(
        text(
            f"""
            DELETE FROM personal_bests
            WHERE score_id IN (
                SELECT id FROM scores WHERE {test_score_filter}
            )
            """
        )
    )
    _ = await session.execute(
        text(
            f"""
            DELETE FROM replay_file_attachments
            WHERE score_id IN (
                SELECT id FROM scores WHERE {test_score_filter}
            )
            """
        )
    )
    _ = await session.execute(text(f"DELETE FROM scores WHERE {test_score_filter}"))
    _ = await session.execute(text("DELETE FROM blobs WHERE storage_key LIKE 'test/replay/%'"))
    _ = await session.execute(
        text(
            """
            DELETE FROM score_submissions
            WHERE user_id = 1000 AND beatmap_checksum = 'abc123'
            """
        )
    )


async def _seed_score_submission_beatmap(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    uow_factory = SQLAlchemyUnitOfWorkFactory(session_factory)
    async with uow_factory() as uow:
        await uow.beatmaps.save_beatmapset_snapshot(_resolved_beatmapset())
        await uow.commit()

    async with session_factory() as session:
        _ = await session.execute(
            text("UPDATE beatmaps SET play_count = 0, pass_count = 0 WHERE id = 1")
        )
        await session.commit()


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
        await _seed_score_submission_beatmap(factory)
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
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> SQLAlchemyUnitOfWorkFactory:
    return SQLAlchemyUnitOfWorkFactory(session_factory)


@pytest.fixture
def service(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> ProcessScoreSubmissionUseCase:
    """永続化 repository で ProcessScoreSubmissionUseCase を作る。

    Args:
        uow_factory: integration test 用 Unit of Work factory。

    Returns:
        PostgreSQL-backed repository を使う score submission use-case。

    Raises:
        例外は送出しない。

    Constraints:
        Production composition graph は使わず、repository 境界だけを integration する。
    """
    auth_service = make_score_authorization_service()
    beatmap_resolver = FakeBeatmapResolver(_eligible_beatmap())
    submit_score_use_case = SubmitScoreUseCase(unit_of_work_factory=uow_factory)
    return ProcessScoreSubmissionUseCase(
        submit_score_use_case,
        SQLAlchemyBlobStorageStub(uow_factory),
        auth_service,
        beatmap_resolver,
    )


@pytest.fixture
def valid_input() -> ParsedSubmissionInput:
    """有効な score submission input を返す。

    Args:
        なし。

    Returns:
        PostgreSQL integration test 用の ParsedSubmissionInput。

    Raises:
        例外は送出しない。

    Constraints:
        Transport wire payload ではなく command 境界の入力を直接生成する。
    """
    return make_test_submission_input(
        replay_data=b"replay_binary_data_integration",
        request_hash="integration_test_hash",
    )


@pytest.mark.asyncio
async def test_e2e_valid_submission_persists_to_database(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    uow_factory: SQLAlchemyUnitOfWorkFactory,
    query_budget: QueryBudget,
) -> None:
    """有効な submission が score、replay、submission record を DB に作る。

    Args:
        service: test 対象の use-case。
        valid_input: 有効な command input。
        uow_factory: assertion 用 Unit of Work factory。
        query_budget: SQL query 数を検証する helper。

    Returns:
        None。

    Raises:
        AssertionError: DB に保存された score、replay、submission が期待と異なる場合。

    Constraints:
        実 PostgreSQL transaction と repository 実装を通して検証する。
    """
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:integration_test_checksum_001:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    with query_budget(
        max_queries=30,
        name="score-submission-valid-execute",
        duplicate_threshold=1,
    ):
        result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None

    async with uow_factory() as uow:
        score = await uow.scores.get_by_id(result.score_id)
    assert score is not None
    assert score.user_id == 1000
    assert score.online_checksum == "integration_test_checksum_001"
    assert score.passed is True
    assert score.ruleset == Ruleset.OSU
    assert score.playstyle == Playstyle.VANILLA
    assert score.beatmap_status_at_submission is BeatmapRankStatus.RANKED

    assert input_data.replay_data is not None
    replay_checksum = hashlib.sha256(input_data.replay_data).hexdigest()
    async with uow_factory() as uow:
        assert await uow.replays.exists_by_checksum(replay_checksum)

    fingerprint = _fingerprint_for(input_data)
    async with uow_factory() as uow:
        submission = await uow.submissions.get_by_fingerprint(fingerprint)
    assert submission is not None
    assert submission.state == "completed"
    assert submission.result_snapshot is not None
    assert submission.result_snapshot["score_id"] == result.score_id
    assert (
        submission.result_snapshot["beatmap_status_at_submission"]
        == BeatmapRankStatus.RANKED.value
    )


@pytest.mark.asyncio
async def test_e2e_database_transaction_handling(
    service: ProcessScoreSubmissionUseCase,
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """データベース transaction が正しく commit されることを検証する。"""
    input_data = make_test_submission_input(
        payload=(
            "1000:test_user:abc123:integration_test_checksum_002:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
        request_hash="tx_test_hash",
        replay_data=b"replay_data_tx_test",
    )

    result = await service.execute(input_data)
    assert result.outcome == SubmissionOutcome.COMPLETED

    assert result.score_id is not None
    async with uow_factory() as uow:
        score = await uow.scores.get_by_id(result.score_id)
    assert score is not None

    assert input_data.replay_data is not None
    replay_checksum = hashlib.sha256(input_data.replay_data).hexdigest()
    async with uow_factory() as uow:
        assert await uow.replays.exists_by_checksum(replay_checksum)


@pytest.mark.asyncio
async def test_e2e_concurrent_submission_handling(
    service: ProcessScoreSubmissionUseCase,
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """異なる checksum の concurrent submission を正しく保存する。"""
    # Create 3 concurrent submissions with different fingerprints
    inputs = [
        make_test_submission_input(
            payload=f"1000:test_user:abc123:int_test_cc_{i}:0:0:100:10:5:0:0:2:500000:99:1:1",
            request_hash=f"concurrent_hash_{i}",
            replay_data=f"replay_data_concurrent_{i}".encode(),
        )
        for i in range(3)
    ]

    results = await asyncio.gather(*[service.execute(inp) for inp in inputs])

    # All submissions should succeed
    assert all(r.outcome == SubmissionOutcome.COMPLETED for r in results)
    assert all(r.score_id is not None for r in results)

    # All score IDs should be unique
    score_ids = [r.score_id for r in results]
    assert len(set(score_ids)) == 3

    async with uow_factory() as uow:
        for score_id in score_ids:
            assert score_id is not None
            score = await uow.scores.get_by_id(score_id)
            assert score is not None


@pytest.mark.asyncio
async def test_e2e_duplicate_online_checksum_rejected_in_db(
    service: ProcessScoreSubmissionUseCase,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """重複 online checksum が別 submission を terminal reject する。"""
    parsed_score = make_test_parsed_score(
        "1000:test_user:abc123:int_test_dup:0:0:100:10:5:0:0:2:500000:99:1:1"
    )

    # First submission
    input1 = make_test_submission_input(
        parsed_score=parsed_score,
        request_hash="duplicate_test_hash_1",
        replay_data=b"replay_data_1",
    )
    result1 = await service.execute(input1)
    assert result1.outcome == SubmissionOutcome.COMPLETED

    # Second submission (different fingerprint, same online checksum)
    input2 = make_test_submission_input(
        parsed_score=parsed_score,
        request_hash="duplicate_test_hash_2",
        replay_data=b"replay_data_2",
    )
    result2 = await service.execute(input2)
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.score_id is None
    assert result2.error_reason == "duplicate_online_checksum"

    async with session_factory() as session:
        query_result = await session.execute(
            text("SELECT COUNT(*) FROM scores WHERE online_checksum = :checksum"),
            {"checksum": "int_test_dup"},
        )
        count = query_result.scalar()
        assert count == 1


@pytest.mark.asyncio
async def test_e2e_eligible_submission_updates_leaderboard_projection_and_retry_uses_snapshot(
    service: ProcessScoreSubmissionUseCase,
    session_factory: async_sessionmaker[AsyncSession],
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """適格 submit が projection を更新し retry で保存済み PB delta を返す。"""

    previous_input = make_test_submission_input(
        payload="1000:test_user:abc123:int_test_lb_prev:0:0:100:10:5:0:0:2:400000:99:1:1",
        request_hash="leaderboard_previous_hash",
        replay_data=b"replay_data_previous_best",
        submitted_at=datetime.fromisoformat("2024-01-01T12:00:00+00:00"),
    )
    previous_result = await service.execute(previous_input)

    assert previous_result.outcome == SubmissionOutcome.COMPLETED
    assert previous_result.score_id is not None
    assert previous_result.personal_best_delta is not None
    assert previous_result.personal_best_delta.before_score_id is None
    assert previous_result.personal_best_delta.after_score_id == previous_result.score_id
    assert previous_result.personal_best_delta.updated is True

    new_input = make_test_submission_input(
        payload=(
            "1000:test_user:abc123:int_test_lb_retry:0:"
            f"{int(Mod.DOUBLE_TIME)}:100:10:5:0:0:2:500000:99:1:1"
        ),
        request_hash="leaderboard_new_hash",
        replay_data=b"replay_data_new_best",
        submitted_at=datetime.fromisoformat("2024-01-01T12:01:00+00:00"),
    )
    new_result = await service.execute(new_input)

    assert new_result.outcome == SubmissionOutcome.COMPLETED
    assert new_result.score_id is not None
    assert new_result.personal_best_delta is not None
    assert new_result.personal_best_delta.before_score_id == previous_result.score_id
    assert new_result.personal_best_delta.before_score == 400_000
    assert new_result.personal_best_delta.after_score_id == new_result.score_id
    assert new_result.personal_best_delta.after_score == 500_000
    assert new_result.personal_best_delta.updated is True

    all_mods_best = await _get_leaderboard_best(
        uow_factory,
        _leaderboard_scope(),
    )
    assert all_mods_best is not None
    assert all_mods_best.score_id == new_result.score_id

    await _replace_user_projection_with_score(
        uow_factory,
        user_id=1000,
        score_id=previous_result.score_id,
        score=400_000,
        submitted_at=previous_input.submitted_at,
    )

    retry_result = await service.execute(replace(new_input, submitted_at=datetime.now(UTC)))

    assert retry_result.outcome == SubmissionOutcome.COMPLETED
    assert retry_result.score_id == new_result.score_id
    assert retry_result.personal_best_delta == new_result.personal_best_delta

    all_mods_best_after_retry = await _get_leaderboard_best(
        uow_factory,
        _leaderboard_scope(),
    )
    assert all_mods_best_after_retry is not None
    assert all_mods_best_after_retry.score_id == previous_result.score_id

    async with session_factory() as session:
        query_result = await session.execute(
            text("SELECT COUNT(*) FROM scores WHERE online_checksum = :checksum"),
            {"checksum": "int_test_lb_retry"},
        )
        count = query_result.scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_e2e_failed_play_persists_to_database(
    service: ProcessScoreSubmissionUseCase,
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """失敗 play (passed=0) を database に保存する。"""
    input_data = make_test_submission_input(
        payload="1000:test_user:abc123:int_test_failed:0:0:50:10:5:0:0:10:200000:40:0:0",
        request_hash="failed-play-hash",
        replay_data=b"replay_data_failed",
        fail_time_ms=30000,
        submit_exit_classification="1",
    )

    result = await service.execute(input_data)
    assert result.outcome == SubmissionOutcome.COMPLETED

    assert result.score_id is not None
    async with uow_factory() as uow:
        score = await uow.scores.get_by_id(result.score_id)
    assert score is not None
    assert score.passed is False
    assert score.score == 200000
    assert score.grade == Grade.B
    assert score.fail_time_ms == 30000
    assert score.play_time_seconds == 30
    assert score.play_time_source is PlayTimeSource.FAIL_TIME
    assert score.submit_exit_classification == "1"


@pytest.mark.asyncio
async def test_e2e_passed_score_submission_uses_beatmap_length_for_play_time(
    uow_factory: SQLAlchemyUnitOfWorkFactory,
) -> None:
    """受理済み passed score が beatmap-length play time を保存する。"""
    auth_service = make_score_authorization_service()
    beatmap_resolver = FakeBeatmapResolver(_eligible_beatmap(), beatmap_total_length=123)
    submit_score_use_case = SubmitScoreUseCase(unit_of_work_factory=uow_factory)
    service = ProcessScoreSubmissionUseCase(
        submit_score_use_case,
        SQLAlchemyBlobStorageStub(uow_factory),
        auth_service,
        beatmap_resolver,
    )

    input_data = make_test_submission_input(
        payload="1000:test_user:abc123:int_test_passed_timing:0:0:100:10:5:0:0:2:500000:99:1:1",
        request_hash="passed-timing-hash",
        replay_data=b"replay_data_passed_timing",
        fail_time_ms=0,
        submit_exit_classification="1",
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    async with uow_factory() as uow:
        score = await uow.scores.get_by_id(result.score_id)
    assert score is not None
    assert score.passed is True
    assert score.fail_time_ms == 0
    assert score.play_time_seconds == 123
    assert score.play_time_source is PlayTimeSource.BEATMAP_TOTAL_LENGTH
    assert score.submit_exit_classification == "1"


@pytest.mark.asyncio
async def test_e2e_idempotent_retry_returns_cached_result(
    service: ProcessScoreSubmissionUseCase,
    session_factory: async_sessionmaker[AsyncSession],
    query_budget: QueryBudget,
) -> None:
    """冪等 retry が database の cached result を返す。"""
    input_data = make_test_submission_input(
        payload="1000:test_user:abc123:int_test_idem:0:0:100:10:5:0:0:2:500000:99:1:1",
        request_hash="idempotent_test_hash",
        replay_data=b"replay_data_idempotent",
        submitted_at=datetime.fromisoformat("2024-01-01T12:00:00+00:00"),
    )

    # First submission
    with query_budget(
        max_queries=30,
        name="score-submission-idempotent-first-execute",
        duplicate_threshold=1,
    ):
        result1 = await service.execute(input_data)
    assert result1.outcome == SubmissionOutcome.COMPLETED
    score_id1 = result1.score_id

    resent_input = replace(input_data, submitted_at=datetime.now(UTC))

    # Second submission has the same request content and a different receive time.
    with query_budget(
        max_queries=5,
        name="score-submission-idempotent-retry-execute",
        duplicate_threshold=1,
    ):
        result2 = await service.execute(resent_input)
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
