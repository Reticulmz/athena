"""Tests for Task 6.1: DI integration, route registration, and subdomain routing.

Validates:
- providers.py registers infrastructure-layer services (httpx, HIBP, CountryResolver)
- app.py _register_services wires repositories, services, handlers
- httpx.AsyncClient lifecycle (shutdown hook registered)
- Environment-based repository switching (InMemory vs SQLAlchemy)
- BanchoEndpoint and RegistrationHandler are resolvable
- app.py subdomain routing (Host-based) and path-based fallbacks
- Config domain field
"""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
import pytest
from starlette.routing import Host, Mount, Route
from taskiq import AsyncBroker
from taskiq_redis import ListQueueBroker

from osu_server.app import app, create_app, register_services
from osu_server.config import AppConfig
from osu_server.domain.users.events import UserDisconnected
from osu_server.infrastructure.country.cloudflare import CloudflareCountryResolver
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.di.providers import build_container
from osu_server.infrastructure.messaging.interfaces import EventBus
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter

if TYPE_CHECKING:
    from osu_server.infrastructure.di.container import Container
from osu_server.infrastructure.security.hibp import HIBPClient
from osu_server.repositories.interfaces.channel_repository import ChannelRepository
from osu_server.repositories.interfaces.chat_repository import ChatRepository
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.chat_repository import InMemoryChatRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.auth_service import AuthService
from osu_server.services.channel_service import ChannelService
from osu_server.services.chat_service import ChatService
from osu_server.services.command_service import CommandService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.services.private_message_service import PrivateMessageService
from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.endpoint import BanchoEndpoint
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.workflows.login import LoginWorkflow
from osu_server.transports.bancho.workflows.login_response_builder import LoginResponseBuilder
from osu_server.transports.bancho.workflows.polling import PollingWorkflow
from osu_server.transports.web_legacy.registration import RegistrationHandler

_EXPECTED_MIN_SHUTDOWN_HOOKS = 3
_EXPECTED_MIN_HOST_ROUTES = 2


