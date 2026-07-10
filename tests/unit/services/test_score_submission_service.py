"""スコア送信 use-case の unit test。"""

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast, final, override

import pytest
import structlog.testing

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
from osu_server.domain.scores.user_stats import UserCurrentStats
from osu_server.domain.storage.blobs import BlobStored
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.beatmaps.file_warmup import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupOutcome,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
    RequestBeatmapFileWarmupUseCase,
)
from osu_server.services.commands.scores import (
    BeatmapRankDelta,
    ParsedSubmissionInput,
    ProcessScoreSubmissionUseCase,
    SubmissionOutcome,
    generate_submission_fingerprint,
)
from osu_server.services.commands.scores.performance import (
    RequestPerformanceCalculationCommand,
    RequestPerformanceCalculationOutcome,
    RequestPerformanceCalculationResult,
)
from osu_server.services.queries.scores import (
    BeatmapPersonalBestRankQueryInput,
    BeatmapPersonalBestRankQueryResult,
    CurrentUserStatsQueryInput,
    CurrentUserStatsQueryResult,
    PerformanceSubmitResponse,
    PerformanceSubmitResponseQuery,
    PerformanceSubmitResponseState,
)
from tests.support.fakes import (
    ScoreRepositoryViews,
    StubBlobStorageService,
    make_score_authorization_service,
    make_score_repository_views,
    make_submit_score_use_case,
    make_test_parsed_score,
    make_test_submission_input,
)


def _score_payload(*parts: str) -> str:
    return "".join(parts)


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


def _ineligible_beatmap(reason: str = "status_not_eligible") -> BeatmapEligibility:
    return BeatmapEligibility(
        accepts_scores=False,
        has_leaderboard=False,
        awards_ranked_pp=False,
        awards_loved_pp=False,
        requires_osu_file_for_pp=False,
        is_officially_verified=True,
        is_mirror_derived=False,
        accepts_failed_scores=False,
        failed_scores_have_leaderboard=False,
        failed_scores_update_best_score=False,
        failed_scores_award_ranked_pp=False,
        failed_scores_award_loved_pp=False,
        denial_reason=reason,
    )


