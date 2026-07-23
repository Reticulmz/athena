"""beatmap metadata解決pipelineのend-to-end contractを検証する."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFetchTargetKind,
    BeatmapFileState,
    BeatmapFreshnessPolicy,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
)
from osu_server.infrastructure.beatmaps.metadata_source_adapters import (
    InMemoryBeatmapMetadataProvider,
)
from osu_server.infrastructure.beatmaps.metadata_sources import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.services.commands.beatmaps import FetchBeatmapMetadataUseCase
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)
from tests.support.beatmaps import InMemoryBeatmapStore

_ONE_HOUR = timedelta(hours=1)
_THIRTY_DAYS = timedelta(days=30)
_NOW = datetime.now(UTC)

_BEATMAP_ID = 2000
_BEATMAPSET_ID = 1000
_CHECKSUM = "0123456789abcdef0123456789abcdef"

_ALT_BEATMAP_ID = 2001
_ALT_BEATMAPSET_ID = 1001
_ALT_CHECKSUM = "abcdef0123456789abcdef0123456789"


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    *,
    beatmap_id: int = _BEATMAP_ID,
    beatmapset_id: int = _BEATMAPSET_ID,
    checksum_md5: str = _CHECKSUM,
    mode: str = "osu",
    version: str = "Another",
    artist: str = "Camellia",
    title: str = "Exit This Earth's Atomosphere",
    creator: str = "Realazy",
    source: BeatmapMetadataSource | None = None,
    verified: BeatmapSourceVerification | None = None,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    official_status_source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    official_status_verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> BeatmapsetSnapshot:
    """指定値からmetadata resolution用beatmapset snapshotを作る.

    Args:
        beatmap_id (int): 所属beatmap識別子.
        beatmapset_id (int): beatmapset識別子.
        checksum_md5 (str): beatmapのMD5 checksum.
        mode (str): game mode名.
        version (str): difficulty version名.
        artist (str): artist名.
        title (str): 曲名.
        creator (str): beatmap作成者名.
        source (BeatmapMetadataSource | None): snapshot source. Noneならofficial status source.
        verified (BeatmapSourceVerification | None):
            source verification. Noneならofficial status verification.
        official_status (BeatmapRankStatus): official rank status.
        official_status_source (BeatmapMetadataSource): official statusのsource.
        official_status_verified (BeatmapSourceVerification): official statusのverification.
        last_fetched_at (datetime | None): 最終取得時刻. Noneなら固定test時刻.
        next_refresh_at (datetime | None): 次回更新時刻. Noneなら30日後.

    Returns:
        BeatmapsetSnapshot: metadata providerへ登録するsnapshot.
    """
    fetched_at = last_fetched_at or _NOW
    refresh_at = next_refresh_at or _NOW + _THIRTY_DAYS
    _source = source if source is not None else official_status_source
    _verified = verified if verified is not None else official_status_verified
    bm = BeatmapSnapshot(
        beatmap_id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
        mode=BeatmapMode(mode),
        version=version,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        total_length=240,
        hit_length=220,
        max_combo=1234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        last_fetched_at=fetched_at,
        next_refresh_at=refresh_at,
    )
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=artist,
        title=title,
        creator=creator,
        source=_source,
        verified=_verified,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        beatmaps=(bm,),
        last_fetched_at=fetched_at,
        next_refresh_at=refresh_at,
    )


def _make_mirror_snapshot(**kwargs: object) -> BeatmapsetSnapshot:
    """Unverified mirror sourceを持つbeatmapset snapshotを作る.

    Args:
        kwargs (object): _make_snapshotへ渡す追加keyword引数.

    Returns:
        BeatmapsetSnapshot: mirror fallback test用のunverified snapshot.
    """
    return _make_snapshot(
        source=BeatmapMetadataSource.MIRROR,
        verified=BeatmapSourceVerification.UNVERIFIED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        **kwargs,  # pyright: ignore[reportArgumentType]
    )


def _make_freshness_policy() -> BeatmapFreshnessPolicy:
    """Metadata resolution test用のfreshness policyを作る.

    Returns:
        BeatmapFreshnessPolicy: rankedとgraveyardを30日, 他を1時間で更新するpolicy.
    """
    return BeatmapFreshnessPolicy(
        ranked_refresh_interval=_THIRTY_DAYS,
        pending_refresh_interval=_ONE_HOUR,
        graveyard_refresh_interval=_THIRTY_DAYS,
        mirror_refresh_interval=_ONE_HOUR,
    )


# ---------------------------------------------------------------------------
# Wiring helper
# ---------------------------------------------------------------------------


def _build_service_with_job(
    repo: InMemoryBeatmapStore,
    official_provider: InMemoryBeatmapMetadataProvider,
    *,
    mirror_trust_enabled: bool = False,
) -> tuple[BeatmapMirrorService, FetchBeatmapMetadataUseCase, list[BeatmapFetchTarget]]:
    """Enqueue targetを記録するserviceとmetadata jobを組み立てる.

    Args:
        repo (InMemoryBeatmapStore): test用のin-memory beatmap store.
        official_provider (InMemoryBeatmapMetadataProvider): official sourceとして使うprovider.
        mirror_trust_enabled (bool): mirror sourceを信頼済みと扱うか.

    Returns:
        tuple[BeatmapMirrorService, FetchBeatmapMetadataUseCase, list[BeatmapFetchTarget]]:
            service, job, enqueue target一覧.
    """
    composite = CompositeBeatmapMetadataProvider(
        official=official_provider,
        mirror=InMemoryBeatmapMetadataProvider(),
    )
    job = FetchBeatmapMetadataUseCase(
        uow_factory=repo.uow_factory,
        metadata_provider=composite,
        freshness_policy=_make_freshness_policy(),
    )
    enqueued: list[BeatmapFetchTarget] = []

    async def _enqueue(target: BeatmapFetchTarget) -> None:
        """serviceが要求したmetadata refresh targetを記録する.

        Args:
            target (BeatmapFetchTarget): 後でjobへ渡すfetch対象.

        Returns:
            None: targetを記録し, 呼び出し側へ値を返さずに完了する.
        """
        enqueued.append(target)

    service = BeatmapMirrorService(
        repository=repo.query_repository,
        eligibility_service=BeatmapEligibilityService(),
        freshness_policy=_make_freshness_policy(),
        mirror_trust_enabled=mirror_trust_enabled,
        enqueue_refresh=_enqueue,
    )
    return service, job, enqueued


# ---------------------------------------------------------------------------
# Tests: beatmap id resolution E2E
# ---------------------------------------------------------------------------


class TestMetadataResolutionByBeatmapIdE2E:
    """beatmap idによるmetadata解決のpendingからfreshへの遷移を検証する."""

    @pytest.mark.asyncio
    async def test_missing_beatmap_transitions_from_pending_to_fresh(self) -> None:
        """未知beatmap idがmetadata job後にPENDING_FETCHからFRESHへ遷移することを検証する.

        空repositoryをresolveしてtargetをenqueueし,
        job実行後のresolveがofficial verified metadataを返すことを確認する.

        Returns:
            None: beatmap id解決のobservable lifecycleを検証し, 呼び出し側へ値を返さずに完了する.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, job, enqueued = _build_service_with_job(repo, official)

        # --- First resolve: beatmap is unknown ---------------------------------
        result1 = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result1.beatmap is None
        assert result1.beatmapset is None
        assert result1.eligibility is None
        assert result1.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert result1.file_status is BeatmapFileState.MISSING
        assert result1.source is None
        assert result1.verified is False
        assert result1.reason == "unsolicited"
        assert len(enqueued) == 1
        assert enqueued[0].kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID
        assert enqueued[0].target_key == str(_BEATMAP_ID)

        # --- Execute the metadata job ------------------------------------------
        await job.execute(enqueued[0])

        # --- Second resolve: beatmap is now cached -----------------------------
        result2 = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result2.beatmap is not None
        assert result2.beatmap.id == _BEATMAP_ID
        assert result2.beatmap.checksum_md5 == _CHECKSUM
        assert result2.beatmap.mode is BeatmapMode.OSU
        assert result2.beatmap.version == "Another"
        assert result2.beatmapset is not None
        assert result2.beatmapset.id == _BEATMAPSET_ID
        assert result2.beatmapset.title == "Exit This Earth's Atomosphere"
        assert result2.metadata_status is BeatmapFetchState.FRESH
        assert result2.source is BeatmapMetadataSource.OFFICIAL
        assert result2.verified is True
        assert result2.eligibility is not None
        assert result2.eligibility.accepts_scores is True
        assert result2.eligibility.awards_ranked_pp is True
        assert result2.reason is None

    @pytest.mark.asyncio
    async def test_official_mirror_fallback_flow(self) -> None:
        """Official source不在時にmirror fallbackがunverified metadataを保存することを検証する.

        official providerを空にしてmirror snapshotだけを登録し,
        resolveがmirror sourceとscore拒否eligibilityを返すことを確認する.

        Returns:
            None: mirror fallbackのtrust contractを検証し, 呼び出し側へ値を返さずに完了する.
        """
        repo = InMemoryBeatmapStore()
        mirror_snapshot = _make_mirror_snapshot()
        mirror = InMemoryBeatmapMetadataProvider()
        mirror.add_snapshot(mirror_snapshot)

        composite = CompositeBeatmapMetadataProvider(
            official=InMemoryBeatmapMetadataProvider(),
            mirror=mirror,
        )
        job = FetchBeatmapMetadataUseCase(
            uow_factory=repo.uow_factory,
            metadata_provider=composite,
            freshness_policy=_make_freshness_policy(),
        )
        enqueued: list[BeatmapFetchTarget] = []

        async def _enqueue(target: BeatmapFetchTarget) -> None:
            """Mirror fallback test用にrefresh targetを記録する.

            Args:
                target (BeatmapFetchTarget): 後でjobへ渡すfetch対象.

            Returns:
                None: targetを記録し, 呼び出し側へ値を返さずに完了する.
            """
            enqueued.append(target)

        service = BeatmapMirrorService(
            repository=repo.query_repository,
            eligibility_service=BeatmapEligibilityService(),
            freshness_policy=_make_freshness_policy(),
            enqueue_refresh=_enqueue,
        )

        # First resolve: unknown
        _ = await service.resolve_by_beatmap_id(_BEATMAP_ID)
        assert len(enqueued) == 1

        # Execute job
        await job.execute(enqueued[0])

        # Second resolve: mirror-sourced, unverified, eligibility denied
        result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result.beatmap is not None
        assert result.source is BeatmapMetadataSource.MIRROR
        assert result.verified is False
        assert result.eligibility is not None
        assert result.eligibility.accepts_scores is False
        assert result.eligibility.denial_reason == "untrusted_mirror_status"


