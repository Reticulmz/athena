"""Server-side identity authorization language."""

from __future__ import annotations

from enum import IntFlag


class Privileges(IntFlag):
    NONE = 0
    NORMAL = 1 << 0
    VERIFIED = 1 << 1
    SUPPORTER = 1 << 2
    MODERATOR = 1 << 3
    ADMIN = 1 << 4
    DEVELOPER = 1 << 5
    TOURNAMENT = 1 << 6
    UNRESTRICTED = 1 << 7
    EDIT_CHANNEL = 1 << 8
    BYPASS_CHANNEL_ACL = 1 << 9


def has_privilege(user_privileges: int, required: Privileges) -> bool:
    """Check if user has all required privileges. ADMIN bypasses all checks."""
    if user_privileges & Privileges.ADMIN:
        return True
    return (user_privileges & required) == required
