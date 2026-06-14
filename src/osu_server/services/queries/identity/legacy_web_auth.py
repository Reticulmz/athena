"""Legacy web authentication query use-case boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.authentication import LegacyWebAuthResult


class _LegacyWebAuthService(Protocol):
    async def authenticate(
        self,
        username: str | None,
        password_md5: str | None,
    ) -> LegacyWebAuthResult: ...


@dataclass(slots=True, frozen=True)
class LegacyWebAuthQueryInput:
    username: str | None
    password_md5: str | None


@dataclass(slots=True, frozen=True)
class LegacyWebAuthQueryResult:
    outcome: LegacyWebAuthResult


class LegacyWebAuthQuery(Protocol):
    async def execute(self, input_data: LegacyWebAuthQueryInput) -> LegacyWebAuthQueryResult: ...


class LegacyWebAuthQueryUseCase:
    """Authenticate legacy web credentials without creating durable state."""

    _legacy_web_auth_service: _LegacyWebAuthService

    def __init__(self, *, legacy_web_auth_service: _LegacyWebAuthService) -> None:
        self._legacy_web_auth_service = legacy_web_auth_service

    async def execute(self, input_data: LegacyWebAuthQueryInput) -> LegacyWebAuthQueryResult:
        outcome = await self._legacy_web_auth_service.authenticate(
            username=input_data.username,
            password_md5=input_data.password_md5,
        )
        return LegacyWebAuthQueryResult(outcome=outcome)


__all__ = [
    "LegacyWebAuthQuery",
    "LegacyWebAuthQueryInput",
    "LegacyWebAuthQueryResult",
    "LegacyWebAuthQueryUseCase",
]
