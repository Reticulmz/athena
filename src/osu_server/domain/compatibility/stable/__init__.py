"""Stable client compatibility domain package."""

from osu_server.domain.compatibility.stable.grade import StableGrade
from osu_server.domain.compatibility.stable.mode import StableMode
from osu_server.domain.compatibility.stable.presence_filter import StablePresenceFilter
from osu_server.domain.compatibility.stable.replay_download import (
    REPLAY_DOWNLOAD_CONTRACT_BRANCH_LABELS_BY_BRANCH,
    ReplayDownloadBodyStrategy,
    ReplayDownloadBranch,
    ReplayDownloadResponseBody,
    ReplayDownloadStoredBlobObject,
)
from osu_server.domain.compatibility.stable.status import (
    DEFAULT_STABLE_USER_STATUS,
    StableStatus,
    StableUserStatus,
)

__all__ = [
    "DEFAULT_STABLE_USER_STATUS",
    "REPLAY_DOWNLOAD_CONTRACT_BRANCH_LABELS_BY_BRANCH",
    "ReplayDownloadBodyStrategy",
    "ReplayDownloadBranch",
    "ReplayDownloadResponseBody",
    "ReplayDownloadStoredBlobObject",
    "StableGrade",
    "StableMode",
    "StablePresenceFilter",
    "StableStatus",
    "StableUserStatus",
]
