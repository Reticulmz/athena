"""Tests for command-side SQLAlchemy chat persistence repository logging."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog.testing
from sqlalchemy.exc import SQLAlchemyError, StatementError

from osu_server.domain.chat import ChatPersistenceFailureReason
from osu_server.repositories.sqlalchemy.commands.chat import SQLAlchemyChatCommandRepository
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    PrivateMessageModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable


class ChannelIdResult:
    """Minimal scalar result returned by the fake command session."""

    def __init__(self, channel_id: int | None) -> None:
        self._channel_id: int | None = channel_id

    def scalar_one_or_none(self) -> int | None:
        return self._channel_id


class FakeCommandSession:
    """Session fake for command repository tests without a DB driver."""

    def __init__(
        self,
        *,
        channel_id: int | None = None,
        flush_error: SQLAlchemyError | None = None,
    ) -> None:
        self.channel_id: int | None = channel_id
        self.flush_error: SQLAlchemyError | None = flush_error
        self.added: list[object] = []
        self.execute_calls: int = 0
        self.flush_calls: int = 0

    async def execute(self, statement: Executable) -> ChannelIdResult:
        _ = statement
        self.execute_calls += 1
        return ChannelIdResult(self.channel_id)

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error
        self.flush_calls += 1


def make_repo(session: FakeCommandSession) -> SQLAlchemyChatCommandRepository:
    return SQLAlchemyChatCommandRepository(cast("AsyncSession", cast("object", session)))


def make_statement_error(message: str) -> StatementError:
    return StatementError(
        message,
        "insert into channel_messages",
        {"sender_id": 2, "content": "hello"},
        ValueError("foreign key violation"),
    )


async def test_save_channel_message_logs_storage_error_details() -> None:
    session = FakeCommandSession(
        channel_id=10,
        flush_error=make_statement_error("channel insert failed"),
    )
    repo = make_repo(session)

    with structlog.testing.capture_logs() as logs:
        result = await repo.save_channel_message(
            sender_id=2,
            channel_name="#osu",
            content="hello",
        )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.STORAGE_ERROR
    assert len(session.added) == 1
    assert isinstance(session.added[0], ChannelMessageModel)

    entries = [entry for entry in logs if entry.get("event") == "chat_persistence_storage_error"]
    assert len(entries) == 1
    assert entries[0]["operation"] == "save_channel_message"
    assert entries[0]["sender_id"] == 2
    assert entries[0]["channel_name"] == "#osu"
    assert entries[0]["reason"] == "storage_error"
    assert entries[0]["error_type"] == "StatementError"
    assert "channel insert failed" in entries[0]["error_message"]
    assert "StatementError" in entries[0]["error_repr"]
    assert entries[0]["sqlalchemy_code"] is None
    assert entries[0]["sqlalchemy_statement"] == "insert into channel_messages"
    assert entries[0]["sqlalchemy_params_repr"] == "{'sender_id': 2, 'content': 'hello'}"
    assert entries[0]["sqlalchemy_ismulti"] is None
    assert entries[0]["original_error_type"] == "ValueError"
    assert entries[0]["original_error_message"] == "foreign key violation"
    assert entries[0]["original_error_repr"] == "ValueError('foreign key violation')"


async def test_save_private_message_logs_storage_error_details() -> None:
    session = FakeCommandSession(
        flush_error=SQLAlchemyError("private insert failed"),
    )
    repo = make_repo(session)

    with structlog.testing.capture_logs() as logs:
        result = await repo.save_private_message(
            sender_id=2,
            target_id=3,
            content="hello pm",
        )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.STORAGE_ERROR
    assert len(session.added) == 1
    assert isinstance(session.added[0], PrivateMessageModel)

    entries = [entry for entry in logs if entry.get("event") == "chat_persistence_storage_error"]
    assert len(entries) == 1
    assert entries[0]["operation"] == "save_private_message"
    assert entries[0]["sender_id"] == 2
    assert entries[0]["target_id"] == 3
    assert entries[0]["reason"] == "storage_error"
    assert entries[0]["error_type"] == "SQLAlchemyError"