# ---------------------------------------------------------------------------
# Tests: beatmapset id resolution E2E
# ---------------------------------------------------------------------------


class TestMetadataResolutionByBeatmapsetIdE2E:
    """beatmapset idによるmetadata解決のpendingからfreshへの遷移を検証する."""

    @pytest.mark.asyncio
    async def test_missing_beatmapset_transitions_from_pending_to_fresh(self) -> None:
        """未知beatmapset idのmetadata fetch lifecycleを検証する.

        official snapshotを登録したin-memory providerに対して未知のbeatmapset idをresolveし,
        PENDING_FETCHとMETADATA_BY_BEATMAPSET_ID targetのenqueueを確認する.
        targetのjob実行後に同じidを再resolveし, FRESHなofficial verified beatmapsetを確認する.

        Returns:
            None: pendingからfreshへのstate遷移とresolve metadataを検証して完了する.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot(beatmapset_id=_ALT_BEATMAPSET_ID, beatmap_id=_ALT_BEATMAP_ID)
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, job, enqueued = _build_service_with_job(repo, official)

        result1 = await service.resolve_by_beatmapset_id(_ALT_BEATMAPSET_ID)

        assert result1.beatmapset is None
        assert result1.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert result1.source is None
        assert result1.verified is False
        assert result1.reason == "unsolicited"
        assert len(enqueued) == 1
        assert enqueued[0].kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID

        await job.execute(enqueued[0])

        result2 = await service.resolve_by_beatmapset_id(_ALT_BEATMAPSET_ID)

        assert result2.beatmapset is not None
        assert result2.beatmapset.id == _ALT_BEATMAPSET_ID
        assert result2.metadata_status is BeatmapFetchState.FRESH
        assert result2.source is BeatmapMetadataSource.OFFICIAL
        assert result2.verified is True
        assert result2.reason is None


# ---------------------------------------------------------------------------
# Tests: checksum resolution E2E
# ---------------------------------------------------------------------------


class TestMetadataResolutionByChecksumE2E:
    """checksumによるmetadata解決のpendingからfreshへの遷移を検証する."""

    @pytest.mark.asyncio
    async def test_missing_beatmap_by_checksum_transitions_from_pending_to_fresh(self) -> None:
        """未知checksumのmetadata fetch lifecycleを検証する.

        official snapshotのchecksumを指定して未解決のchecksumをresolveし,
        PENDING_FETCHとMETADATA_BY_CHECKSUM targetおよびtarget keyを確認する.
        targetのjob実行後に同じchecksumを再resolveし,
        FRESHなbeatmap idとofficial verificationを確認する.

        Returns:
            None: checksum resolveのpendingからfreshへのobservable stateを検証して完了する.
        """
        repo = InMemoryBeatmapStore()
        checksum = _ALT_CHECKSUM
        snapshot = _make_snapshot(beatmap_id=_ALT_BEATMAP_ID, checksum_md5=checksum)
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, job, enqueued = _build_service_with_job(repo, official)

        result1 = await service.resolve_by_checksum(checksum)

        assert result1.beatmap is None
        assert result1.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert result1.source is None
        assert result1.verified is False
        assert result1.reason == "unsolicited"
        assert len(enqueued) == 1
        assert enqueued[0].kind is BeatmapFetchTargetKind.METADATA_BY_CHECKSUM
        assert enqueued[0].target_key == checksum

        await job.execute(enqueued[0])

        result2 = await service.resolve_by_checksum(checksum)

        assert result2.beatmap is not None
        assert result2.beatmap.checksum_md5 == checksum
        assert result2.beatmap.id == _ALT_BEATMAP_ID
        assert result2.metadata_status is BeatmapFetchState.FRESH
        assert result2.source is BeatmapMetadataSource.OFFICIAL
        assert result2.verified is True


# ---------------------------------------------------------------------------
# Tests: idempotency (req 14)
# ---------------------------------------------------------------------------


class TestMetadataResolutionIdempotencyE2E:
    """metadata解決のconcurrent callとcache reuse contractを検証する."""

    @pytest.mark.asyncio
    async def test_concurrent_missing_resolves_produce_consistent_pending_state(
        self,
    ) -> None:
        """同一未知beatmapへのconcurrent resolveのpending contractを検証する.

        snapshotを持つproviderと空のrepositoryを用意し, 同一beatmap idのresolveを2件同時実行する.
        両responseがPENDING_FETCHとなり,
        job実行前でも少なくとも1件のrefresh targetがenqueueされることを確認する.

        Returns:
            None: concurrent requestのstateとenqueueのobservable outcomeを検証して完了する.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, _job, enqueued = _build_service_with_job(repo, official)

        r1, r2 = await asyncio.gather(
            service.resolve_by_beatmap_id(_BEATMAP_ID),
            service.resolve_by_beatmap_id(_BEATMAP_ID),
        )

        # Both return pending (unknown result)
        assert r1.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert r2.metadata_status is BeatmapFetchState.PENDING_FETCH
        # Two enqueues happened (one per resolve call); this is acceptable
        # because the job itself is idempotent through try_mark_fetch_pending.
        assert len(enqueued) >= 1

    @pytest.mark.asyncio
    async def test_re_resolve_after_cached_does_not_enqueue(self) -> None:
        """保存済みfresh metadataの再resolveがrefreshをenqueueしないcontractを検証する.

        最初のresolveでenqueueされたmetadata jobを実行してsnapshotを保存し, enqueue spyをclearする.
        同じbeatmap idを再resolveした結果がFRESHとなり, 新しいtargetが記録されないことを確認する.

        Returns:
            None: cache reuse時のstateとenqueue countを検証して完了する.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, job, enqueued = _build_service_with_job(repo, official)

        # Initial resolve + fetch
        _ = await service.resolve_by_beatmap_id(_BEATMAP_ID)
        assert len(enqueued) == 1
        await job.execute(enqueued[0])

        # Reset enqueue spy
        enqueued.clear()

        # Re-resolve the now-cached beatmap
        result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result.metadata_status is BeatmapFetchState.FRESH
        assert len(enqueued) == 0  # no refresh needed


# ---------------------------------------------------------------------------
# Tests: bounded wait (req 2.5)
# ---------------------------------------------------------------------------


class TestMetadataResolutionBoundedWaitE2E:
    """metadata解決のbounded wait成功とtimeout contractを検証する."""

    @pytest.mark.asyncio
    async def test_bounded_wait_returns_fresh_when_data_arrives_in_time(self) -> None:
        """Bounded wait中にmetadataが到着するとresolveがFRESHを返すことを検証する.

        background taskでenqueue後のjobを実行し,
        timeout内にbeatmapが保存されたresolve結果を確認する.

        Returns:
            None: bounded wait成功時のobservable stateを検証し, 呼び出し側へ値を返さずに完了する.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)

        composite = CompositeBeatmapMetadataProvider(
            official=official,
            mirror=InMemoryBeatmapMetadataProvider(),
        )
        job = FetchBeatmapMetadataUseCase(
            uow_factory=repo.uow_factory,
            metadata_provider=composite,
            freshness_policy=_make_freshness_policy(),
        )
        enqueued: list[BeatmapFetchTarget] = []

        async def _enqueue(target: BeatmapFetchTarget) -> None:
            """Bounded wait test用にrefresh targetを記録する.

            Args:
                target (BeatmapFetchTarget): 後でbackground jobへ渡すfetch対象.

            Returns:
                None: targetを記録し, 呼び出し側へ値を返さずに完了する.
            """
            enqueued.append(target)

        service = BeatmapMirrorService(
            repository=repo.query_repository,
            eligibility_service=BeatmapEligibilityService(),
            freshness_policy=_make_freshness_policy(),
            enqueue_refresh=_enqueue,
        )

        # Background task: execute the job shortly after the resolve starts
        async def _populate() -> None:
            """enqueueされたtargetのmetadata jobをbackground taskで実行する.

            Returns:
                None: metadataを保存し, 呼び出し側へ値を返さずに完了する.
            """
            # Wait for enqueue to happen
            while not enqueued:
                await asyncio.sleep(0.001)
            await job.execute(enqueued[0])

        populate_task = asyncio.create_task(_populate())

        result = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(wait_timeout_seconds=5.0),
        )

        await populate_task

        assert result.beatmap is not None
        assert result.beatmap.id == _BEATMAP_ID
        assert result.metadata_status is BeatmapFetchState.FRESH

    @pytest.mark.asyncio
    async def test_bounded_wait_returns_pending_on_timeout(self) -> None:
        """Bounded wait timeoutがexceptionではなくpending resultを返すcontractを検証する.

        snapshotを持たないproviderと空のrepositoryでwait timeoutを0.001秒に指定してresolveする.
        metadataが保存されないままtimeoutしても,
        beatmapなしのPENDING_FETCHとunsolicited reasonを確認する.

        Returns:
            None: timeout時のnon-exception response stateを検証して完了する.
        """
        repo = InMemoryBeatmapStore()
        official = InMemoryBeatmapMetadataProvider()
        service, _job, _enqueued = _build_service_with_job(repo, official)

        result = await service.resolve_by_beatmap_id(
            _BEATMAP_ID,
            options=BeatmapResolveOptions(wait_timeout_seconds=0.001),
        )

        assert result.beatmap is None
        assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
        assert result.reason == "unsolicited"


