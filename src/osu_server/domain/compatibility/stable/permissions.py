"""Stable client permission compatibility values."""

from __future__ import annotations

from enum import IntFlag

from osu_server.domain.identity.authorization import Privileges


class BanchoClientPermission(IntFlag):
    """Flags the stable osu! client understands for login permission packets."""

    NORMAL = 1
    MODERATOR = 2
    SUPPORTER = 4
    PEPPY = 8
    DEVELOPER = 16


def to_bancho_client_permissions(privileges: Privileges) -> BanchoClientPermission:
    """Convert server-side privileges to stable client-visible permissions."""
    flags = BanchoClientPermission.NORMAL

    mapping: tuple[tuple[Privileges, BanchoClientPermission], ...] = (
        (Privileges.MODERATOR, BanchoClientPermission.MODERATOR),
        (Privileges.SUPPORTER, BanchoClientPermission.SUPPORTER),
        (Privileges.ADMIN, BanchoClientPermission.PEPPY),
        (Privileges.DEVELOPER, BanchoClientPermission.DEVELOPER),
    )

    for privilege, client_flag in mapping:
        if privilege in privileges:
            flags |= client_flag

    return flags