def _resolved_beatmap() -> Beatmap:
    return Beatmap(
        id=1,
        beatmapset_id=10,
        checksum_md5="0123456789abcdef0123456789abcdef",
        mode="osu",
        version="Test",
        total_length=None,
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


@dataclass(slots=True)
class FakeBeatmapResolver:
    eligibility: BeatmapEligibility | None = None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        del beatmap_id, options
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
        del checksum_md5, options
        return BeatmapResolveResult(
            beatmap=_resolved_beatmap(),
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


class RecordingWarmupUseCase:
    def __init__(
        self,
        events: list[str],
        *,
        outcome: BeatmapFileWarmupOutcome = BeatmapFileWarmupOutcome.REQUESTED,
    ) -> None:
        self.events: list[str] = events
        self.outcome: BeatmapFileWarmupOutcome = outcome
        self.requests: list[BeatmapFileWarmupRequest] = []

    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult:
        self.events.append("warmup")
        self.requests.append(request)
        return BeatmapFileWarmupResult(
            outcome=self.outcome,
            entrance=request.entrance,
            user_id=request.user_id,
            beatmap_id=request.beatmap_id,
            checksum_md5=request.checksum_md5,
            reason=None,
        )


@final
class RecordingPerformanceCalculationRequest:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.commands: list[RequestPerformanceCalculationCommand] = []

    async def execute(
        self,
        command: RequestPerformanceCalculationCommand,
    ) -> RequestPerformanceCalculationResult:
        self.commands.append(command)
        if self._fail:
            msg = "performance request failed"
            raise RuntimeError(msg)
        return RequestPerformanceCalculationResult(
            outcome=RequestPerformanceCalculationOutcome.CREATED,
            score_id=command.score_id,
        )


@final
class RecordingPerformanceResponseQuery:
    def __init__(self, response: PerformanceSubmitResponse) -> None:
        self.response: PerformanceSubmitResponse = response
        self.queries: list[PerformanceSubmitResponseQuery] = []

    async def wait_for_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse:
        self.queries.append(query)
        return self.response

    async def get_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse:
        self.queries.append(query)
        return self.response


@final
class RecordingCurrentUserStatsQuery:
    def __init__(self, responses: tuple[UserCurrentStats | None, ...]) -> None:
        self._responses = responses
        self.queries: list[CurrentUserStatsQueryInput] = []

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        self.queries.append(input_data)
        response_index = len(self.queries) - 1
        response = self._responses[response_index]
        if response is None:
            return CurrentUserStatsQueryResult(stats=())
        return CurrentUserStatsQueryResult(stats=(response,))


@final
class RecordingBeatmapPersonalBestRankQuery:
    def __init__(self, responses: tuple[int | None, ...]) -> None:
        self._responses = responses
        self.queries: list[BeatmapPersonalBestRankQueryInput] = []

    async def execute(
        self,
        input_data: BeatmapPersonalBestRankQueryInput,
    ) -> BeatmapPersonalBestRankQueryResult:
        self.queries.append(input_data)
        response_index = len(self.queries) - 1
        return BeatmapPersonalBestRankQueryResult(rank=self._responses[response_index])


@final
class StubPerformanceCalculatorIdentity:
    def calculator_name(self) -> str:
        return "test-calculator"

    def calculator_version(self) -> str:
        return "1.2.3"


@dataclass(slots=True)
class FakeWarmupResolver:
    file_status: BeatmapFileState
    reason: str | None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        del options
        return self._result(beatmap_id)

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        del checksum_md5, options
        return self._result(1)

    def _result(self, beatmap_id: int) -> BeatmapResolveResult:
        beatmap = replace(_resolved_beatmap(), id=beatmap_id, file_state=self.file_status)
        return BeatmapResolveResult(
            beatmap=beatmap,
            beatmapset=None,
            eligibility=_eligible_beatmap(),
            metadata_status=BeatmapFetchState.FRESH,
            file_status=self.file_status,
            source=BeatmapMetadataSource.OFFICIAL,
            verified=True,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=self.reason,
        )


class RecordingBlobStorageService(StubBlobStorageService):
    def __init__(self, events: list[str], *, fail_writes: bool = False) -> None:
        super().__init__(fail_writes=fail_writes)
        self.events: list[str] = events

    @override
    async def put_bytes(self, data: bytes, *, content_type: str) -> BlobStored:
        self.events.append("blob_storage")
        return await super().put_bytes(data, content_type=content_type)


@pytest.fixture
def uow_factory() -> InMemoryUnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory()


@pytest.fixture
def repos(uow_factory: InMemoryUnitOfWorkFactory) -> ScoreRepositoryViews:
    """スコア送信 test 用の in-memory repository view を作る。

    Args:
        uow_factory: test 用 Unit of Work factory。

    Returns:
        score、submission、replay repository view。

    Raises:
        例外は送出しない。

    Constraints:
        DB I/O を使わず、同じ in-memory state を command と assertion で共有する。
    """
    return make_score_repository_views(uow_factory)


@pytest.fixture
def beatmap_resolver() -> FakeBeatmapResolver:
    return FakeBeatmapResolver(_eligible_beatmap())


@pytest.fixture
def blob_storage() -> StubBlobStorageService:
    return StubBlobStorageService()


@pytest.fixture
def service(
    uow_factory: InMemoryUnitOfWorkFactory,
    beatmap_resolver: FakeBeatmapResolver,
    blob_storage: StubBlobStorageService,
) -> ProcessScoreSubmissionUseCase:
    """インメモリ依存で ProcessScoreSubmissionUseCase を作る。

    Args:
        uow_factory: test 用 Unit of Work factory。
        beatmap_resolver: eligibility を返す fake resolver。
        blob_storage: replay 保存を記録する fake storage。

    Returns:
        score submission command workflow の use-case。

    Raises:
        例外は送出しない。

    Constraints:
        Production repository や external storage は使わない。
    """
    auth_service = make_score_authorization_service()
    return ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        blob_storage,
        auth_service,
        beatmap_resolver,
    )


@pytest.fixture
def valid_input() -> ParsedSubmissionInput:
    """有効な score submission command input を返す。

    Args:
        なし。

    Returns:
        成功 score submit を表す ParsedSubmissionInput。

    Raises:
        例外は送出しない。

    Constraints:
        Transport wire payload ではなく正規化済み command input を返す。
    """
    return make_test_submission_input()


def _fingerprint_for(
    input_data: ParsedSubmissionInput,
    *,
    beatmap_checksum: str = "abc123",
    user_id: int = 1000,
    submitted_timestamp: str | None = None,
) -> str:
    return generate_submission_fingerprint(
        user_id=user_id,
        beatmap_checksum=beatmap_checksum,
        submitted_timestamp=submitted_timestamp,
        request_hash=input_data.request_hash,
    )


@pytest.mark.asyncio
async def test_happy_path_valid_submission_creates_score(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
) -> None:
    """有効な submission が score record を作成することを検証する。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。
        repos: assertion 用 repository view。

    Returns:
        None。

    Raises:
        AssertionError: score や submission snapshot が期待と異なる場合。

    Constraints:
        replay storage と DB は in-memory fake だけを使う。
    """
    score_repo, submission_repo, _replay_repo = repos

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.user_id == 1000
    assert result.ruleset is Ruleset.OSU
    assert result.playstyle is Playstyle.VANILLA
    assert result.score_id is not None
    assert result.error_reason is None

    # Verify score persisted
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.user_id == 1000
    assert score.passed is True
    assert score.ruleset == Ruleset.OSU
    assert score.playstyle == Playstyle.VANILLA
    assert score.beatmap_status_at_submission == BeatmapRankStatus.RANKED.value

    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(valid_input))
    assert submission is not None
    assert submission.result_snapshot is not None
    assert (
        submission.result_snapshot["beatmap_status_at_submission"]
        == BeatmapRankStatus.RANKED.value
    )


@pytest.mark.asyncio
async def test_completed_submission_requests_performance_calculation(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """受理済み score 永続化後に性能計算 request を作成することを検証する。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: score 保存や性能計算 command が期待と異なる場合。

    Constraints:
        性能計算 request は score 永続化後に一度だけ送る。
    """
    score_repo, _submission_repo, _replay_repo = repos
    performance_request = RecordingPerformanceCalculationRequest()
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=performance_request,
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_perf_request:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert await score_repo.get_by_id(result.score_id) is not None
    assert performance_request.commands == [
        RequestPerformanceCalculationCommand(
            score_id=result.score_id,
            calculator_name="test-calculator",
            calculator_version="1.2.3",
            requested_at=input_data.submitted_at,
        )
    ]


@pytest.mark.asyncio
async def test_completed_submission_waits_for_performance_response_after_request(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """性能 response を組み立てる前に計算 request を送ることを検証する。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: 性能計算 request と response query の順序が期待と異なる場合。

    Constraints:
        request が成功した accepted score だけ performance response を待機する。
    """
    score_repo, _submission_repo, _replay_repo = repos
    performance_request = RecordingPerformanceCalculationRequest()
    performance_response = RecordingPerformanceResponseQuery(
        PerformanceSubmitResponse(
            state=PerformanceSubmitResponseState.COMPLETED,
            stable_pp=248,
        )
    )
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=performance_request,
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
        performance_response_query=performance_response,
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_perf_wait:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert await score_repo.get_by_id(result.score_id) is not None
    assert performance_request.commands[0].score_id == result.score_id
    assert performance_response.queries == [
        PerformanceSubmitResponseQuery(score_id=result.score_id)
    ]
    assert result.stable_pp == 248


@pytest.mark.asyncio
async def test_performance_wait_response_preserves_cumulative_beatmap_counts(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """性能値待機経由の completed response でも beatmap play/pass count を保持する。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: 連続 submission の beatmap play/pass count が期待と異なる場合。

    Constraints:
        performance response 待機で補完した stable_pp は count 集計を変えない。
    """
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=RecordingPerformanceCalculationRequest(),
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
        performance_response_query=RecordingPerformanceResponseQuery(
            PerformanceSubmitResponse(
                state=PerformanceSubmitResponseState.COMPLETED,
                stable_pp=248,
            )
        ),
    )
    first_input = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_counts_1:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )
    second_input = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_counts_2:0:0:100:10:5:0:0:2:600000:99:1:1"
        ),
        request_hash="different_hash",
        replay_data=b"second_replay_data",
        submitted_at=datetime.now(UTC),
    )

    first = await service.execute(first_input)
    second = await service.execute(second_input)

    assert first.outcome == SubmissionOutcome.COMPLETED
    assert first.beatmap_playcount == 1
    assert first.beatmap_passcount == 1
    assert second.outcome == SubmissionOutcome.COMPLETED
    assert second.beatmap_playcount == 2
    assert second.beatmap_passcount == 2


