"""Stable client compatibility domain package."""

from osu_server.domain.compatibility.stable.mode import StableMode
from osu_server.domain.compatibility.stable.presence_filter import StablePresenceFilter
from osu_server.domain.compatibility.stable.status import (
    DEFAULT_STABLE_USER_STATUS,
    StableStatus,
    StableUserStatus,
)

__all__ = [
    "DEFAULT_STABLE_USER_STATUS",
    "StableMode",
    "StablePresenceFilter",
    "StableStatus",
    "StableUserStatus",
]
