"""Identity context の friend relationship と system-user policy を定義する module."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.identity.system_users import SystemUserIdentity


@dataclass(frozen=True, slots=True)
class FriendRelationship:
    """Owner user から target user へ向かう一方向の friend edge を表す value object.

    Attributes:
        owner_user_id (int): friend list を所有する user の ID.
        target_user_id (int): owner が friend として登録する user の ID.

    Notes:
        self-target は有効な friend relationship ではない.
    """

    owner_user_id: int
    target_user_id: int

    def __post_init__(self) -> None:
        """Self-target を拒否して friend relationship の invariant を検証する.

        Returns:
            None: validation だけを行い値を返さない.

        Raises:
            ValueError: owner_user_id と target_user_id が同一の場合.
        """
        if self.owner_user_id == self.target_user_id:
            msg = "friend relationship cannot target self"
            raise ValueError(msg)


class FriendMutationStatus(StrEnum):
    """Friend add/remove command の型付き outcome を表す enum.

    Attributes:
        ADDED (FriendMutationStatus): relationship を新たに追加した結果.
        REMOVED (FriendMutationStatus): 既存 relationship を削除した結果.
        NO_OP (FriendMutationStatus): 状態変更が不要だった結果.
    """

    ADDED = "added"
    REMOVED = "removed"
    NO_OP = "no_op"


@dataclass(frozen=True, slots=True)
class FriendMutationOutcome:
    """Friend mutation command の結果を表す immutable value object.

    Attributes:
        status (FriendMutationStatus): add, remove, または no-op を示す結果.
    """

    status: FriendMutationStatus

    @property
    def changed(self) -> bool:
        """結果が durable な friend relationship を変更したか返す.

        Returns:
            bool: status が ADDED または REMOVED の場合はTrue.
        """
        return self.status in {
            FriendMutationStatus.ADDED,
            FriendMutationStatus.REMOVED,
        }


class FriendableSystemUserCatalog:
    """System user を friend target にできるか判定する policy catalog.

    Attributes:
        _system_user_ids (frozenset[int]): system user として予約された user ID 群.
        _friendable_user_ids (frozenset[int]): 明示的に friend 登録を許可する system user ID 群.
    """

    def __init__(
        self,
        *,
        system_users: Iterable[SystemUserIdentity],
        friendable_user_ids: frozenset[int],
    ) -> None:
        """System user と friendable な system user の集合から policy を作成する.

        Args:
            system_users (Iterable[SystemUserIdentity]): system user として予約する identity 群.
            friendable_user_ids (frozenset[int]): friend 登録を許可する system user ID 群.

        Notes:
            Human user の存在確認はこの catalog の責務ではなく repository 側で行う.
        """
        self._system_user_ids: frozenset[int] = frozenset(
            identity.user_id for identity in system_users
        )
        self._friendable_user_ids: frozenset[int] = friendable_user_ids

    @classmethod
    def with_bancho_bot(
        cls,
        bancho_bot_identity: SystemUserIdentity = BANCHO_BOT_IDENTITY,
    ) -> FriendableSystemUserCatalog:
        """BanchoBot だけを friendable にした default policy を返す.

        Args:
            bancho_bot_identity (SystemUserIdentity): system user として登録する
                BanchoBot identity.

        Returns:
            FriendableSystemUserCatalog: BanchoBot を system user かつ friendable とする policy.
        """
        return cls(
            system_users=(bancho_bot_identity,),
            friendable_user_ids=frozenset({bancho_bot_identity.user_id}),
        )

    def is_system_user(self, user_id: int) -> bool:
        """指定した user ID が system user として予約されているか返す.

        Args:
            user_id (int): 判定する user ID.

        Returns:
            bool: catalog に system user として含まれる場合はTrue.
        """
        return user_id in self._system_user_ids

    def is_friendable_system_user(self, user_id: int) -> bool:
        """指定した system user ID を明示的に friend 登録できるか返す.

        Args:
            user_id (int): 判定する user ID.

        Returns:
            bool: catalog に friendable system user として含まれる場合はTrue.
        """
        return user_id in self._friendable_user_ids

    def allows_target(self, user_id: int) -> bool:
        """System-user policy が指定 target を許可するか返す.

        Args:
            user_id (int): friend target として判定する user ID.

        Returns:
            bool: human user または friendable な system user の場合はTrue.

        Notes:
            Human user の実在確認は caller が repository query で別途行う.
        """
        return not self.is_system_user(user_id) or self.is_friendable_system_user(user_id)
