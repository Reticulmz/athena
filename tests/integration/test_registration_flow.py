# pyright: reportUnknownMemberType=false, reportAny=false, reportPrivateUsage=false
"""E2E integration tests for the osu! stable account registration flow.

Tests the full POST /web/users request -> response cycle through all layers
with InMemory repositories (ENVIRONMENT=test).

Covers:
- Registration validation (check=1): validate only, no DB write
- Registration creation (check=0): validate + create account
- Duplicate username error
- Short password error
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from osu_server.app import create_app
from osu_server.domain.role import Privileges, Role
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette

    from osu_server.infrastructure.di.container import Container

# ── Seed data ────────────────────────────────────────────────────────────

_DEFAULT_ROLE = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED,
    position=0,
)


@contextmanager
def _test_env() -> Generator[None]:
    """Temporarily set ENVIRONMENT=test for the duration of the block."""
    old = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "test"
    _ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
    _ = os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    try:
        yield
    finally:
        if old is None:
            _ = os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = old


def _seed_default_role(app: Starlette) -> None:
    """Seed the Default role into the InMemoryRoleRepository.

    Must be called after TestClient enters (lifespan has run).
    """
    container: Container = app.state.container
    registration = container._registrations[RoleRepository]  # noqa: SLF001
    repo = registration.instance
    assert isinstance(repo, InMemoryRoleRepository)
    repo._roles_by_id[_DEFAULT_ROLE.id] = _DEFAULT_ROLE  # noqa: SLF001
    repo._roles_by_name[_DEFAULT_ROLE.name] = _DEFAULT_ROLE.id  # noqa: SLF001


def _registration_form(
    *,
    username: str = "TestPlayer",
    email: str = "test@example.com",
    password: str = "ExamplePass1234",
    check: str = "0",
) -> dict[str, str]:
    """Build a registration form data dict."""
    return {
        "user[username]": username,
        "user[user_email]": email,
        "user[password]": password,
        "check": check,
    }


class TestRegistrationValidation:
    """POST /web/users with check=1 validates only, never creates an account."""

    def test_check_only_returns_ok(self) -> None:
        """Valid form with check=1 returns 200 ok without creating a user."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/web/users",
                    data=_registration_form(check="1"),
                )

                assert response.status_code == HTTPStatus.OK
                assert response.content == b"ok"

    def test_check_only_does_not_create_user(self) -> None:
        """After check=1, a subsequent registration with the same username succeeds."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                # First: validate only
                resp_check = client.post(
                    "/web/users",
                    data=_registration_form(check="1"),
                )
                assert resp_check.status_code == HTTPStatus.OK

                # Second: actually create — should succeed because check=1 didn't create
                resp_create = client.post(
                    "/web/users",
                    data=_registration_form(check="0"),
                )
                assert resp_create.status_code == HTTPStatus.OK
                assert resp_create.content == b"ok"


class TestRegistrationCreation:
    """POST /web/users with check=0 validates and creates an account."""

    def test_successful_registration_returns_ok(self) -> None:
        """Valid form with check=0 returns 200 ok."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                response = client.post(
                    "/web/users",
                    data=_registration_form(),
                )

                assert response.status_code == HTTPStatus.OK
                assert response.content == b"ok"


class TestRegistrationErrors:
    """POST /web/users returns 400 form_error for invalid input."""

    def test_duplicate_username_returns_form_error(self) -> None:
        """Registering the same username twice returns 400 with username error."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                # First registration succeeds
                resp1 = client.post(
                    "/web/users",
                    data=_registration_form(),
                )
                assert resp1.status_code == HTTPStatus.OK

                # Second registration with same username fails
                resp2 = client.post(
                    "/web/users",
                    data=_registration_form(email="other@example.com"),
                )
                assert resp2.status_code == HTTPStatus.BAD_REQUEST

                body = json.loads(resp2.content)
                assert "form_error" in body
                assert "username" in body["form_error"]["user"]

    def test_short_password_returns_form_error(self) -> None:
        """Password below minimum length returns 400 with password error."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/web/users",
                    data=_registration_form(password="ab"),
                )

                assert response.status_code == HTTPStatus.BAD_REQUEST

                body = json.loads(response.content)
                assert "form_error" in body
                assert "password" in body["form_error"]["user"]

    def test_invalid_email_returns_form_error(self) -> None:
        """Invalid email format returns 400 with email error."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/web/users",
                    data=_registration_form(email="not-an-email"),
                )

                assert response.status_code == HTTPStatus.BAD_REQUEST

                body = json.loads(response.content)
                assert "form_error" in body
                assert "email" in body["form_error"]["user"]

    def test_duplicate_email_returns_form_error(self) -> None:
        """Registering the same email twice returns 400 with email error."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                resp1 = client.post(
                    "/web/users",
                    data=_registration_form(),
                )
                assert resp1.status_code == HTTPStatus.OK

                resp2 = client.post(
                    "/web/users",
                    data=_registration_form(username="OtherPlayer"),
                )
                assert resp2.status_code == HTTPStatus.BAD_REQUEST

                body = json.loads(resp2.content)
                assert "form_error" in body
                assert "email" in body["form_error"]["user"]
