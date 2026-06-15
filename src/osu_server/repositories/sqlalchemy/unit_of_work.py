"""SQLAlchemy command Unit of Work implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from osu_server.repositories.sqlalchemy.commands import (
    SQLAlchemyBeatmapCommandRepository,
    SQLAlchemyBlobCommandRepository,
    SQLAlchemyChannelCommandRepository,
    SQLAlchemyChatCommandRepository,
    SQLAlchemyReplayCommandRepository,
    SQLAlchemyRoleCommandRepository,
    SQLAlchemyScoreCommandRepository,
    SQLAlchemyScoreSubmissionCommandRepository,
    SQLAlchemyUserCommandRepository,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession

    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork


class SQLAlchemyCommandSessionFactory(Protocol):
    """Factory shape required by the SQLAlchemy command UoW."""

    def __call__(self) -> AsyncSession: ...


class SQLAlchemyUnitOfWorkFactory:
    """Factory that opens SQLAlchemy command UoW scopes."""

    def __init__(self, session_factory: SQLAlchemyCommandSessionFactory) -> None:
        self._session_factory: SQLAlchemyCommandSessionFactory = session_factory

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        return SQLAlchemyUnitOfWork(self._session_factory)


class SQLAlchemyUnitOfWork:
    """SQLAlchemy command transaction boundary."""

    users: SQLAlchemyUserCommandRepository
    roles: SQLAlchemyRoleCommandRepository
    channels: SQLAlchemyChannelCommandRepository
    chat: SQLAlchemyChatCommandRepository
    scores: SQLAlchemyScoreCommandRepository
    submissions: SQLAlchemyScoreSubmissionCommandRepository
    replays: SQLAlchemyReplayCommandRepository
    blobs: SQLAlchemyBlobCommandRepository
    beatmaps: SQLAlchemyBeatmapCommandRepository

    def __init__(self, session_factory: SQLAlchemyCommandSessionFactory) -> None:
        self._session_factory: SQLAlchemyCommandSessionFactory = session_factory
        self._session: AsyncSession | None = None
        self._committed: bool = False
        self.users = cast("SQLAlchemyUserCommandRepository", cast("object", None))
        self.roles = cast("SQLAlchemyRoleCommandRepository", cast("object", None))
        self.channels = cast("SQLAlchemyChannelCommandRepository", cast("object", None))
        self.chat = cast("SQLAlchemyChatCommandRepository", cast("object", None))
        self.scores = cast("SQLAlchemyScoreCommandRepository", cast("object", None))
        self.submissions = cast("SQLAlchemyScoreSubmissionCommandRepository", cast("object", None))
        self.replays = cast("SQLAlchemyReplayCommandRepository", cast("object", None))
        self.blobs = cast("SQLAlchemyBlobCommandRepository", cast("object", None))
        self.beatmaps = cast("SQLAlchemyBeatmapCommandRepository", cast("object", None))

    async def __aenter__(self) -> UnitOfWork:
        self._session = self._session_factory()
        self._bind_repositories(self._session)
        return cast("UnitOfWork", cast("object", self))

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            if exc_type is not None or not self._committed:
                await session.rollback()
        finally:
            await session.close()

    async def commit(self) -> None:
        session = self._require_session()
        await session.commit()
        self._committed = True

    async def rollback(self) -> None:
        session = self._require_session()
        await session.rollback()
        self._committed = False

    def _bind_repositories(self, session: AsyncSession) -> None:
        self.users = SQLAlchemyUserCommandRepository(session)
        self.roles = SQLAlchemyRoleCommandRepository(session)
        self.channels = SQLAlchemyChannelCommandRepository(session)
        self.chat = SQLAlchemyChatCommandRepository(session)
        self.scores = SQLAlchemyScoreCommandRepository(session)
        self.submissions = SQLAlchemyScoreSubmissionCommandRepository(session)
        self.replays = SQLAlchemyReplayCommandRepository(session)
        self.blobs = SQLAlchemyBlobCommandRepository(session)
        self.beatmaps = SQLAlchemyBeatmapCommandRepository(session)

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            msg = "SQLAlchemyUnitOfWork must be entered before use"
            raise RuntimeError(msg)
        return self._session
