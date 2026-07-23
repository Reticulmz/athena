"""Stable Bancho packet 用の client-visible authorization を変換する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.compatibility.stable.permissions import (
    BanchoClientPermission,
    to_bancho_client_permissions,
    to_user_presence_permissions,
)

if TYPE_CHECKING:
    from osu_server.domain.identity.authorization import Privileges


@dataclass(frozen=True, slots=True)
class StableBanchoAuthorizationOutput:
    """Stable Bancho packet へ載せる client-visible authorization を表す.

    Attributes:
        login_permissions (BanchoClientPermission): login reply に使う permission flag.
        presence_permissions (BanchoClientPermission): USER_PRESENCE に使う permission flag.
    """

    login_permissions: BanchoClientPermission
    presence_permissions: BanchoClientPermission


def map_stable_bancho_authorization(
    privileges: Privileges,
) -> StableBanchoAuthorizationOutput:
    """server-side privilege を Stable Bancho authorization output へ変換する.

    Args:
        privileges (Privileges): domain が認可に使う server-side privilege 集合.

    Returns:
        StableBanchoAuthorizationOutput: login と presence の両方に使う stable permission flag.
    """
    client_permissions = to_bancho_client_permissions(privileges)
    return StableBanchoAuthorizationOutput(
        login_permissions=client_permissions,
        presence_permissions=to_user_presence_permissions(client_permissions),
    )


__all__ = ["StableBanchoAuthorizationOutput", "map_stable_bancho_authorization"]
