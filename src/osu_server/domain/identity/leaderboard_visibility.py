"""Leaderboard visibility policy for identity privileges."""

from __future__ import annotations

from osu_server.domain.identity.authorization import Privileges

_LEADERBOARD_VISIBLE_PRIVILEGES = Privileges.NORMAL | Privileges.UNRESTRICTED


def is_leaderboard_visible_user(privileges: Privileges | int) -> bool:
    """Return whether privileges satisfy public leaderboard visibility."""
    user_privileges = Privileges(privileges)
    return (user_privileges & _LEADERBOARD_VISIBLE_PRIVILEGES) == _LEADERBOARD_VISIBLE_PRIVILEGES


__all__ = ("is_leaderboard_visible_user",)
