"""Beatmap mirror serviceのcache解決,refresh要求,待機契約を検証する.

memory repositoryを使い,既知と未発見のbeatmap/beatmapset,file要件,
eligibility,background fetch enqueue,bounded waitのobservable outcomeを対象にする.
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFetchTargetKind,
    BeatmapFileState,
    BeatmapFreshnessPolicy,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSet,
    BeatmapSetResolveResult,
    BeatmapSourceVerification,
)
from osu_server.repositories.memory.commands.beatmaps import InMemoryBeatmapCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)

_NOW = datetime.now(UTC).replace(microsecond=0)
_ONE_HOUR = timedelta(hours=1)
_THIRTY_DAYS = timedelta(days=30)

_DEFAULT_CHECKSUM = "0123456789abcdef0123456789abcdef"
_ALT_CHECKSUM = "abcdef0123456789abcdef0123456789"
_BEATMAP_ID = 2_000
_BEATMAPSET_ID = 1_000


# ---------------------------------------------------------------------------
# Test helpers -- domain object factories
# ---------------------------------------------------------------------------


def _make_beatmap(
    *,
    beatmap_id: int = _BEATMAP_ID,
    beatmapset_id: int = _BEATMAPSET_ID,
    checksum_md5: str = _DEFAULT_CHECKSUM,
    mode: str = "osu",
    version: str = "Another",
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    official_status_source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    official_status_verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    metadata_fetch_state: BeatmapFetchState = BeatmapFetchState.FRESH,
    file_state: BeatmapFileState = BeatmapFileState.MISSING,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> Beatmap:
    """Mirror serviceの解決条件を持つbeatmapを生成する.

    Args:
        beatmap_id (int): 生成するbeatmapの識別子.
        beatmapset_id (int): 生成するbeatmapが属するbeatmapsetの識別子.
        checksum_md5 (str): checksum検索に使用する小文字MD5値.
        mode (str): BeatmapModeへ変換するgame mode名.
        version (str): 生成するdifficulty名.
        official_status (BeatmapRankStatus): eligibility判定に使用する公式公開状態.
        official_status_source (BeatmapMetadataSource): 公式公開状態を得たmetadata source.
        official_status_verified (BeatmapSourceVerification): metadata sourceの検証状態.
        metadata_fetch_state (BeatmapFetchState): 保存済みmetadataの取得状態.
        file_state (BeatmapFileState): osu file attachmentの取得状態.
        last_fetched_at (datetime | None): metadataを最後に取得したUTC時刻.
        next_refresh_at (datetime | None): freshness判定に使用する次回refresh時刻.

    Returns:
        Beatmap: file attachmentとlocal overrideを持たない検証用beatmap.
    """
    return Beatmap(
        id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
        mode=BeatmapMode(mode),
        version=version,
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        local_status_override=None,
        metadata_fetch_state=metadata_fetch_state,
        file_state=file_state,
        file_attachment=None,
        last_fetched_at=last_fetched_at,
        next_refresh_at=next_refresh_at,
    )


def _make_beatmapset(
    *,
    beatmapset_id: int = _BEATMAPSET_ID,
    artist: str = "Camellia",
    title: str = "Exit This Earth's Atomosphere",
    creator: str = "Realazy",
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    official_status_source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    official_status_verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    beatmaps: tuple[Beatmap, ...] | None = None,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> BeatmapSet:
    """Mirror serviceのset解決条件を持つbeatmapsetを生成する.

    Args:
        beatmapset_id (int): 生成するbeatmapsetの識別子.
        artist (str): set metadataへ設定するartist名.
        title (str): set metadataへ設定する曲名.
        creator (str): set metadataへ設定する作成者名.
        official_status (BeatmapRankStatus): setに設定する公式公開状態.
        official_status_source (BeatmapMetadataSource): set metadataの取得source.
        official_status_verified (BeatmapSourceVerification): set metadataの検証状態.
        beatmaps (tuple[Beatmap, ...] | None): setに所属させるdifficulty列. Noneなら空列.
        last_fetched_at (datetime | None): set metadataを最後に取得したUTC時刻.
        next_refresh_at (datetime | None): set metadataをrefreshする予定のUTC時刻.

    Returns:
        BeatmapSet: 指定metadataとdifficulty列を持つ検証用beatmapset.
    """
    return BeatmapSet(
        id=beatmapset_id,
        artist=artist,
        title=title,
        creator=creator,
        artist_unicode=None,
        title_unicode=None,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        beatmaps=beatmaps or (),
        last_fetched_at=last_fetched_at,
        next_refresh_at=next_refresh_at,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def freshness_policy() -> BeatmapFreshnessPolicy:
    """各公開状態とmirror sourceに固定したrefresh間隔を提供する.

    Returns:
        BeatmapFreshnessPolicy: ranked/graveyardは30日,pending/mirrorは1時間のpolicy.
    """
    return BeatmapFreshnessPolicy(
        ranked_refresh_interval=_THIRTY_DAYS,
        pending_refresh_interval=_ONE_HOUR,
        graveyard_refresh_interval=_THIRTY_DAYS,
        mirror_refresh_interval=_ONE_HOUR,
    )


@pytest.fixture
def command_state() -> InMemoryCommandRepositoryState:
    """Repository fixture間で共有する空のin-memory永続化状態を提供する.

    Returns:
        InMemoryCommandRepositoryState: testごとに新規作成した共有可能なrepository state.
    """
    return InMemoryCommandRepositoryState()


@pytest.fixture
def repo(command_state: InMemoryCommandRepositoryState) -> InMemoryBeatmapCommandRepository:
    """snapshotとfetch stateを準備するin-memory beatmap repositoryを提供する.

    Args:
        command_state (InMemoryCommandRepositoryState): serviceと共有する永続化状態.

    Returns:
        InMemoryBeatmapCommandRepository: test setupでbeatmap snapshotを保存するrepository.
    """
    return InMemoryBeatmapCommandRepository(command_state)


@pytest.fixture
def service(
    command_state: InMemoryCommandRepositoryState,
    freshness_policy: BeatmapFreshnessPolicy,
) -> BeatmapMirrorService:
    """Enqueue callbackなしでcache解決を行うmirror serviceを提供する.

    Args:
        command_state (InMemoryCommandRepositoryState): query repositoryと共有する状態.
        freshness_policy (BeatmapFreshnessPolicy): 解決結果のfreshnessを判定するpolicy.

    Returns:
        BeatmapMirrorService: 保存済みsnapshotを読み取り,fetch要求を送らないservice.
    """
    return BeatmapMirrorService(
        repository=InMemoryBeatmapQueryRepository(InMemoryUnitOfWorkFactory(command_state)),
        eligibility_service=BeatmapEligibilityService(),
        freshness_policy=freshness_policy,
    )


# ---------------------------------------------------------------------------
# Tests: resolve_by_beatmap_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_returns_cached_beatmap(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """新鮮な保存済みbeatmapを完全な解決結果として返す契約を検証する.

    対応するbeatmapsetをrepositoryへ保存してID検索し,entity,FRESH状態,公式source,
    許可されたeligibilityが返ることを確認する.

    Args:
        service (BeatmapMirrorService): cache-first解決を実行するservice fixture.
        repo (InMemoryBeatmapCommandRepository): 保存済みsnapshotを準備するrepository fixture.

    Returns:
        None: cached beatmapと関連setを含む正常な解決結果を検証して完了する.
    """
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,), last_fetched_at=_NOW)
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

    assert result.beatmap is not None
    assert result.beatmap.id == _BEATMAP_ID
    assert result.beatmapset is not None
    assert result.beatmapset.id == _BEATMAPSET_ID
    assert result.metadata_status is BeatmapFetchState.FRESH
    assert result.file_status is BeatmapFileState.MISSING
    assert result.source is BeatmapMetadataSource.OFFICIAL
    assert result.verified is True
    assert result.eligibility is not None
    assert result.eligibility.accepts_scores is True
    assert result.reason is None


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_unknown_returns_pending(
    service: BeatmapMirrorService,
) -> None:
    """未保存のBeatmap IDをpending fetchのunavailable結果へ投影する契約を検証する.

    cache missのIDを解決し,entityとeligibilityを返さず,PENDING_FETCH,MISSING,
    unsolicited理由を返すことを確認する.

    Args:
        service (BeatmapMirrorService): 未保存IDを解決するservice fixture.

    Returns:
        None: fetch待機を示すunavailable結果を検証して完了する.
    """
    result = await service.resolve_by_beatmap_id(999)

    assert result.beatmap is None
    assert result.beatmapset is None
    assert result.eligibility is None
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.file_status is BeatmapFileState.MISSING
    assert result.source is None
    assert result.verified is False
    assert result.reason == "unsolicited"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_returns_failed_when_fetch_failed(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """失敗済みmetadata fetchをBeatmap ID解決結果へ保持する契約を検証する.

    未保存IDのfetch stateをprovider_timeoutでFAILEDにして解決し,entityなしのFAILED状態と
    同じ失敗理由が返ることを確認する.

    Args:
        service (BeatmapMirrorService): fetch stateを投影するservice fixture.
        repo (InMemoryBeatmapCommandRepository): 失敗済みfetch stateを保存するrepository fixture.

    Returns:
        None: FAILED状態とprovider_timeout理由を検証して完了する.
    """
    target = BeatmapFetchTarget(
        target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID, target_key="999"
    )
    now = _NOW
    await repo.mark_fetch_failed(target, "provider_timeout", now)

    result = await service.resolve_by_beatmap_id(999)

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.FAILED
    assert result.reason == "provider_timeout"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_returns_pending_for_pending_fetch(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """実行中のmetadata fetchをBeatmap ID解決時にpendingとして返す契約を検証する.

    未保存IDをPENDING_FETCHにして解決し,entityを返さずpending_fetch理由を維持することを
    確認する.

    Args:
        service (BeatmapMirrorService): fetch stateを投影するservice fixture.
        repo (InMemoryBeatmapCommandRepository): pending fetch stateを保存するrepository fixture.

    Returns:
        None: PENDING_FETCH状態とpending_fetch理由を検証して完了する.
    """
    target = BeatmapFetchTarget(
        target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID, target_key="999"
    )
    now = _NOW
    _ = await repo.try_mark_fetch_pending(target, now)

    result = await service.resolve_by_beatmap_id(999)

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.reason == "pending_fetch"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_returns_stale_when_past_next_refresh(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """refresh期限を過ぎた保存済みbeatmapをSTALEとして投影する契約を検証する.

    next_refresh_atが現在より前のbeatmapを保存して解決し,entityを維持しつつSTALE状態と
    stale理由を返すことを確認する.

    Args:
        service (BeatmapMirrorService): freshnessを評価するservice fixture.
        repo (InMemoryBeatmapCommandRepository): 期限切れsnapshotを保存するrepository fixture.

    Returns:
        None: STALE状態とstale理由を持つ解決結果を検証して完了する.
    """
    beatmap = _make_beatmap(
        last_fetched_at=_NOW - _THIRTY_DAYS - _ONE_HOUR,
        next_refresh_at=_NOW - _ONE_HOUR,  # already past
        file_state=BeatmapFileState.AVAILABLE,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

    assert result.beatmap is not None
    assert result.metadata_status is BeatmapFetchState.STALE
    assert result.reason == "stale"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_force_refresh_overrides_freshness(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """force_refresh指定が新鮮なcacheを再取得対象にする契約を検証する.

    将来のnext_refresh_atを持つbeatmapをforce_refresh付きで解決し,STALE状態と
    force_refresh理由を返すことを確認する.

    Args:
        service (BeatmapMirrorService): force refreshを評価するservice fixture.
        repo (InMemoryBeatmapCommandRepository): 新鮮なsnapshotを保存するrepository fixture.

    Returns:
        None: force_refreshが通常のfreshnessを上書きする結果を検証して完了する.
    """
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,  # still fresh
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(
        _BEATMAP_ID,
        options=BeatmapResolveOptions(force_refresh=True),
    )

    assert result.beatmap is not None
    assert result.metadata_status is BeatmapFetchState.STALE
    assert result.reason == "force_refresh"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_require_osu_file_when_file_missing(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """Osu file必須の解決で欠落fileを利用不能理由として返す契約を検証する.

    新鮮だがfile_stateがMISSINGのbeatmapをrequire_osu_file付きで解決し,MISSING状態と
    osu_file_required_but_unavailable理由を返すことを確認する.

    Args:
        service (BeatmapMirrorService): file要件を投影するservice fixture.
        repo (InMemoryBeatmapCommandRepository): file欠落snapshotを保存するrepository fixture.

    Returns:
        None: file要件を満たさない解決結果を検証して完了する.
    """
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
        file_state=BeatmapFileState.MISSING,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(
        _BEATMAP_ID,
        options=BeatmapResolveOptions(require_osu_file=True),
    )

    assert result.beatmap is not None
    assert result.file_status is BeatmapFileState.MISSING
    assert result.reason == "osu_file_required_but_unavailable"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_file_available_ok(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """Osu file必須の解決で利用可能fileを正常結果として返す契約を検証する.

    新鮮でfile_stateがAVAILABLEのbeatmapをrequire_osu_file付きで解決し,AVAILABLE状態と
    理由なしの結果を返すことを確認する.

    Args:
        service (BeatmapMirrorService): file要件を投影するservice fixture.
        repo (InMemoryBeatmapCommandRepository): file利用可能snapshotを保存するrepository fixture.

    Returns:
        None: file要件を満たす理由なしの解決結果を検証して完了する.
    """
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
        file_state=BeatmapFileState.AVAILABLE,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(
        _BEATMAP_ID,
        options=BeatmapResolveOptions(require_osu_file=True),
    )

    assert result.file_status is BeatmapFileState.AVAILABLE
    assert result.reason is None


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_projects_eligibility(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """QUALIFIED beatmapのscore可否とPP非付与を解決結果へ投影する契約を検証する.

    QUALIFIEDのbeatmapsetを保存してID検索し,scoreは受理する一方でranked/loved PPは
    付与しないeligibilityを返すことを確認する.

    Args:
        service (BeatmapMirrorService): eligibilityを解決結果へ投影するservice fixture.
        repo (InMemoryBeatmapCommandRepository): QUALIFIED snapshotを保存するrepository fixture.

    Returns:
        None: score受理とPP非付与を持つeligibilityを検証して完了する.
    """
    beatmap = _make_beatmap(
        official_status=BeatmapRankStatus.QUALIFIED,
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = _make_beatmapset(
        beatmaps=(beatmap,),
        official_status=BeatmapRankStatus.QUALIFIED,
    )
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

    assert result.eligibility is not None
    assert result.eligibility.accepts_scores is True
    assert result.eligibility.awards_ranked_pp is False
    assert result.eligibility.awards_loved_pp is False


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_untrusted_mirror_denies_eligibility(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """未信頼mirror metadataがscore eligibilityを拒否する契約を検証する.

    UNVERIFIEDなMIRROR由来のRANKED beatmapを解決し,entityを返してもeligibilityは
    accepts_scores=Falseとuntrusted_mirror_status理由になることを確認する.

    Args:
        service (BeatmapMirrorService): source trustを判定するservice fixture.
        repo (InMemoryBeatmapCommandRepository): 未信頼mirror snapshotを保存するrepository fixture.

    Returns:
        None: mirror trust不足によるeligibility拒否を検証して完了する.
    """
    beatmap = _make_beatmap(
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = _make_beatmapset(
        beatmaps=(beatmap,),
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
    )
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

    assert result.eligibility is not None
    assert result.eligibility.accepts_scores is False
    assert result.eligibility.denial_reason == "untrusted_mirror_status"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_unknown_with_file_fetch_failed(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """未保存beatmapのmetadata/file失敗状態を同時に投影する契約を検証する.

    metadataとfileのfetch stateをそれぞれFAILEDにして解決し,両方のFAILED状態と
    metadata側のprovider_error理由を返すことを確認する.

    Args:
        service (BeatmapMirrorService): 未保存beatmapのfetch stateを解決するservice fixture.
        repo (InMemoryBeatmapCommandRepository): metadata/file失敗状態を保存するrepository fixture.

    Returns:
        None: metadataとfileの失敗状態を含むunavailable結果を検証して完了する.
    """
    metadata_target = BeatmapFetchTarget(
        target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID, target_key="999"
    )
    file_target = BeatmapFetchTarget(
        target_type=BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID, target_key="999"
    )
    now = _NOW
    await repo.mark_fetch_failed(metadata_target, "provider_error", now)
    await repo.mark_fetch_failed(file_target, "file_download_failed", now)

    result = await service.resolve_by_beatmap_id(999)

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.FAILED
    assert result.file_status is BeatmapFileState.FAILED
    assert result.reason == "provider_error"


# ---------------------------------------------------------------------------
# Tests: resolve_by_beatmapset_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_by_beatmapset_id_returns_cached_set(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """新鮮な保存済みbeatmapsetを公式source付きで返す契約を検証する.

    freshなbeatmapとsetを保存してset ID検索し,entity,FRESH状態,公式source,検証済みフラグ,
    理由なしの結果を返すことを確認する.

    Args:
        service (BeatmapMirrorService): beatmapsetを解決するservice fixture.
        repo (InMemoryBeatmapCommandRepository): cached setを保存するrepository fixture.

    Returns:
        None: cached beatmapsetの正常な解決結果を検証して完了する.
    """
    beatmap = _make_beatmap(last_fetched_at=_NOW, next_refresh_at=_NOW + _THIRTY_DAYS)
    beatmapset = _make_beatmapset(
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmapset_id(_BEATMAPSET_ID)

    assert result.beatmapset is not None
    assert result.beatmapset.id == _BEATMAPSET_ID
    assert result.metadata_status is BeatmapFetchState.FRESH
    assert result.source is BeatmapMetadataSource.OFFICIAL
    assert result.verified is True
    assert result.reason is None


@pytest.mark.asyncio
async def test_resolve_by_beatmapset_id_unknown_returns_pending(
    service: BeatmapMirrorService,
) -> None:
    """未保存のBeatmapset IDをpending fetchのunavailable結果へ投影する契約を検証する.

    cache missのset IDを解決し,entityとsourceを返さずPENDING_FETCH,未検証,
    unsolicited理由を返すことを確認する.

    Args:
        service (BeatmapMirrorService): 未保存set IDを解決するservice fixture.

    Returns:
        None: pending metadata fetchを示すset解決結果を検証して完了する.
    """
    result = await service.resolve_by_beatmapset_id(999)

    assert result.beatmapset is None
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.source is None
    assert result.verified is False
    assert result.reason == "unsolicited"


@pytest.mark.asyncio
async def test_resolve_by_beatmapset_id_failed_fetch_returns_failed(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """失敗済みbeatmapset metadata fetchを解決結果へ保持する契約を検証する.

    未保存set IDのfetch stateをapi_unreachableでFAILEDにして解決し,entityなしのFAILED状態と
    同じ失敗理由を返すことを確認する.

    Args:
        service (BeatmapMirrorService): set fetch stateを投影するservice fixture.
        repo (InMemoryBeatmapCommandRepository): 失敗済みset fetch stateを保存する
            repository fixture.

    Returns:
        None: FAILED状態とapi_unreachable理由を検証して完了する.
    """
    target = BeatmapFetchTarget(
        target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID, target_key="999"
    )
    now = _NOW
    await repo.mark_fetch_failed(target, "api_unreachable", now)

    result = await service.resolve_by_beatmapset_id(999)

    assert result.beatmapset is None
    assert result.metadata_status is BeatmapFetchState.FAILED
    assert result.reason == "api_unreachable"


# ---------------------------------------------------------------------------
# Tests: resolve_by_checksum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_by_checksum_returns_cached_beatmap(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """保存済みMD5 checksumから新鮮なbeatmapを解決する契約を検証する.

    checksumを持つfreshなbeatmapを保存して同じ値で検索し,entity,FRESH状態,公式source,
    検証済みフラグを返すことを確認する.

    Args:
        service (BeatmapMirrorService): checksumでbeatmapを解決するservice fixture.
        repo (InMemoryBeatmapCommandRepository): checksum一致snapshotを保存するrepository fixture.

    Returns:
        None: checksum一致のcached beatmap解決結果を検証して完了する.
    """
    beatmap = _make_beatmap(
        checksum_md5=_DEFAULT_CHECKSUM,
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_checksum(_DEFAULT_CHECKSUM)

    assert result.beatmap is not None
    assert result.beatmap.checksum_md5 == _DEFAULT_CHECKSUM
    assert result.metadata_status is BeatmapFetchState.FRESH
    assert result.source is BeatmapMetadataSource.OFFICIAL
    assert result.verified is True


@pytest.mark.asyncio
async def test_resolve_by_checksum_unknown_returns_pending(
    service: BeatmapMirrorService,
) -> None:
    """未保存MD5 checksumをpending fetchのunavailable結果へ投影する契約を検証する.

    cacheにないchecksumを解決し,entityとsourceを返さずPENDING_FETCH,未検証,
    unsolicited理由を返すことを確認する.

    Args:
        service (BeatmapMirrorService): 未保存checksumを解決するservice fixture.

    Returns:
        None: pending metadata fetchを示すchecksum解決結果を検証して完了する.
    """
    result = await service.resolve_by_checksum(_ALT_CHECKSUM)

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.source is None
    assert result.verified is False
    assert result.reason == "unsolicited"


@pytest.mark.asyncio
async def test_resolve_by_checksum_failed_fetch_returns_failed(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """失敗済みchecksum metadata fetchを解決結果へ保持する契約を検証する.

    未保存checksumのfetch stateをchecksum_not_foundでFAILEDにして解決し,entityなしのFAILED状態と
    同じ失敗理由を返すことを確認する.

    Args:
        service (BeatmapMirrorService): checksum fetch stateを投影するservice fixture.
        repo (InMemoryBeatmapCommandRepository): 失敗済みchecksum fetch stateを保存する
            repository fixture.

    Returns:
        None: FAILED状態とchecksum_not_found理由を検証して完了する.
    """
    target = BeatmapFetchTarget(
        target_type=BeatmapFetchTargetKind.METADATA_BY_CHECKSUM, target_key=_ALT_CHECKSUM
    )
    now = _NOW
    await repo.mark_fetch_failed(target, "checksum_not_found", now)

    result = await service.resolve_by_checksum(_ALT_CHECKSUM)

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.FAILED
    assert result.reason == "checksum_not_found"


# ---------------------------------------------------------------------------
# Tests: BeatmapResolveResult structure
# ---------------------------------------------------------------------------


def test_resolve_result_is_frozen() -> None:
    """Beatmap解決結果が作成後に変更できない値objectである契約を検証する.

    PENDING_FETCHの結果を作成してreasonへ代入を試み,FrozenInstanceErrorになることを確認する.

    Returns:
        None: BeatmapResolveResultのfrozen不変条件を検証して完了する.
    """
    result = BeatmapResolveResult(
        beatmap=None,
        beatmapset=None,
        eligibility=None,
        metadata_status=BeatmapFetchState.PENDING_FETCH,
        file_status=BeatmapFileState.MISSING,
        source=None,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="unsolicited",
    )
    with pytest.raises(FrozenInstanceError):
        result.reason = "changed"  # pyright: ignore[reportAttributeAccessIssue]


def test_set_resolve_result_is_frozen() -> None:
    """Beatmapset解決結果が作成後に変更できない値objectである契約を検証する.

    PENDING_FETCHのset結果を作成してreasonへ代入を試み,FrozenInstanceErrorになることを確認する.

    Returns:
        None: BeatmapSetResolveResultのfrozen不変条件を検証して完了する.
    """
    result = BeatmapSetResolveResult(
        beatmapset=None,
        metadata_status=BeatmapFetchState.PENDING_FETCH,
        source=None,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="unsolicited",
    )
    with pytest.raises(FrozenInstanceError):
        result.reason = "changed"  # pyright: ignore[reportAttributeAccessIssue]


def test_resolve_options_defaults() -> None:
    """解決optionの既定値が追加file要件とrefreshを要求しない契約を検証する.

    引数なしでoptionを生成し,require_osu_fileとforce_refreshがFalse,wait_timeout_secondsが
    0.0であることを確認する.

    Returns:
        None: 呼び出し側が指定しない既定の解決制約を検証して完了する.
    """
    opts = BeatmapResolveOptions()
    assert opts.require_osu_file is False
    assert opts.wait_timeout_seconds == 0.0
    assert opts.force_refresh is False


# ---------------------------------------------------------------------------
# Fixtures for enqueue-aware tests
# ---------------------------------------------------------------------------


@pytest.fixture
def enqueue_spy() -> list[BeatmapFetchTarget]:
    """Enqueue callbackが受け取ったfetch targetを記録する空の可変列を提供する.

    Returns:
        list[BeatmapFetchTarget]: testごとに独立し,callbackがappendするtargetの列.
    """
    return []


@pytest.fixture
def service_with_enqueue(
    repo: InMemoryBeatmapCommandRepository,
    freshness_policy: BeatmapFreshnessPolicy,
    enqueue_spy: list[BeatmapFetchTarget],
) -> BeatmapMirrorService:
    """enqueue要求を記録するcallback付きmirror serviceを提供する.

    Args:
        repo (InMemoryBeatmapCommandRepository): queryとfetch stateを共有するmemory repository.
        freshness_policy (BeatmapFreshnessPolicy): cached metadataのfreshnessを評価するpolicy.
        enqueue_spy (list[BeatmapFetchTarget]): callbackが要求targetをappendする観測用列.

    Returns:
        BeatmapMirrorService: enqueue_refreshがtargetをenqueue_spyへ記録するservice.
    """

    async def _spy(target: BeatmapFetchTarget) -> None:
        """要求されたfetch targetをtestの観測用列へ追加する.

        Args:
            target (BeatmapFetchTarget): serviceがbackground refreshに渡したtarget.

        Returns:
            None: targetをenqueue_spyへ記録し,値を返さずに完了する.
        """
        enqueue_spy.append(target)

    return BeatmapMirrorService(
        repository=repo,
        eligibility_service=BeatmapEligibilityService(),
        freshness_policy=freshness_policy,
        enqueue_refresh=_spy,
    )


# ---------------------------------------------------------------------------
# Tests: enqueue refresh on resolve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_beatmap_id_enqueues_metadata_fetch(
    service_with_enqueue: BeatmapMirrorService,
    enqueue_spy: list[BeatmapFetchTarget],
) -> None:
    """未保存Beatmap IDの解決がmetadata fetchをenqueueする契約を検証する.

    cache missのIDを解決し,callbackにMETADATA_BY_BEATMAP_ID targetが1件だけ記録され,
    target keyがID文字列になることを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): enqueue callback付きservice fixture.
        enqueue_spy (list[BeatmapFetchTarget]): callbackが受け取ったtargetを観測する列.

    Returns:
        None: 未保存ID用metadata fetch targetのenqueueを検証して完了する.
    """
    _ = await service_with_enqueue.resolve_by_beatmap_id(999)

    assert len(enqueue_spy) == 1
    target = enqueue_spy[0]
    assert target.kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID
    assert target.target_key == "999"


@pytest.mark.asyncio
async def test_unknown_beatmapset_id_enqueues_metadata_fetch(
    service_with_enqueue: BeatmapMirrorService,
    enqueue_spy: list[BeatmapFetchTarget],
) -> None:
    """未保存Beatmapset IDの解決がmetadata fetchをenqueueする契約を検証する.

    cache missのset IDを解決し,callbackにMETADATA_BY_BEATMAPSET_ID targetが1件だけ記録され,
    target keyがID文字列になることを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): enqueue callback付きservice fixture.
        enqueue_spy (list[BeatmapFetchTarget]): callbackが受け取ったtargetを観測する列.

    Returns:
        None: 未保存set ID用metadata fetch targetのenqueueを検証して完了する.
    """
    _ = await service_with_enqueue.resolve_by_beatmapset_id(999)

    assert len(enqueue_spy) == 1
    target = enqueue_spy[0]
    assert target.kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID
    assert target.target_key == "999"


@pytest.mark.asyncio
async def test_unknown_checksum_enqueues_metadata_fetch(
    service_with_enqueue: BeatmapMirrorService,
    enqueue_spy: list[BeatmapFetchTarget],
) -> None:
    """未保存MD5 checksumの解決がmetadata fetchをenqueueする契約を検証する.

    cache missのchecksumを解決し,callbackにMETADATA_BY_CHECKSUM targetが1件だけ記録され,
    target keyが検索値と一致することを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): enqueue callback付きservice fixture.
        enqueue_spy (list[BeatmapFetchTarget]): callbackが受け取ったtargetを観測する列.

    Returns:
        None: 未保存checksum用metadata fetch targetのenqueueを検証して完了する.
    """
    _ = await service_with_enqueue.resolve_by_checksum(_ALT_CHECKSUM)

    assert len(enqueue_spy) == 1
    target = enqueue_spy[0]
    assert target.kind is BeatmapFetchTargetKind.METADATA_BY_CHECKSUM
    assert target.target_key == _ALT_CHECKSUM


@pytest.mark.asyncio
async def test_stale_beatmap_enqueues_metadata_refresh(
    service_with_enqueue: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
    enqueue_spy: list[BeatmapFetchTarget],
) -> None:
    """期限切れbeatmapの解決が通常refresh targetをenqueueする契約を検証する.

    next_refresh_atを過去にしたsnapshotを解決し,METADATA_BY_BEATMAP_ID targetが1件記録され,
    target keyがbeatmap IDでforce_refreshがFalseになることを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): enqueue callback付きservice fixture.
        repo (InMemoryBeatmapCommandRepository): 期限切れsnapshotを保存するrepository fixture.
        enqueue_spy (list[BeatmapFetchTarget]): callbackが受け取ったtargetを観測する列.

    Returns:
        None: stale metadata用の通常refresh enqueueを検証して完了する.
    """
    beatmap = _make_beatmap(
        last_fetched_at=_NOW - _THIRTY_DAYS - _ONE_HOUR,
        next_refresh_at=_NOW - _ONE_HOUR,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    _ = await service_with_enqueue.resolve_by_beatmap_id(_BEATMAP_ID)

    assert len(enqueue_spy) == 1
    target = enqueue_spy[0]
    assert target.kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID
    assert target.target_key == str(_BEATMAP_ID)
    assert target.force_refresh is False


@pytest.mark.asyncio
async def test_force_refresh_enqueues_metadata_fetch(
    service_with_enqueue: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
    enqueue_spy: list[BeatmapFetchTarget],
) -> None:
    """force_refresh指定が新鮮なbeatmapの強制metadata fetchをenqueueする契約を検証する.

    refresh期限前のsnapshotをforce_refresh付きで解決し,METADATA_BY_BEATMAP_ID targetが
    1件記録され,target keyがbeatmap IDでforce_refreshがTrueになることを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): enqueue callback付きservice fixture.
        repo (InMemoryBeatmapCommandRepository): 新鮮なsnapshotを保存するrepository fixture.
        enqueue_spy (list[BeatmapFetchTarget]): callbackが受け取ったtargetを観測する列.

    Returns:
        None: force_refresh付きmetadata fetch targetのenqueueを検証して完了する.
    """
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    _ = await service_with_enqueue.resolve_by_beatmap_id(
        _BEATMAP_ID,
        options=BeatmapResolveOptions(force_refresh=True),
    )

    assert len(enqueue_spy) == 1
    target = enqueue_spy[0]
    assert target.kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID
    assert target.target_key == str(_BEATMAP_ID)
    assert target.force_refresh is True


@pytest.mark.asyncio
async def test_fresh_beatmap_does_not_enqueue(
    service_with_enqueue: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
    enqueue_spy: list[BeatmapFetchTarget],
) -> None:
    """新鮮で追加要件のないbeatmapがrefreshをenqueueしない契約を検証する.

    refresh期限前のsnapshotを通常optionで解決し,callbackのtarget列が空のままになることを
    確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): enqueue callback付きservice fixture.
        repo (InMemoryBeatmapCommandRepository): 新鮮なsnapshotを保存するrepository fixture.
        enqueue_spy (list[BeatmapFetchTarget]): callbackが受け取ったtargetを観測する列.

    Returns:
        None: fresh cacheにbackground fetch要求がないことを検証して完了する.
    """
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    _ = await service_with_enqueue.resolve_by_beatmap_id(_BEATMAP_ID)

    assert len(enqueue_spy) == 0


@pytest.mark.asyncio
async def test_require_osu_file_missing_enqueues_file_fetch(
    service_with_enqueue: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
    enqueue_spy: list[BeatmapFetchTarget],
) -> None:
    """欠落osu fileを必須にした解決がfile fetchをenqueueする契約を検証する.

    file_stateがMISSINGのsnapshotをrequire_osu_file付きで解決し,記録されたtargetのうち
    file fetchが1件でbeatmap IDを持つことを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): enqueue callback付きservice fixture.
        repo (InMemoryBeatmapCommandRepository): file欠落snapshotを保存するrepository fixture.
        enqueue_spy (list[BeatmapFetchTarget]): callbackが受け取ったtargetを観測する列.

    Returns:
        None: 必須fileを取得するbackground fetch要求を検証して完了する.
    """
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
        file_state=BeatmapFileState.MISSING,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    _ = await service_with_enqueue.resolve_by_beatmap_id(
        _BEATMAP_ID,
        options=BeatmapResolveOptions(require_osu_file=True),
    )

    file_targets = [t for t in enqueue_spy if t.is_file_fetch]
    assert len(file_targets) == 1
    assert file_targets[0].target_key == str(_BEATMAP_ID)


@pytest.mark.asyncio
async def test_require_osu_file_available_does_not_enqueue(
    service_with_enqueue: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
    enqueue_spy: list[BeatmapFetchTarget],
) -> None:
    """利用可能なosu fileを必須にしてもfile fetchをenqueueしない契約を検証する.

    file_stateがAVAILABLEのsnapshotをrequire_osu_file付きで解決し,記録targetにfile fetchが
    1件もないことを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): enqueue callback付きservice fixture.
        repo (InMemoryBeatmapCommandRepository): file利用可能snapshotを保存するrepository fixture.
        enqueue_spy (list[BeatmapFetchTarget]): callbackが受け取ったtargetを観測する列.

    Returns:
        None: 既存fileの再取得要求がないことを検証して完了する.
    """
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
        file_state=BeatmapFileState.AVAILABLE,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    _ = await service_with_enqueue.resolve_by_beatmap_id(
        _BEATMAP_ID,
        options=BeatmapResolveOptions(require_osu_file=True),
    )

    file_targets = [t for t in enqueue_spy if t.is_file_fetch]
    assert len(file_targets) == 0


@pytest.mark.asyncio
async def test_unknown_beatmap_with_require_osu_enqueues_both(
    service_with_enqueue: BeatmapMirrorService,
    enqueue_spy: list[BeatmapFetchTarget],
) -> None:
    """未知beatmapでosu fileを必須にするとmetadata/file両方をenqueueする契約を検証する.

    cache missのIDをrequire_osu_file付きで解決し,METADATA_BY_BEATMAP_IDとFILE_BY_BEATMAP_IDが
    各1件で,どちらも同じID文字列をtarget keyに持つことを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): enqueue callback付きservice fixture.
        enqueue_spy (list[BeatmapFetchTarget]): callbackが受け取ったtargetを観測する列.

    Returns:
        None: metadata/file fetch双方のenqueueを検証して完了する.
    """
    _ = await service_with_enqueue.resolve_by_beatmap_id(
        999,
        options=BeatmapResolveOptions(require_osu_file=True),
    )

    assert len(enqueue_spy) == 2
    types = {target.kind for target in enqueue_spy}
    assert types == {
        BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID,
        BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID,
    }
    for t in enqueue_spy:
        assert t.target_key == "999"


# ---------------------------------------------------------------------------
# Tests: bounded wait
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bounded_wait_completes_when_data_arrives(
    service_with_enqueue: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """Bounded waitが待機中に保存されたbeatmapを返す契約を検証する.

    短時間後にsnapshotを保存するtaskと5秒のwait timeoutで未知IDを解決し,timeout前に
    beatmapとFRESH状態を返すことを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): bounded waitを実行するservice fixture.
        repo (InMemoryBeatmapCommandRepository): 後からsnapshotを保存するrepository fixture.

    Returns:
        None: 到着したbeatmapをbounded waitが返すことを検証して完了する.
    """
    beatmap_id = 999

    async def populate() -> None:
        """短い待機後に対象beatmap snapshotを共有repositoryへ保存する.

        Returns:
            None: bounded waitのpoll中にfreshなbeatmapsetを保存して完了する.
        """
        await asyncio.sleep(0.02)
        beatmap = _make_beatmap(
            beatmap_id=beatmap_id,
            last_fetched_at=_NOW,
            next_refresh_at=_NOW + _THIRTY_DAYS,
        )
        beatmapset = _make_beatmapset(beatmaps=(beatmap,), last_fetched_at=_NOW)
        await repo.save_beatmapset_snapshot(beatmapset)

    task = asyncio.create_task(populate())

    result = await service_with_enqueue.resolve_by_beatmap_id(
        beatmap_id,
        options=BeatmapResolveOptions(wait_timeout_seconds=5.0),
    )

    await task

    assert result.beatmap is not None
    assert result.beatmap.id == beatmap_id
    assert result.metadata_status is BeatmapFetchState.FRESH


@pytest.mark.asyncio
async def test_bounded_wait_returns_pending_on_timeout(
    service_with_enqueue: BeatmapMirrorService,
) -> None:
    """Bounded waitがtimeoutまでdataを得られない場合にpendingを返す契約を検証する.

    snapshotを保存せず極短いwait timeoutで未知IDを解決し,entityなしのPENDING_FETCHと
    unsolicited理由を返すことを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): timeout付き解決を実行するservice fixture.

    Returns:
        None: timeout後のpending unavailable結果を検証して完了する.
    """
    result = await service_with_enqueue.resolve_by_beatmap_id(
        999,
        options=BeatmapResolveOptions(wait_timeout_seconds=0.001),
    )

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.reason == "unsolicited"


@pytest.mark.asyncio
async def test_bounded_wait_beatmapset_completes_when_data_arrives(
    service_with_enqueue: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """Bounded waitが待機中に保存されたbeatmapsetを返す契約を検証する.

    短時間後にset snapshotを保存するtaskと5秒のwait timeoutで未知set IDを解決し,timeout前に
    beatmapsetとFRESH状態を返すことを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): bounded waitを実行するservice fixture.
        repo (InMemoryBeatmapCommandRepository): 後からset snapshotを保存するrepository fixture.

    Returns:
        None: 到着したbeatmapsetをbounded waitが返すことを検証して完了する.
    """
    beatmapset_id = 999

    async def populate() -> None:
        """短い待機後に対象beatmapset snapshotを共有repositoryへ保存する.

        Returns:
            None: bounded waitのpoll中にfreshなbeatmapsetを保存して完了する.
        """
        await asyncio.sleep(0.02)
        beatmap = _make_beatmap(
            beatmap_id=beatmapset_id,
            beatmapset_id=beatmapset_id,
            last_fetched_at=_NOW,
            next_refresh_at=_NOW + _THIRTY_DAYS,
        )
        beatmapset = _make_beatmapset(
            beatmapset_id=beatmapset_id,
            beatmaps=(beatmap,),
            last_fetched_at=_NOW,
            next_refresh_at=_NOW + _THIRTY_DAYS,
        )
        await repo.save_beatmapset_snapshot(beatmapset)

    task = asyncio.create_task(populate())

    result = await service_with_enqueue.resolve_by_beatmapset_id(
        beatmapset_id,
        options=BeatmapResolveOptions(wait_timeout_seconds=5.0),
    )

    await task

    assert result.beatmapset is not None
    assert result.beatmapset.id == beatmapset_id
    assert result.metadata_status is BeatmapFetchState.FRESH


@pytest.mark.asyncio
async def test_bounded_wait_checksum_completes_when_data_arrives(
    service_with_enqueue: BeatmapMirrorService,
    repo: InMemoryBeatmapCommandRepository,
) -> None:
    """Bounded waitが待機中に保存されたchecksum一致beatmapを返す契約を検証する.

    短時間後にchecksum一致snapshotを保存するtaskと5秒のwait timeoutで解決し,timeout前に
    beatmapと同じchecksumを返すことを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): checksumのbounded waitを実行する
            service fixture.
        repo (InMemoryBeatmapCommandRepository): 後からchecksum一致snapshotを保存する
            repository fixture.

    Returns:
        None: 到着したchecksum一致beatmapをbounded waitが返すことを検証して完了する.
    """
    checksum = _ALT_CHECKSUM

    async def populate() -> None:
        """短い待機後にchecksum一致beatmap snapshotを共有repositoryへ保存する.

        Returns:
            None: bounded waitのpoll中にchecksum検索可能なsnapshotを保存して完了する.
        """
        await asyncio.sleep(0.02)
        beatmap = _make_beatmap(
            beatmap_id=999,
            checksum_md5=checksum,
            last_fetched_at=_NOW,
            next_refresh_at=_NOW + _THIRTY_DAYS,
        )
        beatmapset = _make_beatmapset(beatmapset_id=1000, beatmaps=(beatmap,))
        await repo.save_beatmapset_snapshot(beatmapset)

    task = asyncio.create_task(populate())

    result = await service_with_enqueue.resolve_by_checksum(
        checksum,
        options=BeatmapResolveOptions(wait_timeout_seconds=5.0),
    )

    await task

    assert result.beatmap is not None
    assert result.beatmap.checksum_md5 == checksum


@pytest.mark.asyncio
async def test_bounded_wait_beatmapset_returns_pending_on_timeout(
    service_with_enqueue: BeatmapMirrorService,
) -> None:
    """beatmapsetのbounded waitがtimeout時にpendingを返す契約を検証する.

    set snapshotを保存せず極短いwait timeoutで未知IDを解決し,entityなしのPENDING_FETCHと
    unsolicited理由を返すことを確認する.

    Args:
        service_with_enqueue (BeatmapMirrorService): setのtimeout付き解決を実行するservice fixture.

    Returns:
        None: timeout後のpending set結果を検証して完了する.
    """
    result = await service_with_enqueue.resolve_by_beatmapset_id(
        999,
        options=BeatmapResolveOptions(wait_timeout_seconds=0.001),
    )

    assert result.beatmapset is None
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.reason == "unsolicited"
