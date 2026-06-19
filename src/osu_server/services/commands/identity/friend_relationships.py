"""Friend relationship command use-cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.identity.friends import (
    FriendableSystemUserCatalog,
    FriendMutationOutcome,
    FriendMutationStatus,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.session_store import SessionPrivacyRuntime
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class AddFriendCommand:
    owner_user_id: int
    target_user_id: int


@dataclass(frozen=True, slots=True)
class RemoveFriendCommand:
    owner_user_id: int
    target_user_id: int


@dataclass(frozen=True, slots=True)
class UpdateFriendOnlyDmCommand:
    user_id: int
    enabled: bool


class AddFriendCommandUseCase(Protocol):
    async def execute(self, command: AddFriendCommand) -> FriendMutationOutcome: ...


class RemoveFriendCommandUseCase(Protocol):
    async def execute(self, command: RemoveFriendCommand) -> FriendMutationOutcome: ...


class UpdateFriendOnlyDmCommandUseCase(Protocol):
    async def execute(self, command: UpdateFriendOnlyDmCommand) -> bool: ...


class AddFriendUseCase:
    """Add a directed friend relationship with Bancho-compatible no-op semantics."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        system_user_catalog: FriendableSystemUserCatalog,
    ) -> None:
        self._uow_factory: UnitOfWorkFactory = uow_factory
        self._system_user_catalog: FriendableSystemUserCatalog = system_user_catalog

    async def execute(self, command: AddFriendCommand) -> FriendMutationOutcome:
        if command.owner_user_id == command.target_user_id:
            return _no_op()
        if not self._system_user_catalog.allows_target(command.target_user_id):
            return _no_op()

        async with self._uow_factory() as uow:
            if not await uow.friends.target_exists(command.target_user_id):
                return _no_op()
            changed = await uow.friends.add_relationship(
                command.owner_user_id,
                command.target_user_id,
            )
            if changed:
                await uow.commit()
                return FriendMutationOutcome(status=FriendMutationStatus.ADDED)
        return _no_op()


class RemoveFriendUseCase:
    """Remove a directed friend relationship with idempotent missing-target handling."""

    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory: UnitOfWorkFactory = uow_factory

    async def execute(self, command: RemoveFriendCommand) -> FriendMutationOutcome:
        if command.owner_user_id == command.target_user_id:
            return _no_op()

        async with self._uow_factory() as uow:
            changed = await uow.friends.remove_relationship(
                command.owner_user_id,
                command.target_user_id,
            )
            if changed:
                await uow.commit()
                return FriendMutationOutcome(status=FriendMutationStatus.REMOVED)
        return _no_op()


class UpdateFriendOnlyDmUseCase:
    """Patch active session Friend-Only DM state."""

    def __init__(self, *, session_store: SessionPrivacyRuntime) -> None:
        self._session_store: SessionPrivacyRuntime = session_store

    async def execute(self, command: UpdateFriendOnlyDmCommand) -> bool:
        return await self._session_store.update_pm_private(command.user_id, command.enabled)


def _no_op() -> FriendMutationOutcome:
    return FriendMutationOutcome(status=FriendMutationStatus.NO_OP)


__all__ = [
    "AddFriendCommand",
    "AddFriendCommandUseCase",
    "AddFriendUseCase",
    "RemoveFriendCommand",
    "RemoveFriendCommandUseCase",
    "RemoveFriendUseCase",
    "UpdateFriendOnlyDmCommand",
    "UpdateFriendOnlyDmCommandUseCase",
    "UpdateFriendOnlyDmUseCase",
]
