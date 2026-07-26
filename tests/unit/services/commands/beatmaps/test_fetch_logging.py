"""このmoduleはbeatmap fetch jobの構造化logging contractを検証する.

metadataとfile fetchの開始, 成功, 失敗, mirror fallback, checksum mismatchのeventを確認する.
すべてのtestはlogging sink設定に依存せずcapture_logsでevent名とfieldを検証する.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from structlog.testing import capture_logs
from tests.support.beatmaps import InMemoryBeatmapStore

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapFreshnessPolicy,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    OsuFileFetchResult,
)
from osu_server.domain.storage.blobs import Blob, BlobStorageBackendKind, BlobStored
from osu_server.infrastructure.beatmaps.metadata_sources import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)

_NOW = datetime.now(UTC) + timedelta(days=365)
_ONE_HOUR = timedelta(hours=1)
_THIRTY_DAYS = timedelta(days=30)
_DEFAULT_CHECKSUM = "0123456789abcdef0123456789abcdef"


# ---------------------------------------------------------------------------
# Stub providers (same pattern as test_fetch.py)
# ---------------------------------------------------------------------------


@dataclass
class StubMetadataProvider:
    """このlog capture test用のin-memory metadata providerを提供する.

    Attributes:
        by_beatmap_id (dict[int, BeatmapsetSnapshot | None]): beatmap IDごとの返却snapshot.
        by_beatmapset_id (dict[int, BeatmapsetSnapshot | None]): beatmapset IDごとの返却snapshot.
        by_checksum (dict[str, BeatmapsetSnapshot | None]): MD5 checksumごとの返却snapshot.
        exception (Exception | None): lookup時に意図的に送出する例外.
        delay (float): 各lookupの前に待機する秒数.
        calls (list[str]): 実行したlookup種別と入力値の履歴.
    """

    by_beatmap_id: dict[int, BeatmapsetSnapshot | None] = field(default_factory=dict)
    by_beatmapset_id: dict[int, BeatmapsetSnapshot | None] = field(default_factory=dict)
    by_checksum: dict[str, BeatmapsetSnapshot | None] = field(default_factory=dict)
    exception: Exception | None = None
    delay: float = 0
    calls: list[str] = field(default_factory=list)

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        """対象beatmap IDでsnapshotを検索するtest double呼出を処理する.

        Args:
            beatmap_id (int): 検索対象のbeatmap ID.

        Returns:
            BeatmapsetSnapshot | None: 設定済みsnapshot. 未設定の場合はNone.

        Raises:
            Exception: exception属性に設定された例外がある場合.
        """
        self.calls.append(f"beatmap_id:{beatmap_id}")
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.exception is not None:
            raise self.exception
        return self.by_beatmap_id.get(beatmap_id)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        """対象beatmapset IDでsnapshotを検索するtest double呼出を処理する.

        Args:
            beatmapset_id (int): 検索対象のbeatmapset ID.

        Returns:
            BeatmapsetSnapshot | None: 設定済みsnapshot. 未設定の場合はNone.

        Raises:
            Exception: exception属性に設定された例外がある場合.
        """
        self.calls.append(f"beatmapset_id:{beatmapset_id}")
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.exception is not None:
            raise self.exception
        return self.by_beatmapset_id.get(beatmapset_id)

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        """MD5 checksumでsnapshotを検索するtest double呼出を処理する.

        Args:
            checksum_md5 (str): 検索対象のMD5 checksum.

        Returns:
            BeatmapsetSnapshot | None: 設定済みsnapshot. 未設定の場合はNone.

        Raises:
            Exception: exception属性に設定された例外がある場合.
        """
        self.calls.append(f"checksum:{checksum_md5}")
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.exception is not None:
            raise self.exception
        return self.by_checksum.get(checksum_md5)


@dataclass
class StubFileProvider:
    """このlog capture test用のin-memory file providerを提供する.

    Attributes:
        by_beatmap_id (dict[int, OsuFileFetchResult]): beatmap IDごとの返却file結果.
        exception (Exception | None): fetch時に意図的に送出する例外.
        delay (float): fetch前に待機する秒数.
        calls (list[int]): fetchしたbeatmap IDの履歴.
    """

    by_beatmap_id: dict[int, OsuFileFetchResult] = field(default_factory=dict)
    exception: Exception | None = None
    delay: float = 0
    calls: list[int] = field(default_factory=list)

    async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult:
        """対象beatmapのosu fileを取得するtest double呼出を処理する.

        Args:
            beatmap_id (int): 取得対象のbeatmap ID.

        Returns:
            OsuFileFetchResult: 設定済みのfile取得結果.

        Raises:
            Exception: exception属性に設定された例外がある場合.
            ValueError: 指定beatmap IDのfile結果が未設定の場合.
        """
        self.calls.append(beatmap_id)
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.exception is not None:
            raise self.exception
        result = self.by_beatmap_id.get(beatmap_id)
        if result is None:
            raise ValueError(f"No file configured for beatmap_id={beatmap_id}")
        return result


@dataclass
class StubBlobStorageService:
    """このlog capture test用に保存済みblobを記録するstorage serviceを提供する.

    Attributes:
        next_blob_id (int): 次に保存するblobへ割り当てる識別子.
        stored (list[Blob]): 保存済みblobの履歴.
    """

    next_blob_id: int = 1
    stored: list[Blob] = field(default_factory=list)

    async def put_bytes(self, data: bytes, *, content_type: str) -> BlobStored:
        """対象byte列をlocal blobとして記録して保存結果を返す.

        Args:
            data (bytes): 保存対象のosu file byte列.
            content_type (str): 保存するcontent type.

        Returns:
            BlobStored: 新規blobを含む保存結果.
        """
        blob = Blob(
            id=self.next_blob_id,
            sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            content_type=content_type,
            storage_backend=BlobStorageBackendKind.LOCAL,
            storage_key=f"stub/{self.next_blob_id}",
            created_at=_NOW,
        )
        self.next_blob_id += 1
        self.stored.append(blob)
        return BlobStored(blob=blob)


# ---------------------------------------------------------------------------
# Snapshot factory helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    *,
    beatmap_id: int = 2000,
    beatmapset_id: int = 1000,
    checksum_md5: str = _DEFAULT_CHECKSUM,
    mode: str = "osu",
    version: str = "Another",
    artist: str = "Camellia",
    title: str = "Exit This Earth's Atomosphere",
    creator: str = "Realazy",
    source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    official_status_source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    official_status_verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    beatmap_count: int = 1,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> BeatmapsetSnapshot:
    """対象metadata fetch test用のbeatmapset snapshotを作る.

    Args:
        beatmap_id (int): 先頭beatmapへ設定する識別子.
        beatmapset_id (int): snapshotへ設定するbeatmapset識別子.
        checksum_md5 (str): 先頭beatmapへ設定するMD5 checksum.
        mode (str): 先頭beatmapへ設定するgame mode値.
        version (str): 先頭beatmapへ設定するdifficulty version.
        artist (str): beatmapsetへ設定するartist名.
        title (str): beatmapsetへ設定するtitle.
        creator (str): beatmapsetへ設定するcreator名.
        source (BeatmapMetadataSource): snapshotを提供したmetadata source.
        verified (BeatmapSourceVerification): sourceの検証状態.
        official_status (BeatmapRankStatus): official rank status.
        official_status_source (BeatmapMetadataSource): official statusの取得source.
        official_status_verified (BeatmapSourceVerification): official status sourceの検証状態.
        beatmap_count (int): 生成するchild beatmap snapshot数.
        last_fetched_at (datetime | None): metadataを取得した時刻. Noneの場合は固定test時刻.
        next_refresh_at (datetime | None): 次回更新時刻. Noneの場合は30日後.

    Returns:
        BeatmapsetSnapshot: 指定したmetadataとchild beatmapを持つsnapshot.
    """
    fetched_at = last_fetched_at or _NOW
    refresh_at = next_refresh_at or _NOW + _THIRTY_DAYS
    child_snapshots = [
        BeatmapSnapshot(
            beatmap_id=beatmap_id + i,
            beatmapset_id=beatmapset_id,
            checksum_md5=checksum_md5 if i == 0 else "abcdef0123456789abcdef0123456789",
            mode=BeatmapMode(mode),
            version=version,
            official_status=official_status,
            official_status_source=official_status_source,
            official_status_verified=official_status_verified,
            last_fetched_at=fetched_at,
            next_refresh_at=refresh_at,
        )
        for i in range(beatmap_count)
    ]
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=artist,
        title=title,
        creator=creator,
        source=source,
        verified=verified,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        beatmaps=tuple(child_snapshots),
        last_fetched_at=fetched_at,
        next_refresh_at=refresh_at,
    )


def _make_mirror_snapshot(**kwargs: object) -> BeatmapsetSnapshot:
    """このunverified mirror sourceを持つbeatmapset snapshotを作る.

    Args:
        **kwargs (object): 基底snapshot factoryへ渡すoverride値.

    Returns:
        BeatmapsetSnapshot: mirror由来かつunverifiedとして設定されたsnapshot.
    """
    return _make_snapshot(
        source=BeatmapMetadataSource.MIRROR,
        verified=BeatmapSourceVerification.UNVERIFIED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        **kwargs,  # pyright: ignore[reportArgumentType]
    )


def _make_freshness_policy() -> BeatmapFreshnessPolicy:
    """対象metadata cacheのrefresh判定policyを作る.

    Returns:
        BeatmapFreshnessPolicy: ranked, pending, graveyard, mirrorの更新間隔を持つpolicy.
    """
    return BeatmapFreshnessPolicy(
        ranked_refresh_interval=_THIRTY_DAYS,
        pending_refresh_interval=_ONE_HOUR,
        graveyard_refresh_interval=_THIRTY_DAYS,
        mirror_refresh_interval=_ONE_HOUR,
    )


_FILE_BODY = b"osu file format v14\n[General]\nAudioFilename: audio.mp3\n"
_FILE_BODY_MD5 = "c76db67ba86527673e81495b1602f24b"
_FILE_BODY_MISMATCH = b"osu file format v14\n[General]\nAudioFilename: wrong.mp3\n"


# ---------------------------------------------------------------------------
# Metadata fetch job logging tests
# ---------------------------------------------------------------------------


class TestMetadataFetchJobLogging:
    """このmetadata fetch jobの構造化eventを検証するtest group."""

    @staticmethod
    def _make_job(
        repo: InMemoryBeatmapStore,
        *,
        official: StubMetadataProvider | None = None,
        mirror: StubMetadataProvider | None = None,
    ) -> FetchBeatmapMetadataUseCase:
        """指定providerを持つmetadata fetch use caseを作る.

        Args:
            repo (InMemoryBeatmapStore): fetch状態とsnapshotを保持するin-memory repository.
            official (StubMetadataProvider | None): official sourceとして使うprovider.
                Noneの場合は空のstubを使う.
            mirror (StubMetadataProvider | None): fallback mirrorとして使うprovider.
                Noneの場合は空のstubを使う.

        Returns:
            FetchBeatmapMetadataUseCase: 構造化loggingを検証するためのuse case.
        """
        _official = official or StubMetadataProvider()
        _mirror = mirror or StubMetadataProvider()
        composite = CompositeBeatmapMetadataProvider(official=_official, mirror=_mirror)
        return FetchBeatmapMetadataUseCase(
            uow_factory=repo.uow_factory,
            metadata_provider=composite,
            freshness_policy=_make_freshness_policy(),
        )

    async def test_logs_start_and_success_for_beatmap_id(self) -> None:
        """対象beatmap ID metadata fetchが開始と成功eventを記録する契約を検証する.

        official providerがsnapshotを返す条件でfetchする.
        target種別, key, beatmapset ID, sourceを持つeventを確認する.

        Returns:
            None: 開始eventと成功eventを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        started = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_started"]
        assert len(started) == 1
        assert started[0]["target_type"] == "metadata:beatmap"
        assert started[0]["target_key"] == "2000"

        succeeded = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_succeeded"]
        assert len(succeeded) == 1
        assert succeeded[0]["target_type"] == "metadata:beatmap"
        assert succeeded[0]["target_key"] == "2000"
        assert succeeded[0]["beatmapset_id"] == snapshot.beatmapset_id
        assert succeeded[0]["source"] == BeatmapMetadataSource.OFFICIAL.value

    async def test_logs_start_and_success_for_checksum(self) -> None:
        """対象checksum metadata fetchが開始と成功eventを記録する契約を検証する.

        checksumでofficial snapshotを検索する.
        成功eventがchecksum target種別と入力keyを持つことを確認する.

        Returns:
            None: 成功eventのtarget fieldを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        checksum = _DEFAULT_CHECKSUM
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_checksum={checksum: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_checksum(checksum)

        with capture_logs() as logs:
            await job.execute(target)

        succeeded = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_succeeded"]
        assert len(succeeded) == 1
        assert succeeded[0]["target_type"] == "metadata:checksum"
        assert succeeded[0]["target_key"] == checksum

    async def test_logs_failure_when_all_sources_fail(self) -> None:
        """全sourceが結果を返さないmetadata fetchの失敗eventを検証する.

        officialとmirrorの両providerがNoneを返す条件でfetchする.
        target情報とerror fieldを持つ失敗eventを確認する.

        Returns:
            None: 失敗eventのtarget fieldとerror fieldを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        official = StubMetadataProvider()
        mirror = StubMetadataProvider()
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        failed = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_failed"]
        assert len(failed) == 1
        assert failed[0]["target_type"] == "metadata:beatmap"
        assert failed[0]["target_key"] == "2000"
        assert "error" in failed[0]

    async def test_logs_failure_when_all_providers_raise(self) -> None:
        """全providerが例外を送出するmetadata fetchの失敗eventを検証する.

        officialとmirrorの両providerを失敗させる.
        処理が例外を伝播せず失敗eventを一度だけ記録することを確認する.

        Returns:
            None: 失敗eventの件数を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        official = StubMetadataProvider(exception=RuntimeError("official down"))
        mirror = StubMetadataProvider(exception=RuntimeError("mirror down"))
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        failed = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_failed"]
        assert len(failed) == 1

    async def test_logs_mirror_fallback_when_official_returns_none(self) -> None:
        """対象official sourceがNoneを返す場合のmirror fallback eventを検証する.

        mirror providerがsnapshotを返す条件でfetchする.
        fallback eventがmetadata source種別とbeatmap ID keyを持つことを確認する.

        Returns:
            None: mirror fallback eventのfieldを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        mirror_snapshot = _make_mirror_snapshot()
        official = StubMetadataProvider()
        mirror = StubMetadataProvider(by_beatmap_id={2000: mirror_snapshot})
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        mirror_events = [e for e in logs if e.get("event") == "beatmap_mirror_fallback_used"]
        assert len(mirror_events) == 1
        assert mirror_events[0]["source_type"] == "metadata"
        assert mirror_events[0]["key_kind"] == "beatmap_id"
        assert mirror_events[0]["key"] == "2000"

    async def test_logs_mirror_fallback_when_official_raises(self) -> None:
        """対象official sourceが例外を送出する場合のmirror fallback eventを検証する.

        official providerの失敗後にmirror providerがsnapshotを返す条件でfetchする.
        metadata fallback eventが記録されることを確認する.

        Returns:
            None: mirror fallback eventのsource種別を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        mirror_snapshot = _make_mirror_snapshot()
        official = StubMetadataProvider(exception=RuntimeError("official down"))
        mirror = StubMetadataProvider(by_beatmap_id={2000: mirror_snapshot})
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        mirror_events = [e for e in logs if e.get("event") == "beatmap_mirror_fallback_used"]
        assert len(mirror_events) == 1
        assert mirror_events[0]["source_type"] == "metadata"

    async def test_does_not_log_mirror_fallback_when_official_succeeds(self) -> None:
        """対象official sourceが成功する場合にmirror fallback eventを記録しない契約を検証する.

        official providerだけがsnapshotを返す条件でfetchする.
        mirror fallback eventが0件になることを確認する.

        Returns:
            None: fallback eventが不在であることを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        mirror = StubMetadataProvider()
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        mirror_events = [e for e in logs if e.get("event") == "beatmap_mirror_fallback_used"]
        assert len(mirror_events) == 0

    async def test_logs_cache_hit_without_provider_fetch_lifecycle(self) -> None:
        """対象fresh cache hitがprovider fetch lifecycleと区別されるeventを記録する契約を検証する.

        同じtargetを二度実行する.
        二回目がcache hit eventだけを記録してproviderを再呼出ししないことを確認する.

        Returns:
            None: cache hit eventとprovider呼出履歴を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)
        await job.execute(target)

        with capture_logs() as logs:
            await job.execute(target)

        cache_hits = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_cache_hit"]
        assert len(cache_hits) == 1
        assert cache_hits[0]["target_type"] == "metadata:beatmap"
        assert cache_hits[0]["target_key"] == "2000"

        started = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_started"]
        assert started == []
        succeeded = [e for e in logs if e.get("event") == "beatmap_metadata_fetch_succeeded"]
        assert succeeded == []
        assert official.calls == ["beatmap_id:2000"]

    async def test_no_api_credentials_in_logs(self) -> None:
        """このlog eventがAPI credentialやauthorization fieldを含まない契約を検証する.

        metadata fetchで出力されたすべてのevent keyを走査する.
        機密値を示すfield名が含まれないことを確認する.

        Returns:
            None: event keyから機密fieldが除外されることを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        sensitive_fields = {
            "api_key",
            "api_token",
            "token",
            "secret",
            "credential",
            "authorization",
            "password",
            "password_hash",
            "password_md5",
            "api_secret",
            "access_token",
            "bearer",
            "apikey",
            "client_secret",
        }

        for entry in logs:
            for key in entry:
                lower_key = key.lower()
                for sensitive in sensitive_fields:
                    assert sensitive not in lower_key, (
                        f"Sensitive field '{key}' found in log event '{entry.get('event')}'"
                    )


