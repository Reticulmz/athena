"""Identity context の system user identity 値を定義する module."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SystemUserIdentity:
    """Active session を持たない system user の immutable identity を表す value object.

    Attributes:
        user_id (int): system user に予約された user ID.
        username (str): system user の表示 user name.
    """

    user_id: int
    username: str


BANCHO_BOT_USER_ID = 1
BANCHO_BOT_DEFAULT_USERNAME = "BanchoBot"
BANCHO_BOT_USERNAME_MIN = 2
BANCHO_BOT_USERNAME_MAX = 15
BANCHO_BOT_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_ -]+$")

BANCHO_BOT_IDENTITY = SystemUserIdentity(
    user_id=BANCHO_BOT_USER_ID,
    username=BANCHO_BOT_DEFAULT_USERNAME,
)


def create_bancho_bot_identity(username: str) -> SystemUserIdentity:
    """検証済み display name から runtime BanchoBot identity を作成する.

    Args:
        username (str): caller が policy に従って検証済みにした表示 user name.

    Returns:
        SystemUserIdentity: 固定の BanchoBot user ID と username を持つ identity.

    Notes:
        この関数は username を検証せず, BANCHO_BOT_USER_ID への結び付けだけを行う.
    """
    return SystemUserIdentity(user_id=BANCHO_BOT_USER_ID, username=username)
