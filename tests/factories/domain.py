"""chatとidentity domain modelを作る型安全なtest data factoryを提供する."""

from __future__ import annotations

from datetime import UTC, datetime

from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType
from osu_server.domain.identity.users import User


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
    """指定値またはtest default値からChannelを作る.

    Args:
        id (int): channel識別子.
        name (str): channel名.
        topic (str): channel topic.
        channel_type (ChannelType): channelの公開種別.
        auto_join (bool): login時に自動joinするか.
        rate_limit_messages (int | None): window内で許可するmessage数.
        rate_limit_window (int | None): rate limit windowの秒数.
        created_at (datetime | None): 作成時刻. Noneなら現在UTC時刻.
        updated_at (datetime | None): 更新時刻. Noneならcreated_at.

    Returns:
        Channel: channel behavior testへ渡す型安全なdomain model.
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
    """指定したrole権限を持つChannelRoleOverrideを作る.

    Args:
        channel_id (int): 対象channel識別子.
        role_id (int): 適用するrole識別子.
        can_read (bool): roleにreadを許可するか.
        can_write (bool): roleにwriteを許可するか.

    Returns:
        ChannelRoleOverride: channel authorization testへ渡すoverride model.
    """
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
    """指定値またはtest default値からUserを作る.

    Args:
        id (int): user識別子.
        username (str): 表示用user名.
        safe_username (str | None): 正規化済みuser名. Noneならusernameから生成する.
        email (str): login用email address.
        password_hash (str): 永続化するpassword hash.
        country (str): 2文字country code.
        created_at (datetime | None): 作成時刻. Noneなら現在UTC時刻.
        updated_at (datetime | None): 更新時刻. Noneならcreated_at.

    Returns:
        User: identity testへ渡す型安全なdomain model.
    """
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