@pytest.mark.asyncio
async def test_completed_submission_returns_overall_stats_delta(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """送信 response 用に current stats の before/after を返す。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: current stats query や before/after snapshot が期待と異なる場合。

    Constraints:
        stats は submission 前後で同じ ruleset/playstyle を query する。
    """
    current_stats_query = RecordingCurrentUserStatsQuery(
        (
            UserCurrentStats(
                user_id=1000,
                pp=Decimal("122.4"),
                accuracy=0.9567,
                global_rank=2,
                play_count=7,
                ranked_score=400_000,
                total_score=900_000,
            ),
            UserCurrentStats(
                user_id=1000,
                pp=Decimal("248.5"),
                accuracy=0.9876,
                global_rank=1,
                play_count=8,
                ranked_score=500_000,
                total_score=1_400_000,
            ),
        )
    )
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=RecordingPerformanceCalculationRequest(),
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
        performance_response_query=RecordingPerformanceResponseQuery(
            PerformanceSubmitResponse(
                state=PerformanceSubmitResponseState.COMPLETED,
                stable_pp=248,
            )
        ),
        current_user_stats_query=current_stats_query,
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_overall_delta:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.overall_stats_before is not None
    assert result.overall_stats_before.global_rank == 2
    assert result.overall_stats_before.ranked_score == 400_000
    assert result.overall_stats_before.total_score == 900_000
    assert result.overall_stats_before.accuracy == 0.9567
    assert result.overall_stats_before.pp == Decimal("122.4")
    assert result.overall_stats_after is not None
    assert result.overall_stats_after.global_rank == 1
    assert result.overall_stats_after.ranked_score == 500_000
    assert result.overall_stats_after.total_score == 1_400_000
    assert result.overall_stats_after.accuracy == 0.9876
    assert result.overall_stats_after.pp == Decimal("248.5")
    assert current_stats_query.queries == [
        CurrentUserStatsQueryInput(
            user_ids=(1000,),
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
        ),
        CurrentUserStatsQueryInput(
            user_ids=(1000,),
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
        ),
    ]


@pytest.mark.asyncio
async def test_completed_submission_returns_beatmap_rank_delta(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """送信 response 用に beatmap rank の before/after を返す。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: beatmap rank delta や rank query が期待と異なる場合。

    Constraints:
        rank query は submission 前後で同じ beatmap/ruleset/playstyle を使う。
    """
    beatmap_rank_query = RecordingBeatmapPersonalBestRankQuery((4, 2))
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=RecordingPerformanceCalculationRequest(),
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
        performance_response_query=RecordingPerformanceResponseQuery(
            PerformanceSubmitResponse(
                state=PerformanceSubmitResponseState.COMPLETED,
                stable_pp=248,
            )
        ),
        beatmap_personal_best_rank_query=beatmap_rank_query,
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_rank_delta:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.beatmap_rank_delta == BeatmapRankDelta(before=4, after=2)
    assert beatmap_rank_query.queries == [
        BeatmapPersonalBestRankQueryInput(
            user_id=1000,
            beatmap_id=1,
            beatmap_checksum="abc123",
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
        ),
        BeatmapPersonalBestRankQueryInput(
            user_id=1000,
            beatmap_id=1,
            beatmap_checksum="abc123",
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
        ),
    ]


@pytest.mark.asyncio
async def test_retryable_performance_response_keeps_score_accepted_without_rejecting(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """性能計算 pending が retryable response でも score を durable に残す。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: retryable result、score 保存、submission state が期待と異なる場合。

    Constraints:
        性能計算待ちの retryable は score 永続化を巻き戻さない。
    """
    score_repo, submission_repo, _replay_repo = repos
    performance_response = RecordingPerformanceResponseQuery(
        PerformanceSubmitResponse(
            state=PerformanceSubmitResponseState.RETRYABLE,
            stable_pp=None,
        )
    )
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=RecordingPerformanceCalculationRequest(),
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
        performance_response_query=performance_response,
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_perf_retryable:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.RETRYABLE
    assert result.score_id is not None
    assert result.error_reason == "performance_calculation_pending"
    assert await score_repo.get_by_id(result.score_id) is not None
    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input_data))
    assert submission is not None
    assert submission.state == "completed"


@pytest.mark.asyncio
async def test_completed_performance_pp_is_result_only_not_submission_snapshot(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """安定版 PP が response 専用値で submission snapshot に残らないことを検証する。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: response の pp や persisted snapshot が期待と異なる場合。

    Constraints:
        stable_pp は legacy response 用の派生値で、canonical snapshot には保存しない。
    """
    _score_repo, submission_repo, _replay_repo = repos
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=RecordingPerformanceCalculationRequest(),
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
        performance_response_query=RecordingPerformanceResponseQuery(
            PerformanceSubmitResponse(
                state=PerformanceSubmitResponseState.COMPLETED,
                stable_pp=321,
            )
        ),
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_perf_snapshot:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.stable_pp == 321
    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input_data))
    assert submission is not None
    assert submission.result_snapshot is not None
    assert "pp" not in submission.result_snapshot
    assert "stable_pp" not in submission.result_snapshot


