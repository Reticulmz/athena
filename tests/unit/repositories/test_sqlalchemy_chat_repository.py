"""Tests for SQLAlchemyChatRepository chat history persistence."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, cast, override

import structlog.testing
from sqlalchemy.exc import SQLAlchemyError, StatementError

from osu_server.domain.chat import ChatPersistenceFailureReason
from osu_server.repositories.sqlalchemy.commands.chat import SQLAlchemyChatCommandRepository
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    PrivateMessageModel,
)

if TYPE_CHECKING:
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable


class ChannelIdResult:
    """Minimal scalar result returned by the fake session."""

    _channel_id: int | None

    def __init__(self, channel_id: int | None) -> None:
        self._channel_id = channel_id

    def scalar_one_or_none(self) -> int | None:
        """Return configured channel id."""
        return self._channel_id


class FakeSession(AbstractAsyncContextManager["FakeSession"]):
    """Session fake for repository unit tests without a database driver."""

    channel_id: int | None
    flush_error: SQLAlchemyError | None
    added: list[object]
    execute_calls: int
    flushes: int

    def __init__(
        self,
        *,
        channel_id: int | None = None,
        flush_error: SQLAlchemyError | None = None,
    ) -> None:
        self.channel_id = channel_id
        self.flush_error = flush_error
        self.added = []
        self.execute_calls = 0
        self.flushes = 0

    @override
    async def __aenter__(self) -> FakeSession:
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc
        _ = traceback

    async def execute(self, statement: Executable) -> ChannelIdResult:
        _ = statement
        self.execute_calls += 1
        return ChannelIdResult(self.channel_id)

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error
        self.flushes += 1


def make_repo(session: FakeSession) -> SQLAlchemyChatCommandRepository:
    """Create repository with a typed fake session factory."""
    return SQLAlchemyChatCommandRepository(cast("AsyncSession", cast("object", session)))


def make_statement_error(message: str) -> StatementError:
    """Create a SQLAlchemy statement error with details visible in logs."""
    return StatementError(
        message,
        "insert into private_messages",
        {"sender_id": 1, "target_user_id": 2, "content": "secret"},
        ValueError("foreign key violation"),
    )


class TestSaveChannelMessage:
    """save_channel_message() persists accepted public chat history."""

    async def test_adds_message_with_resolved_channel_id(self) -> None:
        session = FakeSession(channel_id=10)
        repo = make_repo(session)

        result = await repo.save_channel_message(
            sender_id=1,
            channel_name="#osu",
            content="hello",
        )

        assert result.success is True
        assert result.reason is None
        assert session.execute_calls == 1
        assert session.flushes == 1
        assert len(session.added) == 1
        message = session.added[0]
        assert isinstance(message, ChannelMessageModel)
        assert message.sender_id == 1
        assert message.channel_id == 10
        assert message.content == "hello"

    async def test_unresolved_channel_returns_failure_without_insert(self) -> None:
        session = FakeSession(channel_id=None)
        repo = make_repo(session)

        result = await repo.save_channel_message(
            sender_id=1,
            channel_name="#missing",
            content="hello",
        )

        assert result.success is False
        assert result.reason is ChatPersistenceFailureReason.CHANNEL_NOT_FOUND
        assert session.execute_calls == 1
        assert session.flushes == 0
        assert session.added == []


class TestSavePrivateMessage:
    """save_private_message() persists accepted private chat history."""

    async def test_adds_private_message(self) -> None:
        session = FakeSession()
        repo = make_repo(session)

        result = await repo.save_private_message(
            sender_id=1,
            target_id=2,
            content="secret",
        )

        assert result.success is True
        assert result.reason is None
        assert session.execute_calls == 0
        assert session.flushes == 1
        assert len(session.added) == 1
        message = session.added[0]
        assert isinstance(message, PrivateMessageModel)
        assert message.sender_id == 1
        assert message.target_user_id == 2
        assert message.content == "secret"

    async def test_storage_error_returns_failure(self) -> None:
        session = FakeSession(flush_error=make_statement_error("storage failed"))
        repo = make_repo(session)

        with structlog.testing.capture_logs() as logs:
            result = await repo.save_private_message(
                sender_id=1,
                target_id=2,
                content="secret",
            )

        assert result.success is False
        assert result.reason is ChatPersistenceFailureReason.STORAGE_ERROR
        assert session.flushes == 0

        entries = [
            entry for entry in logs if entry.get("event") == "chat_persistence_storage_error"
        ]
        assert len(entries) == 1
        assert entries[0]["operation"] == "save_private_message"
        assert entries[0]["sender_id"] == 1
        assert entries[0]["target_id"] == 2
        assert entries[0]["reason"] == "storage_error"
        assert entries[0]["error_type"] == "StatementError"
        assert "storage failed" in entries[0]["error_message"]
        assert "StatementError" in entries[0]["error_repr"]
        assert entries[0]["sqlalchemy_code"] is None
        assert entries[0]["sqlalchemy_statement"] == "insert into private_messages"
        assert (
            entries[0]["sqlalchemy_params_repr"]
            == "{'sender_id': 1, 'target_user_id': 2, 'content': 'secret'}"
        )
        assert entries[0]["sqlalchemy_ismulti"] is None
        assert entries[0]["original_error_type"] == "ValueError"
        assert entries[0]["original_error_message"] == "foreign key violation"
