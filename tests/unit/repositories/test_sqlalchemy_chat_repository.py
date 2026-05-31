"""Tests for SQLAlchemyChatRepository chat history persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.interfaces.chat_repository import ChatPersistenceFailureReason
from osu_server.repositories.sqlalchemy.chat_repository import SQLAlchemyChatRepository
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    ChannelModel,
    ChannelRoleOverrideModel,
    PrivateMessageModel,
)
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel
from osu_server.repositories.sqlalchemy.models.user import UserModel

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Create an in-memory SQLite session factory for chat repository tests."""
    _ = ChannelModel
    _ = ChannelRoleOverrideModel
    _ = ChannelMessageModel
    _ = PrivateMessageModel
    _ = RoleModel
    _ = UserRoleModel
    _ = UserModel

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        _ = await conn.execute(text("DROP TABLE channel_messages"))
        _ = await conn.execute(
            text(
                """
                CREATE TABLE channel_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    sender_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        _ = await conn.execute(text("DROP TABLE private_messages"))
        _ = await conn.execute(
            text(
                """
                CREATE TABLE private_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL,
                    target_user_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )

    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def seed_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: int,
    username: str,
) -> None:
    """Insert a user row required by message foreign keys."""
    async with session_factory() as session:
        _ = await session.execute(
            text(
                """
                INSERT INTO users
                    (id, username, safe_username, email, password_hash)
                VALUES
                    (:id, :username, :username, :email, 'hash')
                """
            ),
            {
                "id": user_id,
                "username": username,
                "email": f"{username}@example.com",
            },
        )
        await session.commit()


async def seed_channel(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel_id: int,
    name: str,
) -> None:
    """Insert a channel row for channel message tests."""
    async with session_factory() as session:
        _ = await session.execute(
            text("INSERT INTO channels (id, name, topic) VALUES (:id, :name, 'General')"),
            {"id": channel_id, "name": name},
        )
        await session.commit()


class TestSaveChannelMessage:
    """save_channel_message() persists accepted public chat history."""

    async def test_inserts_message_with_resolved_channel_id(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        await seed_user(session_factory, user_id=1, username="sender")
        await seed_channel(session_factory, channel_id=10, name="#osu")
        repo = SQLAlchemyChatRepository(session_factory)

        result = await repo.save_channel_message(
            sender_id=1,
            channel_name="#osu",
            content="hello",
        )

        assert result.success is True
        assert result.reason is None
        async with session_factory() as session:
            row = await session.execute(
                text("SELECT sender_id, channel_id, content FROM channel_messages")
            )
            assert row.one() == (1, 10, "hello")

    async def test_unresolved_channel_returns_failure_without_insert(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        await seed_user(session_factory, user_id=1, username="sender")
        repo = SQLAlchemyChatRepository(session_factory)

        result = await repo.save_channel_message(
            sender_id=1,
            channel_name="#missing",
            content="hello",
        )

        assert result.success is False
        assert result.reason is ChatPersistenceFailureReason.CHANNEL_NOT_FOUND
        async with session_factory() as session:
            row = await session.execute(text("SELECT COUNT(*) FROM channel_messages"))
            assert row.scalar_one() == 0


class TestSavePrivateMessage:
    """save_private_message() persists accepted private chat history."""

    async def test_inserts_private_message(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        await seed_user(session_factory, user_id=1, username="sender")
        await seed_user(session_factory, user_id=2, username="target")
        repo = SQLAlchemyChatRepository(session_factory)

        result = await repo.save_private_message(
            sender_id=1,
            target_id=2,
            content="secret",
        )

        assert result.success is True
        assert result.reason is None
        async with session_factory() as session:
            row = await session.execute(
                text("SELECT sender_id, target_user_id, content FROM private_messages")
            )
            assert row.one() == (1, 2, "secret")

    async def test_storage_error_returns_failure(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        await seed_user(session_factory, user_id=1, username="sender")
        await seed_user(session_factory, user_id=2, username="target")
        async with session_factory() as session:
            _ = await session.execute(text("DROP TABLE private_messages"))
            await session.commit()
        repo = SQLAlchemyChatRepository(session_factory)

        result = await repo.save_private_message(
            sender_id=1,
            target_id=2,
            content="secret",
        )

        assert result.success is False
        assert result.reason is ChatPersistenceFailureReason.STORAGE_ERROR
