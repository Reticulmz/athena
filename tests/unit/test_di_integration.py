# ruff: noqa: PLC0415
# pyright: reportAny=false
"""Tests for Task 6.1: DI integration, route registration, and subdomain routing.

Validates:
- providers.py registers infrastructure-layer services (httpx, HIBP, CountryResolver)
- app.py _register_services wires repositories, services, handlers
- httpx.AsyncClient lifecycle (shutdown hook registered)
- Environment-based repository switching (InMemory vs SQLAlchemy)
- LoginHandler and RegistrationHandler are resolvable
- app.py subdomain routing (Host-based) and path-based fallbacks
- Config domain field
"""

from __future__ import annotations

import httpx
from starlette.routing import Host, Mount, Route

from osu_server.app import _register_services
from osu_server.config import AppConfig
from osu_server.infrastructure.country.cloudflare import CloudflareCountryResolver
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.di.providers import build_container
from osu_server.infrastructure.security.hibp import HIBPClient
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.auth_service import AuthService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.transports.bancho.handlers.login import LoginHandler
from osu_server.transports.web_legacy.registration import RegistrationHandler

_EXPECTED_MIN_SHUTDOWN_HOOKS = 3
_EXPECTED_MIN_HOST_ROUTES = 2


def _make_config(*, environment: str = "test", **kwargs: object) -> AppConfig:
    """Create a minimal AppConfig for testing."""
    return AppConfig(
        database_url="postgresql://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        environment=environment,
        **kwargs,  # pyright: ignore[reportAny]
    )


async def _build_full_container(
    config: AppConfig | None = None,
) -> tuple[AppConfig, object]:
    """Build container with both infrastructure and service registrations."""
    if config is None:
        config = _make_config()
    container = await build_container(config)
    await _register_services(container, config)
    return config, container


# ---------------------------------------------------------------------------
# Infrastructure-layer DI registrations (providers.py)
# ---------------------------------------------------------------------------


class TestDIInfraRegistrations:
    """build_container registers infrastructure-layer services."""

    async def test_resolves_httpx_async_client(self) -> None:
        config = _make_config()
        container = await build_container(config)

        client = await container.resolve(httpx.AsyncClient)
        assert isinstance(client, httpx.AsyncClient)

    async def test_resolves_hibp_client(self) -> None:
        config = _make_config()
        container = await build_container(config)

        hibp = await container.resolve(HIBPClient)
        assert isinstance(hibp, HIBPClient)

    async def test_resolves_country_resolver(self) -> None:
        config = _make_config()
        container = await build_container(config)

        resolver = await container.resolve(CountryResolver)
        assert isinstance(resolver, CloudflareCountryResolver)


# ---------------------------------------------------------------------------
# Full DI registrations (providers.py + _register_services)
# ---------------------------------------------------------------------------


class TestDIAuthRegistrations:
    """_register_services registers all auth/login related services."""

    async def test_resolves_password_service(self) -> None:
        _, container = await _build_full_container()

        svc = await container.resolve(PasswordService)  # pyright: ignore[reportUnknownMemberType]
        assert isinstance(svc, PasswordService)

    async def test_resolves_user_repository(self) -> None:
        _, container = await _build_full_container()

        repo = await container.resolve(UserRepository)  # pyright: ignore[reportUnknownMemberType]
        assert repo is not None

    async def test_resolves_role_repository(self) -> None:
        _, container = await _build_full_container()

        repo = await container.resolve(RoleRepository)  # pyright: ignore[reportUnknownMemberType]
        assert repo is not None

    async def test_resolves_permission_service(self) -> None:
        _, container = await _build_full_container()

        svc = await container.resolve(PermissionService)  # pyright: ignore[reportUnknownMemberType]
        assert isinstance(svc, PermissionService)

    async def test_resolves_auth_service(self) -> None:
        _, container = await _build_full_container()

        svc = await container.resolve(AuthService)  # pyright: ignore[reportUnknownMemberType]
        assert isinstance(svc, AuthService)

    async def test_resolves_login_handler(self) -> None:
        _, container = await _build_full_container()

        handler = await container.resolve(LoginHandler)  # pyright: ignore[reportUnknownMemberType]
        assert isinstance(handler, LoginHandler)

    async def test_resolves_registration_handler(self) -> None:
        _, container = await _build_full_container()

        handler = await container.resolve(RegistrationHandler)  # pyright: ignore[reportUnknownMemberType]
        assert isinstance(handler, RegistrationHandler)