@pytest.mark.asyncio
async def test_performance_calculation_request_failure_keeps_completed_response(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """性能計算 request 失敗でも accepted submission を completed として返す。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: request 失敗時の result、log、response query が期待と異なる場合。

    Constraints:
        性能計算 request が失敗した後は performance response query に入らない。
    """
    performance_request = RecordingPerformanceCalculationRequest(fail=True)
    performance_response = RecordingPerformanceResponseQuery(
        PerformanceSubmitResponse(
            state=PerformanceSubmitResponseState.COMPLETED,
            stable_pp=248,
        )
    )
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=performance_request,
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
        performance_response_query=performance_response,
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_perf_failure:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    with structlog.testing.capture_logs() as logs:
        result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert result.stable_pp is None
    assert len(performance_request.commands) == 1
    assert performance_response.queries == []
    entries = [
        entry for entry in logs if entry["event"] == "score_performance_calculation_request_failed"
    ]
    assert len(entries) == 1
    assert entries[0]["score_id"] == result.score_id
    assert entries[0]["error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_client_server_grade_discrepancy_is_preserved(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
) -> None:
    """クライアントと server の grade mismatch を診断用に log と snapshot へ残す。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。
        repos: assertion 用 repository view。

    Returns:
        None。

    Raises:
        AssertionError: discrepancy log や submission snapshot が期待と異なる場合。

    Constraints:
        grade mismatch は rejection ではなく diagnostic data として保存する。
    """
    _score_repo, submission_repo, _replay_repo = repos

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            _score_payload(
                "abc123:test_user:online_grade_discrepancy:",
                "300:0:0:0:0:0:1000000:500:1:D:0:1:0:",
                "20240101:b20240101:client_checksum",
            )
        ),
    )

    with structlog.testing.capture_logs() as cap_logs:
        result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    submission = await submission_repo.get_by_fingerprint(
        _fingerprint_for(input_data, submitted_timestamp="20240101")
    )
    assert submission is not None
    assert submission.result_snapshot is not None
    assert submission.result_snapshot["grade_discrepancy"] == {
        "client_grade": "D",
        "server_grade": "X",
    }

    discrepancy_log = next(
        entry for entry in cap_logs if entry["event"] == "score_grade_discrepancy"
    )
    assert discrepancy_log["client_grade"] == "D"
    assert discrepancy_log["server_grade"] == "X"


@pytest.mark.asyncio
async def test_failed_play_handling(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
) -> None:
    """失敗 play (passed=0) を score として保存する。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。
        repos: assertion 用 repository view。

    Returns:
        None。

    Raises:
        AssertionError: failed play の outcome や persisted score が期待と異なる場合。

    Constraints:
        passed=0 は validation reject ではなく保存対象の score として扱う。
    """
    score_repo, _, _ = repos
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_2:0:0:50:10:5:0:0:10:200000:40:0:0"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.passed is False


@pytest.mark.asyncio
async def test_failed_play_without_replay_is_accepted_without_blob_write(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    blob_storage: StubBlobStorageService,
) -> None:
    """失敗 play は replay data なしでも保存できる。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        blob_storage: replay storage fake。

    Returns:
        None。

    Raises:
        AssertionError: failed play 保存や blob write 記録が期待と異なる場合。

    Constraints:
        failed play の replay data 欠落は blob storage write を発生させない。
    """
    score_repo, _, _ = repos
    input_without_replay = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            _score_payload(
                "1000:test_user:abc123:online_checksum_failed_no_replay:",
                "0:0:50:10:5:0:0:10:200000:40:0:0",
            )
        ),
        replay_data=None,
        fail_time_ms=42_000,
    )

    result = await service.execute(input_without_replay)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.passed is False
    assert blob_storage.writes == []


@pytest.mark.asyncio
async def test_passed_play_without_replay_is_accepted_without_blob_write(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    blob_storage: StubBlobStorageService,
) -> None:
    """成功 play でも replay data がなければ attachment なし score を作る。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        blob_storage: replay storage fake。

    Returns:
        None。

    Raises:
        AssertionError: accepted score や blob write 記録が期待と異なる場合。

    Constraints:
        replay data がない successful play は attachment なしで完了させる。
    """
    score_repo, _, _ = repos
    input_without_replay = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            _score_payload(
                "1000:test_user:abc123:online_checksum_passed_no_replay:",
                "0:0:100:10:5:0:0:2:500000:99:1:1",
            )
        ),
        replay_data=None,
    )

    result = await service.execute(input_without_replay)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert await score_repo.exists_by_online_checksum("online_checksum_passed_no_replay")
    assert blob_storage.writes == []


