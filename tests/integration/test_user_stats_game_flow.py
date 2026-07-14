from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import final

import pytest

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.identity.authentication import LoginResponse
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.domain.scores import Grade, ModCombination, Playstyle, Ruleset, Score
from osu_server.domain.scores.performance import FormulaProfile
from osu_server.infrastructure.performance import (
    PerformanceCalculatorCompleted,
    PerformanceCalculatorInput,
)
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.performance_completion_signal import (
    InMemoryPerformanceCompletionSignal,
)
from osu_server.infrastructure.state.memory.stable_user_status_store import (
    InMemoryStableUserStatusStore,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    CreateScorePerformanceCalculation,
)
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.friends import (
    InMemoryFriendRelationshipQueryRepository,
)
from osu_server.repositories.memory.queries.user_stats import InMemoryUserStatsQueryRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.beatmaps import (
    BeatmapFileWarmupOutcome,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
)
from osu_server.services.commands.scores.performance import (
    ExecutePerformanceCalculationCommand,
    ExecutePerformanceCalculationOutcome,
    ExecutePerformanceCalculationUseCase,
    PerformanceBeatmapFileProvenance,
    PerformanceBeatmapFileQuery,
    PerformanceBeatmapFileReady,
    PerformanceBeatmapFileResult,
)
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListVisibleChannelsQuery,
)
from osu_server.services.queries.identity.friend_relationships import ListFriendIdsQuery
from osu_server.services.queries.identity.online_sessions import ListActiveSessionsQueryUseCase
from osu_server.services.queries.scores import CurrentUserStatsQuery, CurrentUserStatsQueryInput
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.handlers.status import StatusChangeHandlers
from osu_server.transports.stable.bancho.protocol.c2s import (
    status_change_payload,
)
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import user_stats
from osu_server.transports.stable.bancho.protocol.types import StatusUpdate
from osu_server.transports.stable.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)
from osu_server.transports.stable.bancho.workflows.polling import (
    PollingWorkflow,
    PollingWorkflowInput,
)

_NOW = datetime(2026, 6, 28, 0, 0, 0, tzinfo=UTC)
_VISIBLE_ROLE_ID = 1
_USER_ID = 1000
_TOKEN = "test-token"
_CALCULATOR_NAME = "rosu-pp-py"
_CALCULATOR_VERSION = "4.0.2"
_FORMULA_PROFILE = FormulaProfile.VANILLA_RANKED
_HEADER = struct.Struct("<HBI")
_LOW_SCORE_ACCURACY = 0.95
_HIGH_SCORE_ACCURACY = 0.9876
_MANIA_SCORE_ACCURACY = 0.99


