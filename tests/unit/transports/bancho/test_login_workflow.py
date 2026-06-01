"""Tests for Starlette-independent login workflow orchestration."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, cast, final, override

import structlog.contextvars
import structlog.testing

from osu_server.domain.auth import LoginRequest, LoginResponse, LoginResult
from osu_server.domain.role import Privileges
from osu_server.domain.session import SessionData
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.auth_service import AuthService
from osu_server.services.channel_service import ChannelService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.transports.bancho.protocol.s2c.login import login_reply
from osu_server.transports.bancho.workflows import (
    LoginResponseBuilder,
    LoginWorkflow,
    LoginWorkflowInput,
    LoginWorkflowResult,
)
from tests.factories.domain import make_user

if TYPE_CHECKING:
    from collections.abc import Mapping

_PASSWORD = "SecurePass1234"
_PASSWORD_MD5 = hashlib.md5(_PASSWORD.encode()).hexdigest()
_SUCCESS_STREAM = b"successful-login-stream"
_USER_ID = 42
_ROLE_ID = 1
_UTC_OFFSET = 9


@final
class _RecordingCountryResolver:
    """Country resolver that records the header mapping it received."""

    _country: str
    headers: Mapping[str, str] | None

    def __init__(self, country: str = "JP") -> None:
        self._country = country
        self.headers = None

    def resolve(self, headers: Mapping[str, str]) -> str:
        self.headers = headers
        return self._country


@final
class _RecordingAuthService(AuthService):
    """Auth service fake that records parsed login input."""

    _result: LoginResponse | LoginResult
    login_request: LoginRequest | None
    country: str | None

    def __init__(self, result: LoginResponse | LoginResult) -> None:
        role_repo = InMemoryRoleRepository()
        super().__init__(
            user_repo=InMemoryUserRepository(),
            role_repo=role_repo,
            password_service=PasswordService(hibp_client=None, banned_passwords=[]),
            permission_service=PermissionService(role_repo=role_repo),
            session_store=InMemorySessionStore(),
        )
        self._result = result
        self.login_request = None
        self.country = None

    @override
    async def login(
        self,
        login_request: LoginRequest,
        *,
        country: str,
    ) -> LoginResponse | LoginResult:
        self.login_request = login_request
        self.country = country
        return self._result


@final
class _RecordingLoginResponseBuilder(LoginResponseBuilder):
    """Login response builder fake that records successful responses."""

    _content: bytes
    login_response: LoginResponse | None

    def __init__(
        self,
        *,
        channel_service: ChannelService,
        content: bytes = _SUCCESS_STREAM,
    ) -> None:
        super().__init__(channel_service=channel_service)
        self._content = content
        self.login_response = None

    @override
    async def build(self, login_response: LoginResponse) -> bytes:
        self.login_response = login_response
        return self._content


def _build_login_body(
    *,
    username: str = "TestUser",
    password_md5: str = _PASSWORD_MD5,
    osu_version: str = "20231111",
    utc_offset: int = _UTC_OFFSET,
    display_city: int = 1,
    client_hashes: str = "hash1:hash2:hash3",
    pm_private: int = 0,
) -> bytes:
    client_info = f"{osu_version}|{utc_offset}|{display_city}|{client_hashes}|{pm_private}"
    return f"{username}\n{password_md5}\n{client_info}\n".encode()


def _make_channel_service() -> ChannelService:
    return ChannelService(
        channel_repo=InMemoryChannelRepository(),
        channel_state=InMemoryChannelStateStore(),
    )


def _login_response() -> LoginResponse:
    user = make_user(id=_USER_ID, username="TestUser", country="JP")
    privileges = Privileges.NORMAL | Privileges.VERIFIED
    return LoginResponse(
        token="issued-token",
        user=user,
        privileges=privileges,
        role_ids=(_ROLE_ID,),
        country="JP",
        session_data=SessionData(
            user_id=user.id,
            username=user.username,
            privileges=int(privileges),
            country="JP",
            osu_version="20231111",
            utc_offset=_UTC_OFFSET,
            display_city=False,
            client_hashes="hash1:hash2:hash3",
            pm_private=False,
        ),
    )


def _make_workflow(
    *,
    auth_result: LoginResponse | LoginResult,
    country_resolver: _RecordingCountryResolver | None = None,
    response_builder: _RecordingLoginResponseBuilder | None = None,
) -> tuple[
    LoginWorkflow,
    _RecordingAuthService,
    _RecordingCountryResolver,
    _RecordingLoginResponseBuilder,
]:
    auth_service = _RecordingAuthService(auth_result)
    resolver = country_resolver or _RecordingCountryResolver()
    builder = response_builder or _RecordingLoginResponseBuilder(
        channel_service=_make_channel_service()
    )
    workflow = LoginWorkflow(
        auth_service=auth_service,
        country_resolver=resolver,
        response_builder=builder,
    )
    return workflow, auth_service, resolver, builder


def _contextvars() -> Mapping[str, object]:
    return cast("Mapping[str, object]", structlog.contextvars.get_contextvars())


class TestLoginWorkflow:
    async def test_parse_failure_returns_auth_failed_packet_without_token_and_logs(self) -> None:
        workflow, auth_service, country_resolver, response_builder = _make_workflow(
            auth_result=_login_response()
        )
        structlog.contextvars.clear_contextvars()

        with structlog.testing.capture_logs() as logs:
            result = await workflow.execute(
                LoginWorkflowInput(body=b"malformed\x00garbage", headers={"x-test": "1"})
            )

        assert result == LoginWorkflowResult(
            content=login_reply(LoginResult.AUTHENTICATION_FAILED),
            cho_token=None,
        )
        assert auth_service.login_request is None
        assert country_resolver.headers is None
        assert response_builder.login_response is None
        parse_logs = [
            log
            for log in cast("list[dict[str, object]]", logs)
            if log.get("event") == "login_parse_failed"
        ]
        assert len(parse_logs) == 1
        assert parse_logs[0].get("log_level") == "warning"
        assert "user" not in _contextvars()
        assert "user_id" not in _contextvars()

    async def test_auth_rejection_returns_login_result_packet_without_token(self) -> None:
        headers = {"x-real-ip": "203.0.113.10"}
        country_resolver = _RecordingCountryResolver(country="US")
        workflow, auth_service, resolver, response_builder = _make_workflow(
            auth_result=LoginResult.AUTHENTICATION_FAILED,
            country_resolver=country_resolver,
        )
        structlog.contextvars.clear_contextvars()

        result = await workflow.execute(
            LoginWorkflowInput(body=_build_login_body(), headers=headers)
        )

        assert result == LoginWorkflowResult(
            content=login_reply(LoginResult.AUTHENTICATION_FAILED),
            cho_token=None,
        )
        assert auth_service.login_request is not None
        assert auth_service.login_request.username == "TestUser"
        assert auth_service.country == "US"
        assert resolver.headers is headers
        assert response_builder.login_response is None
        assert "user" not in _contextvars()
        assert "user_id" not in _contextvars()

    async def test_success_delegates_response_building_and_returns_issued_token(self) -> None:
        login_response = _login_response()
        headers = {"x-real-ip": "203.0.113.20"}
        response_builder = _RecordingLoginResponseBuilder(
            channel_service=_make_channel_service(),
            content=_SUCCESS_STREAM,
        )
        workflow, auth_service, resolver, builder = _make_workflow(
            auth_result=login_response,
            response_builder=response_builder,
        )
        structlog.contextvars.clear_contextvars()

        try:
            result = await workflow.execute(
                LoginWorkflowInput(body=_build_login_body(), headers=headers)
            )

            assert result == LoginWorkflowResult(
                content=_SUCCESS_STREAM,
                cho_token=login_response.token,
            )
            assert auth_service.login_request is not None
            assert auth_service.login_request.username == "TestUser"
            assert auth_service.country == "JP"
            assert resolver.headers is headers
            assert builder.login_response is login_response
            context = _contextvars()
            assert context.get("user") == login_response.user.username
            assert context.get("user_id") == login_response.user.id
        finally:
            structlog.contextvars.clear_contextvars()