@pytest.mark.asyncio
async def test_replay_attachment(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    blob_storage: StubBlobStorageService,
) -> None:
    """リプレイ data を score attachment として保存する。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        blob_storage: replay storage fake。

    Returns:
        None。

    Raises:
        AssertionError: replay checksum、repository、blob storage の状態が期待と異なる場合。

    Constraints:
        replay attachment は replay bytes の sha256 checksum で照合する。
    """
    _, _, replay_repo = repos

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_3:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED

    # Verify replay exists
    assert input_data.replay_data is not None
    replay_checksum = hashlib.sha256(input_data.replay_data).hexdigest()
    assert await replay_repo.exists_by_checksum(replay_checksum)
    assert blob_storage.writes == [input_data.replay_data]
    assert blob_storage.stored[0].sha256 == replay_checksum


@pytest.mark.asyncio
async def test_score_submit_fallback_warmup_runs_before_replay_blob_storage(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """受理済み submission は warmup 結果を診断扱いにして replay 保存前に warm する。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: warmup と blob storage の呼び出し順序や request が期待と異なる場合。

    Constraints:
        fallback warmup failure は accepted submission の保存を妨げない。
    """
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events, outcome=BeatmapFileWarmupOutcome.FAILED)
    blob_storage = RecordingBlobStorageService(events)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        blob_storage,
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_warmup:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
        beatmap_id=42,
    )
    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.beatmap_id == 42
    assert events == ["warmup", "blob_storage"]
    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_SCORE_SUBMIT_FALLBACK,
            user_id=1000,
            beatmap_id=42,
            checksum_md5="abc123",
        )
    ]


@pytest.mark.asyncio
async def test_score_submit_accepts_file_pending_and_logs_fallback_warmup(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """譜面 file pending は診断扱いにして accepted response shape を保つ。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: accepted response や fallback warmup log が期待と異なる場合。

    Constraints:
        beatmap file pending は user-visible reject ではなく diagnostic log に留める。
    """
    warmup = RequestBeatmapFileWarmupUseCase(
        FakeWarmupResolver(
            file_status=BeatmapFileState.PENDING_FETCH,
            reason="pending_fetch",
        )
    )
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_warmup_pending:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    with structlog.testing.capture_logs() as logs:
        result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.error_reason is None
    assert result.score_id is not None
    assert result.beatmap_id == 1

    warmup_events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(warmup_events) == 1
    warmup_event = warmup_events[0]
    assert warmup_event["entrance"] == "stable_score_submit_fallback"
    assert warmup_event["outcome"] == "requested"
    assert warmup_event["beatmap_id"] == 1
    assert warmup_event["checksum_md5"] is None
    assert warmup_event["reason"] == "pending_fetch"


@pytest.mark.asyncio
async def test_score_submit_fallback_warmup_precedes_retryable_replay_storage_failure(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """リプレイ storage の retryable failure は fallback warmup request 後に発生する。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: retryable result、event 順序、warmup request が期待と異なる場合。

    Constraints:
        replay blob storage failure は fallback warmup request の後に扱う。
    """
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events)
    blob_storage = RecordingBlobStorageService(events, fail_writes=True)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        blob_storage,
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_warmup_retry:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.RETRYABLE
    assert result.error_reason == "replay_blob_store_failed"
    assert events == ["warmup", "blob_storage"]
    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_SCORE_SUBMIT_FALLBACK,
            user_id=1000,
            beatmap_id=1,
            checksum_md5="abc123",
        )
    ]


@pytest.mark.asyncio
async def test_score_submit_terminal_reject_does_not_request_fallback_warmup(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """ヒット validation 前の terminal reject は fallback warmup を起動しない。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: terminal reject result や warmup 未実行状態が期待と異なる場合。

    Constraints:
        validation reject は beatmap file fallback warmup の対象外にする。
    """
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_warmup_reject:0:0:0:0:0:0:0:0:500000:0:1:1"
        ),
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "validation_failed" in result.error_reason
    assert events == []
    assert warmup.requests == []


@pytest.mark.asyncio
async def test_online_checksum_duplicate_rejection(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
) -> None:
    """重複 online checksum は別 submission として terminal reject する。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。
        repos: assertion 用 repository view。

    Returns:
        None。

    Raises:
        AssertionError: duplicate result や terminal rejected snapshot が期待と異なる場合。

    Constraints:
        fingerprint が異なっても online checksum が同じなら重複として扱う。
    """
    _score_repo, submission_repo, _ = repos

    parsed_score = make_test_parsed_score(
        "1000:test_user:abc123:duplicate_checksum:0:0:100:10:5:0:0:2:500000:99:1:1"
    )

    # First submission
    input1 = replace(valid_input, parsed_score=parsed_score, request_hash="duplicate-hash-1")
    result1 = await service.execute(input1)
    assert result1.outcome == SubmissionOutcome.COMPLETED

    # Second submission (different fingerprint but same online checksum)
    input2 = ParsedSubmissionInput(
        parsed_score=parsed_score,
        request_hash="duplicate-hash-2",
        opaque_field_hashes=valid_input.opaque_field_hashes,
        decrypt_latency_ms=valid_input.decrypt_latency_ms,
        replay_data=valid_input.replay_data,
        password_md5=valid_input.password_md5,
        fail_time_ms=valid_input.fail_time_ms,
        osu_version=valid_input.osu_version,
        beatmap_id=valid_input.beatmap_id,
        submitted_at=datetime.now(UTC),  # Different timestamp
    )
    result2 = await service.execute(input2)
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.score_id is None
    assert result2.error_reason == "duplicate_online_checksum"
    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input2))
    assert submission is not None
    assert submission.state == "terminal_rejected"
    assert submission.result_snapshot == {"error_reason": "duplicate_online_checksum"}


