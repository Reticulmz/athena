"""Chat channelのrole based access policyを定義するmodule."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from osu_server.domain.identity.authorization import Privileges, has_privilege

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.chat.channels import ChannelRoleOverride


class ChannelPermission(Enum):
    """Channel role overrideに照合するpermission種別を表す閉集合.

    Attributes:
        READ (str): channelのread permissionを示す値.
        WRITE (str): channelへのmessage送信permissionを示す値.
    """

    READ = "read"
    WRITE = "write"


def has_channel_permission(
    *,
    user_privileges: int,
    user_role_ids: Iterable[int],
    overrides: Iterable[ChannelRoleOverride],
    permission: ChannelPermission,
) -> bool:
    """Userがchannelで要求されたpermissionを持つか判定する.

    Args:
        user_privileges (int): userに付与されたprivilege bitmask.
        user_role_ids (Iterable[int]): userに割り当てられたrole ID群.
        overrides (Iterable[ChannelRoleOverride]): channelに設定されたrole override群.
        permission (ChannelPermission): 判定するreadまたはwrite permission.

    Returns:
        bool: BYPASS_CHANNEL_ACLを持つか,一致するrole overrideが要求permissionを許可するとTrue.

    Notes:
        一致するoverrideがない場合はfail-closedでFalseを返す.
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