@pytest.mark.asyncio
async def test_current_stats_flow_from_score_timing_to_stable_packets() -> None:
    factory = InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())
    _seed_visible_user(factory)
    low_score_id = await _persist_score(
        factory,
        _score(
            score_id=1,
            score=100_000,
            accuracy=_LOW_SCORE_ACCURACY,
            play_time_seconds=40,
        ),
    )
    high_score_id = await _persist_score(
        factory,
        _score(
            score_id=2,
            score=500_000,
            accuracy=_HIGH_SCORE_ACCURACY,
            play_time_seconds=83,
        ),
    )
    _ = await _execute_current_performance(factory, score_id=low_score_id, pp=Decimal("50"))
    _ = await _execute_current_performance(
        factory,
        score_id=high_score_id,
        pp=Decimal("122.5"),
    )
    query = CurrentUserStatsQuery(repository=InMemoryUserStatsQueryRepository(factory))
    query_result = await query.execute(CurrentUserStatsQueryInput(user_ids=(_USER_ID,)))
    current_stats = query_result.get(_USER_ID)
    assert current_stats is not None
    assert current_stats.pp == Decimal("122.5")
    assert current_stats.accuracy == _HIGH_SCORE_ACCURACY
    assert current_stats.global_rank == 1
    assert current_stats.play_count == 2
    assert current_stats.ranked_score == 500_000
    assert current_stats.total_score == 600_000
    assert current_stats.play_time_seconds == 123

    expected_packet = user_stats(
        user_id=_USER_ID,
        status=0,
        status_text="",
        beatmap_md5="",
        mods=0,
        play_mode=0,
        beatmap_id=0,
        ranked_score=500_000,
        accuracy=_HIGH_SCORE_ACCURACY,
        play_count=2,
        total_score=600_000,
        rank=1,
        pp=123,
    )
    session_store = InMemorySessionStore()
    await session_store.create(_USER_ID, _TOKEN, _session_data())
    login_builder = _login_response_builder(factory, session_store, query)
    login_stream = await login_builder.build(_login_response())
    assert expected_packet in login_stream

    packet_queue = InMemoryPacketQueue()
    dispatcher = PacketDispatcher()
    StatusChangeHandlers(
        beatmap_file_warmup=_NoopBeatmapFileWarmupUseCase(),
        current_user_stats_query=query,
        packet_queue=packet_queue,
    ).register_all(dispatcher)
    polling = PollingWorkflow(
        session_store=session_store,
        packet_queue=packet_queue,
        packet_dispatcher=dispatcher,
    )

    response = await polling.execute(
        PollingWorkflowInput(
            token=_TOKEN,
            body=_c2s_packet(ClientPacketID.REQUEST_STATUS, b""),
        )
    )

    assert response.content == expected_packet


@pytest.mark.asyncio
async def test_current_stats_existing_scores_are_scoped_by_ruleset() -> None:
    factory = InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())
    _seed_visible_user(factory)
    osu_score_id = await _persist_score(
        factory,
        _score(
            score_id=10,
            score=100_000,
            accuracy=_LOW_SCORE_ACCURACY,
            play_time_seconds=40,
        ),
    )
    mania_score_id = await _persist_score(
        factory,
        _score(
            score_id=11,
            score=900_000,
            accuracy=_MANIA_SCORE_ACCURACY,
            play_time_seconds=90,
            ruleset=Ruleset.MANIA,
        ),
    )
    _ = await _execute_current_performance(factory, score_id=osu_score_id, pp=Decimal("50"))
    _ = await _execute_current_performance(
        factory,
        score_id=mania_score_id,
        pp=Decimal("250"),
    )
    query = CurrentUserStatsQuery(repository=InMemoryUserStatsQueryRepository(factory))

    osu_result = await query.execute(
        CurrentUserStatsQueryInput(user_ids=(_USER_ID,), ruleset=Ruleset.OSU)
    )
    mania_result = await query.execute(
        CurrentUserStatsQueryInput(user_ids=(_USER_ID,), ruleset=Ruleset.MANIA)
    )

    osu_stats = osu_result.get(_USER_ID)
    mania_stats = mania_result.get(_USER_ID)
    assert osu_stats is not None
    assert mania_stats is not None
    assert osu_stats.pp == Decimal("50")
    assert osu_stats.accuracy == _LOW_SCORE_ACCURACY
    assert osu_stats.play_count == 1
    assert osu_stats.ranked_score == 100_000
    assert mania_stats.pp == Decimal("250")
    assert mania_stats.accuracy == _MANIA_SCORE_ACCURACY
    assert mania_stats.play_count == 1
    assert mania_stats.ranked_score == 900_000