@pytest.mark.asyncio
async def test_performance_integration_preserves_duplicate_terminal_rejects(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """重複 checksum の terminal reject は performance response を待機しない。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: duplicate result、performance query、submission snapshot が
            期待と異なる場合。

    Constraints:
        terminal rejected duplicate submission は performance response wait を開始しない。
    """
    _score_repo, submission_repo, _replay_repo = repos
    performance_request = RecordingPerformanceCalculationRequest()
    performance_response = RecordingPerformanceResponseQuery(
        PerformanceSubmitResponse(
            state=PerformanceSubmitResponseState.COMPLETED,
            stable_pp=111,
        )
    )
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=performance_request,
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
        performance_response_query=performance_response,
    )

    duplicate_online_score = make_test_parsed_score(
        "1000:test_user:abc123:duplicate_perf_online:0:0:100:10:5:0:0:2:500000:99:1:1"
    )
    online_first = replace(
        valid_input,
        parsed_score=duplicate_online_score,
        request_hash="online-hash-1",
        replay_data=b"online-duplicate-replay-1",
    )
    online_second = replace(
        valid_input,
        parsed_score=duplicate_online_score,
        request_hash="online-hash-2",
        replay_data=b"online-duplicate-replay-2",
    )
    replay_first = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:perf_replay_online_1:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
        request_hash="replay-hash-1",
        replay_data=b"same-performance-replay",
    )
    replay_second = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:perf_replay_online_2:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
        request_hash="replay-hash-2",
        replay_data=b"same-performance-replay",
    )

    online_result1 = await service.execute(online_first)
    online_result2 = await service.execute(online_second)
    replay_result1 = await service.execute(replay_first)
    replay_result2 = await service.execute(replay_second)

    assert online_result1.outcome == SubmissionOutcome.COMPLETED
    assert online_result1.score_id is not None
    assert online_result1.stable_pp == 111
    assert online_result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert online_result2.score_id is None
    assert online_result2.error_reason == "duplicate_online_checksum"
    assert replay_result1.outcome == SubmissionOutcome.COMPLETED
    assert replay_result1.score_id is not None
    assert replay_result1.stable_pp == 111
    assert replay_result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert replay_result2.score_id is None
    assert replay_result2.error_reason == "duplicate_replay_checksum"
    assert performance_response.queries == [
        PerformanceSubmitResponseQuery(score_id=online_result1.score_id),
        PerformanceSubmitResponseQuery(score_id=online_result1.score_id),
    ]
    assert [command.score_id for command in performance_request.commands] == [
        online_result1.score_id,
        replay_result1.score_id,
    ]

    online_submission = await submission_repo.get_by_fingerprint(_fingerprint_for(online_second))
    replay_submission = await submission_repo.get_by_fingerprint(_fingerprint_for(replay_second))
    assert online_submission is not None
    assert online_submission.state == "terminal_rejected"
    assert online_submission.result_snapshot == {"error_reason": "duplicate_online_checksum"}
    assert replay_submission is not None
    assert replay_submission.state == "terminal_rejected"
    assert replay_submission.result_snapshot == {"error_reason": "duplicate_replay_checksum"}


@pytest.mark.asyncio
async def test_online_checksum_duplicate_rejection_ignores_fallback_warmup_failure(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """ウォームアップ failure 時も重複 online checksum は terminal reject のままにする。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: duplicate result、warmup 呼び出し、snapshot が期待と異なる場合。

    Constraints:
        fallback warmup failure は duplicate online checksum の rejection 理由を上書きしない。
    """
    _score_repo, submission_repo, _ = repos
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events, outcome=BeatmapFileWarmupOutcome.FAILED)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    parsed_score = make_test_parsed_score(
        "1000:test_user:abc123:duplicate_checksum_with_warmup:0:0:100:10:5:0:0:2:500000:99:1:1"
    )
    input1 = replace(
        valid_input,
        parsed_score=parsed_score,
        replay_data=b"online_duplicate_replay_1",
        request_hash="hash1",
    )
    input2 = replace(
        valid_input,
        parsed_score=parsed_score,
        replay_data=b"online_duplicate_replay_2",
        request_hash="hash2",
    )

    result1 = await service.execute(input1)
    result2 = await service.execute(input2)

    assert result1.outcome == SubmissionOutcome.COMPLETED
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.score_id is None
    assert result2.error_reason == "duplicate_online_checksum"
    assert len(warmup.requests) == 2
    assert events == ["warmup", "warmup"]

    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input2))
    assert submission is not None
    assert submission.state == "terminal_rejected"
    assert submission.result_snapshot == {"error_reason": "duplicate_online_checksum"}


@pytest.mark.asyncio
async def test_online_checksum_duplicate_rejection_ignores_file_pending_warmup(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """ファイル warmup pending 時も重複 online checksum は terminal reject のままにする。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: duplicate result、warmup log、snapshot が期待と異なる場合。

    Constraints:
        file warmup pending は duplicate online checksum の terminal reject を変えない。
    """
    _score_repo, submission_repo, _ = repos
    warmup = RequestBeatmapFileWarmupUseCase(
        FakeWarmupResolver(
            file_status=BeatmapFileState.PENDING_FETCH,
            reason="pending_fetch",
        )
    )
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    parsed_score = make_test_parsed_score(
        _score_payload(
            "1000:test_user:abc123:duplicate_checksum_pending_warmup:0:0:100:10:5:0:0:2:",
            "500000:99:1:1",
        )
    )
    input1 = replace(
        valid_input,
        parsed_score=parsed_score,
        replay_data=b"online_pending_replay_1",
        request_hash="hash1",
    )
    input2 = replace(
        valid_input,
        parsed_score=parsed_score,
        replay_data=b"online_pending_replay_2",
        request_hash="hash2",
    )

    with structlog.testing.capture_logs() as logs:
        result1 = await service.execute(input1)
        result2 = await service.execute(input2)

    assert result1.outcome == SubmissionOutcome.COMPLETED
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.score_id is None
    assert result2.error_reason == "duplicate_online_checksum"

    warmup_events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert [entry["outcome"] for entry in warmup_events] == ["requested", "requested"]
    assert [entry["reason"] for entry in warmup_events] == ["pending_fetch", "pending_fetch"]

    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input2))
    assert submission is not None
    assert submission.state == "terminal_rejected"
    assert submission.result_snapshot == {"error_reason": "duplicate_online_checksum"}