# ---------------------------------------------------------------------------
# Tests: upstream-provider failure (req 7.3, 7.5)
# ---------------------------------------------------------------------------


class TestMetadataResolutionFailureE2E:
    """全metadata provider failure時のFAILED state contractを検証する."""

    @pytest.mark.asyncio
    async def test_all_providers_fail_produces_failed_state(self) -> None:
        """全metadata providerが空の場合のFAILED state contractを検証する.

        snapshotを登録しないproviderで最初のresolveを行い, enqueueされたmetadata jobを実行する.
        再resolve結果がbeatmapなしのFAILEDとなり,
        provider failure reasonとeligibilityなしを返すことを確認する.

        Returns:
            None: all-provider failureのobservable stateとreasonを検証して完了する.
        """
        repo = InMemoryBeatmapStore()
        # Both providers are empty -- no snapshot preloaded
        service, job, enqueued = _build_service_with_job(repo, InMemoryBeatmapMetadataProvider())

        _ = await service.resolve_by_beatmap_id(_BEATMAP_ID)
        assert len(enqueued) == 1

        await job.execute(enqueued[0])

        result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result.beatmap is None
        assert result.metadata_status is BeatmapFetchState.FAILED
        assert result.reason is not None
        assert "all configured metadata providers" in result.reason
        assert result.eligibility is None


