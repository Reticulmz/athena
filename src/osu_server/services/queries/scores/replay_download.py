"""Replay download query service component を提供する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from osu_server.domain.compatibility.stable import (
    ReplayDownloadBodyStrategy,
    ReplayDownloadBranch,
    ReplayDownloadResponseBody,
    ReplayDownloadStoredBlobObject,
)


@dataclass(slots=True, frozen=True)
class ReplayDownloadBodyBuildInput:
    """Replay download response body build の入力を表す.

    Args:
        strategy: Local validation で選ばれた response body strategy.
        stored_blob: Replay attachment から読んだ stored blob object.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Stored blob bytes は validation 済みの値だけを渡す. Transport,
        SQLAlchemy, storage backend detail, credential value は含めない.
    """

    strategy: ReplayDownloadBodyStrategy
    stored_blob: ReplayDownloadStoredBlobObject


@dataclass(slots=True, frozen=True)
class ReplayDownloadBodyBuildResult:
    """Replay download response body build の結果を表す.

    Args:
        branch: Response body build の observable branch.
        response_body: Success branch で client-visible に返す body.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        ValueError: Success branch と response body の有無が矛盾する場合.

    Constraints:
        Success 以外の branch は response body を保持しない. Payload の内容は
        repr に出さない.
    """

    branch: ReplayDownloadBranch
    response_body: ReplayDownloadResponseBody | None = None

    def __post_init__(self) -> None:
        if self.branch is ReplayDownloadBranch.SUCCESS and self.response_body is None:
            msg = "success replay download body result requires response body"
            raise ValueError(msg)
        if self.branch is not ReplayDownloadBranch.SUCCESS and self.response_body is not None:
            msg = "non-success replay download body result must not include response body"
            raise ValueError(msg)

    @property
    def is_success(self) -> bool:
        """Success branch かつ response body があるかを返す.

        Args:
            なし.

        Returns:
            Success branch で response body がある場合は True.

        Raises:
            なし.

        Constraints:
            HTTP status は扱わず, query service result の branch だけを判定する.
        """

        return self.branch is ReplayDownloadBranch.SUCCESS and self.response_body is not None


@final
class ReplayDownloadBodyAssembler:
    """Stored replay bytes から client-visible response body を作る.

    Args:
        なし.

    Returns:
        Class のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Blocked strategy と未確定 assemble strategy は bytes を生成しない.
        Transport, SQLAlchemy, storage backend implementation, Valkey, taskiq,
        composition には依存しない.
    """

    def build(
        self,
        input_data: ReplayDownloadBodyBuildInput,
    ) -> ReplayDownloadBodyBuildResult:
        """Replay download response body build result を返す.

        Args:
            input_data: Strategy と stored blob object.

        Returns:
            Success または body strategy blocked の build result.

        Raises:
            なし.

        Constraints:
            `direct_blob_bytes` では stored blob bytes をそのまま response body
            として返す. `assemble_download_body` は local validation decision が
            まだ存在しないため blocked として扱う.
        """

        match input_data.strategy:
            case ReplayDownloadBodyStrategy.BLOCKED:
                return _blocked_result()
            case ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES:
                return ReplayDownloadBodyBuildResult(
                    branch=ReplayDownloadBranch.SUCCESS,
                    response_body=ReplayDownloadResponseBody(
                        payload=input_data.stored_blob.payload,
                    ),
                )
            case ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY:
                # Local validation decision が入るまでは format 変換を推測しない.
                return _blocked_result()


def _blocked_result() -> ReplayDownloadBodyBuildResult:
    return ReplayDownloadBodyBuildResult(
        branch=ReplayDownloadBranch.BODY_STRATEGY_BLOCKED,
        response_body=None,
    )


__all__ = [
    "ReplayDownloadBodyAssembler",
    "ReplayDownloadBodyBuildInput",
    "ReplayDownloadBodyBuildResult",
]
