"""Leaderboard visibility policy for identity privileges."""

from __future__ import annotations

from typing import Final

from osu_server.domain.identity.authorization import Privileges

LEADERBOARD_VISIBLE_PRIVILEGES: Final[Privileges] = Privileges.NORMAL | Privileges.UNRESTRICTED
LEADERBOARD_VISIBLE_PERMISSION_MASK: Final[int] = int(LEADERBOARD_VISIBLE_PRIVILEGES)


def is_leaderboard_visible_user(privileges: Privileges | int) -> bool:
    """Return whether privileges satisfy public leaderboard visibility."""
    user_privileges = Privileges(privileges)
    return (user_privileges & LEADERBOARD_VISIBLE_PRIVILEGES) == LEADERBOARD_VISIBLE_PRIVILEGES


__all__ = (
    "LEADERBOARD_VISIBLE_PERMISSION_MASK",
    "LEADERBOARD_VISIBLE_PRIVILEGES",
    "is_leaderboard_visible_user",
)
