"""Registration command use-case boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.authentication import RegistrationForm, RegistrationResult


class _RegistrationService(Protocol):
    async def register(
        self,
        form_data: RegistrationForm,
        check_only: bool = False,
    ) -> RegistrationResult: ...


@dataclass(slots=True, frozen=True)
class RegisterUserCommandInput:
    form_data: RegistrationForm
    check_only: bool = False


@dataclass(slots=True, frozen=True)
class RegisterUserCommandResult:
    outcome: RegistrationResult


class RegisterUserCommand(Protocol):
    async def execute(self, input_data: RegisterUserCommandInput) -> RegisterUserCommandResult: ...


class RegisterUserCommandUseCase:
    """Validate registration input and create an account when requested."""

    _auth_service: _RegistrationService

    def __init__(self, *, auth_service: _RegistrationService) -> None:
        self._auth_service = auth_service

    async def execute(self, input_data: RegisterUserCommandInput) -> RegisterUserCommandResult:
        outcome = await self._auth_service.register(
            form_data=input_data.form_data,
            check_only=input_data.check_only,
        )
        return RegisterUserCommandResult(outcome=outcome)


__all__ = [
    "RegisterUserCommand",
    "RegisterUserCommandInput",
    "RegisterUserCommandResult",
    "RegisterUserCommandUseCase",
]
