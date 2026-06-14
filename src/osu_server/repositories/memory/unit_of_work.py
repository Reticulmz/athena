"""In-memory command Unit of Work implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from osu_server.repositories.memory.commands import (
    InMemoryBeatmapCommandRepository,
    InMemoryBlobCommandRepository,
    InMemoryChannelCommandRepository,
    InMemoryCommandRepositoryState,
    InMemoryReplayCommandRepository,
    InMemoryRoleCommandRepository,
    InMemoryScoreCommandRepository,
    InMemoryScoreSubmissionCommandRepository,
    InMemoryUserCommandRepository,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from osu_server.domain.identity.roles import Role
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork


class InMemoryUnitOfWorkFactory:
    """Factory that opens isolated in-memory command UoW scopes."""

    def __init__(self, state: InMemoryCommandRepositoryState | None = None) -> None:
        self._state: InMemoryCommandRepositoryState = state or InMemoryCommandRepositoryState()

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        return cast("AbstractAsyncContextManager[UnitOfWork]", InMemoryUnitOfWork(self))

    def snapshot(self) -> InMemoryCommandRepositoryState:
        return self._state.clone()

    def commit_state(self, state: InMemoryCommandRepositoryState) -> None:
        self._state = state.clone()

    def seed_roles(self, roles: list[Role]) -> None:
        """Seed roles into factory state (test helper)."""
        for role in roles:
            self._state.roles_by_id[role.id] = role
            self._state.role_id_by_name[role.name] = role.id


class InMemoryUnitOfWork:
    """In-memory command transaction boundary with commit/rollback semantics."""

    users: InMemoryUserCommandRepository
    roles: InMemoryRoleCommandRepository
    channels: InMemoryChannelCommandRepository
    scores: InMemoryScoreCommandRepository
    submissions: InMemoryScoreSubmissionCommandRepository
    replays: InMemoryReplayCommandRepository
    blobs: InMemoryBlobCommandRepository
    beatmaps: InMemoryBeatmapCommandRepository

    def __init__(self, factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = factory
        self._state: InMemoryCommandRepositoryState = factory.snapshot()
        self._committed: bool = False
        self._bind_repositories()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None or not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        self._factory.commit_state(self._state)
        self._committed = True

    async def rollback(self) -> None:
        self._state = self._factory.snapshot()
        self._committed = False
        self._bind_repositories()

    def _bind_repositories(self) -> None:
        self.users = InMemoryUserCommandRepository(self._state)
        self.roles = InMemoryRoleCommandRepository(self._state)
        self.channels = InMemoryChannelCommandRepository(self._state)
        self.scores = InMemoryScoreCommandRepository(self._state)
        self.submissions = InMemoryScoreSubmissionCommandRepository(self._state)
        self.replays = InMemoryReplayCommandRepository(self._state)
        self.blobs = InMemoryBlobCommandRepository(self._state)
        self.beatmaps = InMemoryBeatmapCommandRepository(self._state)