@pytest.mark.asyncio
async def test_stats_request_after_status_change_uses_current_play_mode() -> None:
    factory = InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())
    _seed_visible_user(factory)
    osu_score_id = await _persist_score(
        factory,
        _score(
            score_id=20,
            score=100_000,
            accuracy=_LOW_SCORE_ACCURACY,
            play_time_seconds=40,
        ),
    )
    mania_score_id = await _persist_score(
        factory,
        _score(
            score_id=21,
            score=900_000,
            accuracy=_MANIA_SCORE_ACCURACY,
            play_time_seconds=90,
            ruleset=Ruleset.MANIA,
        ),
    )
    _ = await _execute_current_performance(factory, score_id=osu_score_id, pp=Decimal("50"))
    _ = await _execute_current_performance(
        factory,
        score_id=mania_score_id,
        pp=Decimal("250"),
    )
    query = CurrentUserStatsQuery(repository=InMemoryUserStatsQueryRepository(factory))
    session_store = InMemorySessionStore()
    packet_queue = InMemoryPacketQueue()
    status_store = InMemoryStableUserStatusStore()
    await session_store.create(_USER_ID, _TOKEN, _session_data())
    dispatcher = PacketDispatcher()
    StatusChangeHandlers(
        beatmap_file_warmup=_NoopBeatmapFileWarmupUseCase(),
        stable_user_status_store=status_store,
        current_user_stats_query=query,
        packet_queue=packet_queue,
    ).register_all(dispatcher)
    polling = PollingWorkflow(
        session_store=session_store,
        packet_queue=packet_queue,
        packet_dispatcher=dispatcher,
        stable_user_status_store=status_store,
    )

    response = await polling.execute(
        PollingWorkflowInput(
            token=_TOKEN,
            body=_c2s_packet(ClientPacketID.STATUS_CHANGE, _status_payload(play_mode=3)),
        )
    )

    assert response.content == user_stats(
        user_id=_USER_ID,
        status=2,
        status_text="playing",
        beatmap_md5="a" * 32,
        mods=0,
        play_mode=3,
        beatmap_id=100,
        ranked_score=900_000,
        accuracy=_MANIA_SCORE_ACCURACY,
        play_count=1,
        total_score=900_000,
        rank=1,
        pp=250,
    )


def _seed_visible_user(factory: InMemoryUnitOfWorkFactory) -> None:
    state = factory.snapshot()
    state.roles_by_id[_VISIBLE_ROLE_ID] = Role(
        id=_VISIBLE_ROLE_ID,
        name="Visible",
        permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        position=1,
    )
    state.users_by_id[_USER_ID] = _user()
    state.role_ids_by_user_id[_USER_ID] = {_VISIBLE_ROLE_ID}
    factory.commit_state(state)


async def _persist_score(factory: InMemoryUnitOfWorkFactory, score: Score) -> int:
    async with factory() as uow:
        created = await uow.scores.create(score)
        await uow.commit()
    assert created.id is not None
    return created.id


async def _execute_current_performance(
    factory: InMemoryUnitOfWorkFactory,
    *,
    score_id: int,
    pp: Decimal,
) -> int:
    async with factory() as uow:
        created = await uow.score_performance.create_or_reuse_calculation(
            CreateScorePerformanceCalculation(
                score_id=score_id,
                calculator_name=_CALCULATOR_NAME,
                calculator_version=_CALCULATOR_VERSION,
                formula_profile=_FORMULA_PROFILE,
                requested_at=_NOW,
            )
        )
        await uow.commit()

    assert created.calculation.id is not None
    calculation_id = created.calculation.id
    use_case = ExecutePerformanceCalculationUseCase(
        unit_of_work_factory=factory,
        beatmap_file_provider=_ReadyBeatmapFileProvider(),
        calculator=_FixedPerformanceCalculator(pp),
        completion_signal=InMemoryPerformanceCompletionSignal(),
    )
    result = await use_case.execute(
        ExecutePerformanceCalculationCommand(
            calculation_id=calculation_id,
            claim_owner="test-worker",
            claimed_at=_NOW,
        )
    )

    assert result.outcome is ExecutePerformanceCalculationOutcome.COMPLETED
    assert result.calculation is not None
    assert result.calculation.id == calculation_id
    return calculation_id