# ---------------------------------------------------------------------------
# Tests: beatmap identity completeness (req 1.5)
# ---------------------------------------------------------------------------


class TestBeatmapIdentityAfterResolutionE2E:
    """解決済みbeatmapがdownstream consumer向け完全identityを公開することを検証する."""

    @pytest.mark.asyncio
    async def test_resolved_beatmap_exposes_full_identity(self) -> None:
        """解決済みbeatmapがmetadata job後に完全identityを公開するcontractを検証する.

        official snapshotを登録し, 最初のresolveでenqueueされたmetadata jobを実行してから
        再resolveする. beatmapのid, checksum, mode, difficulty fieldとbeatmapsetのartist,
        title, creatorを確認する.

        Returns:
            None: downstream consumer向けidentity metadataを検証して完了する.
        """
        repo = InMemoryBeatmapStore()
        snapshot = _make_snapshot()
        official = InMemoryBeatmapMetadataProvider()
        official.add_snapshot(snapshot)
        service, job, enqueued = _build_service_with_job(repo, official)

        _ = await service.resolve_by_beatmap_id(_BEATMAP_ID)
        await job.execute(enqueued[0])

        result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

        assert result.beatmap is not None
        assert result.beatmap.id == _BEATMAP_ID
        assert result.beatmap.beatmapset_id == _BEATMAPSET_ID
        assert result.beatmap.checksum_md5 == _CHECKSUM
        assert result.beatmap.mode is BeatmapMode.OSU
        assert result.beatmap.version == "Another"
        assert result.beatmap.total_length == 240
        assert result.beatmap.bpm == 180.0
        assert result.beatmap.cs == 4.0
        assert result.beatmap.od == 8.5
        assert result.beatmap.ar == 9.4
        assert result.beatmap.hp == 6.5
        assert result.beatmap.difficulty_rating == 5.67

        assert result.beatmapset is not None
        assert result.beatmapset.artist == "Camellia"
        assert result.beatmapset.title == "Exit This Earth's Atomosphere"
        assert result.beatmapset.creator == "Realazy"
