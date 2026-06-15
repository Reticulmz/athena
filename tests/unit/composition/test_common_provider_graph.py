"""Common Dishka provider graph tests."""

from __future__ import annotations

import httpx
import pytest
from dishka import AsyncContainer, Scope
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from taskiq import AsyncBroker
from tests.factories.config import make_app_config

from osu_server.composition.providers.container import make_app_container, make_worker_container
from osu_server.composition.providers.test import TestProviderSet, replace_value
from osu_server.config import AppConfig
from osu_server.infrastructure.crypto import ScoreCryptoService
from osu_server.infrastructure.messaging.interfaces import EventBus
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
from osu_server.repositories.sqlalchemy.queries.scores import SQLAlchemyScoreQueryRepository
from osu_server.repositories.sqlalchemy.queries.users import SQLAlchemyUserQueryRepository
from osu_server.services.commands.chat import JoinChannelUseCase, LeaveChannelUseCase
from osu_server.services.queries.beatmaps import (
    ResolveBeatmapByChecksumQuery,
    ResolveBeatmapByIdQuery,
)
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListChannelMessagesQuery,
    ListPrivateMessagesQuery,
    ListVisibleChannelsQuery,
    ResolveChannelMessageDeliveryQuery,
)
from osu_server.services.queries.scores import BeatmapScoreListingQuery
from osu_server.transports.stable.web_legacy.mappers import StableScoreSubmitMapper


def _runtime_state_overrides() -> TestProviderSet:
    return TestProviderSet(
        replace_value(PacketQueue, InMemoryPacketQueue(), scope=Scope.APP),
        replace_value(ChannelStateStore, InMemoryChannelStateStore(), scope=Scope.APP),
        replace_value(RateLimiter, InMemoryRateLimiter(), scope=Scope.APP),
    )


async def _close_common_dependencies(container: AsyncContainer) -> None:
    await container.close()


@pytest.mark.asyncio
async def test_app_provider_graph_resolves_common_runtime_dependencies() -> None:
    config = make_app_config(environment="development")
    container = make_app_container(config, overrides=(_runtime_state_overrides(),))

    try:
        resolved_config = await container.get(AppConfig)
        engine = await container.get(AsyncEngine)
        session_factory = await container.get(async_sessionmaker[AsyncSession])
        broker = await container.get(AsyncBroker)
        http_client = await container.get(httpx.AsyncClient)
        blob_backend = await container.get(BlobStorageBackend)
        event_bus = await container.get(EventBus)
        score_crypto = await container.get(ScoreCryptoService)
        stable_score_submit_mapper = await container.get(StableScoreSubmitMapper)

        assert resolved_config is config
        assert isinstance(engine, AsyncEngine)
        assert isinstance(session_factory, async_sessionmaker)
        assert broker.find_task("persist_channel_message") is not None
        assert broker.find_task("persist_private_message") is not None
        assert broker.find_task("fetch_beatmap_metadata") is not None
        assert broker.find_task("fetch_beatmap_file") is not None
        assert isinstance(http_client, httpx.AsyncClient)
        assert blob_backend is not None
        assert event_bus is not None
        assert isinstance(score_crypto, ScoreCryptoService)
        assert isinstance(stable_score_submit_mapper, StableScoreSubmitMapper)
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
    finally:
        await _close_common_dependencies(container)


@pytest.mark.asyncio
async def test_app_provider_graph_resolves_query_and_lightweight_command_use_cases() -> None:
    config = make_app_config(environment="development")
    container = make_app_container(config, overrides=(_runtime_state_overrides(),))

    expected_types = (
        ResolveBeatmapByIdQuery,
        ResolveBeatmapByChecksumQuery,
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
async def test_worker_provider_graph_uses_same_common_dependencies() -> None:
    config = make_app_config(environment="production")
    container = make_worker_container(config, overrides=(_runtime_state_overrides(),))

    try:
        assert isinstance(await container.get(ResolveBeatmapByIdQuery), ResolveBeatmapByIdQuery)
        assert isinstance(await container.get(BeatmapScoreListingQuery), BeatmapScoreListingQuery)
        assert isinstance(await container.get(ListVisibleChannelsQuery), ListVisibleChannelsQuery)
        assert isinstance(await container.get(JoinChannelUseCase), JoinChannelUseCase)
    finally:
        await _close_common_dependencies(container)
