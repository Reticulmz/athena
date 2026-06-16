"""Dishka provider graph tests for shared and app-only provider groups."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from dishka import AsyncContainer, Scope
from dishka.exceptions import NoFactoryError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from taskiq import AsyncBroker
from tests.factories.config import make_app_config

from osu_server.composition.providers.app import AppProviderGraph
from osu_server.composition.providers.container import make_app_container, make_worker_container
from osu_server.composition.providers.test import (
    TestProviderSet,
    make_in_memory_runtime_provider_set,
    replace_value,
)
from osu_server.composition.providers.worker import WorkerProviderGraph
from osu_server.config import AppConfig
from osu_server.domain.beatmaps import (
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
)
from osu_server.domain.identity.system_users import SystemUserIdentity
from osu_server.domain.scores.performance import FormulaProfilePolicy
from osu_server.infrastructure.crypto import ScoreCryptoService
from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.infrastructure.storage.interfaces import BlobStorageBackend
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.queries.blobs import BlobQueryRepository
from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository
from osu_server.repositories.interfaces.queries.chat import ChatHistoryQueryRepository
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceQueryRepository,
)
from osu_server.repositories.interfaces.queries.scores import ScoreQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.sqlalchemy.queries.beatmap_score_listing import (
    SQLAlchemyBeatmapScoreListingQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.beatmaps import SQLAlchemyBeatmapQueryRepository
from osu_server.repositories.sqlalchemy.queries.blobs import SQLAlchemyBlobQueryRepository
from osu_server.repositories.sqlalchemy.queries.channels import SQLAlchemyChannelQueryRepository
from osu_server.repositories.sqlalchemy.queries.chat import SQLAlchemyChatHistoryQueryRepository
from osu_server.repositories.sqlalchemy.queries.roles import SQLAlchemyRoleQueryRepository
from osu_server.repositories.sqlalchemy.queries.score_performance import (
    SQLAlchemyScorePerformanceQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.scores import SQLAlchemyScoreQueryRepository
from osu_server.repositories.sqlalchemy.queries.users import SQLAlchemyUserQueryRepository
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
    RequestBeatmapFileWarmupUseCase,
)
from osu_server.services.commands.chat import (
    ChatPersistenceWorkPublisher,
    JoinChannelUseCase,
    LeaveChannelUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
)
from osu_server.services.commands.chat.bancho_bot.command_service import CommandService
from osu_server.services.commands.identity import (
    LoginCommandUseCase,
    RefreshRoleAuthorizationCommandUseCase,
    RefreshUserAuthorizationCommandUseCase,
    RegisterUserCommandUseCase,
)
from osu_server.services.commands.identity.auth_service import AuthService
from osu_server.services.commands.identity.session_authorization_service import (
    SessionAuthorizationService,
)
from osu_server.services.commands.scores import ProcessScoreSubmissionUseCase, SubmitScoreUseCase
from osu_server.services.commands.scores.authorization import ScoreAuthorizationService
from osu_server.services.commands.scores.performance import PerformanceRuntimeSettings
from osu_server.services.commands.storage.blob_storage import BlobStorageService
from osu_server.services.queries.beatmaps import (
    ResolveBeatmapByChecksumQuery,
    ResolveBeatmapByIdQuery,
)
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListChannelMessagesQuery,
    ListPrivateMessagesQuery,
    ListVisibleChannelsQuery,
    ResolveChannelMessageDeliveryQuery,
    ResolvePrivateMessageTargetQuery,
)
from osu_server.services.queries.chat.private_message_service import PrivateMessageService
from osu_server.services.queries.identity import (
    ComputePermissionsQueryUseCase,
    ComputeSessionAuthorizationQueryUseCase,
    ListOnlineUsersQueryUseCase,
    SessionCredentialsQueryUseCase,
)
from osu_server.services.queries.identity.online_users_service import OnlineUsersService
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.identity.permission_service import PermissionService
from osu_server.services.queries.scores import BeatmapScoreListingQuery
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.bancho.handlers.chat import ChatHandlers
from osu_server.transports.stable.bancho.handlers.lifecycle import LifecycleHandlers
from osu_server.transports.stable.bancho.handlers.status import StatusChangeHandlers
from osu_server.transports.stable.bancho.workflows.login import LoginWorkflow
from osu_server.transports.stable.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)
from osu_server.transports.stable.bancho.workflows.polling import PollingWorkflow
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.mappers import (
    GetscoresQueryParser,
    GetscoresStatusMapper,
    StableScorePayloadParser,
    StableScoreSubmitMapper,
)
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler


def _runtime_state_overrides() -> TestProviderSet:
    return TestProviderSet(
        replace_value(PacketQueue, InMemoryPacketQueue(), scope=Scope.APP),
        replace_value(ChannelStateStore, InMemoryChannelStateStore(), scope=Scope.APP),
        replace_value(RateLimiter, InMemoryRateLimiter(), scope=Scope.APP),
    )


async def _close_common_dependencies(container: AsyncContainer) -> None:
    await container.close()


@pytest.mark.asyncio
async def test_app_provider_graph_resolves_shared_infrastructure_dependencies() -> None:
    config = make_app_config(environment="development")
    container = make_app_container(config, overrides=(_runtime_state_overrides(),))

    try:
        resolved_config = await container.get(AppConfig)
        engine = await container.get(AsyncEngine)
        session_factory = await container.get(async_sessionmaker[AsyncSession])
        broker = await container.get(AsyncBroker)
        http_client = await container.get(httpx.AsyncClient)
        blob_backend = await container.get(BlobStorageBackend)
        event_bus = await container.get(LocalEventBus)
        chat_publisher = await container.get(ChatPersistenceWorkPublisher)

        assert resolved_config is config
        assert isinstance(engine, AsyncEngine)
        assert isinstance(session_factory, async_sessionmaker)
        assert broker.find_task("persist_channel_message") is not None
        assert broker.find_task("persist_private_message") is not None
        assert broker.find_task("fetch_beatmap_metadata") is not None
        assert broker.find_task("fetch_beatmap_file") is not None
        assert broker.find_task("calculate_score_performance") is not None
        assert broker.find_task("process_performance_recalculation_batch") is not None
        assert isinstance(http_client, httpx.AsyncClient)
        assert blob_backend is not None
        assert event_bus is not None
        assert chat_publisher is not None
    finally:
        await _close_common_dependencies(container)


@pytest.mark.asyncio
async def test_app_provider_graph_resolves_query_repositories() -> None:
    config = make_app_config(environment="development")
    container = make_app_container(config, overrides=(_runtime_state_overrides(),))

    try:
        assert isinstance(await container.get(UserQueryRepository), SQLAlchemyUserQueryRepository)
        assert isinstance(await container.get(RoleQueryRepository), SQLAlchemyRoleQueryRepository)
        assert isinstance(
            await container.get(ChannelQueryRepository),
            SQLAlchemyChannelQueryRepository,
        )
        assert isinstance(
            await container.get(ChatHistoryQueryRepository),
            SQLAlchemyChatHistoryQueryRepository,
        )
        assert isinstance(
            await container.get(BeatmapQueryRepository),
            SQLAlchemyBeatmapQueryRepository,
        )
        assert isinstance(
            await container.get(BeatmapScoreListingQueryRepository),
            SQLAlchemyBeatmapScoreListingQueryRepository,
        )
        assert isinstance(await container.get(BlobQueryRepository), SQLAlchemyBlobQueryRepository)
        assert isinstance(
            await container.get(ScoreQueryRepository), SQLAlchemyScoreQueryRepository
        )
        assert isinstance(
            await container.get(ScorePerformanceQueryRepository),
            SQLAlchemyScorePerformanceQueryRepository,
        )
    finally:
        await _close_common_dependencies(container)


@pytest.mark.asyncio
async def test_app_provider_graph_resolves_shared_provider_groups() -> None:
    config = make_app_config(environment="development")
    container = make_app_container(config, overrides=(_runtime_state_overrides(),))

    expected_types = (
        BlobStorageService,
        BeatmapFreshnessPolicy,
        BeatmapMetadataProvider,
        BeatmapFileProvider,
        BeatmapEligibilityService,
        ResolveBeatmapByIdQuery,
        ResolveBeatmapByChecksumQuery,
        FetchBeatmapMetadataUseCase,
        FetchBeatmapFileUseCase,
        ScoreCryptoService,
        PerformanceRuntimeSettings,
        FormulaProfilePolicy,
        BeatmapScoreListingQuery,
        ListVisibleChannelsQuery,
        ListAutojoinChannelsQuery,
        ResolveChannelMessageDeliveryQuery,
        ListChannelMessagesQuery,
        ListPrivateMessagesQuery,
        JoinChannelUseCase,
        LeaveChannelUseCase,
    )

    try:
        for dependency_type in expected_types:
            resolved = await container.get(dependency_type)
            assert isinstance(resolved, dependency_type)
    finally:
        await _close_common_dependencies(container)


@pytest.mark.asyncio
async def test_app_provider_graph_resolves_app_only_provider_groups() -> None:
    config = make_app_config(environment="test")
    container = make_app_container(config, overrides=(make_in_memory_runtime_provider_set(),))

    expected_types = (
        AppProviderGraph,
        SystemUserIdentity,
        PasswordService,
        PermissionService,
        ComputePermissionsQueryUseCase,
        ComputeSessionAuthorizationQueryUseCase,
        AuthService,
        LoginCommandUseCase,
        RegisterUserCommandUseCase,
        SessionAuthorizationService,
        RefreshUserAuthorizationCommandUseCase,
        RefreshRoleAuthorizationCommandUseCase,
        OnlineUsersService,
        ListOnlineUsersQueryUseCase,
        SessionCredentialsQueryUseCase,
        ResolvePrivateMessageTargetQuery,
        PrivateMessageService,
        CommandService,
        SendChannelMessageUseCase,
        SendPrivateMessageUseCase,
        BeatmapMirrorService,
        RequestBeatmapFileWarmupUseCase,
        ScoreAuthorizationService,
        SubmitScoreUseCase,
        StableScorePayloadParser,
        ProcessScoreSubmissionUseCase,
        LoginResponseBuilder,
        LoginWorkflow,
        LifecycleHandlers,
        ChatHandlers,
        StatusChangeHandlers,
        PacketDispatcher,
        PollingWorkflow,
        BanchoEndpoint,
        RegistrationHandler,
        GetscoresQueryParser,
        GetscoresStatusMapper,
        GetscoresHandler,
        StableScoreSubmitMapper,
        ScoreSubmitHandler,
    )

    try:
        for dependency_type in expected_types:
            resolved = await container.get(dependency_type)
            assert isinstance(resolved, dependency_type)
    finally:
        await _close_common_dependencies(container)


@pytest.mark.asyncio
async def test_app_provider_graph_wires_single_warmup_use_case_into_stable_workflows() -> None:
    config = make_app_config(environment="test")
    container = make_app_container(config, overrides=(make_in_memory_runtime_provider_set(),))

    try:
        warmup = await container.get(RequestBeatmapFileWarmupUseCase)
        getscores = await container.get(GetscoresHandler)
        status_handlers = await container.get(StatusChangeHandlers)
        score_submission = await container.get(ProcessScoreSubmissionUseCase)
        getscores_warmup = cast(
            "RequestBeatmapFileWarmupUseCase",
            object.__getattribute__(
                getscores,
                "_beatmap_file_warmup",
            ),
        )
        status_warmup = cast(
            "RequestBeatmapFileWarmupUseCase",
            object.__getattribute__(
                status_handlers,
                "_beatmap_file_warmup",
            ),
        )
        wired_warmup = cast(
            "RequestBeatmapFileWarmupUseCase | None",
            object.__getattribute__(
                score_submission,
                "_beatmap_file_warmup_use_case",
            ),
        )
        assert getscores_warmup is warmup
        assert status_warmup is warmup
        assert wired_warmup is warmup
    finally:
        await _close_common_dependencies(container)


@pytest.mark.asyncio
async def test_worker_provider_graph_uses_shared_dependencies_without_app_only_groups() -> None:
    config = make_app_config(environment="production")
    container = make_worker_container(config, overrides=(_runtime_state_overrides(),))

    try:
        assert isinstance(await container.get(WorkerProviderGraph), WorkerProviderGraph)
        assert isinstance(await container.get(ResolveBeatmapByIdQuery), ResolveBeatmapByIdQuery)
        assert isinstance(
            await container.get(PerformanceRuntimeSettings),
            PerformanceRuntimeSettings,
        )
        assert isinstance(await container.get(FormulaProfilePolicy), FormulaProfilePolicy)
        assert isinstance(await container.get(BeatmapScoreListingQuery), BeatmapScoreListingQuery)
        assert isinstance(await container.get(ListVisibleChannelsQuery), ListVisibleChannelsQuery)
        assert isinstance(await container.get(JoinChannelUseCase), JoinChannelUseCase)
        with pytest.raises(NoFactoryError):
            _ = await container.get(BanchoEndpoint)
    finally:
        await _close_common_dependencies(container)
