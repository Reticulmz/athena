"""Chat channel access policies."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from osu_server.domain.identity.authorization import Privileges, has_privilege

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.chat.channels import ChannelRoleOverride


class ChannelPermission(Enum):
    """Permission checked against channel role overrides."""

    READ = "read"
    WRITE = "write"


def has_channel_permission(
    *,
    user_privileges: int,
    user_role_ids: Iterable[int],
    overrides: Iterable[ChannelRoleOverride],
    permission: ChannelPermission,
) -> bool:
    """Return whether a user can read or write a channel.

    Channels with no matching overrides are fail-closed unless the user has the
    explicit ACL bypass privilege.
    """
    if has_privilege(user_privileges, Privileges.BYPASS_CHANNEL_ACL):
        return True

    user_role_set = set(user_role_ids)
    for override in overrides:
        if override.role_id not in user_role_set:
            continue
        if permission is ChannelPermission.READ and override.can_read:
            return True
        if permission is ChannelPermission.WRITE and override.can_write:
            return True
    return False