@pytest.mark.asyncio
async def test_replay_checksum_duplicate_rejection(
    service: ProcessScoreSubmissionUseCase,
    repos: ScoreRepositoryViews,
) -> None:
    """重複 replay checksum を terminal reject する。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        repos: assertion 用 repository view。

    Returns:
        None。

    Raises:
        AssertionError: duplicate replay checksum の result が期待と異なる場合。

    Constraints:
        online checksum が異なっても replay checksum が同じなら重複として扱う。
    """
    _, _, _replay_repo = repos

    # First submission
    input1 = make_test_submission_input(
        payload="1000:test_user:abc123:online_1:0:0:100:10:5:0:0:2:500000:99:1:1",
        request_hash="hash1",
        replay_data=b"same_replay_data",
    )
    result1 = await service.execute(input1)
    assert result1.outcome == SubmissionOutcome.COMPLETED

    # Second submission (same replay)
    input2 = make_test_submission_input(
        payload="1000:test_user:abc123:online_2:0:0:100:10:5:0:0:2:500000:99:1:1",
        request_hash="hash2",
        replay_data=b"same_replay_data",
    )
    result2 = await service.execute(input2)
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.error_reason is not None
    assert "duplicate_replay_checksum" in result2.error_reason


@pytest.mark.asyncio
async def test_replay_checksum_duplicate_rejection_ignores_fallback_warmup_failure(
    uow_factory: InMemoryUnitOfWorkFactory,
    repos: ScoreRepositoryViews,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """ウォームアップ failure 時も重複 replay checksum は terminal reject のままにする。

    Args:
        uow_factory: test 用 Unit of Work factory。
        repos: assertion 用 repository view。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: duplicate result、warmup 呼び出し、snapshot が期待と異なる場合。

    Constraints:
        fallback warmup failure は duplicate replay checksum の rejection 理由を上書きしない。
    """
    _score_repo, submission_repo, _replay_repo = repos
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events, outcome=BeatmapFileWarmupOutcome.FAILED)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    input1 = make_test_submission_input(
        payload=("1000:test_user:abc123:online_warmup_replay_1:0:0:100:10:5:0:0:2:500000:99:1:1"),
        request_hash="hash1",
        replay_data=b"same_warmup_replay_data",
    )
    input2 = make_test_submission_input(
        payload=("1000:test_user:abc123:online_warmup_replay_2:0:0:100:10:5:0:0:2:500000:99:1:1"),
        request_hash="hash2",
        replay_data=b"same_warmup_replay_data",
    )

    result1 = await service.execute(input1)
    result2 = await service.execute(input2)

    assert result1.outcome == SubmissionOutcome.COMPLETED
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.score_id is None
    assert result2.error_reason == "duplicate_replay_checksum"
    assert len(warmup.requests) == 2
    assert events == ["warmup", "warmup"]

    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input2))
    assert submission is not None
    assert submission.state == "terminal_rejected"
    assert submission.result_snapshot == {"error_reason": "duplicate_replay_checksum"}


@pytest.mark.asyncio
async def test_submission_fingerprint_idempotency(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """同じ request content は保存済み result を cache として返す。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。

    Returns:
        None。

    Raises:
        AssertionError: cached result の outcome や score id が期待と異なる場合。

    Constraints:
        server receive time が変わっても request fingerprint が同じなら同じ result を返す。
    """
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_idem:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    # First submission
    result1 = await service.execute(input_data)
    assert result1.outcome == SubmissionOutcome.COMPLETED
    score_id1 = result1.score_id

    resent_input = replace(input_data, submitted_at=datetime.now(UTC))

    # Second submission has a different server receive time but identical request content.
    result2 = await service.execute(resent_input)
    assert result2.outcome == SubmissionOutcome.COMPLETED
    assert result2.score_id == score_id1  # Same score ID


@pytest.mark.asyncio
async def test_same_fingerprint_retry_rebuilds_response_from_existing_score_performance(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """同じ fingerprint の retry は既存 score の current performance を読む。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        repos: assertion 用 repository view。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: cached result、performance query、submission snapshot が期待と異なる場合。

    Constraints:
        same-fingerprint retry は新規計算 request を増やさず既存 score の response を再構築する。
    """
    _score_repo, submission_repo, _replay_repo = repos
    performance_request = RecordingPerformanceCalculationRequest()
    performance_response = RecordingPerformanceResponseQuery(
        PerformanceSubmitResponse(
            state=PerformanceSubmitResponseState.COMPLETED,
            stable_pp=456,
        )
    )
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=performance_request,
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
        performance_response_query=performance_response,
    )
    replayless_input = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_idem_pp:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
        replay_data=None,
    )

    result1 = await service.execute(replayless_input)
    result2 = await service.execute(replace(replayless_input, submitted_at=datetime.now(UTC)))

    assert result1.outcome == SubmissionOutcome.COMPLETED
    assert result1.score_id is not None
    assert result2.outcome == SubmissionOutcome.COMPLETED
    assert result2.score_id == result1.score_id
    assert result2.stable_pp == 456
    assert performance_request.commands == [
        RequestPerformanceCalculationCommand(
            score_id=result1.score_id,
            calculator_name="test-calculator",
            calculator_version="1.2.3",
            requested_at=replayless_input.submitted_at,
        )
    ]
    assert performance_response.queries == [
        PerformanceSubmitResponseQuery(score_id=result1.score_id),
        PerformanceSubmitResponseQuery(score_id=result1.score_id),
    ]
    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(replayless_input))
    assert submission is not None
    assert submission.result_snapshot is not None
    assert "pp" not in submission.result_snapshot
    assert "stable_pp" not in submission.result_snapshot


