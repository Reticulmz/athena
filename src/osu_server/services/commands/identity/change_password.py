"""Change user password command use-case."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.identity.passwords import (
    PASSWORD_COMPROMISED_MESSAGE,
    validate_plain_password,
)
from osu_server.domain.identity.system_users import BANCHO_BOT_USER_ID
from osu_server.domain.identity.users import User

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


class _PasswordService(Protocol):
    async def prepare_password(self, plain_password: str) -> str: ...

    async def is_password_banned(self, password: str) -> bool: ...


class ChangeUserPasswordStatus(StrEnum):
    CHANGED = "changed"
    USER_NOT_FOUND = "user_not_found"
    INVALID_PASSWORD = "invalid_password"
    SYSTEM_USER_DENIED = "system_user_denied"


@dataclass(slots=True, frozen=True)
class ChangeUserPasswordCommandInput:
    username: str
    plain_password: str


@dataclass(slots=True, frozen=True)
class ChangeUserPasswordCommandResult:
    status: ChangeUserPasswordStatus
    username: str
    user_id: int | None = None
    errors: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.status is ChangeUserPasswordStatus.CHANGED


class ChangeUserPasswordCommand(Protocol):
    async def execute(
        self,
        input_data: ChangeUserPasswordCommandInput,
    ) -> ChangeUserPasswordCommandResult: ...


class ChangeUserPasswordCommandUseCase:
    """Update a user's password hash through the command Unit of Work boundary."""

    _uow_factory: UnitOfWorkFactory
    _user_query_repository: UserQueryRepository
    _password_service: _PasswordService
    _system_user_id: int

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        user_query_repository: UserQueryRepository,
        password_service: _PasswordService,
        system_user_id: int = BANCHO_BOT_USER_ID,
    ) -> None:
        self._uow_factory = uow_factory
        self._user_query_repository = user_query_repository
        self._password_service = password_service
        self._system_user_id = system_user_id

    async def execute(
        self,
        input_data: ChangeUserPasswordCommandInput,
    ) -> ChangeUserPasswordCommandResult:
        safe_username = User.normalize_username(input_data.username)
        user = await self._user_query_repository.get_by_safe_username(safe_username)
        if user is None:
            return ChangeUserPasswordCommandResult(
                status=ChangeUserPasswordStatus.USER_NOT_FOUND,
                username=input_data.username,
            )

        if user.id == self._system_user_id:
            return ChangeUserPasswordCommandResult(
                status=ChangeUserPasswordStatus.SYSTEM_USER_DENIED,
                username=user.username,
                user_id=user.id,
            )

        policy_errors = validate_plain_password(input_data.plain_password)
        if policy_errors:
            return ChangeUserPasswordCommandResult(
                status=ChangeUserPasswordStatus.INVALID_PASSWORD,
                username=user.username,
                user_id=user.id,
                errors=policy_errors,
            )

        if await self._password_service.is_password_banned(input_data.plain_password):
            return ChangeUserPasswordCommandResult(
                status=ChangeUserPasswordStatus.INVALID_PASSWORD,
                username=user.username,
                user_id=user.id,
                errors=(PASSWORD_COMPROMISED_MESSAGE,),
            )

        password_hash = await self._password_service.prepare_password(input_data.plain_password)
        async with self._uow_factory() as uow:
            updated = await uow.users.update_password_hash(user.id, password_hash)
            if not updated:
                return ChangeUserPasswordCommandResult(
                    status=ChangeUserPasswordStatus.USER_NOT_FOUND,
                    username=user.username,
                    user_id=user.id,
                )
            await uow.commit()

        return ChangeUserPasswordCommandResult(
            status=ChangeUserPasswordStatus.CHANGED,
            username=user.username,
            user_id=user.id,
        )


__all__ = [
    "ChangeUserPasswordCommand",
    "ChangeUserPasswordCommandInput",
    "ChangeUserPasswordCommandResult",
    "ChangeUserPasswordCommandUseCase",
    "ChangeUserPasswordStatus",
]
