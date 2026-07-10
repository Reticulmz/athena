"""Dishka app composition integration tests."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import httpx
import pytest
from glide import GlideClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.routing import Host, Mount, Route, Router
from starlette.testclient import TestClient
from taskiq import AsyncBroker

from osu_server.app import app, create_app
from osu_server.composition.providers.container import make_app_container
from osu_server.composition.providers.test import (
    TestProviderSet,
    make_in_memory_runtime_provider_set,
    replace_value,
)
from osu_server.config import AppConfig, load_routing_config
from osu_server.domain.compatibility.stable import (
    ReplayDownloadBranch,
    ReplayDownloadResponseBody,
)
from osu_server.domain.identity.authentication import LegacyWebAuthResult
from osu_server.domain.scores.score import Ruleset
from osu_server.infrastructure.country.cloudflare import CloudflareCountryResolver
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.infrastructure.state.interfaces.replay_download_accounting_gate import (
    ReplayDownloadAccountingGate,
)
from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
    StableUserStatusStore,
)
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.infrastructure.state.memory.replay_download_accounting_gate import (
    InMemoryReplayDownloadAccountingGate,
)
from osu_server.infrastructure.state.memory.stable_user_status_store import (
    InMemoryStableUserStatusStore,
)
from osu_server.infrastructure.state.valkey.replay_download_accounting_gate import (
    ValkeyReplayDownloadAccountingGate,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.queries.blobs import BlobQueryRepository
from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository
from osu_server.repositories.interfaces.queries.chat import ChatHistoryQueryRepository
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadQueryRepository,
)
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.user_stats import UserStatsQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.repositories.memory.queries.blobs import InMemoryBlobQueryRepository
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.chat import InMemoryChatHistoryQueryRepository
from osu_server.repositories.memory.queries.replay_download import (
    InMemoryReplayDownloadQueryRepository,
)
from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.queries.user_stats import InMemoryUserStatsQueryRepository
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
from osu_server.services.commands.scores.replay_download_accounting import (
    ReplayDownloadAccountingInput,
    ReplayDownloadAccountingPublisher,
    ReplayDownloadAccountingUseCase,
)
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
from osu_server.services.queries.identity.session_credentials import (
    SessionCredentialsQueryInput,
    SessionCredentialsQueryResult,
    SessionCredentialsQueryUseCase,
)
from osu_server.services.queries.scores import (
    ReplayDownloadAccountingMetadata,
    ReplayDownloadBodyAssembler,
    ReplayDownloadQuery,
    ReplayDownloadQueryInput,
    ReplayDownloadQueryResult,
)
from osu_server.services.queries.storage import BlobByteReader, BlobByteReaderAdapter
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.bancho.workflows.login import LoginWorkflow
from osu_server.transports.stable.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)
from osu_server.transports.stable.bancho.workflows.polling import PollingWorkflow
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.replay_download import ReplayDownloadHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler
from tests.factories.config import make_app_config
from tests.support.starlette_requests import make_starlette_request

_EXPECTED_MIN_HOST_ROUTES = 4

if TYPE_CHECKING:
    from pathlib import Path


class _FakeValkeyClient:
    async def invoke_script(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        return 1


class _InjectedSessionCredentialsQuery:
    async def execute(
        self,
        input_data: SessionCredentialsQueryInput,
    ) -> SessionCredentialsQueryResult:
        del input_data
        return SessionCredentialsQueryResult(
            outcome=LegacyWebAuthResult(user_id=42, username="PlayerOne")
        )


class _InjectedReplayDownloadQuery:
    inputs: list[ReplayDownloadQueryInput]

    def __init__(self) -> None:
        self.inputs = []

    async def execute(
        self,
        input_data: ReplayDownloadQueryInput,
    ) -> ReplayDownloadQueryResult:
        self.inputs.append(input_data)
        return ReplayDownloadQueryResult(
            branch=ReplayDownloadBranch.SUCCESS,
            response_body=ReplayDownloadResponseBody(payload=b"di-replay-body"),
            accounting_metadata=ReplayDownloadAccountingMetadata(
                score_id=515,
                score_owner_user_id=616,
            ),
        )


class _InjectedReplayDownloadAccountingPublisher:
    inputs: list[ReplayDownloadAccountingInput]

    def __init__(self) -> None:
        self.inputs = []

    async def publish(self, input_data: ReplayDownloadAccountingInput) -> None:
        self.inputs.append(input_data)


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


def test_create_app_registers_replay_download_primary_route_only() -> None:
    created = create_app()
    domain = load_routing_config().domain
    host_routes = [route for route in created.routes if isinstance(route, Host)]
    web_host = next(route for route in host_routes if route.host == f"osu.{domain}")

    assert isinstance(web_host.app, Router)
    web_paths = {
        route.path
        for route in web_host.app.routes
        if isinstance(route, Route) and "GET" in (route.methods or set())
    }
    root_paths = {
        route.path
        for route in created.routes
        if isinstance(route, Route) and "GET" in (route.methods or set())
    }

    assert "/web/osu-getreplay.php" in web_paths
    assert not any(path.startswith("/web/replays") for path in web_paths | root_paths)


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
        assert isinstance(
            await container.get(ReplayDownloadAccountingGate),
            InMemoryReplayDownloadAccountingGate,
        )
        assert isinstance(
            await container.get(StableUserStatusStore),
            InMemoryStableUserStatusStore,
        )
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
        assert isinstance(
            await container.get(UserStatsQueryRepository),
            InMemoryUserStatsQueryRepository,
        )
        replay_download_repository = await container.get(ReplayDownloadQueryRepository)
        assert isinstance(
            replay_download_repository,
            InMemoryReplayDownloadQueryRepository,
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
        ReplayDownloadBodyAssembler,
        ReplayDownloadQuery,
        ReplayDownloadAccountingUseCase,
        ReplayDownloadHandler,
    )

    try:
        for dependency_type in expected_types:
            resolved = await container.get(dependency_type)
            assert isinstance(resolved, dependency_type)
        handler = await container.get(ReplayDownloadHandler)
        assert isinstance(handler, ReplayDownloadHandler)
        blob_reader = await container.get(BlobByteReader)
        assert isinstance(blob_reader, BlobByteReaderAdapter)
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_app_container_injects_replay_download_accounting_publisher_into_handler(
    tmp_path: Path,
) -> None:
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )
    replay_query = _InjectedReplayDownloadQuery()
    accounting = _InjectedReplayDownloadAccountingPublisher()
    container = make_app_container(
        config,
        overrides=(
            make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),
            TestProviderSet(
                replace_value(
                    SessionCredentialsQueryUseCase,
                    cast(
                        "SessionCredentialsQueryUseCase",
                        cast("object", _InjectedSessionCredentialsQuery()),
                    ),
                ),
                replace_value(
                    ReplayDownloadQuery,
                    cast("ReplayDownloadQuery", cast("object", replay_query)),
                ),
                replace_value(
                    ReplayDownloadAccountingPublisher,
                    cast("ReplayDownloadAccountingPublisher", cast("object", accounting)),
                ),
            ),
        ),
    )

    try:
        handler = await container.get(ReplayDownloadHandler)
        response = await handler(
            make_starlette_request(
                method="GET",
                path="/web/osu-getreplay.php",
                query_params={"c": "8675309", "m": "3", "u": "user", "h": "hash"},
            )
        )

        assert response.status_code == HTTPStatus.OK
        assert response.body == b"di-replay-body"
        if response.background is None:
            raise AssertionError("expected replay download accounting background task")
        await response.background()
        assert replay_query.inputs == [
            ReplayDownloadQueryInput(
                authenticated_user_id=42,
                score_id=8675309,
                ruleset=Ruleset.MANIA,
            )
        ]
        assert len(accounting.inputs) == 1
        assert accounting.inputs[0].score_id == 515
        assert accounting.inputs[0].score_owner_user_id == 616
        assert accounting.inputs[0].viewer_user_id == 42
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_runtime_graph_provides_valkey_replay_download_accounting_gate(
    tmp_path: Path,
) -> None:
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )
    container = make_app_container(
        config,
        overrides=(
            TestProviderSet(
                replace_value(
                    GlideClient,
                    cast("GlideClient", cast("object", _FakeValkeyClient())),
                ),
            ),
        ),
    )

    try:
        gate = await container.get(ReplayDownloadAccountingGate)
        assert isinstance(gate, ValkeyReplayDownloadAccountingGate)
    finally:
        await container.close()


def test_in_memory_app_replay_download_route_reaches_handler(tmp_path: Path) -> None:
    created = create_app(
        provider_overrides=(make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),)
    )

    with TestClient(created, raise_server_exceptions=False) as client:
        domain = load_routing_config().domain
        response = client.get(f"http://osu.{domain}/web/osu-getreplay.php")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.content == b""
