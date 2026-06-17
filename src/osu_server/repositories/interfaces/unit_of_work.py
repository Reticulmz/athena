"""Command Unit of Work repository boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from osu_server.repositories.interfaces.commands import (
        BeatmapCommandRepository,
        BlobCommandRepository,
        ChannelCommandRepository,
        ChatCommandRepository,
        FriendRelationshipCommandRepository,
        PersonalBestCommandRepository,
        ReplayCommandRepository,
        RoleCommandRepository,
        ScoreCommandRepository,
        ScorePerformanceCommandRepository,
        ScoreSubmissionCommandRepository,
        UserCommandRepository,
    )


class UnitOfWork(Protocol):
    """Command-side transaction boundary.

    Implementations own the low-level persistence transaction. Command
    repositories obtained from this boundary must not commit or roll back
    independently.
    """

    users: UserCommandRepository
    roles: RoleCommandRepository
    channels: ChannelCommandRepository
    chat: ChatCommandRepository
    friends: FriendRelationshipCommandRepository
    scores: ScoreCommandRepository
    personal_bests: PersonalBestCommandRepository
    score_performance: ScorePerformanceCommandRepository
    submissions: ScoreSubmissionCommandRepository
    replays: ReplayCommandRepository
    blobs: BlobCommandRepository
    beatmaps: BeatmapCommandRepository

    async def commit(self) -> None:
        """Commit all command repository changes as one durable outcome."""
        ...

    async def rollback(self) -> None:
        """Rollback all uncommitted command repository changes."""
        ...


class UnitOfWorkFactory(Protocol):
    """Factory that opens a command Unit of Work scope."""

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        """Return an async context manager for one command transaction."""
        ...
