"""Friend relationship language for the identity bounded context."""

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
    """One directed friend edge from an owner to a target user."""

    owner_user_id: int
    target_user_id: int

    def __post_init__(self) -> None:
        if self.owner_user_id == self.target_user_id:
            msg = "friend relationship cannot target self"
            raise ValueError(msg)


class FriendMutationStatus(StrEnum):
    """Typed outcome for friend add/remove commands."""

    ADDED = "added"
    REMOVED = "removed"
    NO_OP = "no_op"


@dataclass(frozen=True, slots=True)
class FriendMutationOutcome:
    """Result of a friend mutation command."""

    status: FriendMutationStatus

    @property
    def changed(self) -> bool:
        return self.status in {
            FriendMutationStatus.ADDED,
            FriendMutationStatus.REMOVED,
        }


class FriendableSystemUserCatalog:
    """System-user friendability policy."""

    def __init__(
        self,
        *,
        system_users: Iterable[SystemUserIdentity],
        friendable_user_ids: frozenset[int],
    ) -> None:
        self._system_user_ids: frozenset[int] = frozenset(
            identity.user_id for identity in system_users
        )
        self._friendable_user_ids: frozenset[int] = friendable_user_ids

    @classmethod
    def with_bancho_bot(
        cls,
        bancho_bot_identity: SystemUserIdentity = BANCHO_BOT_IDENTITY,
    ) -> FriendableSystemUserCatalog:
        """Return the default system-user policy with explicit BanchoBot friendability."""
        return cls(
            system_users=(bancho_bot_identity,),
            friendable_user_ids=frozenset({bancho_bot_identity.user_id}),
        )

    def is_system_user(self, user_id: int) -> bool:
        """Return whether *user_id* is known as a system user."""
        return user_id in self._system_user_ids

    def is_friendable_system_user(self, user_id: int) -> bool:
        """Return whether *user_id* is a system user that can be explicitly friended."""
        return user_id in self._friendable_user_ids

    def allows_target(self, user_id: int) -> bool:
        """Return whether system-user policy allows this target.

        Human users are evaluated by repository existence checks.  Known
        system users must be explicitly marked friendable.
        """
        return not self.is_system_user(user_id) or self.is_friendable_system_user(user_id)
