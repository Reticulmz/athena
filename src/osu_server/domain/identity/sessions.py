"""Session and session authorization language for the identity context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.identity.authorization import Privileges


@dataclass(slots=True)
class SessionData:
    user_id: int
    username: str
    privileges: int
    country: str
    osu_version: str
    utc_offset: int
    display_city: bool
    client_hashes: str
    pm_private: bool
    role_ids: tuple[int, ...] = ()
    silence_end: int = 0

    def __post_init__(self) -> None:
        self.role_ids = tuple(self.role_ids)


@dataclass(slots=True, frozen=True)
class SessionAuthorization:
    """Immutable snapshot of current role-derived authorization.

    Represents privileges and role_ids as one consistent snapshot
    computed from the same role list at a single point in time.
    """

    privileges: Privileges
    role_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_ids", tuple(self.role_ids))


class AuthorizationRefreshStatus(StrEnum):
    """Outcome status for an authorization refresh operation."""

    REFRESHED = "refreshed"
    NO_ACTIVE_SESSION = "no_active_session"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class UserAuthorizationRefreshResult:
    """Result of refreshing authorization for a single user.

    Invariants:
        authorization is present only when status is REFRESHED.
    """

    user_id: int
    status: AuthorizationRefreshStatus
    authorization: SessionAuthorization | None = None

    def __post_init__(self) -> None:
        if self.status == AuthorizationRefreshStatus.REFRESHED:
            if self.authorization is None:
                raise ValueError("authorization must be present when status is REFRESHED")
        elif self.authorization is not None:
            raise ValueError("authorization must be None when status is not REFRESHED")


@dataclass(slots=True, frozen=True)
class RoleAuthorizationRefreshResult:
    """Aggregated result of refreshing authorization for all users assigned to a role.

    Contains one UserAuthorizationRefreshResult per assigned user returned by
    RoleRepository.get_user_ids_for_role().
    """

    role_id: int
    user_results: tuple[UserAuthorizationRefreshResult, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_results", tuple(self.user_results))
