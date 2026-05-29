from __future__ import annotations

from datetime import UTC, datetime

from osu_server.domain.channel import Channel, ChannelRoleOverride, ChannelType
from osu_server.domain.user import User


def make_channel(
    *,
    id: int = 1,  # noqa: A002
    name: str = "#osu",
    topic: str = "General discussion",
    channel_type: ChannelType = ChannelType.PUBLIC,
    auto_join: bool = True,
    rate_limit_messages: int | None = None,
    rate_limit_window: int | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Channel:
    """Type-safe factory for Channel.

    Guarantees the returned object is typed correctly.
    """
    now = created_at or datetime.now(UTC)
    return Channel(
        id=id,
        name=name,
        topic=topic,
        channel_type=channel_type,
        auto_join=auto_join,
        rate_limit_messages=rate_limit_messages,
        rate_limit_window=rate_limit_window,
        created_at=now,
        updated_at=updated_at or now,
    )


def make_channel_role_override(
    *,
    channel_id: int = 1,
    role_id: int = 1,
    can_read: bool = True,
    can_write: bool = True,
) -> ChannelRoleOverride:
    """Type-safe factory for ChannelRoleOverride."""
    return ChannelRoleOverride(
        channel_id=channel_id,
        role_id=role_id,
        can_read=can_read,
        can_write=can_write,
    )


def make_user(
    *,
    id: int = 1,  # noqa: A002
    username: str = "TestUser",
    safe_username: str | None = None,
    email: str = "test@example.com",
    password_hash: str = "secure_password_hash",
    country: str = "JP",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> User:
    """Type-safe factory for User."""
    now = created_at or datetime.now(UTC)
    safe_name = safe_username or User.normalize_username(username)
    return User(
        id=id,
        username=username,
        safe_username=safe_name,
        email=email,
        password_hash=password_hash,
        country=country,
        created_at=now,
        updated_at=updated_at or now,
    )
