"""beatmap metadataとfile workflow用のtest data factoryを提供する."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import md5
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.storage.blobs import Blob
    from osu_server.services.commands.storage.blob_storage import BlobStorageService

_DEFAULT_BEATMAP_ID = 2_000
_DEFAULT_BEATMAPSET_ID = 1_000
_DEFAULT_CHECKSUM_MD5 = "0123456789abcdef0123456789abcdef"


class FakeProviderResultKind(StrEnum):
    """fake providerが返す結果種別を表す.

    Attributes:
        SUCCESS (str): providerが要求値を返した状態.
        PENDING (str): provider処理が完了していない状態.
        NOT_FOUND (str): 要求値が存在しない状態.
        RATE_LIMITED (str): providerがrate limitを返した状態.
        TIMEOUT (str): provider呼び出しがtimeoutした状態.
        SERVER_FAILURE (str): provider側のserver failure状態.
    """

    SUCCESS = "success"
    PENDING = "pending"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    SERVER_FAILURE = "server_failure"


class FakeProviderErrorKind(StrEnum):
    """fake provider responseへ付与するerror種別を表す.

    Attributes:
        RATE_LIMITED (str): rate limitによるfailure.
        TIMEOUT (str): timeoutによるfailure.
        SERVER_FAILURE (str): server failure.
        CHECKSUM_MISMATCH (str): checksum不一致によるfailure.
        NOT_FOUND (str): 要求値が存在しないfailure.
    """

    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    SERVER_FAILURE = "server_failure"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    NOT_FOUND = "not_found"


@dataclass(slots=True, frozen=True)
class BeatmapSnapshotFactory:
    """beatmap snapshot用の不変test dataを表す.

    Attributes:
        beatmap_id (int): beatmap識別子.
        beatmapset_id (int): 所属beatmapset識別子.
        checksum_md5 (str): beatmap contentのMD5 checksum.
        mode (str): game mode名.
        version (str): difficulty version名.
        official_status (str): official rank status名.
        official_status_source (str): official statusの取得元.
        official_status_verified (bool): official statusを検証済みか.
        local_status_override (str | None): local override status. 未設定時はNone.
        source (str): snapshotの取得元.
        verified (bool): snapshotの信頼性を検証済みか.
        last_fetched_at (datetime): 最終取得時刻.
        next_refresh_at (datetime): 次回更新予定時刻.
    """

    beatmap_id: int
    beatmapset_id: int
    checksum_md5: str
    mode: str
    version: str
    official_status: str
    official_status_source: str
    official_status_verified: bool
    local_status_override: str | None
    source: str
    verified: bool
    last_fetched_at: datetime
    next_refresh_at: datetime


@dataclass(slots=True, frozen=True)
class BeatmapSetSnapshotFactory:
    """beatmapset snapshot用の不変test dataを表す.

    Attributes:
        beatmapset_id (int): beatmapset識別子.
        artist (str): artist名.
        title (str): 曲名.
        creator (str): beatmap作成者名.
        source (str): snapshotの取得元.
        verified (bool): snapshotの信頼性を検証済みか.
        official_status (str): official rank status名.
        official_status_source (str): official statusの取得元.
        official_status_verified (bool): official statusを検証済みか.
        beatmaps (tuple[BeatmapSnapshotFactory, ...]): 所属beatmap snapshot群.
        last_fetched_at (datetime): 最終取得時刻.
        next_refresh_at (datetime): 次回更新予定時刻.
    """

    beatmapset_id: int
    artist: str
    title: str
    creator: str
    source: str
    verified: bool
    official_status: str
    official_status_source: str
    official_status_verified: bool
    beatmaps: tuple[BeatmapSnapshotFactory, ...]
    last_fetched_at: datetime
    next_refresh_at: datetime


@dataclass(slots=True, frozen=True)
class BeatmapFetchStateFactory:
    """beatmap fetch state用の不変test dataを表す.

    Attributes:
        target_type (str): fetch対象の種別.
        target_key (str): fetch対象を識別するkey.
        status (str): fetch lifecycleの状態.
        attempt_count (int): 実行試行回数.
        last_error (str | None): 最終failureの説明. 成功時はNone.
        pending_since (datetime | None): pending開始時刻. 未設定時はNone.
        last_attempted_at (datetime | None): 最終試行時刻. 未試行時はNone.
    """

    target_type: str
    target_key: str
    status: str
    attempt_count: int
    last_error: str | None
    pending_since: datetime | None
    last_attempted_at: datetime | None


@dataclass(slots=True, frozen=True)
class BeatmapFileAttachmentFactory:
    """beatmap file attachment用の不変test dataを表す.

    Attributes:
        beatmap_id (int): attachment先のbeatmap識別子.
        blob_id (int): file bodyを保持するblob識別子.
        checksum_md5 (str): 要求されたbeatmap checksum.
        verified_md5 (str): 取得fileから検証したMD5 checksum.
        source (str): fileの取得元.
        original_filename (str): providerが返した元filename.
        fetched_at (datetime): file取得時刻.
        verified_at (datetime): checksum検証時刻.
    """

    beatmap_id: int
    blob_id: int
    checksum_md5: str
    verified_md5: str
    source: str
    original_filename: str
    fetched_at: datetime
    verified_at: datetime


@dataclass(slots=True, frozen=True)
class BeatmapFileBodyFactory:
    """beatmap file body用の不変test dataを表す.

    Attributes:
        content (bytes): .osu fileのbyte列.
        md5 (str): contentのMD5 checksum.
        original_filename (str): providerが返す元filename.
    """

    content: bytes
    md5: str
    original_filename: str


@dataclass(slots=True, frozen=True)
class BeatmapBlobStorageWriteFactory:
    """blob保存結果とbeatmap attachmentをまとめるtest dataを表す.

    Attributes:
        blob (Blob): 保存済みfile bodyのblob metadata.
        attachment (BeatmapFileAttachmentFactory): blobを参照するbeatmap attachment.
    """

    blob: Blob
    attachment: BeatmapFileAttachmentFactory


@dataclass(slots=True, frozen=True)
class FakeMetadataProviderResponse:
    """metadata provider fakeが返す設定済みresponseを表す.

    Attributes:
        kind (FakeProviderResultKind): responseの結果種別.
        snapshot (BeatmapSetSnapshotFactory | None): 成功時に返すsnapshot. 不在時はNone.
        error_kind (FakeProviderErrorKind | None): failure種別. 成功またはpending時はNone.
    """

    kind: FakeProviderResultKind
    snapshot: BeatmapSetSnapshotFactory | None = None
    error_kind: FakeProviderErrorKind | None = None


@dataclass(slots=True, frozen=True)
class FakeFileProviderResponse:
    """file provider fakeが返す設定済みresponseを表す.

    Attributes:
        kind (FakeProviderResultKind): responseの結果種別.
        body (BeatmapFileBodyFactory | None): 成功時に返すfile body. 失敗時はNone.
        source (str): fileを取得したsource名.
        error_kind (FakeProviderErrorKind | None): failure種別. 成功時はNone.
    """

    kind: FakeProviderResultKind
    body: BeatmapFileBodyFactory | None = None
    source: str = "official"
    error_kind: FakeProviderErrorKind | None = None


def make_beatmap_snapshot_factory(
    *,
    beatmap_id: int = _DEFAULT_BEATMAP_ID,
    beatmapset_id: int = _DEFAULT_BEATMAPSET_ID,
    checksum_md5: str = _DEFAULT_CHECKSUM_MD5,
    mode: str = "osu",
    version: str = "Another",
    official_status: str = "ranked",
    official_status_source: str = "osu_api",
    official_status_verified: bool = True,
    local_status_override: str | None = None,
    source: str = "official",
    verified: bool = True,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> BeatmapSnapshotFactory:
    """指定値またはdefault値からbeatmap snapshot test dataを作る.

    Args:
        beatmap_id (int): beatmap識別子.
        beatmapset_id (int): 所属beatmapset識別子.
        checksum_md5 (str): contentのMD5 checksum.
        mode (str): game mode名.
        version (str): difficulty version名.
        official_status (str): official rank status名.
        official_status_source (str): official statusの取得元.
        official_status_verified (bool): official statusを検証済みか.
        local_status_override (str | None): local override status.
        source (str): snapshotの取得元.
        verified (bool): snapshotを検証済みか.
        last_fetched_at (datetime | None): 取得時刻. Noneなら現在UTC時刻.
        next_refresh_at (datetime | None): 次回更新時刻. Noneなら取得時刻から30日後.

    Returns:
        BeatmapSnapshotFactory: metadata resolution testへ渡すsnapshot data.
    """
    fetched_at = last_fetched_at or datetime.now(UTC)
    return BeatmapSnapshotFactory(
        beatmap_id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
        mode=mode,
        version=version,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        local_status_override=local_status_override,
        source=source,
        verified=verified,
        last_fetched_at=fetched_at,
        next_refresh_at=next_refresh_at or fetched_at + timedelta(days=30),
    )


def make_beatmapset_snapshot_factory(
    *,
    beatmapset_id: int = _DEFAULT_BEATMAPSET_ID,
    artist: str = "Camellia",
    title: str = "Exit This Earth's Atomosphere",
    creator: str = "Realazy",
    source: str = "official",
    verified: bool = True,
    official_status: str = "ranked",
    official_status_source: str = "osu_api",
    official_status_verified: bool = True,
    beatmaps: Iterable[BeatmapSnapshotFactory] | None = None,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> BeatmapSetSnapshotFactory:
    """指定値またはdefault値からbeatmapset snapshot test dataを作る.

    Args:
        beatmapset_id (int): beatmapset識別子.
        artist (str): artist名.
        title (str): 曲名.
        creator (str): beatmap作成者名.
        source (str): snapshotの取得元.
        verified (bool): snapshotを検証済みか.
        official_status (str): official rank status名.
        official_status_source (str): official statusの取得元.
        official_status_verified (bool): official statusを検証済みか.
        beatmaps (Iterable[BeatmapSnapshotFactory] | None): 所属beatmap. Noneならdefaultの1件.
        last_fetched_at (datetime | None): 取得時刻. Noneなら現在UTC時刻.
        next_refresh_at (datetime | None): 次回更新時刻. Noneなら取得時刻から30日後.

    Returns:
        BeatmapSetSnapshotFactory: metadata provider fakeへ渡すsnapshot data.
    """
    fetched_at = last_fetched_at or datetime.now(UTC)
    child_beatmaps = tuple(
        beatmaps
        if beatmaps is not None
        else (
            make_beatmap_snapshot_factory(
                beatmapset_id=beatmapset_id,
                official_status=official_status,
                official_status_source=official_status_source,
                official_status_verified=official_status_verified,
                source=source,
                verified=verified,
                last_fetched_at=fetched_at,
            ),
        )
    )
    return BeatmapSetSnapshotFactory(
        beatmapset_id=beatmapset_id,
        artist=artist,
        title=title,
        creator=creator,
        source=source,
        verified=verified,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        beatmaps=child_beatmaps,
        last_fetched_at=fetched_at,
        next_refresh_at=next_refresh_at or fetched_at + timedelta(days=30),
    )


def make_beatmap_fetch_state_factory(
    *,
    target_type: str = "metadata",
    target_key: str = "2000",
    status: str = "pending",
    attempt_count: int = 0,
    last_error: str | None = None,
    pending_since: datetime | None = None,
    last_attempted_at: datetime | None = None,
) -> BeatmapFetchStateFactory:
    """指定値からbeatmap fetch state test dataを作る.

    Args:
        target_type (str): fetch対象の種別.
        target_key (str): fetch対象のkey.
        status (str): fetch lifecycle状態.
        attempt_count (int): 実行試行回数.
        last_error (str | None): 最終failureの説明.
        pending_since (datetime | None): pending開始時刻.
        last_attempted_at (datetime | None): 最終試行時刻.

    Returns:
        BeatmapFetchStateFactory: persistence fakeへ渡すfetch state data.
    """
    return BeatmapFetchStateFactory(
        target_type=target_type,
        target_key=target_key,
        status=status,
        attempt_count=attempt_count,
        last_error=last_error,
        pending_since=pending_since,
        last_attempted_at=last_attempted_at,
    )


def make_beatmap_file_attachment_factory(
    *,
    beatmap_id: int = _DEFAULT_BEATMAP_ID,
    blob_id: int = 1,
    checksum_md5: str = _DEFAULT_CHECKSUM_MD5,
    verified_md5: str | None = None,
    source: str = "official",
    original_filename: str = "2000.osu",
    fetched_at: datetime | None = None,
    verified_at: datetime | None = None,
) -> BeatmapFileAttachmentFactory:
    """指定値またはdefault値からbeatmap file attachment test dataを作る.

    Args:
        beatmap_id (int): attachment先のbeatmap識別子.
        blob_id (int): file bodyを保持するblob識別子.
        checksum_md5 (str): 要求されたbeatmap checksum.
        verified_md5 (str | None): 検証済みMD5 checksum. Noneならchecksum_md5.
        source (str): fileの取得元.
        original_filename (str): providerが返した元filename.
        fetched_at (datetime | None): file取得時刻. Noneなら現在UTC時刻.
        verified_at (datetime | None): checksum検証時刻. Noneならfetched_at.

    Returns:
        BeatmapFileAttachmentFactory: file fetch testへ渡すattachment data.
    """
    fetched = fetched_at or datetime.now(UTC)
    return BeatmapFileAttachmentFactory(
        beatmap_id=beatmap_id,
        blob_id=blob_id,
        checksum_md5=checksum_md5,
        verified_md5=verified_md5 or checksum_md5,
        source=source,
        original_filename=original_filename,
        fetched_at=fetched,
        verified_at=verified_at or fetched,
    )


def make_beatmap_file_body(
    *,
    content: bytes = b"osu file format v14\n[General]\nAudioFilename: audio.mp3\n",
    md5: str | None = _DEFAULT_CHECKSUM_MD5,
    original_filename: str = "2000.osu",
) -> BeatmapFileBodyFactory:
    """指定値またはdefault値からbeatmap file body test dataを作る.

    Args:
        content (bytes): .osu fileのbyte列.
        md5 (str | None): contentのMD5 checksum. Noneならcontentから計算する.
        original_filename (str): providerが返す元filename.

    Returns:
        BeatmapFileBodyFactory: file provider fakeへ渡すbody data.
    """
    return BeatmapFileBodyFactory(
        content=content,
        md5=md5 or _md5_hex(content),
        original_filename=original_filename,
    )


def make_metadata_provider_response(
    *,
    kind: FakeProviderResultKind = FakeProviderResultKind.SUCCESS,
    snapshot: BeatmapSetSnapshotFactory | None = None,
    error_kind: FakeProviderErrorKind | None = None,
) -> FakeMetadataProviderResponse:
    """Metadata provider fake用のresponseを結果種別に整合させて作る.

    Args:
        kind (FakeProviderResultKind): responseの結果種別.
        snapshot (BeatmapSetSnapshotFactory | None): 成功時のsnapshot.
        error_kind (FakeProviderErrorKind | None): 明示するfailure種別.

    Returns:
        FakeMetadataProviderResponse: kindとerrorの整合を保つfake response.
    """
    return FakeMetadataProviderResponse(
        kind=kind,
        snapshot=snapshot
        if kind is not FakeProviderResultKind.SUCCESS
        else snapshot or make_beatmapset_snapshot_factory(),
        error_kind=error_kind or _error_kind_for_result(kind),
    )


def make_file_provider_response(
    *,
    kind: FakeProviderResultKind = FakeProviderResultKind.SUCCESS,
    body: BeatmapFileBodyFactory | None = None,
    source: str = "official",
    error_kind: FakeProviderErrorKind | None = None,
) -> FakeFileProviderResponse:
    """File provider fake用のresponseを結果種別に整合させて作る.

    Args:
        kind (FakeProviderResultKind): responseの結果種別.
        body (BeatmapFileBodyFactory | None): 成功時に返すfile body.
        source (str): fileを取得したsource名.
        error_kind (FakeProviderErrorKind | None): 明示するfailure種別.

    Returns:
        FakeFileProviderResponse: kindとerrorの整合を保つfake response.
    """
    resolved_error = error_kind or _error_kind_for_result(kind)
    resolved_kind = kind if error_kind is None else _result_kind_for_error(error_kind)
    return FakeFileProviderResponse(
        kind=resolved_kind,
        body=body if resolved_kind is FakeProviderResultKind.SUCCESS else None,
        source=source,
        error_kind=resolved_error,
    )


@dataclass(slots=True)
class FakeBeatmapMetadataProvider:
    """key別の設定済みresponseを返しcallを記録するmetadata provider fake.

    Attributes:
        by_beatmap_id (dict[int, FakeMetadataProviderResponse]): beatmap id別response.
        by_beatmapset_id (dict[int, FakeMetadataProviderResponse]): beatmapset id別response.
        by_checksum (dict[str, FakeMetadataProviderResponse]): checksum別response.
        calls (list[tuple[str, str]]): 呼び出されたlookup種別とkey.
        default_response (FakeMetadataProviderResponse): key未登録時に返すresponse.
    """

    by_beatmap_id: dict[int, FakeMetadataProviderResponse] = field(default_factory=dict)
    by_beatmapset_id: dict[int, FakeMetadataProviderResponse] = field(default_factory=dict)
    by_checksum: dict[str, FakeMetadataProviderResponse] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    default_response: FakeMetadataProviderResponse = field(
        default_factory=lambda: make_metadata_provider_response(
            kind=FakeProviderResultKind.NOT_FOUND
        )
    )

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> FakeMetadataProviderResponse:
        """Beatmap idに対応する設定済みmetadata responseを返す.

        Args:
            beatmap_id (int): lookupするbeatmap識別子.

        Returns:
            FakeMetadataProviderResponse: 登録済みresponse. 未登録時はdefault_response.
        """
        self.calls.append(("beatmap_id", str(beatmap_id)))
        return self.by_beatmap_id.get(beatmap_id, self.default_response)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> FakeMetadataProviderResponse:
        """Beatmapset idに対応する設定済みmetadata responseを返す.

        Args:
            beatmapset_id (int): lookupするbeatmapset識別子.

        Returns:
            FakeMetadataProviderResponse: 登録済みresponse. 未登録時はdefault_response.
        """
        self.calls.append(("beatmapset_id", str(beatmapset_id)))
        return self.by_beatmapset_id.get(beatmapset_id, self.default_response)

    async def lookup_by_checksum(self, checksum_md5: str) -> FakeMetadataProviderResponse:
        """checksumに対応する設定済みmetadata responseを返す.

        Args:
            checksum_md5 (str): lookupするMD5 checksum.

        Returns:
            FakeMetadataProviderResponse: 登録済みresponse. 未登録時はdefault_response.
        """
        self.calls.append(("checksum_md5", checksum_md5))
        return self.by_checksum.get(checksum_md5, self.default_response)


@dataclass(slots=True)
class FakeBeatmapFileProvider:
    """beatmap id別の設定済みresponseを返しcallを記録するfile provider fake.

    Attributes:
        by_beatmap_id (dict[int, FakeFileProviderResponse]): beatmap id別response.
        calls (list[int]): fetchしたbeatmap識別子.
        default_response (FakeFileProviderResponse): key未登録時に返すresponse.
    """

    by_beatmap_id: dict[int, FakeFileProviderResponse] = field(default_factory=dict)
    calls: list[int] = field(default_factory=list)
    default_response: FakeFileProviderResponse = field(
        default_factory=lambda: make_file_provider_response(kind=FakeProviderResultKind.NOT_FOUND)
    )

    async def fetch_osu_file(self, beatmap_id: int) -> FakeFileProviderResponse:
        """Beatmap idに対応する設定済みfile responseを返す.

        Args:
            beatmap_id (int): fetchするbeatmap識別子.

        Returns:
            FakeFileProviderResponse: 登録済みresponse. 未登録時はdefault_response.
        """
        self.calls.append(beatmap_id)
        return self.by_beatmap_id.get(beatmap_id, self.default_response)


async def store_beatmap_file_body_blob(
    blob_storage_service: BlobStorageService,
    file_body: BeatmapFileBodyFactory,
    *,
    beatmap_id: int = _DEFAULT_BEATMAP_ID,
    source: str = "official",
) -> BeatmapBlobStorageWriteFactory:
    """File bodyをblob storageへ保存してattachment test dataを返す.

    Args:
        blob_storage_service (BlobStorageService): file bodyを保存するservice.
        file_body (BeatmapFileBodyFactory): 保存するfile body data.
        beatmap_id (int): attachment先のbeatmap識別子.
        source (str): attachmentに記録する取得元.

    Returns:
        BeatmapBlobStorageWriteFactory: 保存済みblobと対応attachment.
    """
    result = await blob_storage_service.put_bytes(
        file_body.content,
        content_type="application/octet-stream",
    )
    blob = result.blob
    attachment = make_beatmap_file_attachment_factory(
        beatmap_id=beatmap_id,
        blob_id=blob.id,
        checksum_md5=file_body.md5,
        verified_md5=file_body.md5,
        source=source,
        original_filename=file_body.original_filename,
    )
    return BeatmapBlobStorageWriteFactory(blob=blob, attachment=attachment)


def _error_kind_for_result(kind: FakeProviderResultKind) -> FakeProviderErrorKind | None:
    """provider結果種別に対応するdefault error種別を返す.

    Args:
        kind (FakeProviderResultKind): error種別を求める結果種別.

    Returns:
        FakeProviderErrorKind | None: failure種別. 成功またはpending時はNone.
    """
    if kind in {FakeProviderResultKind.SUCCESS, FakeProviderResultKind.PENDING}:
        return None
    if kind is FakeProviderResultKind.NOT_FOUND:
        return FakeProviderErrorKind.NOT_FOUND
    if kind is FakeProviderResultKind.RATE_LIMITED:
        return FakeProviderErrorKind.RATE_LIMITED
    if kind is FakeProviderResultKind.TIMEOUT:
        return FakeProviderErrorKind.TIMEOUT
    return FakeProviderErrorKind.SERVER_FAILURE


def _result_kind_for_error(error_kind: FakeProviderErrorKind) -> FakeProviderResultKind:
    """Provider error種別に対応する結果種別を返す.

    Args:
        error_kind (FakeProviderErrorKind): 結果種別を求めるfailure種別.

    Returns:
        FakeProviderResultKind: errorを表す結果種別.
    """
    if error_kind is FakeProviderErrorKind.NOT_FOUND:
        return FakeProviderResultKind.NOT_FOUND
    if error_kind is FakeProviderErrorKind.RATE_LIMITED:
        return FakeProviderResultKind.RATE_LIMITED
    if error_kind is FakeProviderErrorKind.TIMEOUT:
        return FakeProviderResultKind.TIMEOUT
    return FakeProviderResultKind.SERVER_FAILURE


def _md5_hex(content: bytes) -> str:
    """Test file contentのMD5 hex digestを計算する.

    Args:
        content (bytes): digestを求めるbyte列.

    Returns:
        str: contentのlowercase MD5 hex digest.
    """
    return md5(content, usedforsecurity=False).hexdigest()
