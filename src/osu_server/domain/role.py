from __future__ import annotations

from dataclasses import dataclass
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


class ClientPermissions(IntFlag):
    """Flags the osu! client understands for login_permissions packet."""

    NORMAL = 1
    MODERATOR = 2
    SUPPORTER = 4
    PEPPY = 8
    DEVELOPER = 16


@dataclass(slots=True)
class Role:
    id: int
    name: str
    permissions: Privileges
    position: int
