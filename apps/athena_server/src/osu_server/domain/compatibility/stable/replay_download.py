"""Stable replay download の transport-independent compatibility vocabulary を定義する module."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping


class ReplayDownloadBranch(StrEnum):
    """Stable replay download の client-visible response branch を表す enum.

    Attributes:
        SUCCESS (ReplayDownloadBranch): replay response を正常に返す branch.
        AUTH_FAILURE (ReplayDownloadBranch): request user を認証できない branch.
        HIDDEN_SCORE (ReplayDownloadBranch): score が閲覧不可の branch.
        STORAGE_MISSING (ReplayDownloadBranch): replay blob が storage にない branch.
        MISSING_REPLAY_PROVISIONAL (ReplayDownloadBranch): replay がない暫定 branch.
        MALFORMED_REQUEST_PROVISIONAL (ReplayDownloadBranch): malformed request の暫定 branch.
        BODY_STRATEGY_BLOCKED (ReplayDownloadBranch): body strategy が response を禁止する branch.

    Notes:
        Client-visible branch label だけを保持し, transport, SQLAlchemy, storage backend,
        athena_cli には依存しない.
    """

    SUCCESS = "success"
    AUTH_FAILURE = "auth_failure"
    HIDDEN_SCORE = "hidden_score"
    STORAGE_MISSING = "storage_missing"
    MISSING_REPLAY_PROVISIONAL = "missing_replay_provisional"
    MALFORMED_REQUEST_PROVISIONAL = "malformed_request_provisional"
    BODY_STRATEGY_BLOCKED = "body_strategy_blocked"


class ReplayDownloadBodyStrategy(StrEnum):
    """Stable replay download response body の生成方針を表す enum.

    Attributes:
        BLOCKED (ReplayDownloadBodyStrategy): success response body の生成を禁止する方針.
        DIRECT_BLOB_BYTES (ReplayDownloadBodyStrategy): stored blob bytes を直接返す方針.
        ASSEMBLE_DOWNLOAD_BODY (ReplayDownloadBodyStrategy): download response body を
            組み立てる方針.

    Notes:
        Stored replay blob object と client-visible response body は別概念として扱う.
    """

    BLOCKED = "blocked"
    DIRECT_BLOB_BYTES = "direct_blob_bytes"
    ASSEMBLE_DOWNLOAD_BODY = "assemble_download_body"


@dataclass(slots=True, frozen=True)
class ReplayDownloadResponseBody:
    """Stable client に返す replay download response body を表す value object.

    Attributes:
        payload (bytes): client-visible response body bytes. repr には出さない.

    Notes:
        Stored replay blob object とは別概念として扱う.
    """

    payload: bytes = field(repr=False)

    @property
    def byte_size(self) -> int:
        """Response body payload の byte size を返す.

        Returns:
            int: payload に含まれる byte 数.

        Notes:
            payload の内容は公開しない.
        """
        return len(self.payload)


@dataclass(slots=True, frozen=True)
class ReplayDownloadStoredBlobObject:
    """保存済み replay blob object を response body と分離して表す value object.

    Attributes:
        payload (bytes): stored replay blob object bytes. repr には出さない.

    Notes:
        ReplayDownloadResponseBody と同一視しない.
    """

    payload: bytes = field(repr=False)

    @property
    def byte_size(self) -> int:
        """Stored blob payload の byte size を返す.

        Returns:
            int: payload に含まれる byte 数.

        Notes:
            payload の内容は公開しない.
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
        ReplayDownloadBranch.BODY_STRATEGY_BLOCKED: ("body_strategy_blocked",),
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