@pytest.mark.asyncio
async def test_submission_fingerprint_idempotency_ignores_fallback_warmup_failure(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """代替 warmup failure は同じ fingerprint の cached result を変えない。

    Args:
        uow_factory: test 用 Unit of Work factory。
        valid_input: valid な command input。
        beatmap_resolver: eligible beatmap を返す fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: cached result や warmup 呼び出し記録が期待と異なる場合。

    Constraints:
        fallback warmup failure は same-fingerprint cached result の error_reason を変えない。
    """
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events, outcome=BeatmapFileWarmupOutcome.FAILED)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )
    replayless_input = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_idem_warmup:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
        replay_data=None,
    )

    result1 = await service.execute(replayless_input)
    result2 = await service.execute(replace(replayless_input, submitted_at=datetime.now(UTC)))

    assert result1.outcome == SubmissionOutcome.COMPLETED
    assert result1.score_id is not None
    assert result2.outcome == SubmissionOutcome.COMPLETED
    assert result2.error_reason is None
    assert result2.score_id == result1.score_id
    assert len(warmup.requests) == 2
    assert events == ["warmup", "warmup"]


@pytest.mark.asyncio
async def test_in_progress_retry_returns_accepted_pending(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
) -> None:
    """処理中 state の同じ fingerprint は accepted_pending を返す。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。
        repos: assertion 用 repository view。

    Returns:
        None。

    Raises:
        AssertionError: in-progress retry result が期待と異なる場合。

    Constraints:
        processing state の submission は二重実行せず accepted_pending として返す。
    """
    _score_repo, submission_repo, _replay_repo = repos

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_pending:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )
    fingerprint = _fingerprint_for(input_data)
    _ = await submission_repo.create(
        ScoreSubmission(
            id=None,
            fingerprint=fingerprint,
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=input_data.submitted_at,
            state=ScoreSubmissionState.PROCESSING,
            result_snapshot=None,
        )
    )

    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.ACCEPTED_PENDING
    assert result.error_reason == "accepted_pending"


@pytest.mark.asyncio
async def test_authorization_failure_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """認可 failure は terminal reject を返す。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。

    Returns:
        None。

    Raises:
        AssertionError: invalid credential の terminal reject result が期待と異なる場合。

    Constraints:
        認可 failure は score 保存前に terminal reject として表現する。
    """

    # Invalid password
    invalid_input = ParsedSubmissionInput(
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_auth:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
        request_hash=valid_input.request_hash,
        opaque_field_hashes=valid_input.opaque_field_hashes,
        decrypt_latency_ms=valid_input.decrypt_latency_ms,
        replay_data=valid_input.replay_data,
        password_md5="invalid_md5",
        fail_time_ms=valid_input.fail_time_ms,
        osu_version=valid_input.osu_version,
        beatmap_id=valid_input.beatmap_id,
        submitted_at=valid_input.submitted_at,
    )

    result = await service.execute(invalid_input)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "authorization_failed" in result.error_reason


@pytest.mark.asyncio
async def test_beatmap_ineligibility_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """不適格 beatmap は terminal reject を返す。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。
        beatmap_resolver: ineligible beatmap を返すよう変更する fake resolver。

    Returns:
        None。

    Raises:
        AssertionError: ineligible beatmap の terminal reject result が期待と異なる場合。

    Constraints:
        beatmap eligibility failure は score 保存前に terminal reject として表現する。
    """

    beatmap_resolver.eligibility = _ineligible_beatmap()

    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_elig:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )
    result = await service.execute(input_data)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "beatmap_ineligible" in result.error_reason


@pytest.mark.asyncio
async def test_validation_failure_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """検証 failure は terminal reject を返す。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。

    Returns:
        None。

    Raises:
        AssertionError: invalid score payload の terminal reject result が期待と異なる場合。

    Constraints:
        hit validation failure は retryable ではなく terminal reject として扱う。
    """
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_val:0:0:0:0:0:0:0:0:500000:0:1:1"
        ),
    )

    result = await service.execute(input_data)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "validation_failed" in result.error_reason


@pytest.mark.asyncio
async def test_metrics_logged_on_success(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
) -> None:
    """成功 submission では metrics を log に出す。

    Args:
        service: test 対象の ProcessScoreSubmissionUseCase。
        valid_input: valid な command input。

    Returns:
        None。

    Raises:
        AssertionError: success metrics log や latency 値が期待と異なる場合。

    Constraints:
        successful submission の latency fields は numeric metrics として出力する。
    """
    input_data = replace(
        valid_input,
        parsed_score=make_test_parsed_score(
            "1000:test_user:abc123:online_checksum_metrics:0:0:100:10:5:0:0:2:500000:99:1:1"
        ),
    )

    with structlog.testing.capture_logs() as cap_logs:
        result = await service.execute(input_data)
    assert result.outcome == SubmissionOutcome.COMPLETED

    logged_metrics = next(
        entry for entry in cap_logs if entry["event"] == "score_submission_completed"
    )
    duration_ms = cast("object", logged_metrics["duration_ms"])
    decrypt_latency_ms = cast("object", logged_metrics["decrypt_latency_ms"])
    beatmap_latency_ms = cast("object", logged_metrics["beatmap_latency_ms"])
    db_latency_ms = cast("object", logged_metrics["db_latency_ms"])
    assert isinstance(duration_ms, float)
    assert isinstance(decrypt_latency_ms, float)
    assert isinstance(beatmap_latency_ms, float)
    assert isinstance(db_latency_ms, float)

    assert duration_ms > 0
    assert decrypt_latency_ms >= 0
    assert beatmap_latency_ms >= 0
    assert db_latency_ms > 0
