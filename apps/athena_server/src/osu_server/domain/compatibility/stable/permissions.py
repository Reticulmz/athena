"""Server-side privilege と Stable client permission の compatibility mapping を定義する module."""

from __future__ import annotations

from enum import IntFlag

from osu_server.domain.identity.authorization import Privileges


class BanchoClientPermission(IntFlag):
    """Stable osu! client が bancho permission packet で解釈する bit flag を表す enum.

    Attributes:
        NORMAL (BanchoClientPermission): 通常 user を表す client-visible flag.
        NOMINATOR (BanchoClientPermission): nominator/moderator を表す client-visible flag.
        MODERATOR (BanchoClientPermission): NOMINATOR の compatibility alias.
        SUPPORTER (BanchoClientPermission): supporter を表す client-visible flag.
        OWNER (BanchoClientPermission): owner/friend を表す client-visible flag.
        FRIEND (BanchoClientPermission): OWNER の compatibility alias.
        DEVELOPER (BanchoClientPermission): developer/admin を表す client-visible flag.
        PEPPY (BanchoClientPermission): DEVELOPER の compatibility alias.
        TOURNAMENT_STAFF (BanchoClientPermission): tournament staff を表す client-visible flag.
    """

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
    """Server-side privilege を Stable client-visible permission へ変換する.

    Args:
        privileges (Privileges): user に付与された server-side privilege bit flag.

    Returns:
        BanchoClientPermission: Stable bancho permission packet に渡す client-visible flag.

    Notes:
        NORMAL は常に含める. ADMIN と DEVELOPER はどちらも DEVELOPER へ写す.
    """
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
    """Stable UserPresence へ載せる最優先の client-visible rank を返す.

    Args:
        permissions (BanchoClientPermission): 変換前の Stable client-visible permission 集合.

    Returns:
        BanchoClientPermission: DEVELOPER, NOMINATOR, SUPPORTER, NORMAL の優先順で選んだ rank.
    """
    rank_order = (
        BanchoClientPermission.DEVELOPER,
        BanchoClientPermission.NOMINATOR,
        BanchoClientPermission.SUPPORTER,
    )
    for rank in rank_order:
        if rank in permissions:
            return rank
    return BanchoClientPermission.NORMAL
