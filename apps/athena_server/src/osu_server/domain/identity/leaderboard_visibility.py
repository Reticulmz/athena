"""Identity privilege に基づく public leaderboard visibility policy を定義する module."""

from __future__ import annotations

from typing import Final

from osu_server.domain.identity.authorization import Privileges

LEADERBOARD_VISIBLE_PRIVILEGES: Final[Privileges] = Privileges.NORMAL | Privileges.UNRESTRICTED
LEADERBOARD_VISIBLE_PERMISSION_MASK: Final[int] = int(LEADERBOARD_VISIBLE_PRIVILEGES)


def is_leaderboard_visible_user(privileges: Privileges | int) -> bool:
    """Public leaderboard に表示できる privilege 状態か判定する.

    Args:
        privileges (Privileges | int): 判定対象 user の privilege bitmask.

    Returns:
        bool: NORMAL と UNRESTRICTED の両方を持つ場合はTrue.

    Notes:
        ADMIN はこの visibility policy を bypass しない.
    """
    user_privileges = Privileges(privileges)
    return (user_privileges & LEADERBOARD_VISIBLE_PRIVILEGES) == LEADERBOARD_VISIBLE_PRIVILEGES


__all__ = (
    "LEADERBOARD_VISIBLE_PERMISSION_MASK",
    "LEADERBOARD_VISIBLE_PRIVILEGES",
    "is_leaderboard_visible_user",
)
