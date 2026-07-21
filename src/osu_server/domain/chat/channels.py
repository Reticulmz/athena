"""永続chat channelとrole based access controlのdomain modelを定義するmodule."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

_CHANNEL_NAME_BODY = re.compile(r"^[a-z0-9_-]+$")


class ChannelType(Enum):
    """Channelの用途を表す閉集合.

    Attributes:
        PUBLIC (str): 通常の公開channelを示す値.
        MULTIPLAYER (str): multiplayer用に予約された値.
        SPECTATOR (str): spectator用に予約された値.
        TEMPORARY (str): 一時channel用に予約された値.
    """

    PUBLIC = "public"
    MULTIPLAYER = "multiplayer"  # reserved
    SPECTATOR = "spectator"  # reserved
    TEMPORARY = "temporary"  # reserved


@dataclass(slots=True)
class Channel:
    """DB管理されるchat channelを表す.

    Attributes:
        id (int): 永続channel ID.
        name (str): `#`で始まるchannel名.
        topic (str): channelの説明文.
        channel_type (ChannelType): channelの用途分類.
        auto_join (bool): login時に自動参加させるか.
        rate_limit_messages (int | None): rate limit内で許可するmessage数. 未設定時はNone.
        rate_limit_window (int | None): rate limitを測る時間window. 未設定時はNone.
        created_at (datetime): channelを作成した日時.
        updated_at (datetime): channelを最後に更新した日時.

    Notes:
        nameは`#`の後ろに`[a-z0-9_-]`を1文字以上持つ. role overrideがないchannelへの
        accessはfail-closedである.
    """

    id: int
    name: str
    topic: str
    channel_type: ChannelType
    auto_join: bool
    rate_limit_messages: int | None
    rate_limit_window: int | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Channel名がdomainの命名規則を満たすか検証する.

        Returns:
            None: channel名を検証して完了する.

        Raises:
            ValueError: nameが`#`で始まらないか、許可外文字を含む場合.
        """
        _validate_channel_name(self.name)


@dataclass(slots=True)
class ChannelRoleOverride:
    """Channelとroleの組ごとのaccess overrideを表す.

    Attributes:
        channel_id (int): overrideを適用するchannel ID.
        role_id (int): overrideを適用するrole ID.
        can_read (bool): channelのreadを許可するか.
        can_write (bool): channelへのmessage送信を許可するか.

    Notes:
        overrideが一件もないchannelはfail-closedである. Default roleは全userに割り当てる
        `@everyone`相当として利用できる.
    """

    channel_id: int
    role_id: int
    can_read: bool
    can_write: bool


def _validate_channel_name(name: str) -> None:
    """Channel名が`#`と許可文字から成るか検証する.

    Args:
        name (str): 検証するchannel名.

    Returns:
        None: nameが命名規則を満たすことを確認して完了する.

    Raises:
        ValueError: nameが`#`で始まらないか、`#`の後ろが空か、許可外文字を含む場合.
    """
    if not name.startswith("#"):
        msg = "Channel name must start with '#'"
        raise ValueError(msg)

    body = name[1:]
    if not body:
        msg = "Channel name must have at least one character after '#'"
        raise ValueError(msg)

    if not _CHANNEL_NAME_BODY.fullmatch(body):
        msg = f"Channel name contains invalid characters: {name!r} (allowed: a-z 0-9 _ -)"
        raise ValueError(msg)
