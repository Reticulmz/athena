"""Stable web legacy RegistrationHandlerのunit testを提供する."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import cast

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.repositories.memory.queries import (
    InMemoryRoleQueryRepository,
    InMemoryUserQueryRepository,
)
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.identity import RegisterUserCommandUseCase
from osu_server.services.commands.identity.auth_service import AuthService
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.identity.permission_service import PermissionService
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler

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
    RegisterUserCommandUseCase,
    InMemoryUserQueryRepository,
    InMemoryRoleQueryRepository,
]:
    """RegistrationHandlerをPOST /usersへ配線したin-memory test appを構築する.

    Returns:
        tuple: Starlette app, registration command, user query repository, role query repository.
    """
    uow_factory = InMemoryUnitOfWorkFactory()
    uow_factory.seed_roles([_ROLE_DEFAULT])

    user_query_repo = InMemoryUserQueryRepository(uow_factory)
    role_query_repo = InMemoryRoleQueryRepository(uow_factory)
    password_service = PasswordService(hibp_client=None, banned_passwords=[])

    session_store = InMemorySessionStore()
    permission_service = PermissionService(role_repo=role_query_repo)

    auth_service = AuthService(
        uow_factory=uow_factory,
        user_query_repo=user_query_repo,
        role_query_repo=role_query_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
    )

    register_user_command = RegisterUserCommandUseCase(auth_service=auth_service)
    handler = RegistrationHandler(register_user_command=register_user_command)

    # Starlette treats callable objects as ASGI apps, but we need
    # request_response wrapping. Pass the bound method instead.
    app = Starlette(routes=[Route("/users", handler.__call__, methods=["POST"])])
    return app, register_user_command, user_query_repo, role_query_repo


def _registration_form(
    *,
    username: str = "TestUser",
    email: str = "test@example.com",
    password: str = "SecurePass1234",
    check: str = "0",
) -> dict[str, str]:
    """Stable client registration formatに一致するform dataを構築する.

    Args:
        username (str): user[username]へ設定する表示名.
        email (str): user[user_email]へ設定するemail address.
        password (str): user[password]へ設定するplain text password.
        check (str): validate-only modeを示すcheck field値.

    Returns:
        dict[str, str]: legacy endpointへ渡すregistration form mapping.
    """
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
    """Valid formとcheck=0によるaccount作成を検証する."""

    async def test_returns_ok_with_body(self) -> None:
        """Successful registrationがok bodyを持つHTTP 200を返すcontractを検証する.

        Returns:
            None: response statusとexact bodyを確認して完了する.
        """
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post("/users", data=_registration_form())
            assert resp.status_code == _OK
            assert resp.content == b"ok"

    async def test_user_persisted_in_repository(self) -> None:
        """Successful registrationがuser query repositoryへ保存されるcontractを検証する.

        Returns:
            None: normalized lookup後のusernameを確認して完了する.
        """
        app, _, user_repo, _ = _make_app()
        with TestClient(app) as client:
            _ = client.post("/users", data=_registration_form())
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        assert user.username == "TestUser"

    async def test_default_role_assigned(self) -> None:
        """Successful registrationがDefault roleをuserへ割り当てるcontractを検証する.

        Returns:
            None: 作成userがDefault roleを1件だけ持つことを確認して完了する.
        """
        app, _, user_repo, role_repo = _make_app()
        with TestClient(app) as client:
            _ = client.post("/users", data=_registration_form())
        # First created user gets id > 1 (id=1 reserved for BanchoBot system user)
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        roles = await role_repo.get_roles_for_user(user.id)
        assert len(roles) == 1
        assert roles[0].name == "Default"


# ═══════════════════════════════════════════════════════════════════════
# Validation errors (Req 1.4, 3.1, 3.3)
# ═══════════════════════════════════════════════════════════════════════


class TestRegistrationValidationError:
    """Invalid registration formがform_error JSONを持つHTTP 400となることを検証する."""

    async def test_bad_username_returns_400(self) -> None:
        """短すぎるusernameをHTTP 400で拒否するcontractを検証する.

        Returns:
            None: invalid username responseのstatusを確認して完了する.
        """
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(username="x"),  # too short
            )
            assert resp.status_code == _BAD_REQUEST

    async def test_bad_username_error_format(self) -> None:
        """Invalid username errorがlegacy form_error JSON shapeを保つcontractを検証する.

        Returns:
            None: user.username errorがlistとして存在することを確認して完了する.
        """
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(username="x"),
            )
            body = cast("dict[str, object]", json.loads(resp.content))
            assert "form_error" in body
            form_error = cast("dict[str, object]", body["form_error"])
            assert "user" in form_error
            user_err = cast("dict[str, object]", form_error["user"])
            assert "username" in user_err
            assert isinstance(user_err["username"], list)

    async def test_bad_password_returns_400(self) -> None:
        """短すぎるpasswordをHTTP 400とpassword errorで拒否するcontractを検証する.

        Returns:
            None: form_error内にpassword field errorがあることを確認して完了する.
        """
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(password="short"),  # too short
            )
            assert resp.status_code == _BAD_REQUEST
            body = cast("dict[str, object]", json.loads(resp.content))
            form_error = cast("dict[str, object]", body["form_error"])
            user_err = cast("dict[str, object]", form_error["user"])
            assert "password" in user_err

    async def test_bad_email_returns_400(self) -> None:
        """Invalid email addressをHTTP 400とemail errorで拒否するcontractを検証する.

        Returns:
            None: form_error内にemail field errorがあることを確認して完了する.
        """
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(email="not-an-email"),
            )
            assert resp.status_code == _BAD_REQUEST
            body = cast("dict[str, object]", json.loads(resp.content))
            form_error = cast("dict[str, object]", body["form_error"])
            user_err = cast("dict[str, object]", form_error["user"])
            assert "email" in user_err

    async def test_multiple_errors_accumulated(self) -> None:
        """複数のinvalid field errorを1つのresponseへ集約するcontractを検証する.

        Returns:
            None: username, password, emailの全errorが同時に存在することを確認して完了する.
        """
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
            body = cast("dict[str, object]", json.loads(resp.content))
            form_error = cast("dict[str, object]", body["form_error"])
            errors = cast("dict[str, object]", form_error["user"])
            assert "username" in errors
            assert "password" in errors
            assert "email" in errors

    async def test_duplicate_username_returns_400(self) -> None:
        """既存usernameによる2回目のregistrationをHTTP 400で拒否するcontractを検証する.

        Returns:
            None: form_error内にusername field errorがあることを確認して完了する.
        """
        app, *_ = _make_app()
        with TestClient(app) as client:
            # First registration succeeds
            _ = client.post("/users", data=_registration_form())
            # Second with same username fails
            resp = client.post(
                "/users",
                data=_registration_form(email="other@example.com"),
            )
            assert resp.status_code == _BAD_REQUEST
            body = cast("dict[str, object]", json.loads(resp.content))
            form_error = cast("dict[str, object]", body["form_error"])
            user_err = cast("dict[str, object]", form_error["user"])
            assert "username" in user_err

    async def test_duplicate_email_returns_400(self) -> None:
        """既存emailによる2回目のregistrationをHTTP 400で拒否するcontractを検証する.

        Returns:
            None: form_error内にemail field errorがあることを確認して完了する.
        """
        app, *_ = _make_app()
        with TestClient(app) as client:
            _ = client.post("/users", data=_registration_form())
            resp = client.post(
                "/users",
                data=_registration_form(username="OtherUser"),
            )
            assert resp.status_code == _BAD_REQUEST
            body = cast("dict[str, object]", json.loads(resp.content))
            form_error = cast("dict[str, object]", body["form_error"])
            user_err = cast("dict[str, object]", form_error["user"])
            assert "email" in user_err


# ═══════════════════════════════════════════════════════════════════════
# Check-only mode (Req 2.1, 2.3)
# ═══════════════════════════════════════════════════════════════════════


class TestRegistrationCheckOnly:
    """check=1がaccountを作らないvalidate-only modeとなることを検証する."""

    async def test_check_only_valid_returns_ok(self) -> None:
        """Valid check-only requestがok bodyを持つHTTP 200を返すcontractを検証する.

        Returns:
            None: response statusとexact bodyを確認して完了する.
        """
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(check="1"),
            )
            assert resp.status_code == _OK
            assert resp.content == b"ok"

    async def test_check_only_does_not_create_user(self) -> None:
        """Check-only requestがuser recordを作成しないcontractを検証する.

        Returns:
            None: request後のuser lookupがNoneであることを確認して完了する.
        """
        app, _, user_repo, _ = _make_app()
        with TestClient(app) as client:
            _ = client.post(
                "/users",
                data=_registration_form(check="1"),
            )
        user = await user_repo.get_by_safe_username("testuser")
        assert user is None

    async def test_check_only_invalid_returns_400(self) -> None:
        """Invalid check-only requestがvalidation errorを返すcontractを検証する.

        Returns:
            None: form_error内にusername field errorがあることを確認して完了する.
        """
        app, *_ = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/users",
                data=_registration_form(username="x", check="1"),
            )
            assert resp.status_code == _BAD_REQUEST
            body = cast("dict[str, object]", json.loads(resp.content))
            form_error = cast("dict[str, object]", body["form_error"])
            user_err = cast("dict[str, object]", form_error["user"])
            assert "username" in user_err
