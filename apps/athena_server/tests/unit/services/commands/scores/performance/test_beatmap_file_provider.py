"""PP計算用beatmap file入力providerの契約を検証する."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileAttachment,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.services.commands.scores.performance import (
    BeatmapMirrorPerformanceBeatmapFileProvider,
    PerformanceBeatmapFilePending,
    PerformanceBeatmapFilePendingReason,
    PerformanceBeatmapFileQuery,
    PerformanceBeatmapFileReady,
    PerformanceBeatmapFileUnavailable,
    PerformanceBeatmapFileUnavailableReason,
)
from osu_server.services.commands.storage.blob_storage import BlobContentUnavailableError

_NOW = datetime(2026, 6, 16, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_BEATMAP_ID = 2_000
_BEATMAPSET_ID = 1_000
_CHECKSUM = "0123456789abcdef0123456789abcdef"
_OSU_BYTES = b"osu file body"


class _Resolver:
    """固定したbeatmap解決結果を返すtest double.

    Attributes:
        result (BeatmapResolveResult): provide呼び出しへ返す解決結果.
        calls (list[tuple[int, BeatmapResolveOptions | None]]): 受け取ったbeatmap識別子と
            optionの記録.
    """

    result: BeatmapResolveResult
    calls: list[tuple[int, BeatmapResolveOptions | None]]

    def __init__(self, result: BeatmapResolveResult) -> None:
        """返却する解決結果を設定する.

        Args:
            result (BeatmapResolveResult): testでproviderへ返すbeatmap解決結果.
        """
        self.result = result
        self.calls = []

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """要求内容を記録して設定済みの解決結果を返す.

        Args:
            beatmap_id (int): 解決対象のbeatmap識別子.
            options (BeatmapResolveOptions | None): providerから渡される解決option.

        Returns:
            BeatmapResolveResult: 初期化時に設定した解決結果.
        """
        self.calls.append((beatmap_id, options))
        return self.result


class _BlobStorage:
    """blob byte列または読み取り失敗を再現するtest double.

    Attributes:
        _blobs (dict[int, bytes]): blob識別子ごとの返却byte列.
        _error (OSError | None): 読み取り時に送出する設定済みの失敗.
        calls (list[int]): 読み取りを要求されたblob識別子の記録.
    """

    _blobs: dict[int, bytes]
    _error: OSError | None
    calls: list[int]

    def __init__(
        self,
        blobs: dict[int, bytes] | None = None,
        error: OSError | None = None,
    ) -> None:
        """返却するblobと任意の失敗を設定する.

        Args:
            blobs (dict[int, bytes] | None): blob識別子ごとの内容. 未指定時は空の保存先を使う.
            error (OSError | None): 各読み取りで送出する失敗. 未指定時は内容を返す.
        """
        self._blobs = dict(blobs or {})
        self._error = error
        self.calls = []

    async def read_bytes(self, blob_id: int) -> bytes:
        """指定blobの内容を返すか利用不能を通知する.

        Args:
            blob_id (int): 読み取るblobの識別子.

        Returns:
            bytes: 設定済みblobの内容.

        Raises:
            OSError: 初期化時に読み取り失敗が設定されている場合.
            BlobContentUnavailableError: 指定blobの内容が設定されていない場合.
        """
        self.calls.append(blob_id)
        if self._error is not None:
            raise self._error
        blob = self._blobs.get(blob_id)
        if blob is None:
            raise BlobContentUnavailableError(f"blob content is unavailable: {blob_id}")
        return blob


@pytest.mark.asyncio
async def test_provider_requests_required_osu_file_and_returns_ready_bytes() -> None:
    """必須osu fileを要求し, 内容とprovenanceを返す契約を検証する.

    attachmentとblob内容を用意し, ready結果とattachment由来のprovenanceを確認する.
    require_osu_file optionの指定も確認する.

    Returns:
        None: providerのready結果と要求内容を検証して完了する.
    """
    attachment = _make_attachment(attachment_id=7, blob_id=42)
    resolver = _Resolver(_resolve_result(_make_beatmap(file_attachment=attachment)))
    blob_storage = _BlobStorage({42: _OSU_BYTES})
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileReady)
    assert result.osu_file_bytes == _OSU_BYTES
    assert result.provenance.beatmap_id == _BEATMAP_ID
    assert result.provenance.beatmap_file_attachment_id == 7
    assert result.provenance.blob_id == 42
    assert result.provenance.checksum_md5 == _CHECKSUM
    assert blob_storage.calls == [42]
    assert len(resolver.calls) == 1
    beatmap_id, options = resolver.calls[0]
    assert beatmap_id == _BEATMAP_ID
    assert options is not None
    assert options.require_osu_file is True


@pytest.mark.asyncio
async def test_provider_treats_missing_file_as_pending_input() -> None:
    """欠落したfileを再試行可能な入力待ちとして扱う契約を検証する.

    file stateがMISSINGのbeatmapを解決し, blobを読まずにpending理由を返すことを確認する.

    Returns:
        None: pending結果とblob未読を検証して完了する.
    """
    beatmap = _make_beatmap(file_state=BeatmapFileState.MISSING)
    resolver = _Resolver(_resolve_result(beatmap, file_status=BeatmapFileState.MISSING))
    blob_storage = _BlobStorage()
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFilePending)
    assert result.reason is PerformanceBeatmapFilePendingReason.OSU_FILE_MISSING
    assert result.file_status is BeatmapFileState.MISSING
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_treats_fetching_file_as_pending_input() -> None:
    """取得中fileを再試行可能な入力待ちとして扱う契約を検証する.

    file stateがPENDING_FETCHのbeatmapを解決し, blobを読まずにpending理由を返すことを確認する.

    Returns:
        None: pending結果とblob未読を検証して完了する.
    """
    beatmap = _make_beatmap(file_state=BeatmapFileState.PENDING_FETCH)
    resolver = _Resolver(_resolve_result(beatmap, file_status=BeatmapFileState.PENDING_FETCH))
    blob_storage = _BlobStorage()
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFilePending)
    assert result.reason is PerformanceBeatmapFilePendingReason.OSU_FILE_FETCH_PENDING
    assert result.file_status is BeatmapFileState.PENDING_FETCH
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_treats_unknown_pending_resolution_as_pending_input() -> None:
    """未解決のmetadata取得待ちを入力待ちとして扱う契約を検証する.

    beatmapを伴わないPENDING_FETCH解決結果を用意し, mirror理由を保ったpending結果を確認する.

    Returns:
        None: pending結果, metadata状態, mirror理由を検証して完了する.
    """
    resolver = _Resolver(
        _resolve_result(
            None,
            metadata_status=BeatmapFetchState.PENDING_FETCH,
            file_status=BeatmapFileState.MISSING,
            reason="unsolicited",
        )
    )
    blob_storage = _BlobStorage()
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFilePending)
    assert result.reason is PerformanceBeatmapFilePendingReason.BEATMAP_RESOLUTION_PENDING
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.mirror_reason == "unsolicited"
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_returns_unavailable_for_failed_file_fetch() -> None:
    """恒久的なfile取得失敗を利用不能として返す契約を検証する.

    FAILED stateのbeatmapを解決し, provenanceなしのunavailable結果とblob未読を確認する.

    Returns:
        None: unavailable理由とblob未読を検証して完了する.
    """
    beatmap = _make_beatmap(file_state=BeatmapFileState.FAILED)
    resolver = _Resolver(_resolve_result(beatmap, file_status=BeatmapFileState.FAILED))
    blob_storage = _BlobStorage()
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_FETCH_FAILED
    assert result.provenance is None
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_returns_unavailable_for_available_state_without_attachment() -> None:
    """attachmentのないAVAILABLE stateを利用不能として返す契約を検証する.

    fileが利用可能でもattachmentがないbeatmapを解決する.
    blobを読まずにunavailableになることを確認する.

    Returns:
        None: attachment利用不能の理由とblob未読を検証して完了する.
    """
    beatmap = _make_beatmap(file_state=BeatmapFileState.AVAILABLE)
    resolver = _Resolver(_resolve_result(beatmap, file_status=BeatmapFileState.AVAILABLE))
    blob_storage = _BlobStorage()
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_ATTACHMENT_UNAVAILABLE
    assert result.provenance is None
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_returns_unavailable_for_attachment_without_persistent_id() -> None:
    """永続識別子のないattachmentを利用不能として扱う契約を検証する.

    attachment idが未割当のbeatmapを解決し, blobを読まずにunavailableになることを確認する.

    Returns:
        None: attachment利用不能の理由とblob未読を検証して完了する.
    """
    attachment = _make_attachment(blob_id=42)
    resolver = _Resolver(_resolve_result(_make_beatmap(file_attachment=attachment)))
    blob_storage = _BlobStorage({42: _OSU_BYTES})
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_ATTACHMENT_UNAVAILABLE
    assert result.provenance is None
    assert blob_storage.calls == []


@pytest.mark.asyncio
async def test_provider_converts_blob_read_failure_to_unavailable_result() -> None:
    """blob読み取り失敗をprovenance付き利用不能結果へ変換する契約を検証する.

    利用可能attachmentと読み取り失敗を用意し, attachment情報を保ったunavailable結果を確認する.

    Returns:
        None: blob利用不能理由, provenance, 読み取り記録を検証して完了する.
    """
    attachment = _make_attachment(attachment_id=7, blob_id=42)
    resolver = _Resolver(_resolve_result(_make_beatmap(file_attachment=attachment)))
    blob_storage = _BlobStorage(error=BlobContentUnavailableError("missing blob"))
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_BLOB_UNAVAILABLE
    assert result.provenance is not None
    assert result.provenance.beatmap_file_attachment_id == 7
    assert result.provenance.blob_id == 42
    assert result.provenance.checksum_md5 == _CHECKSUM
    assert blob_storage.calls == [42]


@pytest.mark.asyncio
async def test_provider_returns_unavailable_for_empty_osu_file_bytes() -> None:
    """空のosu file内容を利用不能として返す契約を検証する.

    空byte列を返すblobを用意し, attachmentのprovenanceを保ったunavailable結果を確認する.

    Returns:
        None: 空file理由とprovenanceを検証して完了する.
    """
    attachment = _make_attachment(attachment_id=7, blob_id=42)
    resolver = _Resolver(_resolve_result(_make_beatmap(file_attachment=attachment)))
    blob_storage = _BlobStorage({42: b""})
    provider = BeatmapMirrorPerformanceBeatmapFileProvider(resolver, blob_storage)

    result = await provider.provide(PerformanceBeatmapFileQuery(beatmap_id=_BEATMAP_ID))

    assert isinstance(result, PerformanceBeatmapFileUnavailable)
    assert result.reason is PerformanceBeatmapFileUnavailableReason.OSU_FILE_EMPTY
    assert result.provenance is not None
    assert result.provenance.beatmap_file_attachment_id == 7
    assert result.provenance.blob_id == 42
    assert result.provenance.checksum_md5 == _CHECKSUM


def _make_attachment(
    *,
    blob_id: int,
    attachment_id: int | None = None,
    beatmap_id: int = _BEATMAP_ID,
) -> BeatmapFileAttachment:
    """test用のbeatmap file attachmentを構築する.

    Args:
        blob_id (int): attachmentが参照するblobの識別子.
        attachment_id (int | None): 永続化済みattachmentの識別子. 未指定時は未永続化を表す.
        beatmap_id (int): attachmentを所有するbeatmapの識別子.

    Returns:
        BeatmapFileAttachment: mirror由来の検証済みattachment.
    """
    return BeatmapFileAttachment(
        beatmap_id=beatmap_id,
        blob_id=blob_id,
        checksum_md5=_CHECKSUM,
        source=BeatmapFileSource.MIRROR,
        original_filename="map.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
        id=attachment_id,
    )


def _make_beatmap(
    *,
    file_state: BeatmapFileState | None = None,
    file_attachment: BeatmapFileAttachment | None = None,
) -> Beatmap:
    """指定したfile状態を持つtest用beatmapを構築する.

    Args:
        file_state (BeatmapFileState | None): 明示するfile取得状態.
            未指定時はattachmentの有無から決める.
        file_attachment (BeatmapFileAttachment | None): beatmapへ関連付けるfile attachment.

    Returns:
        Beatmap: provider入力として使用できるbeatmap.
    """
    return Beatmap(
        id=_BEATMAP_ID,
        beatmapset_id=_BEATMAPSET_ID,
        checksum_md5=_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Another",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=file_state
        or (
            BeatmapFileState.AVAILABLE if file_attachment is not None else BeatmapFileState.MISSING
        ),
        file_attachment=file_attachment,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _resolve_result(
    beatmap: Beatmap | None,
    *,
    metadata_status: BeatmapFetchState = BeatmapFetchState.FRESH,
    file_status: BeatmapFileState | None = None,
    reason: str | None = None,
) -> BeatmapResolveResult:
    """providerに返すbeatmap解決結果を構築する.

    Args:
        beatmap (Beatmap | None): 解決済みbeatmap. Noneはmetadata未解決を表す.
        metadata_status (BeatmapFetchState): metadata取得状態.
        file_status (BeatmapFileState | None): file取得状態.
            未指定時はbeatmap状態またはMISSINGを使う.
        reason (str | None): mirrorが返した補足理由.

    Returns:
        BeatmapResolveResult: 指定状態と任意理由を持つ解決結果.
    """
    return BeatmapResolveResult(
        beatmap=beatmap,
        beatmapset=None,
        eligibility=None,
        metadata_status=metadata_status,
        file_status=file_status
        or (beatmap.file_state if beatmap is not None else BeatmapFileState.MISSING),
        source=BeatmapMetadataSource.OFFICIAL if beatmap is not None else None,
        verified=beatmap is not None,
        last_fetched_at=beatmap.last_fetched_at if beatmap is not None else None,
        next_refresh_at=beatmap.next_refresh_at if beatmap is not None else None,
        reason=reason,
    )
