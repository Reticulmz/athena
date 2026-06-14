"""Login command use-case boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.authentication import LoginRequest, LoginResponse, LoginResult


class _LoginService(Protocol):
    async def login(
        self,
        login_request: LoginRequest,
        *,
        country: str,
    ) -> LoginResponse | LoginResult: ...


@dataclass(slots=True, frozen=True)
class LoginCommandInput:
    login_request: LoginRequest
    country: str


@dataclass(slots=True, frozen=True)
class LoginCommandResult:
    outcome: LoginResponse | LoginResult


class LoginCommand(Protocol):
    async def execute(self, input_data: LoginCommandInput) -> LoginCommandResult: ...


class LoginCommandUseCase:
    """Authenticate a login request and create the active session on success."""

    _auth_service: _LoginService

    def __init__(self, *, auth_service: _LoginService) -> None:
        self._auth_service = auth_service

    async def execute(self, input_data: LoginCommandInput) -> LoginCommandResult:
        outcome = await self._auth_service.login(
            input_data.login_request,
            country=input_data.country,
        )
        return LoginCommandResult(outcome=outcome)


__all__ = [
    "LoginCommand",
    "LoginCommandInput",
    "LoginCommandResult",
    "LoginCommandUseCase",
]