@final
class _ReadyBeatmapFileProvider:
    async def provide(
        self,
        query: PerformanceBeatmapFileQuery,
    ) -> PerformanceBeatmapFileResult:
        return PerformanceBeatmapFileReady(
            beatmap_id=query.beatmap_id,
            osu_file_bytes=b"osu file bytes",
            provenance=PerformanceBeatmapFileProvenance(
                beatmap_id=query.beatmap_id,
                beatmap_file_attachment_id=55,
                blob_id=77,
                checksum_md5="a" * 32,
            ),
        )


@final
class _FixedPerformanceCalculator:
    def __init__(self, pp: Decimal) -> None:
        self._pp = pp

    def calculator_name(self) -> str:
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        return _CALCULATOR_VERSION

    def calculate(self, input_data: PerformanceCalculatorInput) -> PerformanceCalculatorCompleted:
        _ = input_data
        return PerformanceCalculatorCompleted(pp=self._pp, star_rating=Decimal("5.0"))


@final
class _NoopBeatmapFileWarmupUseCase:
    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult:
        return BeatmapFileWarmupResult(
            outcome=BeatmapFileWarmupOutcome.SKIPPED_NO_IDENTITY,
            entrance=request.entrance,
            user_id=request.user_id,
            beatmap_id=request.beatmap_id,
            checksum_md5=request.checksum_md5,
            reason=None,
        )


def _login_response_builder(
    factory: InMemoryUnitOfWorkFactory,
    session_store: InMemorySessionStore,
    query: CurrentUserStatsQuery,
) -> LoginResponseBuilder:
    channel_state = InMemoryChannelStateStore()
    channel_repository = InMemoryChannelQueryRepository(factory)
    friend_query_repository = InMemoryFriendRelationshipQueryRepository(factory)
    return LoginResponseBuilder(
        visible_channels_query=ListVisibleChannelsQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        ),
        autojoin_channels_query=ListAutojoinChannelsQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        ),
        friend_ids_query=ListFriendIdsQuery(repository=friend_query_repository),
        active_sessions_query=ListActiveSessionsQueryUseCase(session_store=session_store),
        current_user_stats_query=query,
    )


def _login_response() -> LoginResponse:
    user = _user()
    return LoginResponse(
        token=_TOKEN,
        user=user,
        privileges=Privileges.NORMAL | Privileges.VERIFIED,
        role_ids=(_VISIBLE_ROLE_ID,),
        country=user.country,
        session_data=_session_data(),
    )


def _session_data() -> SessionData:
    return SessionData(
        user_id=_USER_ID,
        username="StatsUser",
        privileges=int(Privileges.NORMAL | Privileges.VERIFIED),
        country="JP",
        osu_version="20231111",
        utc_offset=9,
        display_city=False,
        client_hashes="",
        pm_private=False,
    )


def _user() -> User:
    return User(
        id=_USER_ID,
        username="StatsUser",
        safe_username="statsuser",
        email="stats@example.test",
        password_hash="hash",
        country="JP",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _score(
    *,
    score_id: int,
    score: int,
    accuracy: float,
    play_time_seconds: int,
    ruleset: Ruleset = Ruleset.OSU,
) -> Score:
    return Score(
        id=score_id,
        user_id=_USER_ID,
        beatmap_id=100,
        beatmap_checksum="a" * 32,
        online_checksum=f"{score_id:032x}",
        ruleset=ruleset,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=300,
        n100=20,
        n50=5,
        geki=0,
        katu=0,
        miss=0,
        score=score,
        max_combo=400,
        accuracy=accuracy,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="b20250101",
        submitted_at=_NOW + timedelta(seconds=score_id),
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
        leaderboard_eligible_at_submission=True,
        play_time_seconds=play_time_seconds,
    )


def _status_payload(*, play_mode: int) -> bytes:
    return status_change_payload(
        StatusUpdate(
            status=2,
            status_text="playing",
            beatmap_md5="a" * 32,
            mods=0,
            play_mode=play_mode,
            beatmap_id=100,
        )
    )


def _c2s_packet(packet_id: ClientPacketID, payload: bytes) -> bytes:
    return _HEADER.pack(packet_id.value, 0, len(payload)) + payload
