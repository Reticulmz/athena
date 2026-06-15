"""Dishka app composition integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.routing import Host, Mount, Route
from taskiq import AsyncBroker

from osu_server.app import app, create_app
from osu_server.composition.providers.container import make_app_container
from osu_server.composition.providers.test import make_in_memory_runtime_provider_set
from osu_server.config import AppConfig, load_routing_config
from osu_server.infrastructure.country.cloudflare import CloudflareCountryResolver
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.queries.blobs import BlobQueryRepository
from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository
from osu_server.repositories.interfaces.queries.chat import ChatHistoryQueryRepository
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.repositories.memory.queries.blobs import InMemoryBlobQueryRepository
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.chat import InMemoryChatHistoryQueryRepository
from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.chat import (
    JoinChannelUseCase,
    LeaveChannelUseCase,
    PersistChannelMessageUseCase,
    PersistPrivateMessageUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
)
from osu_server.services.commands.chat.bancho_bot.command_service import CommandService
from osu_server.services.commands.identity import LoginCommandUseCase, RegisterUserCommandUseCase
from osu_server.services.commands.identity.auth_service import AuthService
from osu_server.services.queries.beatmaps.mirror import BeatmapMirrorService
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListChannelMessagesQuery,
    ListPrivateMessagesQuery,
    ListVisibleChannelsQuery,
    ResolveChannelMessageDeliveryQuery,
    ResolvePrivateMessageTargetQuery,
)
from osu_server.services.queries.chat.private_message_service import PrivateMessageService
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.identity.permission_service import PermissionService
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.bancho.workflows.login import LoginWorkflow
from osu_server.transports.stable.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)
from osu_server.transports.stable.bancho.workflows.polling import PollingWorkflow
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler
from tests.factories.config import make_app_config

_EXPECTED_MIN_HOST_ROUTES = 4

if TYPE_CHECKING:
    from pathlib import Path


def test_public_app_entrypoint_exposes_starlette_app() -> None:
    assert isinstance(app, Starlette)
    assert isinstance(create_app(), Starlette)


def test_create_app_registers_host_and_fallback_routes() -> None:
    created = create_app()
    routes = list(created.routes)
    domain = load_routing_config().domain

    host_routes = [route for route in routes if isinstance(route, Host)]
    fallback_routes = [route for route in routes if isinstance(route, Route)]
    mounts = [route for route in routes if isinstance(route, Mount)]

    assert len(host_routes) >= _EXPECTED_MIN_HOST_ROUTES
    assert {route.host for route in host_routes} >= {
        f"c.{domain}",
        f"c{{server:int}}.{domain}",
        f"ce.{domain}",
        f"osu.{domain}",
    }
    assert not any(
        route.path == "/" and "POST" in (route.methods or set()) for route in fallback_routes
    )
    assert any(
        route.path == "/health" and "GET" in (route.methods or set()) for route in fallback_routes
    )
    assert any(route.path == "/web" for route in mounts)
    assert any(route.path == "/api/v2" for route in mounts)
    assert any(route.path == "/signalr" for route in mounts)


def test_create_app_reads_route_domain_from_environment_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOMAIN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VALKEY_URL", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    _ = (tmp_path / ".env.development").write_text(
        "DOMAIN=example.test\n",
        encoding="utf-8",
    )

    created = create_app()
    host_routes = [route for route in created.routes if isinstance(route, Host)]

    assert {route.host for route in host_routes} >= {
        "c.example.test",
        "c{server:int}.example.test",
        "ce.example.test",
        "osu.example.test",
    }


@pytest.mark.asyncio
async def test_app_container_resolves_common_infrastructure(tmp_path: Path) -> None:
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )
    container = make_app_container(
        config,
        overrides=(make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),),
    )

    try:
        assert await container.get(AppConfig) is config
        assert isinstance(await container.get(AsyncEngine), AsyncEngine)
        assert isinstance(
            await container.get(async_sessionmaker[AsyncSession]),
            async_sessionmaker,
        )
        assert isinstance(await container.get(AsyncBroker), AsyncBroker)
        assert isinstance(await container.get(httpx.AsyncClient), httpx.AsyncClient)
        assert isinstance(await container.get(LocalEventBus), LocalEventBus)
        assert isinstance(await container.get(CountryResolver), CloudflareCountryResolver)
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_app_container_uses_explicit_in_memory_test_overrides(
    tmp_path: Path,
) -> None:
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )
    container = make_app_container(
        config,
        overrides=(make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),),
    )

    try:
        assert isinstance(await container.get(PacketQueue), InMemoryPacketQueue)
        assert isinstance(await container.get(ChannelStateStore), InMemoryChannelStateStore)
        assert isinstance(await container.get(RateLimiter), InMemoryRateLimiter)
        assert isinstance(await container.get(SessionStore), InMemorySessionStore)
        assert isinstance(await container.get(UnitOfWorkFactory), InMemoryUnitOfWorkFactory)
        assert isinstance(await container.get(UserQueryRepository), InMemoryUserQueryRepository)
        assert isinstance(await container.get(RoleQueryRepository), InMemoryRoleQueryRepository)
        assert isinstance(
            await container.get(ChannelQueryRepository),
            InMemoryChannelQueryRepository,
        )
        assert isinstance(
            await container.get(BeatmapQueryRepository),
            InMemoryBeatmapQueryRepository,
        )
        assert isinstance(await container.get(BlobQueryRepository), InMemoryBlobQueryRepository)
        assert isinstance(
            await container.get(ChatHistoryQueryRepository),
            InMemoryChatHistoryQueryRepository,
        )
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_app_container_resolves_identity_and_chat_graph(tmp_path: Path) -> None:
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )
    container = make_app_container(
        config,
        overrides=(make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),),
    )

    expected_types = (
        PasswordService,
        PermissionService,
        AuthService,
        LoginCommandUseCase,
        RegisterUserCommandUseCase,
        PrivateMessageService,
        CommandService,
        ListVisibleChannelsQuery,
        ListAutojoinChannelsQuery,
        ResolveChannelMessageDeliveryQuery,
        ResolvePrivateMessageTargetQuery,
        ListChannelMessagesQuery,
        ListPrivateMessagesQuery,
        SendChannelMessageUseCase,
        SendPrivateMessageUseCase,
        JoinChannelUseCase,
        LeaveChannelUseCase,
        PersistChannelMessageUseCase,
        PersistPrivateMessageUseCase,
    )

    try:
        for dependency_type in expected_types:
            resolved = await container.get(dependency_type)
            assert isinstance(resolved, dependency_type)
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_app_container_resolves_transport_handler_graph(tmp_path: Path) -> None:
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )
    container = make_app_container(
        config,
        overrides=(make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),),
    )

    expected_types = (
        BeatmapMirrorService,
        LoginResponseBuilder,
        LoginWorkflow,
        PacketDispatcher,
        PollingWorkflow,
        BanchoEndpoint,
        RegistrationHandler,
        GetscoresHandler,
        ScoreSubmitHandler,
    )

    try:
        for dependency_type in expected_types:
            resolved = await container.get(dependency_type)
            assert isinstance(resolved, dependency_type)
    finally:
        await container.close()
