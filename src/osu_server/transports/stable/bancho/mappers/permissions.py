"""Stable bancho authorization output mapping."""

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
    """Client-visible authorization flags for stable bancho packets."""

    login_permissions: BanchoClientPermission
    presence_permissions: BanchoClientPermission


def map_stable_bancho_authorization(
    privileges: Privileges,
) -> StableBanchoAuthorizationOutput:
    """Map server-side privileges to stable bancho authorization output."""
    client_permissions = to_bancho_client_permissions(privileges)
    return StableBanchoAuthorizationOutput(
        login_permissions=client_permissions,
        presence_permissions=to_user_presence_permissions(client_permissions),
    )


__all__ = ["StableBanchoAuthorizationOutput", "map_stable_bancho_authorization"]