# ---------------------------------------------------------------------------
# File fetch job logging tests
# ---------------------------------------------------------------------------


class TestFileFetchJobLogging:
    """このfile fetch jobの構造化eventを検証するtest group."""

    @staticmethod
    async def _setup_repo_with_beatmap(
        repo: InMemoryBeatmapStore,
        *,
        beatmap_id: int = 2000,
        beatmapset_id: int = 1000,
        checksum_md5: str = _DEFAULT_CHECKSUM,
    ) -> None:
        """対象file fetch用のbeatmapをin-memory repositoryへ保存する.

        Args:
            repo (InMemoryBeatmapStore): 保存先のin-memory repository.
            beatmap_id (int): 保存するbeatmapの識別子.
            beatmapset_id (int): 保存するbeatmapsetの識別子.
            checksum_md5 (str): 保存するbeatmap fileの期待MD5 checksum.

        Returns:
            None: beatmapset snapshotを保存して完了し, 呼び出し側へ値を返さない.
        """
        bm = Beatmap(
            id=beatmap_id,
            beatmapset_id=beatmapset_id,
            checksum_md5=checksum_md5,
            mode=BeatmapMode.OSU,
            version="Another",
            total_length=None,
            hit_length=None,
            max_combo=None,
            bpm=None,
            cs=None,
            od=None,
            ar=None,
            hp=None,
            difficulty_rating=None,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            local_status_override=None,
            metadata_fetch_state=BeatmapFetchState.FRESH,
            file_state=BeatmapFileState.MISSING,
            file_attachment=None,
            last_fetched_at=_NOW,
            next_refresh_at=_NOW + _THIRTY_DAYS,
        )
        beatmapset = BeatmapSet(
            id=beatmapset_id,
            artist="Camellia",
            title="Exit This Earth's Atomosphere",
            creator="Realazy",
            artist_unicode=None,
            title_unicode=None,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(bm,),
            last_fetched_at=_NOW,
            next_refresh_at=_NOW + _THIRTY_DAYS,
        )
        await repo.save_beatmapset_snapshot(beatmapset)

    @staticmethod
    def _make_job(
        repo: InMemoryBeatmapStore,
        *,
        file_provider: StubFileProvider | None = None,
        blob_storage: StubBlobStorageService | None = None,
    ) -> FetchBeatmapFileUseCase:
        """指定providerとstorageを持つfile fetch use caseを作る.

        Args:
            repo (InMemoryBeatmapStore): fetch状態を保持するin-memory repository.
            file_provider (StubFileProvider | None): osu fileを返すprovider. Noneの場合は空のstub.
            blob_storage (StubBlobStorageService | None): blobを記録するstorage service.
                Noneの場合は空のstubを使う.

        Returns:
            FetchBeatmapFileUseCase: 構造化loggingを検証するためのuse case.
        """
        _provider = file_provider or StubFileProvider()
        _blob = blob_storage or StubBlobStorageService()
        return FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=_provider,
            blob_storage=_blob,
        )

    async def test_logs_start_and_success(self) -> None:
        """対象file fetchが開始と成功eventを記録する契約を検証する.

        一致するMD5のosu fileを取得する.
        target情報, beatmap ID, sourceを持つ開始eventと成功eventを確認する.

        Returns:
            None: 開始eventと成功eventを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        await self._setup_repo_with_beatmap(repo, checksum_md5=_FILE_BODY_MD5)
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        job = self._make_job(repo, file_provider=file_provider)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        started = [e for e in logs if e.get("event") == "beatmap_file_fetch_started"]
        assert len(started) == 1
        assert started[0]["target_type"] == "file:beatmap"
        assert started[0]["target_key"] == "2000"

        succeeded = [e for e in logs if e.get("event") == "beatmap_file_fetch_succeeded"]
        assert len(succeeded) == 1
        assert succeeded[0]["target_type"] == "file:beatmap"
        assert succeeded[0]["target_key"] == "2000"
        assert succeeded[0]["beatmap_id"] == 2000
        assert succeeded[0]["source"] == BeatmapFileSource.OSU_CURRENT.value

    async def test_logs_failure_when_provider_raises(self) -> None:
        """対象file providerの例外がfile fetch失敗eventになる契約を検証する.

        file providerを失敗させ, target情報とerror fieldを持つ失敗eventが記録されることを確認する.

        Returns:
            None: 失敗eventのtarget fieldとerror fieldを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        await self._setup_repo_with_beatmap(repo)
        file_provider = StubFileProvider(exception=RuntimeError("mirror down"))
        job = self._make_job(repo, file_provider=file_provider)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        failed = [e for e in logs if e.get("event") == "beatmap_file_fetch_failed"]
        assert len(failed) == 1
        assert failed[0]["target_type"] == "file:beatmap"
        assert failed[0]["target_key"] == "2000"
        assert "error" in failed[0]

    async def test_logs_checksum_mismatch(self) -> None:
        """取得byte列のchecksum mismatchが専用eventになる契約を検証する.

        期待MD5と異なるosu fileを返す.
        checksum prefixを持つmismatch eventと失敗eventが記録されることを確認する.

        Returns:
            None: mismatch eventと失敗eventを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        await self._setup_repo_with_beatmap(repo, checksum_md5=_DEFAULT_CHECKSUM)
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY_MISMATCH,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        job = self._make_job(repo, file_provider=file_provider)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        mismatch = [e for e in logs if e.get("event") == "beatmap_file_checksum_mismatch"]
        assert len(mismatch) == 1
        assert mismatch[0]["beatmap_id"] == 2000
        # Expected and actual checksums should be present (actual is redacted from full value)
        assert "expected_md5_prefix" in mismatch[0]
        assert mismatch[0]["expected_md5_prefix"] == _DEFAULT_CHECKSUM[:8]

        # The checksum mismatch should also log a failure
        failed = [e for e in logs if e.get("event") == "beatmap_file_fetch_failed"]
        assert len(failed) == 1

    async def test_logs_failure_when_beatmap_not_found(self) -> None:
        """このrepositoryにないbeatmapのfile fetchが失敗eventになる契約を検証する.

        beatmapを保存しない条件でfile fetchを実行し, 失敗eventが一度だけ記録されることを確認する.

        Returns:
            None: 失敗eventの件数を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        file_provider = StubFileProvider()
        job = self._make_job(repo, file_provider=file_provider)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        with capture_logs() as logs:
            await job.execute(target)

        failed = [e for e in logs if e.get("event") == "beatmap_file_fetch_failed"]
        assert len(failed) == 1

    # (test_no_api_credentials_in_logs moved to TestMetadataFetchJobLogging)
