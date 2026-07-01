"""Tests for Starlette-independent login workflow orchestration."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, TypeVar, cast, final, override

import structlog.contextvars
import structlog.testing

from osu_server.domain.events.users import UserConnected
from osu_server.domain.identity.authentication import LoginRequest, LoginResponse, LoginResult
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import SessionData
from osu_server.services.commands.identity import LoginCommandInput, LoginCommandResult
from osu_server.services.queries.chat import ChannelCatalogQueryResult
from osu_server.services.queries.identity import (
    ListActiveSessionsQueryResult,
    ListFriendIdsQueryResult,
)
from osu_server.services.queries.scores import (
    CurrentUserStatsQueryInput,
    CurrentUserStatsQueryResult,
)
from osu_server.transports.stable.bancho.protocol.s2c.login import login_reply
from osu_server.transports.stable.bancho.workflows import (
    LoginResponseBuilder,
    LoginWorkflow,
    LoginWorkflowInput,
    LoginWorkflowResult,
)
from tests.factories.domain import make_user

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from osu_server.services.queries.chat import (
        ListAutojoinChannelsQuery,
        ListVisibleChannelsQuery,
    )
    from osu_server.services.queries.identity import (
        ListActiveSessionsQueryUseCase,
        ListFriendIdsQueryUseCase,
    )
    from osu_server.services.queries.scores import CurrentUserStatsQuery

_PASSWORD = "SecurePass1234"
_PASSWORD_MD5 = hashlib.md5(_PASSWORD.encode()).hexdigest()
_SUCCESS_STREAM = b"successful-login-stream"
_USER_ID = 42
_ROLE_ID = 1
_UTC_OFFSET = 9
TEvent = TypeVar("TEvent", bound=object)


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
class _RecordingLoginCommand:
    """Login command fake that records parsed login input."""

    _result: LoginResponse | LoginResult
    login_request: LoginRequest | None
    country: str | None

    def __init__(self, result: LoginResponse | LoginResult) -> None:
        self._result = result
        self.login_request = None
        self.country = None

    async def execute(
        self,
        input_data: LoginCommandInput,
    ) -> LoginCommandResult:
        self.login_request = input_data.login_request
        self.country = input_data.country
        return LoginCommandResult(outcome=self._result)


@final
class _RecordingLocalEventBus:
    """Local event bus fake that records fired events."""

    events: list[object]
    raise_on_fire: bool

    def __init__(self, *, raise_on_fire: bool = False) -> None:
        self.events = []
        self.raise_on_fire = raise_on_fire

    async def fire(self, event: object) -> None:
        if self.raise_on_fire:
            raise RuntimeError("event fan-out failed")
        self.events.append(event)

    def subscribe(
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], Awaitable[None]],
    ) -> None:
        _ = event_type
        _ = handler


@final
class _EmptyChannelCatalogQuery:
    async def execute(self, _input_data: object) -> ChannelCatalogQueryResult:
        return ChannelCatalogQueryResult(channels=())


@final
class _EmptyFriendIdsQuery:
    async def execute(self, _input_data: object) -> ListFriendIdsQueryResult:
        return ListFriendIdsQueryResult(friend_user_ids=())


@final
class _EmptyActiveSessionsQuery:
    async def execute(self, _input_data: object) -> ListActiveSessionsQueryResult:
        return ListActiveSessionsQueryResult(sessions=())


@final
class _EmptyCurrentUserStatsQuery:
    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        _ = input_data
        return CurrentUserStatsQueryResult(stats=())


@final
class _RecordingLoginResponseBuilder(LoginResponseBuilder):
    """Login response builder fake that records successful responses."""

    _content: bytes
    login_response: LoginResponse | None

    def __init__(
        self,
        *,
        content: bytes = _SUCCESS_STREAM,
    ) -> None:
        empty_query = _EmptyChannelCatalogQuery()
        friend_ids_query = _EmptyFriendIdsQuery()
        active_sessions_query = _EmptyActiveSessionsQuery()
        current_stats_query = _EmptyCurrentUserStatsQuery()
        super().__init__(
            visible_channels_query=cast(
                "ListVisibleChannelsQuery",
                cast("object", empty_query),
            ),
            autojoin_channels_query=cast(
                "ListAutojoinChannelsQuery",
                cast("object", empty_query),
            ),
            friend_ids_query=cast(
                "ListFriendIdsQueryUseCase",
                cast("object", friend_ids_query),
            ),
            active_sessions_query=cast(
                "ListActiveSessionsQueryUseCase",
                cast("object", active_sessions_query),
            ),
            current_user_stats_query=cast(
                "CurrentUserStatsQuery",
                cast("object", current_stats_query),
            ),
        )
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
    event_bus: _RecordingLocalEventBus | None = None,
) -> tuple[
    LoginWorkflow,
    _RecordingLoginCommand,
    _RecordingCountryResolver,
    _RecordingLoginResponseBuilder,
    _RecordingLocalEventBus,
]:
    login_command = _RecordingLoginCommand(auth_result)
    resolver = country_resolver or _RecordingCountryResolver()
    builder = response_builder or _RecordingLoginResponseBuilder()
    local_event_bus = event_bus or _RecordingLocalEventBus()
    workflow = LoginWorkflow(
        login_command=login_command,
        country_resolver=resolver,
        response_builder=builder,
        event_bus=local_event_bus,
    )
    return workflow, login_command, resolver, builder, local_event_bus


def _contextvars() -> Mapping[str, object]:
    return cast("Mapping[str, object]", structlog.contextvars.get_contextvars())


class TestLoginWorkflow:
    async def test_parse_failure_returns_auth_failed_packet_without_token_and_logs(self) -> None:
        workflow, login_command, country_resolver, response_builder, event_bus = _make_workflow(
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
        assert login_command.login_request is None
        assert country_resolver.headers is None
        assert response_builder.login_response is None
        assert event_bus.events == []
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
        workflow, login_command, resolver, response_builder, event_bus = _make_workflow(
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
        assert login_command.login_request is not None
        assert login_command.login_request.username == "TestUser"
        assert login_command.country == "US"
        assert resolver.headers is headers
        assert response_builder.login_response is None
        assert event_bus.events == []
        assert "user" not in _contextvars()
        assert "user_id" not in _contextvars()

    async def test_success_delegates_response_building_and_returns_issued_token(self) -> None:
        login_response = _login_response()
        headers = {"x-real-ip": "203.0.113.20"}
        response_builder = _RecordingLoginResponseBuilder(
            content=_SUCCESS_STREAM,
        )
        workflow, login_command, resolver, builder, event_bus = _make_workflow(
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
            assert login_command.login_request is not None
            assert login_command.login_request.username == "TestUser"
            assert login_command.country == "JP"
            assert resolver.headers is headers
            assert builder.login_response is login_response
            assert event_bus.events == [UserConnected(user_id=login_response.user.id)]
            context = _contextvars()
            assert context.get("user") == login_response.user.username
            assert context.get("user_id") == login_response.user.id
        finally:
            structlog.contextvars.clear_contextvars()

    async def test_success_still_returns_login_result_when_connected_event_fails(self) -> None:
        login_response = _login_response()
        event_bus = _RecordingLocalEventBus(raise_on_fire=True)
        workflow, _, _, _, _ = _make_workflow(
            auth_result=login_response,
            event_bus=event_bus,
        )

        result = await workflow.execute(
            LoginWorkflowInput(body=_build_login_body(), headers={"x-real-ip": "203.0.113.20"})
        )

        assert result == LoginWorkflowResult(
            content=_SUCCESS_STREAM,
            cho_token=login_response.token,
        )
