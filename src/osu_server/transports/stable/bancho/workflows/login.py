"""Stable Bancho login request の解析, 認証, response 構築を orchestrate する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
import structlog.contextvars

from osu_server.domain.events.users import UserConnected
from osu_server.domain.identity.authentication import LoginResult
from osu_server.services.commands.identity import LoginCommandInput
from osu_server.transports.stable.bancho.parsers.login import parse_login_request
from osu_server.transports.stable.bancho.protocol.s2c.login import login_reply

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.infrastructure.country.interfaces import CountryResolver
    from osu_server.infrastructure.messaging.local import LocalEventBus
    from osu_server.services.commands.identity import LoginCommand
    from osu_server.transports.stable.bancho.workflows.login_response_builder import (
        LoginResponseBuilder,
    )

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(slots=True, frozen=True)
class LoginWorkflowInput:
    """Starlette に依存しない login workflow の入力を表す.

    Attributes:
        body (bytes): stable client が送った raw login request body.
        headers (Mapping[str, str]): country resolver へ渡す HTTP request header.
    """

    body: bytes
    headers: Mapping[str, str]


@dataclass(slots=True, frozen=True)
class LoginWorkflowResult:
    """Starlette に依存しない login workflow の response を表す.

    Attributes:
        content (bytes): client へ返す S2C packet stream.
        cho_token (str | None): 成功時の session token. login failure 時は None.
    """

    content: bytes
    cho_token: str | None


class LoginWorkflow:
    """Stable Bancho login の解析, 認証, success response 構築を orchestrate する.

    Attributes:
        _login_command (LoginCommand): login request を認証して session を作る command.
        _country_resolver (CountryResolver): request header から country を解決する dependency.
        _response_builder (LoginResponseBuilder): success response を構築する builder.
        _event_bus (LocalEventBus): successful connection を通知する local event bus.
    """

    _login_command: LoginCommand
    _country_resolver: CountryResolver
    _response_builder: LoginResponseBuilder
    _event_bus: LocalEventBus

    def __init__(
        self,
        *,
        login_command: LoginCommand,
        country_resolver: CountryResolver,
        response_builder: LoginResponseBuilder,
        event_bus: LocalEventBus,
    ) -> None:
        """Login workflow に必要な command, resolver, builder, event bus を設定する.

        Args:
            login_command (LoginCommand): parsed login request を処理する command.
            country_resolver (CountryResolver): request header から country を解決する dependency.
            response_builder (LoginResponseBuilder): successful login response を構築する builder.
            event_bus (LocalEventBus): UserConnected event を fire する local event bus.
        """
        self._login_command = login_command
        self._country_resolver = country_resolver
        self._response_builder = response_builder
        self._event_bus = event_bus

    async def execute(self, workflow_input: LoginWorkflowInput) -> LoginWorkflowResult:
        """Starlette 非依存の stable login workflow を実行する.

        Args:
            workflow_input (LoginWorkflowInput): raw body と HTTP header を持つ login 入力.

        Returns:
            LoginWorkflowResult: authentication result に応じた S2C stream と optional cho-token.

        Raises:
            UnicodeDecodeError: raw body を UTF-8 text として復号できない場合.

        Notes:
            ValueError による body の parse failure と authentication rejection は
            authentication failed packet を返す.
            successful login 後の UserConnected event failure は記録する.
            event failure があっても login response は維持する.
        """
        try:
            login_request = parse_login_request(workflow_input.body)
        except ValueError:
            logger.warning("login_parse_failed")
            return LoginWorkflowResult(
                content=login_reply(LoginResult.AUTHENTICATION_FAILED),
                cho_token=None,
            )

        country = self._country_resolver.resolve(workflow_input.headers)
        command_result = await self._login_command.execute(
            LoginCommandInput(login_request=login_request, country=country),
        )
        result = command_result.outcome

        if isinstance(result, LoginResult):
            return LoginWorkflowResult(content=login_reply(result), cho_token=None)

        _ = structlog.contextvars.bind_contextvars(
            user=result.user.username,
            user_id=result.user.id,
        )

        stream = await self._response_builder.build(result)
        try:
            await self._event_bus.fire(UserConnected(user_id=result.user.id))
        except Exception:
            logger.exception("user_connected_event_failed", user_id=result.user.id)
        return LoginWorkflowResult(content=stream, cho_token=result.token)


__all__ = [
    "LoginWorkflow",
    "LoginWorkflowInput",
    "LoginWorkflowResult",
]
