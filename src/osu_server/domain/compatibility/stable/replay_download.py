"""Stable replay download の互換語彙."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping


class ReplayDownloadBranch(StrEnum):
    """Stable replay download の response branch を表す.

    Args:
        なし.

    Returns:
        Enum class のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Client-visible branch label だけを保持し, transport, SQLAlchemy,
        storage backend, athena_cli には依存しない.
    """

    SUCCESS = "success"
    AUTH_FAILURE = "auth_failure"
    HIDDEN_SCORE = "hidden_score"
    STORAGE_MISSING = "storage_missing"
    MISSING_REPLAY_PROVISIONAL = "missing_replay_provisional"
    MALFORMED_REQUEST_PROVISIONAL = "malformed_request_provisional"
    BODY_STRATEGY_BLOCKED = "body_strategy_blocked"


class ReplayDownloadBodyStrategy(StrEnum):
    """Stable replay download response body の生成方針を表す.

    Args:
        なし.

    Returns:
        Enum class のため戻り値はない.

    Raises:
        なし.

    Constraints:
        `blocked` は success response body を生成してはいけない strategy として扱う.
        Stored Replay blob object と client-visible response body は別概念として扱う.
    """

    BLOCKED = "blocked"
    DIRECT_BLOB_BYTES = "direct_blob_bytes"
    ASSEMBLE_DOWNLOAD_BODY = "assemble_download_body"


@dataclass(slots=True, frozen=True)
class ReplayDownloadResponseBody:
    """Stable client に返す Replay Download Response Body を表す.

    Args:
        payload: Client-visible response body bytes.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Stored Replay blob object とは別概念として扱う. repr には payload を出さない.
    """

    payload: bytes = field(repr=False)

    @property
    def byte_size(self) -> int:
        """Response body payload の byte size を返す.

        Args:
            なし.

        Returns:
            Payload の byte size.

        Raises:
            なし.

        Constraints:
            Payload 内容は公開しない.
        """

        return len(self.payload)


@dataclass(slots=True, frozen=True)
class ReplayDownloadStoredBlobObject:
    """保存済み Replay blob object を response body から分離して表す.

    Args:
        payload: Stored Replay blob object bytes.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Replay Download Response Body と同一視しない. repr には payload を出さない.
    """

    payload: bytes = field(repr=False)

    @property
    def byte_size(self) -> int:
        """Stored blob payload の byte size を返す.

        Args:
            なし.

        Returns:
            Payload の byte size.

        Raises:
            なし.

        Constraints:
            Payload 内容は公開しない.
        """

        return len(self.payload)


REPLAY_DOWNLOAD_CONTRACT_BRANCH_LABELS_BY_BRANCH: Final[
    Mapping[ReplayDownloadBranch, tuple[str, ...]]
] = MappingProxyType(
    {
        ReplayDownloadBranch.SUCCESS: ("success",),
        ReplayDownloadBranch.AUTH_FAILURE: ("auth_failure",),
        ReplayDownloadBranch.HIDDEN_SCORE: ("hidden_score",),
        ReplayDownloadBranch.STORAGE_MISSING: ("storage_missing",),
        ReplayDownloadBranch.MISSING_REPLAY_PROVISIONAL: ("missing_replay",),
        ReplayDownloadBranch.MALFORMED_REQUEST_PROVISIONAL: (
            "missing_score_id",
            "malformed_score_id",
            "missing_mode",
            "malformed_mode",
            "unknown_field",
        ),
    }
)


__all__ = [
    "REPLAY_DOWNLOAD_CONTRACT_BRANCH_LABELS_BY_BRANCH",
    "ReplayDownloadBodyStrategy",
    "ReplayDownloadBranch",
    "ReplayDownloadResponseBody",
    "ReplayDownloadStoredBlobObject",
]