def _is_port_open(host: str, port: int, *, timeout: float = 1.0) -> bool:
    """Check if a TCP port is open and accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _require_valkey() -> None:
    """Skip if VALKEY_URL is not set or Valkey is unreachable."""
    url = os.environ.get("VALKEY_URL")
    if not url:
        pytest.skip("VALKEY_URL not set")
    parsed = urlparse(url)
    if parsed.hostname and parsed.port and not _is_port_open(parsed.hostname, parsed.port):
        pytest.skip(f"Valkey not reachable at {parsed.hostname}:{parsed.port}")


def _make_config(*, environment: str = "test") -> AppConfig:
    """Create a minimal AppConfig for testing."""
    return AppConfig.model_validate(
        {
            "database_url": "postgresql://test:test@localhost:5432/test",
            "valkey_url": "redis://localhost:6379/0",
            "environment": environment,
        }
    )


async def _build_full_container(
    config: AppConfig | None = None,
) -> tuple[AppConfig, Container]:
    """Build container with both infrastructure and service registrations."""
    _require_valkey()
    if config is None:
        config = _make_config()
    container = await build_container(config)
    await register_services(container, config)
    return config, container


# ---------------------------------------------------------------------------
# Infrastructure-layer DI registrations (providers.py)
# ---------------------------------------------------------------------------


class TestDIInfraRegistrations:
    """build_container registers infrastructure-layer services."""

    async def test_resolves_httpx_async_client(self) -> None:
        _require_valkey()
        config = _make_config()
        container = await build_container(config)

        client = await container.resolve(httpx.AsyncClient)
        assert isinstance(client, httpx.AsyncClient)

    async def test_resolves_hibp_client(self) -> None:
        _require_valkey()
        config = _make_config()
        container = await build_container(config)

        hibp = await container.resolve(HIBPClient)
        assert isinstance(hibp, HIBPClient)

    async def test_resolves_country_resolver(self) -> None:
        _require_valkey()
        config = _make_config()
        container = await build_container(config)

        resolver = await container.resolve(CountryResolver)
        assert isinstance(resolver, CloudflareCountryResolver)

    async def test_resolves_taskiq_broker(self) -> None:
        _require_valkey()
        config = _make_config()
        container = await build_container(config)

        broker = await container.resolve(AsyncBroker)
        assert isinstance(broker, ListQueueBroker)


# ---------------------------------------------------------------------------
# Full DI registrations (providers.py + _register_services)
# ---------------------------------------------------------------------------


class TestDIAuthRegistrations:
    """_register_services registers all auth/login related services."""

    async def test_resolves_password_service(self) -> None:
        _, container = await _build_full_container()

        svc = await container.resolve(PasswordService)
        assert isinstance(svc, PasswordService)

    async def test_resolves_user_repository(self) -> None:
        _, container = await _build_full_container()

        repo = await container.resolve(UserRepository)
        assert repo is not None

    async def test_resolves_role_repository(self) -> None:
        _, container = await _build_full_container()

        repo = await container.resolve(RoleRepository)
        assert repo is not None

    async def test_resolves_permission_service(self) -> None:
        _, container = await _build_full_container()

        svc = await container.resolve(PermissionService)
        assert isinstance(svc, PermissionService)

    async def test_resolves_auth_service(self) -> None:
        _, container = await _build_full_container()

        svc = await container.resolve(AuthService)
        assert isinstance(svc, AuthService)

    async def test_resolves_bancho_endpoint(self) -> None:
        _, container = await _build_full_container()

        handler = await container.resolve(BanchoEndpoint)
        assert isinstance(handler, BanchoEndpoint)

    async def test_resolves_registration_handler(self) -> None:
        _, container = await _build_full_container()

        handler = await container.resolve(RegistrationHandler)
        assert isinstance(handler, RegistrationHandler)


# ---------------------------------------------------------------------------
# Bancho endpoint graph resolution
# ---------------------------------------------------------------------------


class TestDIBanchoEndpointGraph:
    """_register_services registers LoginWorkflow, PollingWorkflow,
    LoginResponseBuilder, and PacketDispatcher as singletons."""

    async def test_resolves_login_response_builder(self) -> None:
        _, container = await _build_full_container()

        builder = await container.resolve(LoginResponseBuilder)
        assert isinstance(builder, LoginResponseBuilder)

    async def test_resolves_login_workflow(self) -> None:
        _, container = await _build_full_container()

        workflow = await container.resolve(LoginWorkflow)
        assert isinstance(workflow, LoginWorkflow)

    async def test_resolves_polling_workflow(self) -> None:
        _, container = await _build_full_container()

        workflow = await container.resolve(PollingWorkflow)
        assert isinstance(workflow, PollingWorkflow)

    async def test_resolves_packet_dispatcher(self) -> None:
        _, container = await _build_full_container()

        dispatcher = await container.resolve(PacketDispatcher)
        assert isinstance(dispatcher, PacketDispatcher)

    async def test_polling_workflow_uses_container_dispatcher_with_handlers(self) -> None:
        """PollingWorkflow._packet_dispatcher is the same instance resolved
        from the container, and C2S handlers are registered on it."""
        _, container = await _build_full_container()

        polling = await container.resolve(PollingWorkflow)
        dispatcher = await container.resolve(PacketDispatcher)

        assert polling._packet_dispatcher is dispatcher  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        assert ClientPacketID.SEND_MESSAGE in dispatcher.get_handlers()
        assert ClientPacketID.SEND_PRIVATE_MESSAGE in dispatcher.get_handlers()
        assert ClientPacketID.JOIN_CHANNEL in dispatcher.get_handlers()
        assert ClientPacketID.LEAVE_CHANNEL in dispatcher.get_handlers()


# ---------------------------------------------------------------------------
# Environment-based repository switching
# ---------------------------------------------------------------------------


class TestDIChatRegistrations:
    """_register_services wires ChatRepository into ChatService."""

    async def test_resolves_chat_repository(self) -> None:
        _, container = await _build_full_container()

        repo = await container.resolve(ChatRepository)
        assert isinstance(repo, InMemoryChatRepository)

    async def test_chat_service_persistence_uses_registered_chat_repository(self) -> None:
        _, container = await _build_full_container()
        repo = await container.resolve(ChatRepository)
        assert isinstance(repo, InMemoryChatRepository)

        service = await container.resolve(ChatService)
        channel_result = await service.persist_channel_message(
            sender_id=1,
            channel_name="#osu",
            content="hello",
        )
        private_result = await service.persist_private_message(
            sender_id=1,
            target_id=2,
            content="secret",
        )

        assert channel_result.success is True
        assert private_result.success is True
        assert repo.channel_messages == ((1, "#osu", "hello"),)
        assert repo.private_messages == ((1, 2, "secret"),)


class TestDIChannelSystemRegistrations:
    """_register_services wires channel/chat transport composition."""

    async def test_resolves_channel_system_services(self) -> None:
        _, container = await _build_full_container()

        channel_repo = await container.resolve(ChannelRepository)
        channel_state = await container.resolve(ChannelStateStore)
        rate_limiter = await container.resolve(RateLimiter)
        channel_service = await container.resolve(ChannelService)
        private_message_service = await container.resolve(PrivateMessageService)
        command_service = await container.resolve(CommandService)

        assert isinstance(channel_repo, InMemoryChannelRepository)
        assert isinstance(channel_state, InMemoryChannelStateStore)
        assert isinstance(rate_limiter, InMemoryRateLimiter)
        assert isinstance(channel_service, ChannelService)
        assert isinstance(private_message_service, PrivateMessageService)
        assert isinstance(command_service, CommandService)

    async def test_registers_chat_handlers_with_packet_dispatcher(self) -> None:
        _, container = await _build_full_container()

        dispatcher = await container.resolve(PacketDispatcher)
        handlers = dispatcher.get_handlers()

        assert ClientPacketID.SEND_MESSAGE in handlers
        assert ClientPacketID.SEND_PRIVATE_MESSAGE in handlers
        assert ClientPacketID.JOIN_CHANNEL in handlers
        assert ClientPacketID.LEAVE_CHANNEL in handlers

    async def test_registers_chat_listeners_with_event_bus(self) -> None:
        _, container = await _build_full_container()
        event_bus = await container.resolve(EventBus)
        channel_state = await container.resolve(ChannelStateStore)

        await channel_state.add_member("#osu", 42)
        await event_bus.fire(UserDisconnected(user_id=42))

        assert await channel_state.get_user_channels(42) == set()

    async def test_registers_chat_persistence_jobs_with_broker(self) -> None:
        _, container = await _build_full_container()

        broker = await container.resolve(AsyncBroker)

        assert broker.find_task("persist_channel_message") is not None
        assert broker.find_task("persist_private_message") is not None


class TestEnvironmentBasedRepositories:
    """Test environment selects InMemory repos, others select SQLAlchemy."""

    async def test_test_env_uses_in_memory_user_repository(self) -> None:
        _, container = await _build_full_container(_make_config(environment="test"))

        repo = await container.resolve(UserRepository)
        assert isinstance(repo, InMemoryUserRepository)

    async def test_test_env_uses_in_memory_role_repository(self) -> None:
        _, container = await _build_full_container(_make_config(environment="test"))

        repo = await container.resolve(RoleRepository)
        assert isinstance(repo, InMemoryRoleRepository)

    async def test_test_env_uses_in_memory_chat_repository(self) -> None:
        _, container = await _build_full_container(_make_config(environment="test"))

        repo = await container.resolve(ChatRepository)
        assert isinstance(repo, InMemoryChatRepository)


# ---------------------------------------------------------------------------
# httpx.AsyncClient lifecycle
# ---------------------------------------------------------------------------


class TestHttpxLifecycle:
    """httpx.AsyncClient shutdown hook is registered for aclose()."""

    async def test_shutdown_hook_registered_for_httpx(self) -> None:
        """At least 3 shutdown hooks: engine.dispose, valkey.close, httpx.aclose."""
        _require_valkey()
        config = _make_config()
        container = await build_container(config)

        assert len(container.shutdown_hooks) >= _EXPECTED_MIN_SHUTDOWN_HOOKS


# ---------------------------------------------------------------------------
# Config: domain field
# ---------------------------------------------------------------------------


class TestConfigDomainField:
    """AppConfig includes a domain field with default 'athena.localhost'."""

    def test_default_domain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOMAIN", raising=False)

        config = _make_config()
        assert config.domain == "athena.localhost"

    def test_custom_domain(self) -> None:
        config = AppConfig.model_validate(
            {
                "database_url": "postgresql://test:test@localhost:5432/test",
                "valkey_url": "redis://localhost:6379/0",
                "domain": "example.com",
            }
        )
        assert config.domain == "example.com"


# ---------------------------------------------------------------------------
# App routing structure
# ---------------------------------------------------------------------------


class TestAppRouting:
    """app.py has Host-based subdomain routing and path-based fallbacks."""

    def test_app_has_host_routes(self) -> None:
        app_inst = create_app()
        host_routes = [r for r in app_inst.routes if isinstance(r, Host)]
        assert len(host_routes) >= _EXPECTED_MIN_HOST_ROUTES, (
            "Expected at least 2 Host routes (bancho + web_legacy)"
        )

    def test_app_has_bancho_host_route(self) -> None:
        app_inst = create_app()
        host_routes = [r for r in app_inst.routes if isinstance(r, Host)]
        host_patterns = [r.host for r in host_routes]
        assert any("c." in h for h in host_patterns), (
            f"Expected a Host route containing 'c.' for bancho, got {host_patterns}"
        )

    def test_app_has_web_legacy_host_route(self) -> None:
        app_inst = create_app()
        host_routes = [r for r in app_inst.routes if isinstance(r, Host)]
        host_patterns = [r.host for r in host_routes]
        assert any("osu." in h for h in host_patterns), (
            f"Expected a Host route containing 'osu.' for web_legacy, got {host_patterns}"
        )

    def test_app_has_fallback_post_root(self) -> None:
        """Path-based fallback: POST / exists for local dev without subdomains."""
        app_inst = create_app()
        path_routes = [r for r in app_inst.routes if isinstance(r, Route)]
        root_routes = [r for r in path_routes if r.path == "/"]
        assert len(root_routes) >= 1, "Expected a fallback Route for POST /"

    def test_app_has_fallback_web_mount(self) -> None:
        """Path-based fallback: Mount /web exists for local dev without subdomains."""
        app_inst = create_app()
        mount_routes = [r for r in app_inst.routes if isinstance(r, Mount)]
        web_mounts = [r for r in mount_routes if r.path == "/web"]
        assert len(web_mounts) >= 1, "Expected a fallback Mount for /web"

    def test_app_import_succeeds(self) -> None:
        """python -c 'from osu_server.app import app' should not raise."""
        _ = app
