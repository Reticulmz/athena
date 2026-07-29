"""Identity context が使う server-side authorization language を定義する module."""

from __future__ import annotations

from enum import IntFlag


class Privileges(IntFlag):
    """User に付与する server-side authorization capability の bit flag を表す enum.

    Attributes:
        NONE (Privileges): privilege を一つも持たない状態.
        NORMAL (Privileges): 通常 user として扱う capability.
        VERIFIED (Privileges): verification 済み user として扱う capability.
        SUPPORTER (Privileges): supporter 専用 capability.
        MODERATOR (Privileges): moderation capability.
        ADMIN (Privileges): privilege check を包括的に bypass する administration capability.
        DEVELOPER (Privileges): development operation 用 capability.
        TOURNAMENT (Privileges): tournament staff 用 capability.
        UNRESTRICTED (Privileges): restriction を受けていない状態を表す capability.
        EDIT_CHANNEL (Privileges): channel 編集 capability.
        BYPASS_CHANNEL_ACL (Privileges): channel ACL を bypass する capability.
    """

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
    """User が要求されたすべての privilege を持つか判定する.

    Args:
        user_privileges (int): 判定対象 user の privilege bitmask.
        required (Privileges): 操作に必要な privilege bit flag の組合せ.

    Returns:
        bool: ADMIN を持つか, required の全 bit を持つ場合はTrue.

    Notes:
        ADMIN はこの server-side authorization 判定だけで全 check を bypass する.
    """
    if user_privileges & Privileges.ADMIN:
        return True
    return (user_privileges & required) == required
