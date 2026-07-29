"""このmoduleはbeatmap metadataとfile fetch use caseの契約を検証する.

idempotentなbackground fetchを確認する.
cache判定, mirror fallback, leaderboard再構築通知, osu file保存を確認する.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from tests.support.beatmaps import InMemoryBeatmapStore

from osu_server.domain.beatmaps import (
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
from osu_server.domain.storage.blobs import Blob, BlobStorageBackendKind
from osu_server.infrastructure.beatmaps.metadata_sources import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap, BeatmapMetadataProvider
    from osu_server.domain.storage.blobs import BlobStored
    from osu_server.shared.ports import (
        BeatmapLeaderboardRebuildWorkerWake,
    )

_NOW = datetime.now(UTC) + timedelta(days=365)
_STALE_REFRESH_AT = datetime(2020, 1, 1, tzinfo=UTC)
_ONE_HOUR = timedelta(hours=1)
_THIRTY_DAYS = timedelta(days=30)
_STALE_FETCHED_AT = _STALE_REFRESH_AT - _THIRTY_DAYS
_DEFAULT_CHECKSUM = "0123456789abcdef0123456789abcdef"
_ALT_CHECKSUM = "abcdef0123456789abcdef0123456789"


# ---------------------------------------------------------------------------
# Test doubles -- StubMetadataProvider conforms to BeatmapMetadataProvider
# ---------------------------------------------------------------------------


@dataclass
class StubMetadataProvider:
    """BeatmapMetadataProvider準拠のin-memory test doubleを提供する.

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
        """
        self.calls.append(f"checksum:{checksum_md5}")
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.exception is not None:
            raise self.exception
        return self.by_checksum.get(checksum_md5)


class LeaderboardRebuildWakeRecorder:
    """このleaderboard再構築通知の呼出を記録するtest double.

    Attributes:
        user_calls (list[tuple[int, str]]): user rebuild通知の識別子と理由の履歴.
        beatmapset_calls (list[tuple[int, str]]): beatmapset rebuild通知の識別子と理由の履歴.
    """

    def __init__(self) -> None:
        """空のuserおよびbeatmapset通知履歴を初期化する."""
        self.user_calls: list[tuple[int, str]] = []
        self.beatmapset_calls: list[tuple[int, str]] = []

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        """対象userのleaderboard再構築通知を記録する.

        Args:
            user_id (int): 再構築対象userの識別子.
            reason (str): 再構築を要求する理由.

        Returns:
            None: 通知履歴を追加して完了し, 呼び出し側へ値を返さない.
        """
        self.user_calls.append((user_id, reason))

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        """対象beatmapsetのleaderboard再構築通知を記録する.

        Args:
            beatmapset_id (int): 再構築対象beatmapsetの識別子.
            reason (str): 再構築を要求する理由.

        Returns:
            None: 通知履歴を追加して完了し, 呼び出し側へ値を返さない.
        """
        self.beatmapset_calls.append((beatmapset_id, reason))


class FailingLeaderboardRebuildWake:
    """このbeatmapset leaderboard再構築通知の失敗を再現するtest double."""

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        """対象userのleaderboard通知を成功扱いで消費する.

        Args:
            user_id (int): 再構築対象userの識別子.
            reason (str): 再構築を要求する理由.

        Returns:
            None: 入力を消費して完了し, 呼び出し側へ値を返さない.
        """
        _ = (user_id, reason)

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        """対象beatmapsetのleaderboard通知後に意図的な失敗を送出する.

        Args:
            beatmapset_id (int): 再構築対象beatmapsetの識別子.
            reason (str): 再構築を要求する理由.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            RuntimeError: 非同期通知失敗時のmetadata fetch継続処理を検証する場合.
        """
        _ = (beatmapset_id, reason)
        msg = "leaderboard rebuild enqueue failed"
        raise RuntimeError(msg)


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
            checksum_md5=checksum_md5 if i == 0 else _ALT_CHECKSUM,
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


# ---------------------------------------------------------------------------
# FetchBeatmapMetadataUseCase tests
# ---------------------------------------------------------------------------


class TestFetchBeatmapMetadataUseCase:
    """このidempotentなmetadata fetch use caseの契約を検証するtest group."""

    @staticmethod
    def _make_job(
        repo: InMemoryBeatmapStore,
        *,
        official: StubMetadataProvider | None = None,
        mirror: StubMetadataProvider | None = None,
        leaderboard_rebuild_wake: BeatmapLeaderboardRebuildWorkerWake | None = None,
        official_sources_available: bool = True,
    ) -> FetchBeatmapMetadataUseCase:
        """指定依存を持つmetadata fetch use caseを作る.

        Args:
            repo (InMemoryBeatmapStore): fetch状態とsnapshotを保持するin-memory repository.
            official (StubMetadataProvider | None): official metadata provider.
                Noneの場合は空のstubを使う.
            mirror (StubMetadataProvider | None): mirror metadata provider. Noneの場合は空のstub.
            leaderboard_rebuild_wake (BeatmapLeaderboardRebuildWorkerWake | None): 通知先.
            official_sources_available (bool): official sourceを利用可能として扱うか.

        Returns:
            FetchBeatmapMetadataUseCase: test対象のmetadata fetch use case.
        """
        _official: BeatmapMetadataProvider = official or StubMetadataProvider()
        _mirror: BeatmapMetadataProvider = mirror or StubMetadataProvider()
        composite = CompositeBeatmapMetadataProvider(official=_official, mirror=_mirror)
        return FetchBeatmapMetadataUseCase(
            uow_factory=repo.uow_factory,
            metadata_provider=composite,
            freshness_policy=_make_freshness_policy(),
            official_sources_available=official_sources_available,
            leaderboard_rebuild_wake=leaderboard_rebuild_wake,
        )

    # --- success path --------------------------------------------------------

    async def test_successful_official_fetch_saves_snapshot(self) -> None:
        """対象official metadata fetchがsnapshotを保存してfreshになる契約を検証する.

        official providerがsnapshotを返す条件で, beatmapset保存とFRESH fetch stateを確認する.

        Returns:
            None: 保存済みsnapshotとfetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved = await repo.get_beatmapset(snapshot.beatmapset_id)
        assert saved is not None
        assert saved.title == "Exit This Earth's Atomosphere"
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    async def test_first_metadata_fetch_does_not_wake_leaderboard_rebuild(self) -> None:
        """初回metadata fetchがleaderboard再構築を通知しない契約を検証する.

        既存snapshotのないrepositoryへofficial snapshotを保存する.
        beatmapset通知履歴が空のままであることを確認する.

        Returns:
            None: 初回fetch後の通知履歴を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        wake = LeaderboardRebuildWakeRecorder()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official, leaderboard_rebuild_wake=wake)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        assert wake.beatmapset_calls == []

    async def test_status_change_wakes_beatmapset_leaderboard_rebuild_after_commit(self) -> None:
        """対象rank status変更がcommit後のbeatmapset再構築通知になる契約を検証する.

        staleなPENDING snapshotをRANKEDへ更新し, 保存済みstatusとstatus change理由の通知を確認する.

        Returns:
            None: 更新後statusとcommit後の通知履歴を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        initial = _make_snapshot(
            official_status=BeatmapRankStatus.PENDING,
            last_fetched_at=_STALE_FETCHED_AT,
            next_refresh_at=_STALE_REFRESH_AT,
        )
        await repo.save_beatmapset_snapshot(_snapshot_to_beatmapset(initial))
        updated = _make_snapshot(official_status=BeatmapRankStatus.RANKED)
        wake = LeaderboardRebuildWakeRecorder()
        official = StubMetadataProvider(by_beatmap_id={2000: updated})
        job = self._make_job(repo, official=official, leaderboard_rebuild_wake=wake)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved = await repo.get_beatmapset(updated.beatmapset_id)
        assert saved is not None
        assert saved.beatmaps[0].effective_status is BeatmapRankStatus.RANKED
        assert wake.beatmapset_calls == [(updated.beatmapset_id, "beatmap_status_changed")]

    async def test_checksum_change_wakes_beatmapset_leaderboard_rebuild_after_commit(self) -> None:
        """対象checksum変更がcommit後のbeatmapset再構築通知になる契約を検証する.

        stale snapshotのchecksumを更新し, 保存済みchecksumとchecksum change理由の通知を確認する.

        Returns:
            None: 更新後checksumとcommit後の通知履歴を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        initial = _make_snapshot(
            checksum_md5=_DEFAULT_CHECKSUM,
            last_fetched_at=_STALE_FETCHED_AT,
            next_refresh_at=_STALE_REFRESH_AT,
        )
        await repo.save_beatmapset_snapshot(_snapshot_to_beatmapset(initial))
        updated = _make_snapshot(checksum_md5=_ALT_CHECKSUM)
        wake = LeaderboardRebuildWakeRecorder()
        official = StubMetadataProvider(by_beatmap_id={2000: updated})
        job = self._make_job(repo, official=official, leaderboard_rebuild_wake=wake)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved = await repo.get_beatmap(2000)
        assert saved is not None
        assert saved.checksum_md5 == _ALT_CHECKSUM
        assert wake.beatmapset_calls == [(updated.beatmapset_id, "beatmap_checksum_changed")]

    async def test_leaderboard_wake_failure_does_not_rollback_metadata_fetch(self) -> None:
        """このleaderboard通知失敗がmetadata fetchをrollbackしない契約を検証する.

        status変更後の通知を失敗させ, metadata保存とFRESH fetch stateが維持されることを確認する.

        Returns:
            None: 保存結果とfetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        initial = _make_snapshot(
            official_status=BeatmapRankStatus.PENDING,
            last_fetched_at=_STALE_FETCHED_AT,
            next_refresh_at=_STALE_REFRESH_AT,
        )
        await repo.save_beatmapset_snapshot(_snapshot_to_beatmapset(initial))
        updated = _make_snapshot(official_status=BeatmapRankStatus.RANKED)
        official = StubMetadataProvider(by_beatmap_id={2000: updated})
        job = self._make_job(
            repo,
            official=official,
            leaderboard_rebuild_wake=FailingLeaderboardRebuildWake(),
        )
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved = await repo.get_beatmapset(updated.beatmapset_id)
        assert saved is not None
        assert saved.beatmaps[0].effective_status is BeatmapRankStatus.RANKED
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    # --- mirror fallback -----------------------------------------------------

    async def test_mirror_fallback_when_official_returns_none(self) -> None:
        """対象official providerがNoneを返す場合にmirrorへfallbackする契約を検証する.

        official providerを空にしてmirror snapshotを返す.
        snapshot保存とmirror providerの一回の呼出を確認する.

        Returns:
            None: fallback後の保存結果と呼出履歴を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        mirror_snapshot = _make_mirror_snapshot()
        official = StubMetadataProvider()
        mirror = StubMetadataProvider(by_beatmap_id={2000: mirror_snapshot})
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved = await repo.get_beatmapset(mirror_snapshot.beatmapset_id)
        assert saved is not None
        assert saved.title == "Exit This Earth's Atomosphere"
        # Mirror was called (fallback)
        assert len(mirror.calls) == 1

    async def test_mirror_fallback_when_official_raises(self) -> None:
        """対象official providerが例外を送出する場合にmirrorへfallbackする契約を検証する.

        official providerを失敗させてmirror snapshotを返す.
        例外を伝播せずsnapshotが保存されることを確認する.

        Returns:
            None: fallback後の保存結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        mirror_snapshot = _make_mirror_snapshot()
        official = StubMetadataProvider(exception=RuntimeError("official down"))
        mirror = StubMetadataProvider(by_beatmap_id={2000: mirror_snapshot})
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved = await repo.get_beatmapset(mirror_snapshot.beatmapset_id)
        assert saved is not None

    # --- failure path --------------------------------------------------------

    async def test_mark_failed_when_all_providers_return_none(self) -> None:
        """全metadata providerがNoneを返すfetchがfailedになる契約を検証する.

        officialとmirrorを空にしてfetchを実行し, FAILED stateとerror詳細が記録されることを確認する.

        Returns:
            None: failed fetch stateとerror詳細を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        official = StubMetadataProvider()
        mirror = StubMetadataProvider()
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED
        assert fetch_record.last_error is not None

    async def test_mark_failed_when_all_providers_raise(self) -> None:
        """全metadata providerが例外を送出するfetchがfailedになる契約を検証する.

        officialとmirrorを失敗させ, 処理が例外を伝播せずFAILED fetch stateになることを確認する.

        Returns:
            None: failed fetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        official = StubMetadataProvider(exception=RuntimeError("official down"))
        mirror = StubMetadataProvider(exception=RuntimeError("mirror down"))
        job = self._make_job(repo, official=official, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED

    # --- idempotency ---------------------------------------------------------

    async def test_already_pending_skips_fetch(self) -> None:
        """既にpendingのmetadata targetがproviderを呼ばずにskipする契約を検証する.

        targetをPENDING_FETCHとして事前登録する.
        official providerの呼出履歴が空のままであることを確認する.

        Returns:
            None: pending gateによるprovider未呼出を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)
        # Pre-mark as pending so the job sees it is already claimed.
        _ = await repo.try_mark_fetch_pending(target, _NOW)

        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)

        await job.execute(target)

        # The provider was never called because the pending gate returned False.
        assert len(official.calls) == 0

    async def test_concurrent_calls_only_one_proceeds(self) -> None:
        """同一metadata targetへの同時呼出で一件だけ取得する契約を検証する.

        遅延するofficial providerで二つのexecuteを並行実行する.
        provider呼出が一度だけになることを確認する.

        Returns:
            None: provider呼出回数と最終fetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(
            by_beatmap_id={2000: snapshot},
            delay=0.05,  # Give the second call time to observe pending state
        )
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        _ = await asyncio.gather(
            job.execute(target),
            job.execute(target),
        )

        # The provider should have been called only once (by the first task).
        assert len(official.calls) == 1
        # State should be fresh (from the successful first call).
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    async def test_cache_hit_does_not_clear_pending_force_refresh(self) -> None:
        """通常cache hitが進行中のforce refresh lockを解除しない契約を検証する.

        force refresh targetをpendingにして通常targetを実行する.
        provider未呼出とpending stateの維持を確認する.

        Returns:
            None: force refreshのpending stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        await repo.save_beatmapset_snapshot(_snapshot_to_beatmapset(snapshot))
        force_target = BeatmapFetchTarget.metadata_by_beatmap_id(
            2000,
            force_refresh=True,
        )
        _ = await repo.try_mark_fetch_pending(force_target, _NOW)

        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        normal_target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(normal_target)

        assert official.calls == []
        fetch_record = await repo.get_fetch_state(force_target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.PENDING_FETCH

    # --- local override preservation -----------------------------------------

    async def test_official_refresh_preserves_local_status_override(self) -> None:
        """対象official metadata refreshがlocal status overrideを保持する契約を検証する.

        stale snapshotへLOVED overrideを設定して再取得する.
        保存済みbeatmapのoverrideが変わらないことを確認する.

        Returns:
            None: refresh後のlocal status overrideを検証して完了し, 呼び出し側へ値を返さない.
        """
        from osu_server.domain.beatmaps import LocalBeatmapStatus  # noqa: PLC0415

        repo = InMemoryBeatmapStore()
        # Save initial snapshot with local override set on the beatmap.
        initial_snapshot = _make_snapshot(
            last_fetched_at=_STALE_FETCHED_AT,
            next_refresh_at=_STALE_REFRESH_AT,
        )
        initial_beatset = _snapshot_to_beatmapset(initial_snapshot)
        await repo.save_beatmapset_snapshot(initial_beatset)
        _ = await repo.set_local_status_override(2000, LocalBeatmapStatus.LOVED)

        # Now re-fetch the same beatmap via the job.
        official = StubMetadataProvider(by_beatmap_id={2000: _make_snapshot()})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved_beatmap = await repo.get_beatmap(2000)
        assert saved_beatmap is not None
        assert saved_beatmap.local_status_override is LocalBeatmapStatus.LOVED

    # --- mirror snapshot verification state ----------------------------------

    async def test_mirror_snapshot_saved_as_unverified(self) -> None:
        """対象mirror sourceのsnapshotがunverified statusで保存される契約を検証する.

        mirror providerだけがsnapshotを返す条件でfetchする.
        保存済みbeatmapのofficial status verificationがUNVERIFIEDになることを確認する.

        Returns:
            None: mirror由来beatmapのverification状態を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        mirror_snapshot = _make_mirror_snapshot()
        mirror = StubMetadataProvider(by_beatmap_id={2000: mirror_snapshot})
        job = self._make_job(repo, mirror=mirror)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved_beatmap = await repo.get_beatmap(2000)
        assert saved_beatmap is not None
        assert saved_beatmap.official_status_verified is BeatmapSourceVerification.UNVERIFIED

    # --- source tracking (req 16.1) ------------------------------------------

    async def test_official_source_tracked_in_saved_snapshot(self) -> None:
        """対象official metadata fetchが保存snapshotにsourceを記録する契約を検証する.

        official status sourceをOFFICIALにしたsnapshotを取得する.
        保存済みbeatmapのsourceがOFFICIALであることを確認する.

        Returns:
            None: 保存済みmetadata sourceを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot(
            official_status_source=BeatmapMetadataSource.OFFICIAL,
        )
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        saved_beatmap = await repo.get_beatmap(2000)
        assert saved_beatmap is not None
        assert saved_beatmap.official_status_source is BeatmapMetadataSource.OFFICIAL

    # --- fetch state after re-fetch -----------------------------------------

    async def test_re_fetch_after_fresh_cache_skips_provider_lookup(self) -> None:
        """対象fresh metadata cacheへの再fetchがprovider lookupをskipする契約を検証する.

        同じtargetを二度実行し, 最初のprovider呼出だけでFRESH stateが維持されることを確認する.

        Returns:
            None: provider呼出履歴とfetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)
        await job.execute(target)

        assert official.calls == ["beatmap_id:2000"]
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    async def test_force_refresh_fetches_provider_even_with_fresh_cache(self) -> None:
        """対象force refresh targetがfresh cacheでもproviderを呼ぶ契約を検証する.

        cached snapshotを保存してforce refreshを実行する.
        provider取得後の更新titleが保存されることを確認する.

        Returns:
            None: provider呼出履歴と更新済みsnapshotを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        cached = _make_snapshot(title="Cached Title")
        await repo.save_beatmapset_snapshot(_snapshot_to_beatmapset(cached))
        updated = _make_snapshot(title="Updated Title")
        official = StubMetadataProvider(by_beatmap_id={2000: updated})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000, force_refresh=True)

        await job.execute(target)

        assert official.calls == ["beatmap_id:2000"]
        saved = await repo.get_beatmapset(updated.beatmapset_id)
        assert saved is not None
        assert saved.title == "Updated Title"

    async def test_failed_fetch_state_retries_provider_even_with_fresh_cache(self) -> None:
        """対象failed metadata fetchがfresh cacheでもproviderを再試行する契約を検証する.

        cached snapshotのfetch stateをFAILEDにして実行する.
        provider再取得とFRESH stateへの復帰を確認する.

        Returns:
            None: provider呼出履歴と更新済みsnapshotを検証する.
                fetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        cached = _make_snapshot(title="Cached Title")
        await repo.save_beatmapset_snapshot(_snapshot_to_beatmapset(cached))
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)
        async with repo.uow_factory() as uow:
            await uow.beatmaps.mark_fetch_failed(target, "official down", _NOW)
            await uow.commit()

        updated = _make_snapshot(title="Updated Title")
        official = StubMetadataProvider(by_beatmap_id={2000: updated})
        job = self._make_job(repo, official=official)

        await job.execute(target)

        assert official.calls == ["beatmap_id:2000"]
        saved = await repo.get_beatmapset(updated.beatmapset_id)
        assert saved is not None
        assert saved.title == "Updated Title"
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    async def test_cached_beatmapset_target_skips_provider_lookup(self) -> None:
        """対象fresh beatmapset cacheへのmetadata targetがprovider lookupをskipする契約を検証する.

        beatmapset snapshotを事前保存してtargetを実行する.
        provider呼出履歴が空のままであることを確認する.

        Returns:
            None: beatmapset cache hitでproviderを呼ばないことを検証する.
                呼び出し側へ値を返さずに完了する.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot(beatmapset_id=5678)
        await repo.save_beatmapset_snapshot(_snapshot_to_beatmapset(snapshot))
        official = StubMetadataProvider(by_beatmapset_id={5678: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmapset_id(5678)

        await job.execute(target)

        assert official.calls == []

    async def test_cached_checksum_target_skips_provider_lookup(self) -> None:
        """対象fresh checksum cacheへのmetadata targetがprovider lookupをskipする契約を検証する.

        checksumを持つsnapshotを事前保存してtargetを実行する.
        provider呼出履歴が空のままであることを確認する.

        Returns:
            None: checksum cache hitでproviderを呼ばないことを検証する.
                呼び出し側へ値を返さずに完了する.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot(checksum_md5=_DEFAULT_CHECKSUM)
        await repo.save_beatmapset_snapshot(_snapshot_to_beatmapset(snapshot))
        official = StubMetadataProvider(by_checksum={_DEFAULT_CHECKSUM: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_checksum(_DEFAULT_CHECKSUM)

        await job.execute(target)

        assert official.calls == []

    async def test_stale_cached_beatmap_still_fetches_provider(self) -> None:
        """対象stale metadata cacheがproviderから再取得される契約を検証する.

        更新期限切れsnapshotを保存してtargetを実行し, provider呼出と更新titleの保存を確認する.

        Returns:
            None: stale cacheの再取得結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        stale_snapshot = _make_snapshot(
            last_fetched_at=_STALE_FETCHED_AT,
            next_refresh_at=_STALE_REFRESH_AT,
        )
        await repo.save_beatmapset_snapshot(_snapshot_to_beatmapset(stale_snapshot))
        updated = _make_snapshot(title="Updated Title")
        official = StubMetadataProvider(by_beatmap_id={2000: updated})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        assert official.calls == ["beatmap_id:2000"]
        saved = await repo.get_beatmapset(updated.beatmapset_id)
        assert saved is not None
        assert saved.title == "Updated Title"

    async def test_mirror_cached_beatmap_refreshes_when_official_is_available(self) -> None:
        """対象mirror由来cacheがofficial source利用可能時に再取得される契約を検証する.

        mirror snapshotを事前保存してofficial providerを利用可能にする.
        providerが一度呼ばれることを確認する.

        Returns:
            None: mirror cacheからofficial取得へ移ることを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        mirror_snapshot = _make_mirror_snapshot()
        await repo.save_beatmapset_snapshot(_snapshot_to_beatmapset(mirror_snapshot))
        official_snapshot = _make_snapshot()
        official = StubMetadataProvider(by_beatmap_id={2000: official_snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmap_id(2000)

        await job.execute(target)

        assert official.calls == ["beatmap_id:2000"]

    # --- lookup by beatmapset_id ---------------------------------------------

    async def test_lookup_by_beatmapset_id(self) -> None:
        """対象beatmapset ID targetが対応provider lookupで解決される契約を検証する.

        beatmapset ID用のofficial snapshotを設定し, 対象IDのbeatmapsetが保存されることを確認する.

        Returns:
            None: beatmapset lookup後の保存結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot(beatmapset_id=5678)
        official = StubMetadataProvider(by_beatmapset_id={5678: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_beatmapset_id(5678)

        await job.execute(target)

        saved = await repo.get_beatmapset(5678)
        assert saved is not None
        assert saved.id == 5678

    # --- lookup by checksum --------------------------------------------------

    async def test_lookup_by_checksum(self) -> None:
        """対象checksum targetが対応provider lookupで解決される契約を検証する.

        checksum用のofficial snapshotを設定し, 対象beatmapが保存されることを確認する.

        Returns:
            None: checksum lookup後の保存結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        checksum = _DEFAULT_CHECKSUM
        official = StubMetadataProvider(by_checksum={checksum: snapshot})
        job = self._make_job(repo, official=official)
        target = BeatmapFetchTarget.metadata_by_checksum(checksum)

        await job.execute(target)

        saved_beatmap = await repo.get_beatmap(2000)
        assert saved_beatmap is not None


# ---------------------------------------------------------------------------
# Conversion helper (used by tests that pre-populate repo state)
# ---------------------------------------------------------------------------


def _snapshot_to_beatmapset(snapshot: BeatmapsetSnapshot) -> BeatmapSet:
    """このdomain snapshotをtest setup用のBeatmapSetへ変換する.

    Args:
        snapshot (BeatmapsetSnapshot): repositoryへ事前保存するmetadata snapshot.

    Returns:
        BeatmapSet: file取得前のFRESH metadata stateを持つdomain beatmapset.
    """
    from osu_server.domain.beatmaps import Beatmap  # noqa: PLC0415

    beatmaps = [
        Beatmap(
            id=bm.beatmap_id,
            beatmapset_id=bm.beatmapset_id,
            checksum_md5=bm.checksum_md5,
            mode=bm.mode,
            version=bm.version,
            total_length=bm.total_length,
            hit_length=bm.hit_length,
            max_combo=bm.max_combo,
            bpm=bm.bpm,
            cs=bm.cs,
            od=bm.od,
            ar=bm.ar,
            hp=bm.hp,
            difficulty_rating=bm.difficulty_rating,
            official_status=bm.official_status,
            official_status_source=bm.official_status_source,
            official_status_verified=bm.official_status_verified,
            local_status_override=bm.local_status_override,
            metadata_fetch_state=BeatmapFetchState.FRESH,
            file_state=BeatmapFileState.MISSING,
            file_attachment=None,
            last_fetched_at=bm.last_fetched_at,
            next_refresh_at=bm.next_refresh_at,
        )
        for bm in snapshot.beatmaps
    ]
    return BeatmapSet(
        id=snapshot.beatmapset_id,
        artist=snapshot.artist,
        title=snapshot.title,
        creator=snapshot.creator,
        artist_unicode=snapshot.artist_unicode,
        title_unicode=snapshot.title_unicode,
        official_status=snapshot.official_status,
        official_status_source=snapshot.official_status_source,
        official_status_verified=snapshot.official_status_verified,
        beatmaps=tuple(beatmaps),
        last_fetched_at=snapshot.last_fetched_at,
        next_refresh_at=snapshot.next_refresh_at,
    )


# ---------------------------------------------------------------------------
# FetchBeatmapFileUseCase tests
# ---------------------------------------------------------------------------


@dataclass
class StubFileProvider:
    """BeatmapFileProvider準拠のin-memory test doubleを提供する.

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
    """保存済みblobを記録してBlobStoredを返すtest doubleを提供する.

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
        from osu_server.domain.storage.blobs import BlobStored  # noqa: PLC0415

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


async def _setup_repo_with_beatmap(
    repo: InMemoryBeatmapStore,
    *,
    beatmap_id: int = 2000,
    beatmapset_id: int = 1000,
    checksum_md5: str = _DEFAULT_CHECKSUM,
) -> Beatmap:
    """対象file fetch用の最小beatmapをrepositoryへ保存して返す.

    Args:
        repo (InMemoryBeatmapStore): 保存先のin-memory repository.
        beatmap_id (int): 保存するbeatmapの識別子.
        beatmapset_id (int): 保存するbeatmapsetの識別子.
        checksum_md5 (str): 保存するbeatmap fileの期待MD5 checksum.

    Returns:
        Beatmap: 保存済みbeatmapsetに含めたbeatmap.
    """
    from osu_server.domain.beatmaps import (  # noqa: PLC0415
        Beatmap,
        BeatmapFileState,
        BeatmapMetadataSource,
        BeatmapRankStatus,
        BeatmapSet,
        BeatmapSourceVerification,
    )

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
    return bm


_FILE_BODY = b"osu file format v14\n[General]\nAudioFilename: audio.mp3\n"
_FILE_BODY_MD5 = "c76db67ba86527673e81495b1602f24b"
_FILE_BODY_MISMATCH = b"osu file format v14\n[General]\nAudioFilename: wrong.mp3\n"


class TestFetchBeatmapFileUseCase:
    """このidempotentなosu file fetch use caseの契約を検証するtest group."""

    @staticmethod
    def _make_job(
        repo: InMemoryBeatmapStore,
        file_provider: StubFileProvider | None = None,
        blob_storage: StubBlobStorageService | None = None,
    ) -> FetchBeatmapFileUseCase:
        """指定providerとstorageを持つfile fetch use caseを作る.

        Args:
            repo (InMemoryBeatmapStore): fetch状態とattachmentを保持するin-memory repository.
            file_provider (StubFileProvider | None): osu fileを返すprovider. Noneの場合は空のstub.
            blob_storage (StubBlobStorageService | None): blobを記録するstorage service.
                Noneの場合は空のstubを使う.

        Returns:
            FetchBeatmapFileUseCase: test対象のfile fetch use case.
        """
        _provider: StubFileProvider = file_provider or StubFileProvider()
        _blob: StubBlobStorageService = blob_storage or StubBlobStorageService()
        return FetchBeatmapFileUseCase(
            uow_factory=repo.uow_factory,
            file_provider=_provider,
            blob_storage=_blob,
        )

    # --- success path --------------------------------------------------------

    async def test_successful_file_fetch_verifies_and_attaches(self) -> None:
        """一致するfile fetchがMD5検証後にblobとattachmentを保存する契約を検証する.

        一致するosu fileを返す.
        provider呼出, blob保存, verified attachment, FRESH fetch stateを確認する.

        Returns:
            None: file取得後の保存結果とfetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo, checksum_md5=_FILE_BODY_MD5)
        expected_md5 = _FILE_BODY_MD5
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        blob_storage = StubBlobStorageService()
        job = self._make_job(repo, file_provider=file_provider, blob_storage=blob_storage)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        await job.execute(target)

        # File provider was called once
        assert len(file_provider.calls) == 1
        assert file_provider.calls[0] == 2000

        # Blob was stored
        assert len(blob_storage.stored) == 1
        assert blob_storage.stored[0].byte_size == len(_FILE_BODY)

        # Attachment is attached
        attachment = await repo.get_current_file_attachment(2000)
        assert attachment is not None
        assert attachment.blob_id == blob_storage.stored[0].id
        assert attachment.checksum_md5 == expected_md5
        assert attachment.source is BeatmapFileSource.OSU_CURRENT
        assert attachment.original_filename == "2000.osu"
        assert attachment.fetched_at is not None
        assert attachment.verified_at is not None

        # Fetch state is succeeded
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    # --- checksum mismatch ---------------------------------------------------

    async def test_checksum_mismatch_marks_failed(self) -> None:
        """MD5 checksum mismatchのfile fetchがblobを保存せずfailedになる契約を検証する.

        期待checksumと異なるfile byte列を返し, attachment不在, blob未保存, FAILED stateを確認する.

        Returns:
            None: checksum mismatch後の保存結果とfetch stateを検証する.
                呼び出し側へ値を返さずに完了する.
        """
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo, checksum_md5=_DEFAULT_CHECKSUM)
        # _FILE_BODY_MISMATCH has a different md5 than _DEFAULT_CHECKSUM
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY_MISMATCH,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        blob_storage = StubBlobStorageService()
        job = self._make_job(repo, file_provider=file_provider, blob_storage=blob_storage)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        await job.execute(target)

        # No blob was stored
        assert len(blob_storage.stored) == 0

        # No attachment exists
        attachment = await repo.get_current_file_attachment(2000)
        assert attachment is None

        # Fetch state is failed with checksum mismatch detail
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED
        assert fetch_record.last_error is not None
        assert "checksum mismatch" in fetch_record.last_error.lower()

        # The beatmap's file_state is still the original (unchanged)
        saved_beatmap = await repo.get_beatmap(2000)
        assert saved_beatmap is not None
        assert saved_beatmap.file_state is BeatmapFileState.MISSING

    # --- idempotency ---------------------------------------------------------

    async def test_already_pending_skips_fetch(self) -> None:
        """既にpendingのfile targetがproviderを呼ばずにskipする契約を検証する.

        targetをPENDING_FETCHとして事前登録する.
        file providerの呼出履歴が空のままであることを確認する.

        Returns:
            None: pending gateによるprovider未呼出を検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)
        # Pre-mark as pending
        _ = await repo.try_mark_fetch_pending(target, _NOW)

        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        job = self._make_job(repo, file_provider=file_provider)

        await job.execute(target)

        # The file provider was never called
        assert len(file_provider.calls) == 0

    async def test_duplicate_verified_file_reuses_existing_attachment(self) -> None:
        """このverified済みfileの再fetchが既存attachmentを再利用する契約を検証する.

        同じtargetを二度実行する.
        attachmentが同一でproviderとblob storageが一度だけ使われることを確認する.

        Returns:
            None: attachment再利用とFRESH fetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo, checksum_md5=_FILE_BODY_MD5)
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        blob_storage = StubBlobStorageService()
        job = self._make_job(repo, file_provider=file_provider, blob_storage=blob_storage)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        await job.execute(target)
        first_attachment = await repo.get_current_file_attachment(2000)
        await job.execute(target)
        second_attachment = await repo.get_current_file_attachment(2000)

        assert first_attachment is not None
        assert second_attachment == first_attachment
        assert len(file_provider.calls) == 1
        assert len(blob_storage.stored) == 1
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    async def test_concurrent_calls_only_one_proceeds(self) -> None:
        """同一file targetへの同時呼出で一件だけ取得する契約を検証する.

        遅延するfile providerで二つのexecuteを並行実行する.
        provider呼出が一度だけになることを確認する.

        Returns:
            None: provider呼出回数と最終fetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo, checksum_md5=_FILE_BODY_MD5)
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(
            by_beatmap_id={2000: fetch_result},
            delay=0.05,
        )
        blob_storage = StubBlobStorageService()
        job = self._make_job(repo, file_provider=file_provider, blob_storage=blob_storage)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        _ = await asyncio.gather(
            job.execute(target),
            job.execute(target),
        )

        # The file provider was called only once
        assert len(file_provider.calls) == 1
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FRESH

    # --- beatmap not found ---------------------------------------------------

    async def test_beatmap_not_found_marks_failed(self) -> None:
        """このrepositoryにないbeatmapのfile fetchがprovider未呼出でfailedになる契約を検証する.

        beatmapを保存しない条件でfetchを実行する.
        file providerを呼ばずFAILED stateになることを確認する.

        Returns:
            None: provider未呼出とfailed fetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        # Do NOT set up any beatmap
        fetch_result = OsuFileFetchResult(
            beatmap_id=2000,
            body=_FILE_BODY,
            source=BeatmapFileSource.OSU_CURRENT,
            original_filename="2000.osu",
        )
        file_provider = StubFileProvider(by_beatmap_id={2000: fetch_result})
        job = self._make_job(repo, file_provider=file_provider)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        await job.execute(target)

        # The file provider was never called
        assert len(file_provider.calls) == 0
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED

    # --- provider failure ----------------------------------------------------

    async def test_file_provider_raises_marks_failed(self) -> None:
        """対象file providerの例外がblob未保存のfailed fetchになる契約を検証する.

        file providerを失敗させ, blobを保存せずFAILED stateと失敗詳細が記録されることを確認する.

        Returns:
            None: blob未保存とfailed fetch stateを検証して完了し, 呼び出し側へ値を返さない.
        """
        repo = InMemoryBeatmapStore()
        _ = await _setup_repo_with_beatmap(repo)
        file_provider = StubFileProvider(exception=RuntimeError("mirror down"))
        blob_storage = StubBlobStorageService()
        job = self._make_job(repo, file_provider=file_provider, blob_storage=blob_storage)
        target = BeatmapFetchTarget.file_by_beatmap_id(2000)

        await job.execute(target)

        # No blob was stored
        assert len(blob_storage.stored) == 0
        fetch_record = await repo.get_fetch_state(target)
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.FAILED
        assert fetch_record.last_error is not None
        assert "mirror down" in fetch_record.last_error
