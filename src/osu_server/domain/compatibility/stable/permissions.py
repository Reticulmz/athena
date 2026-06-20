"""Stable client permission compatibility values."""

from __future__ import annotations

from enum import IntFlag

from osu_server.domain.identity.authorization import Privileges


class BanchoClientPermission(IntFlag):
    """Flags the stable osu! client understands for bancho permission packets."""

    NORMAL = 1
    NOMINATOR = 2
    MODERATOR = NOMINATOR
    SUPPORTER = 4
    OWNER = 8
    FRIEND = OWNER
    DEVELOPER = 16
    PEPPY = DEVELOPER
    TOURNAMENT_STAFF = 32


def to_bancho_client_permissions(privileges: Privileges) -> BanchoClientPermission:
    """Convert server-side privileges to stable client-visible permissions."""
    flags = BanchoClientPermission.NORMAL

    mapping: tuple[tuple[Privileges, BanchoClientPermission], ...] = (
        (Privileges.MODERATOR, BanchoClientPermission.NOMINATOR),
        (Privileges.SUPPORTER, BanchoClientPermission.SUPPORTER),
        (Privileges.ADMIN, BanchoClientPermission.DEVELOPER),
        (Privileges.DEVELOPER, BanchoClientPermission.DEVELOPER),
        (Privileges.TOURNAMENT, BanchoClientPermission.TOURNAMENT_STAFF),
    )

    for privilege, client_flag in mapping:
        if privilege in privileges:
            flags |= client_flag

    return flags


def to_user_presence_permissions(
    permissions: BanchoClientPermission,
) -> BanchoClientPermission:
    """Return the dominant client-visible rank for stable UserPresence."""
    rank_order = (
        BanchoClientPermission.DEVELOPER,
        BanchoClientPermission.NOMINATOR,
        BanchoClientPermission.SUPPORTER,
    )
    for rank in rank_order:
        if rank in permissions:
            return rank
    return BanchoClientPermission.NORMAL
