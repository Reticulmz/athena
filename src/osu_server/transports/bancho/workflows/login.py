"""Login workflow contracts and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
import structlog.contextvars

from osu_server.domain.auth import LoginResult
from osu_server.transports.bancho.parsers.login import parse_login_request
from osu_server.transports.bancho.protocol.s2c.login import login_reply

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.infrastructure.country.interfaces import CountryResolver
    from osu_server.services.auth_service import AuthService
    from osu_server.transports.bancho.workflows.login_response_builder import LoginResponseBuilder

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(slots=True, frozen=True)
class LoginWorkflowInput:
    """Input for the Starlette-independent login workflow."""

    body: bytes
    headers: Mapping[str, str]


@dataclass(slots=True, frozen=True)
class LoginWorkflowResult:
    """Result returned by the Starlette-independent login workflow."""

    content: bytes
    cho_token: str | None


class LoginWorkflow:
    """Orchestrate login parsing, authentication, and success response building."""

    _auth_service: AuthService
    _country_resolver: CountryResolver
    _response_builder: LoginResponseBuilder

    def __init__(
        self,
        *,
        auth_service: AuthService,
        country_resolver: CountryResolver,
        response_builder: LoginResponseBuilder,
    ) -> None:
        self._auth_service = auth_service
        self._country_resolver = country_resolver
        self._response_builder = response_builder

    async def execute(self, workflow_input: LoginWorkflowInput) -> LoginWorkflowResult:
        """Execute the Starlette-independent login workflow."""
        try:
            login_request = parse_login_request(workflow_input.body)
        except ValueError:
            logger.warning("login_parse_failed")
            return LoginWorkflowResult(
                content=login_reply(LoginResult.AUTHENTICATION_FAILED),
                cho_token=None,
            )

        country = self._country_resolver.resolve(workflow_input.headers)
        result = await self._auth_service.login(login_request, country=country)

        if isinstance(result, LoginResult):
            return LoginWorkflowResult(content=login_reply(result), cho_token=None)

        _ = structlog.contextvars.bind_contextvars(
            user=result.user.username,
            user_id=result.user.id,
        )

        stream = await self._response_builder.build(result)
        return LoginWorkflowResult(content=stream, cho_token=result.token)


__all__ = [
    "LoginWorkflow",
    "LoginWorkflowInput",
    "LoginWorkflowResult",
]