# ---------------------------------------------------------------------------
# Environment-based repository switching
# ---------------------------------------------------------------------------


class TestEnvironmentBasedRepositories:
    """Test environment selects InMemory repos, others select SQLAlchemy."""

    async def test_test_env_uses_in_memory_user_repository(self) -> None:
        _, container = await _build_full_container(_make_config(environment="test"))

        repo = await container.resolve(UserRepository)  # pyright: ignore[reportUnknownMemberType]
        assert isinstance(repo, InMemoryUserRepository)

    async def test_test_env_uses_in_memory_role_repository(self) -> None:
        _, container = await _build_full_container(_make_config(environment="test"))

        repo = await container.resolve(RoleRepository)  # pyright: ignore[reportUnknownMemberType]
        assert isinstance(repo, InMemoryRoleRepository)


# ---------------------------------------------------------------------------
# httpx.AsyncClient lifecycle
# ---------------------------------------------------------------------------


class TestHttpxLifecycle:
    """httpx.AsyncClient shutdown hook is registered for aclose()."""

    async def test_shutdown_hook_registered_for_httpx(self) -> None:
        """At least 3 shutdown hooks: engine.dispose, redis.aclose, httpx.aclose."""
        config = _make_config()
        container = await build_container(config)

        assert len(container._shutdown_hooks) >= _EXPECTED_MIN_SHUTDOWN_HOOKS  # noqa: SLF001


# ---------------------------------------------------------------------------
# Config: domain field
# ---------------------------------------------------------------------------


class TestConfigDomainField:
    """AppConfig includes a domain field with default 'localhost'."""

    def test_default_domain(self) -> None:
        config = _make_config()
        assert config.domain == "localhost"

    def test_custom_domain(self) -> None:
        config = AppConfig(
            database_url="postgresql://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
            domain="example.com",
        )
        assert config.domain == "example.com"


# ---------------------------------------------------------------------------
# App routing structure
# ---------------------------------------------------------------------------


class TestAppRouting:
    """app.py has Host-based subdomain routing and path-based fallbacks."""

    def test_app_has_host_routes(self) -> None:
        from osu_server.app import create_app

        app = create_app()
        host_routes = [r for r in app.routes if isinstance(r, Host)]
        assert len(host_routes) >= _EXPECTED_MIN_HOST_ROUTES, (
            "Expected at least 2 Host routes (bancho + web_legacy)"
        )

    def test_app_has_bancho_host_route(self) -> None:
        from osu_server.app import create_app

        app = create_app()
        host_routes = [r for r in app.routes if isinstance(r, Host)]
        host_patterns = [r.host for r in host_routes]
        assert any("c." in h for h in host_patterns), (
            f"Expected a Host route containing 'c.' for bancho, got {host_patterns}"
        )

    def test_app_has_web_legacy_host_route(self) -> None:
        from osu_server.app import create_app

        app = create_app()
        host_routes = [r for r in app.routes if isinstance(r, Host)]
        host_patterns = [r.host for r in host_routes]
        assert any("osu." in h for h in host_patterns), (
            f"Expected a Host route containing 'osu.' for web_legacy, got {host_patterns}"
        )

    def test_app_has_fallback_post_root(self) -> None:
        """Path-based fallback: POST / exists for local dev without subdomains."""
        from osu_server.app import create_app

        app = create_app()
        path_routes = [r for r in app.routes if isinstance(r, Route)]
        root_routes = [r for r in path_routes if r.path == "/"]
        assert len(root_routes) >= 1, "Expected a fallback Route for POST /"

    def test_app_has_fallback_web_mount(self) -> None:
        """Path-based fallback: Mount /web exists for local dev without subdomains."""
        from osu_server.app import create_app

        app = create_app()
        mount_routes = [r for r in app.routes if isinstance(r, Mount)]
        web_mounts = [r for r in mount_routes if r.path == "/web"]
        assert len(web_mounts) >= 1, "Expected a fallback Mount for /web"

    def test_app_import_succeeds(self) -> None:
        """python -c 'from osu_server.app import app' should not raise."""
        from osu_server.app import app  # noqa: F401
