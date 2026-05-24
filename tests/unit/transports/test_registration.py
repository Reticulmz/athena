"""RegistrationHandler (POST /users) unit tests.

TDD RED -> GREEN -> REFACTOR.
Tests: successful registration, validation errors, check=1 mode (validate only).

Uses Starlette TestClient with a minimal app that routes POST /users to the handler.
Real AuthService with InMemoryUserRepository, InMemoryRoleRepository, real PasswordService.
"""

from __future__ import annotations

import json
from http import HTTPStatus

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.domain.role import Privileges, Role
from osu_server.infrastructure.state.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.auth_service import AuthService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.transports.web_legacy.registration import RegistrationHandler

# ── Seed data ────────────────────────────────────────────────────────

_ROLE_DEFAULT = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED,
    position=0,
)

_OK = HTTPStatus.OK
_BAD_REQUEST = HTTPStatus.BAD_REQUEST


# ── Helpers ──────────────────────────────────────────────────────────


def _make_app() -> tuple[
    Starlette,
    AuthService,
    InMemoryUserRepository,
    InMemoryRoleRepository,
]:
    """Build a Starlette app with RegistrationHandler wired to POST /users."""
    user_repo = InMemoryUserRepository()
    role_repo = InMemoryRoleRepository(seed_roles=[_ROLE_DEFAULT])
    password_service = PasswordService(hibp_client=None, banned_passwords=[])

    session_store = InMemorySessionStore()
    permission_service = PermissionService(role_repo=role_repo)

    auth_service = AuthService(
        user_repo=user_repo,
        role_repo=role_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
    )

    handler = RegistrationHandler(auth_service=auth_service)

    # Starlette treats callable objects as ASGI apps, but we need
    # request_response wrapping. Pass the bound method instead.
    app = Starlette(routes=[Route("/users", handler.__call__, methods=["POST"])])
    return app, auth_service, user_repo, role_repo


def _registration_form(
    *,
    username: str = "TestUser",
    email: str = "test@example.com",
    password: str = "SecurePass1234",
    check: str = "0",
) -> dict[str, str]:
    """Build form data matching osu! client registration format."""
    return {
        "user[username]": username,
        "user[user_email]": email,
        "user[password]": password,
        "check": check,
    }


# ═══════════════════════════════════════════════════════════════════════
# Successful registration (Req 1.1, 1.2, 2.2)
# ═══════════════════════════════════════════════════════════════════════


class TestRegistrationSuccess:
    """POST /users with valid data and check=0 creates an account."""

    async def test_returns_ok_with_body(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post("/users", data=_registration_form())
            assert resp.status_code == _OK
            assert resp.content == b"ok"

    async def test_user_persisted_in_repository(self) -> None:
        app, _, user_repo, _ = _make_app()
        with TestClient(app) as client:
            client.post("/users", data=_registration_form())
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        assert user.username == "TestUser"

    async def test_default_role_assigned(self) -> None:
        app, _, _, role_repo = _make_app()
        with TestClient(app) as client:
            client.post("/users", data=_registration_form())
        # User id=1 (first created user)
        roles = await role_repo.get_roles_for_user(1)
        assert len(roles) == 1
        assert roles[0].name == "Default"


# ═══════════════════════════════════════════════════════════════════════
# Validation errors (Req 1.4, 3.1, 3.3)
# ═══════════════════════════════════════════════════════════════════════


class TestRegistrationValidationError:
    """POST /users with invalid data returns 400 with form_error JSON."""

    async def test_bad_username_returns_400(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(username="x"),  # too short
            )
            assert resp.status_code == _BAD_REQUEST

    async def test_bad_username_error_format(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(username="x"),
            )
            body = json.loads(resp.content)
            assert "form_error" in body
            assert "user" in body["form_error"]
            assert "username" in body["form_error"]["user"]
            assert isinstance(body["form_error"]["user"]["username"], list)

    async def test_bad_password_returns_400(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(password="short"),  # too short
            )
            assert resp.status_code == _BAD_REQUEST
            body = json.loads(resp.content)
            assert "password" in body["form_error"]["user"]

    async def test_bad_email_returns_400(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(email="not-an-email"),
            )
            assert resp.status_code == _BAD_REQUEST
            body = json.loads(resp.content)
            assert "email" in body["form_error"]["user"]

    async def test_multiple_errors_accumulated(self) -> None:
        """All field errors returned in a single response."""
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(
                    username="x",
                    password="short",
                    email="bad",
                ),
            )
            assert resp.status_code == _BAD_REQUEST
            body = json.loads(resp.content)
            errors = body["form_error"]["user"]
            assert "username" in errors
            assert "password" in errors
            assert "email" in errors

    async def test_duplicate_username_returns_400(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            # First registration succeeds
            client.post("/users", data=_registration_form())
            # Second with same username fails
            resp = client.post(
                "/users",
                data=_registration_form(email="other@example.com"),
            )
            assert resp.status_code == _BAD_REQUEST
            body = json.loads(resp.content)
            assert "username" in body["form_error"]["user"]

    async def test_duplicate_email_returns_400(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            client.post("/users", data=_registration_form())
            resp = client.post(
                "/users",
                data=_registration_form(username="OtherUser"),
            )
            assert resp.status_code == _BAD_REQUEST
            body = json.loads(resp.content)
            assert "email" in body["form_error"]["user"]


# ═══════════════════════════════════════════════════════════════════════
# Check-only mode (Req 2.1, 2.3)
# ═══════════════════════════════════════════════════════════════════════


class TestRegistrationCheckOnly:
    """check=1 validates without creating an account."""

    async def test_check_only_valid_returns_ok(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(check="1"),
            )
            assert resp.status_code == _OK
            assert resp.content == b"ok"

    async def test_check_only_does_not_create_user(self) -> None:
        app, _, user_repo, _ = _make_app()
        with TestClient(app) as client:
            client.post(
                "/users",
                data=_registration_form(check="1"),
            )
        user = await user_repo.get_by_safe_username("testuser")
        assert user is None

    async def test_check_only_invalid_returns_400(self) -> None:
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(username="x", check="1"),
            )
            assert resp.status_code == _BAD_REQUEST
            body = json.loads(resp.content)
            assert "username" in body["form_error"]["user"]
