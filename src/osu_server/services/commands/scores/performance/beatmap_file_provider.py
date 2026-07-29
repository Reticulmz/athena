"""スコア performance calculation 用の beatmap file 入力を解決する."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, final

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import BeatmapFileAttachment


class _BeatmapFileResolver(Protocol):
    """beatmap mirror から beatmap と osu file の状態を解決する内部境界を表す."""

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """指定した beatmap id に対応する mirror 解決結果を返す.

        Args:
            beatmap_id (int): 解決対象の beatmap id.
            options (BeatmapResolveOptions | None):
                osu file の取得要件を含む解決オプション. 未指定時はNone.

        Returns:
            BeatmapResolveResult: beatmap metadata,file 状態,解決理由を含む結果.
        """
        ...


class _BlobReader(Protocol):
    """blob storage から content bytes を取得する内部境界を表す."""

    async def read_bytes(self, blob_id: int) -> bytes:
        """指定 blob の content bytes を読み込む.

        Args:
            blob_id (int): 読み込む blob の永続識別子.

        Returns:
            bytes: 保存済み blob の完全な content bytes.

        Raises:
            OSError: blob content を読み込めない場合.
        """
        ...


class PerformanceBeatmapFileStatus(Enum):
    """performance calculation に渡す beatmap file の可用状態を表す.

    Attributes:
        READY (PerformanceBeatmapFileStatus): 有効な osu file bytes を利用できる状態.
        PENDING (PerformanceBeatmapFileStatus): mirror または file fetch の完了を待つ状態.
        UNAVAILABLE (PerformanceBeatmapFileStatus): 永続的または現時点で利用不能な状態.
    """

    READY = "ready"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class PerformanceBeatmapFilePendingReason(Enum):
    """beatmap file 入力が一時的に利用不能な理由を表す.

    Attributes:
        BEATMAP_RESOLUTION_PENDING (PerformanceBeatmapFilePendingReason):
            beatmap metadata 解決の完了待ち.
        OSU_FILE_MISSING (PerformanceBeatmapFilePendingReason):
            osu file がまだ保存されていない状態.
        OSU_FILE_FETCH_PENDING (PerformanceBeatmapFilePendingReason): osu file fetch の完了待ち.
    """

    BEATMAP_RESOLUTION_PENDING = "beatmap_resolution_pending"
    OSU_FILE_MISSING = "osu_file_missing"
    OSU_FILE_FETCH_PENDING = "osu_file_fetch_pending"


class PerformanceBeatmapFileUnavailableReason(Enum):
    """beatmap file 入力を calculation に使えない理由を表す.

    Attributes:
        BEATMAP_METADATA_UNAVAILABLE (PerformanceBeatmapFileUnavailableReason):
            beatmap metadata の取得失敗.
        OSU_FILE_ATTACHMENT_MISMATCH (PerformanceBeatmapFileUnavailableReason):
            attachment が要求 beatmap と不一致.
        OSU_FILE_FETCH_FAILED (PerformanceBeatmapFileUnavailableReason):
            osu file fetch が失敗した状態.
        OSU_FILE_ATTACHMENT_UNAVAILABLE (PerformanceBeatmapFileUnavailableReason):
            利用可能な attachment がない状態.
        OSU_FILE_BLOB_UNAVAILABLE (PerformanceBeatmapFileUnavailableReason):
            attachment の blob を読み込めない状態.
        OSU_FILE_EMPTY (PerformanceBeatmapFileUnavailableReason):
            読み込んだ osu file bytes が空の状態.
    """

    BEATMAP_METADATA_UNAVAILABLE = "beatmap_metadata_unavailable"
    OSU_FILE_ATTACHMENT_MISMATCH = "osu_file_attachment_mismatch"
    OSU_FILE_FETCH_FAILED = "osu_file_fetch_failed"
    OSU_FILE_ATTACHMENT_UNAVAILABLE = "osu_file_attachment_unavailable"
    OSU_FILE_BLOB_UNAVAILABLE = "osu_file_blob_unavailable"
    OSU_FILE_EMPTY = "osu_file_empty"


@dataclass(slots=True, frozen=True)
class PerformanceBeatmapFileQuery:
    """performance calculation 用 beatmap file の解決要求を表す.

    Attributes:
        beatmap_id (int): 解決する beatmap の正の永続識別子.
    """

    beatmap_id: int

    def __post_init__(self) -> None:
        """指定した beatmap id が正の永続識別子であることを検証する.

        Returns:
            None: 入力値を検証し,呼び出し側へ値を返さずに完了する.

        Raises:
            ValueError: beatmap_id が0以下の場合.
        """
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class PerformanceBeatmapFileProvenance:
    """後続 calculation の provenance に必要な BeatmapFileAttachment 識別子を表す.

    Attributes:
        beatmap_id (int): attachment が属する beatmap の正の永続識別子.
        beatmap_file_attachment_id (int): 使用した beatmap file attachment の正の永続識別子.
        blob_id (int): osu file content を保持する blob の正の永続識別子.
        checksum_md5 (str): 使用した osu file content の MD5 checksum.
    """

    beatmap_id: int
    beatmap_file_attachment_id: int
    blob_id: int
    checksum_md5: str

    def __post_init__(self) -> None:
        """この provenance の永続識別子がすべて正であることを検証する.

        Returns:
            None: 識別子を検証し,呼び出し側へ値を返さずに完了する.

        Raises:
            ValueError: beatmap,attachment,または blob の id が0以下の場合.
        """
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)
        if self.beatmap_file_attachment_id <= 0:
            msg = "beatmap_file_attachment_id must be positive"
            raise ValueError(msg)
        if self.blob_id <= 0:
            msg = "blob_id must be positive"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class PerformanceBeatmapFileReady:
    """performance calculation に使える beatmap file 入力を表す.

    Attributes:
        beatmap_id (int): 解決済み beatmap の永続識別子.
        osu_file_bytes (bytes): calculation に渡す空でない osu file content.
        provenance (PerformanceBeatmapFileProvenance): 使用 file を追跡する永続 provenance.
        status (PerformanceBeatmapFileStatus): 常に READY となる入力状態.
    """

    beatmap_id: int
    osu_file_bytes: bytes
    provenance: PerformanceBeatmapFileProvenance
    status: PerformanceBeatmapFileStatus = field(
        init=False,
        default=PerformanceBeatmapFileStatus.READY,
    )


@dataclass(slots=True, frozen=True)
class PerformanceBeatmapFilePending:
    """一時的な解決待ちにより calculation を延期する beatmap file 入力を表す.

    Attributes:
        beatmap_id (int): 解決を試みた beatmap の永続識別子.
        reason (PerformanceBeatmapFilePendingReason): 再試行可能な待機理由.
        metadata_status (BeatmapFetchState): mirror が報告した metadata fetch 状態.
        file_status (BeatmapFileState): mirror が報告した osu file 状態.
        mirror_reason (str | None): mirror が返した補助的な理由. ない場合はNone.
        status (PerformanceBeatmapFileStatus): 常に PENDING となる入力状態.
    """

    beatmap_id: int
    reason: PerformanceBeatmapFilePendingReason
    metadata_status: BeatmapFetchState
    file_status: BeatmapFileState
    mirror_reason: str | None
    status: PerformanceBeatmapFileStatus = field(
        init=False,
        default=PerformanceBeatmapFileStatus.PENDING,
    )


@dataclass(slots=True, frozen=True)
class PerformanceBeatmapFileUnavailable:
    """calculation に利用できない beatmap file 入力を表す.

    Attributes:
        beatmap_id (int): 解決を試みた beatmap の永続識別子.
        reason (PerformanceBeatmapFileUnavailableReason): 利用不能と判定した理由.
        metadata_status (BeatmapFetchState): mirror が報告した metadata fetch 状態.
        file_status (BeatmapFileState): mirror が報告した osu file 状態.
        mirror_reason (str | None): mirror が返した補助的な理由. ない場合はNone.
        provenance (PerformanceBeatmapFileProvenance | None):
            確認できた file provenance. 不明な場合はNone.
        status (PerformanceBeatmapFileStatus): 常に UNAVAILABLE となる入力状態.
    """

    beatmap_id: int
    reason: PerformanceBeatmapFileUnavailableReason
    metadata_status: BeatmapFetchState
    file_status: BeatmapFileState
    mirror_reason: str | None
    provenance: PerformanceBeatmapFileProvenance | None = None
    status: PerformanceBeatmapFileStatus = field(
        init=False,
        default=PerformanceBeatmapFileStatus.UNAVAILABLE,
    )


PerformanceBeatmapFileResult = (
    PerformanceBeatmapFileReady | PerformanceBeatmapFilePending | PerformanceBeatmapFileUnavailable
)


class PerformanceBeatmapFileProvider(Protocol):
    """performance calculation 用の beatmap file 入力を提供する公開境界を表す."""

    async def provide(
        self,
        query: PerformanceBeatmapFileQuery,
    ) -> PerformanceBeatmapFileResult:
        """指定 query に対応する ready,pending,または unavailable 入力を返す.

        Args:
            query (PerformanceBeatmapFileQuery): 解決対象 beatmap を指定する要求.

        Returns:
            PerformanceBeatmapFileResult: calculation に渡せる bytes または遅延/利用不能の理由.
        """
        ...


@final
class BeatmapMirrorPerformanceBeatmapFileProvider:
    """beatmap mirror と blob storage を通じて PP 用 beatmap file bytes を解決する."""

    def __init__(
        self,
        beatmap_resolver: _BeatmapFileResolver,
        blob_storage: _BlobReader,
    ) -> None:
        """依存する beatmap resolver と blob reader を受け取る.

        Args:
            beatmap_resolver (_BeatmapFileResolver): metadata と osu file 状態を解決する adapter.
            blob_storage (_BlobReader): attachment の content bytes を読み込む adapter.
        """
        self._beatmap_resolver = beatmap_resolver
        self._blob_storage = blob_storage

    async def provide(
        self,
        query: PerformanceBeatmapFileQuery,
    ) -> PerformanceBeatmapFileResult:
        """指定 beatmap の osu file を解決し,calculation 用の入力状態へ変換する.

        Args:
            query (PerformanceBeatmapFileQuery): 要求する beatmap の正の永続識別子.

        Returns:
            PerformanceBeatmapFileResult:
                ready bytes,再試行可能な pending,または unavailable の結果.
        """
        result = await self._beatmap_resolver.resolve_by_beatmap_id(
            query.beatmap_id,
            BeatmapResolveOptions(require_osu_file=True),
        )

        pending_or_unavailable = _result_before_blob_read(query.beatmap_id, result)
        if pending_or_unavailable is not None:
            return pending_or_unavailable

        assert result.beatmap is not None
        attachment = result.beatmap.file_attachment
        assert attachment is not None

        return await self._read_attachment(query.beatmap_id, result, attachment)

    async def _read_attachment(
        self,
        beatmap_id: int,
        result: BeatmapResolveResult,
        attachment: BeatmapFileAttachment,
    ) -> PerformanceBeatmapFileReady | PerformanceBeatmapFileUnavailable:
        """解決済み attachment の blob を読み込み,ready または unavailable 結果へ変換する.

        Args:
            beatmap_id (int): 要求された beatmap の永続識別子.
            result (BeatmapResolveResult): mirror が返した解決結果.
            attachment (BeatmapFileAttachment): bytes を読み込む解決済み file attachment.

        Returns:
            PerformanceBeatmapFileReady | PerformanceBeatmapFileUnavailable:
                空でない bytes または読込失敗理由.
        """
        provenance = _provenance_from_attachment(attachment)
        try:
            osu_file_bytes = await self._blob_storage.read_bytes(attachment.blob_id)
        except OSError:
            return _unavailable(
                beatmap_id,
                result,
                PerformanceBeatmapFileUnavailableReason.OSU_FILE_BLOB_UNAVAILABLE,
                provenance=provenance,
            )

        if len(osu_file_bytes) == 0:
            return _unavailable(
                beatmap_id,
                result,
                PerformanceBeatmapFileUnavailableReason.OSU_FILE_EMPTY,
                provenance=provenance,
            )

        return PerformanceBeatmapFileReady(
            beatmap_id=beatmap_id,
            osu_file_bytes=osu_file_bytes,
            provenance=provenance,
        )


def _result_before_blob_read(
    beatmap_id: int,
    result: BeatmapResolveResult,
) -> PerformanceBeatmapFilePending | PerformanceBeatmapFileUnavailable | None:
    """読み込み前に確定する pending または unavailable 結果を返す.

    Args:
        beatmap_id (int): 要求された beatmap の永続識別子.
        result (BeatmapResolveResult): mirror が返した metadata と file の状態.

    Returns:
        PerformanceBeatmapFilePending | PerformanceBeatmapFileUnavailable | None:
            blob 読込を止める結果. 続行可能ならNone.
    """
    if result.beatmap is None:
        return _unknown_beatmap_result(beatmap_id, result)

    pending_reason = _pending_reason_for_file_state(result.file_status)
    if pending_reason is not None:
        return _pending(beatmap_id, result, pending_reason)

    unavailable_reason = _unavailable_reason_for_file_state(result.file_status)
    if unavailable_reason is not None:
        return _unavailable(beatmap_id, result, unavailable_reason)

    attachment_reason = _unavailable_reason_for_attachment(beatmap_id, result)
    if attachment_reason is not None:
        return _unavailable(beatmap_id, result, attachment_reason)

    return None


def _unknown_beatmap_result(
    beatmap_id: int,
    result: BeatmapResolveResult,
) -> PerformanceBeatmapFilePending | PerformanceBeatmapFileUnavailable:
    """解決できない metadata の mirror 結果を pending または unavailable へ変換する.

    Args:
        beatmap_id (int): 要求された beatmap の永続識別子.
        result (BeatmapResolveResult): beatmap がない mirror 解決結果.

    Returns:
        PerformanceBeatmapFilePending | PerformanceBeatmapFileUnavailable:
            metadata fetch 状態に対応する入力結果.
    """
    if result.metadata_status is BeatmapFetchState.FAILED:
        return _unavailable(
            beatmap_id,
            result,
            PerformanceBeatmapFileUnavailableReason.BEATMAP_METADATA_UNAVAILABLE,
        )
    return _pending(
        beatmap_id,
        result,
        PerformanceBeatmapFilePendingReason.BEATMAP_RESOLUTION_PENDING,
    )


def _pending_reason_for_file_state(
    file_state: BeatmapFileState,
) -> PerformanceBeatmapFilePendingReason | None:
    """指定 file 状態に対応する再試行可能な pending 理由を返す.

    Args:
        file_state (BeatmapFileState): mirror が報告した osu file の状態.

    Returns:
        PerformanceBeatmapFilePendingReason | None:
            MISSING または PENDING_FETCH の理由. それ以外はNone.
    """
    return {
        BeatmapFileState.MISSING: PerformanceBeatmapFilePendingReason.OSU_FILE_MISSING,
        BeatmapFileState.PENDING_FETCH: PerformanceBeatmapFilePendingReason.OSU_FILE_FETCH_PENDING,
    }.get(file_state)


def _unavailable_reason_for_file_state(
    file_state: BeatmapFileState,
) -> PerformanceBeatmapFileUnavailableReason | None:
    """指定 file 状態に対応する利用不能理由を返す.

    Args:
        file_state (BeatmapFileState): mirror が報告した osu file の状態.

    Returns:
        PerformanceBeatmapFileUnavailableReason | None: FAILED の理由. それ以外はNone.
    """
    if file_state is BeatmapFileState.FAILED:
        return PerformanceBeatmapFileUnavailableReason.OSU_FILE_FETCH_FAILED
    return None


def _unavailable_reason_for_attachment(
    beatmap_id: int,
    result: BeatmapResolveResult,
) -> PerformanceBeatmapFileUnavailableReason | None:
    """利用可能な attachment と beatmap 所有関係から利用不能理由を返す.

    Args:
        beatmap_id (int): 要求された beatmap の永続識別子.
        result (BeatmapResolveResult): attachment を含む可能性がある mirror 解決結果.

    Returns:
        PerformanceBeatmapFileUnavailableReason | None: attachment の不備理由. 使用可能ならNone.
    """
    assert result.beatmap is not None
    attachment = result.beatmap.file_attachment
    if attachment is None or attachment.id is None:
        return PerformanceBeatmapFileUnavailableReason.OSU_FILE_ATTACHMENT_UNAVAILABLE
    if attachment.beatmap_id != beatmap_id:
        return PerformanceBeatmapFileUnavailableReason.OSU_FILE_ATTACHMENT_MISMATCH
    return None


def _pending(
    beatmap_id: int,
    result: BeatmapResolveResult,
    reason: PerformanceBeatmapFilePendingReason,
) -> PerformanceBeatmapFilePending:
    """解決済み mirror 結果から pending 入力を構成する.

    Args:
        beatmap_id (int): 要求された beatmap の永続識別子.
        result (BeatmapResolveResult): metadata と file 状態を含む mirror 解決結果.
        reason (PerformanceBeatmapFilePendingReason): calculation を延期する理由.

    Returns:
        PerformanceBeatmapFilePending: mirror 状態を保持した再試行可能な入力結果.
    """
    return PerformanceBeatmapFilePending(
        beatmap_id=beatmap_id,
        reason=reason,
        metadata_status=result.metadata_status,
        file_status=result.file_status,
        mirror_reason=result.reason,
    )


def _unavailable(
    beatmap_id: int,
    result: BeatmapResolveResult,
    reason: PerformanceBeatmapFileUnavailableReason,
    *,
    provenance: PerformanceBeatmapFileProvenance | None = None,
) -> PerformanceBeatmapFileUnavailable:
    """解決済み mirror 結果から unavailable 入力を構成する.

    Args:
        beatmap_id (int): 要求された beatmap の永続識別子.
        result (BeatmapResolveResult): metadata と file 状態を含む mirror 解決結果.
        reason (PerformanceBeatmapFileUnavailableReason): calculation に利用できない理由.
        provenance (PerformanceBeatmapFileProvenance | None):
            確認済み file provenance. 不明な場合はNone.

    Returns:
        PerformanceBeatmapFileUnavailable: mirror 状態を保持した利用不能入力結果.
    """
    return PerformanceBeatmapFileUnavailable(
        beatmap_id=beatmap_id,
        reason=reason,
        metadata_status=result.metadata_status,
        file_status=result.file_status,
        mirror_reason=result.reason,
        provenance=provenance,
    )


def _provenance_from_attachment(
    attachment: BeatmapFileAttachment,
) -> PerformanceBeatmapFileProvenance:
    """永続化済み file attachment から calculation provenance を構成する.

    Args:
        attachment (BeatmapFileAttachment): 永続識別子を持つ解決済み file attachment.

    Returns:
        PerformanceBeatmapFileProvenance: calculation に記録する attachment と blob の識別情報.
    """
    assert attachment.id is not None
    return PerformanceBeatmapFileProvenance(
        beatmap_id=attachment.beatmap_id,
        beatmap_file_attachment_id=attachment.id,
        blob_id=attachment.blob_id,
        checksum_md5=attachment.checksum_md5,
    )


__all__ = (
    "BeatmapMirrorPerformanceBeatmapFileProvider",
    "PerformanceBeatmapFilePending",
    "PerformanceBeatmapFilePendingReason",
    "PerformanceBeatmapFileProvenance",
    "PerformanceBeatmapFileProvider",
    "PerformanceBeatmapFileQuery",
    "PerformanceBeatmapFileReady",
    "PerformanceBeatmapFileResult",
    "PerformanceBeatmapFileStatus",
    "PerformanceBeatmapFileUnavailable",
    "PerformanceBeatmapFileUnavailableReason",
)
