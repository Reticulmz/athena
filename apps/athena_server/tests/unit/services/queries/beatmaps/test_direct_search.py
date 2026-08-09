"""osu!direct検索queryのunit testを定義する."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.support.beatmaps import InMemoryBeatmapStore

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
    DirectPointLookupRequest,
    DirectPointLookupTargetKind,
    DirectSearchBackendResult,
    DirectSearchCandidate,
    DirectSearchListing,
    DirectSearchRequest,
)
from osu_server.domain.compatibility.stable.direct import STABLE_DIRECT_MORE_RESULTS_SENTINEL
from osu_server.services.queries.beatmaps.direct_search import (
    DirectPointLookupQuery,
    DirectSearchQuery,
)
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)


class DirectSearchBackendStub:
    """固定候補を返し受け取った検索requestを記録するbackend test double.

    Attributes:
        result (DirectSearchBackendResult): search呼び出しで返す固定候補結果.
        search_requests (list[DirectSearchRequest]): searchへ渡されたrequestの記録.
    """

    result: DirectSearchBackendResult
    search_requests: list[DirectSearchRequest]

    def __init__(self, result: DirectSearchBackendResult) -> None:
        """固定の検索結果を持つbackend stubを初期化する.

        Args:
            result (DirectSearchBackendResult): 各search呼び出しで返す候補結果.
        """
        self.result = result
        self.search_requests = []

    async def search(self, request: DirectSearchRequest) -> DirectSearchBackendResult:
        """受信requestを記録して固定候補結果を返す.

        Args:
            request (DirectSearchRequest): query use-caseから渡された検索条件.

        Returns:
            DirectSearchBackendResult: 初期化時に指定した候補結果.
        """
        self.search_requests.append(request)
        return self.result

    async def validate(self) -> None:
        """Protocol互換のvalidationを何もせず完了する.

        Returns:
            None: test backendが常に利用可能であることを示して完了する.
        """


class DirectPointLookupResolverStub:
    """Direct point lookup queryがresolverへ渡すtargetとoptionsを記録するtest double.

    Attributes:
        calls (list[tuple[str, int | str, BeatmapResolveOptions | None]]):
            resolver method名, target値, optionsの呼出履歴.
    """

    calls: list[tuple[str, int | str, BeatmapResolveOptions | None]]

    def __init__(self) -> None:
        """空の呼出履歴を持つresolver stubを初期化する."""
        self.calls = []

    async def resolve_by_beatmapset_id(
        self,
        beatmapset_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapSetResolveResult:
        """Beatmapset ID lookupを記録して未解決結果を返す.

        Args:
            beatmapset_id (int): direct point lookupから渡されたbeatmapset ID.
            options (BeatmapResolveOptions | None): direct point lookupが設定した解決option.

        Returns:
            BeatmapSetResolveResult: metadata pendingの空結果.
        """
        self.calls.append(("beatmapset_id", beatmapset_id, options))
        return _empty_set_result()

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Beatmap ID lookupを記録して未解決結果を返す.

        Args:
            beatmap_id (int): direct point lookupから渡されたbeatmap ID.
            options (BeatmapResolveOptions | None): direct point lookupが設定した解決option.

        Returns:
            BeatmapResolveResult: metadata pendingの空結果.
        """
        self.calls.append(("beatmap_id", beatmap_id, options))
        return _empty_beatmap_result()

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Checksum lookupを記録して未解決結果を返す.

        Args:
            checksum_md5 (str): direct point lookupから渡されたMD5 checksum.
            options (BeatmapResolveOptions | None): direct point lookupが設定した解決option.

        Returns:
            BeatmapResolveResult: metadata pendingの空結果.
        """
        self.calls.append(("checksum", checksum_md5, options))
        return _empty_beatmap_result()


async def test_hydrates_candidates_in_backend_order_for_special_listing() -> None:
    """Special listingの候補をmetadataからbackend順のstable-ready setへhydrateする契約を検証する.

    `Top Rated`として解析済みのrequestを渡し、backend候補のID順を保ったmetadataだけが結果へ
    返ることを確認する.

    Returns:
        None: backend入力とstable-ready metadata列を検証して完了する.
    """
    first = _beatmapset(10)
    second = _beatmapset(20)
    store = InMemoryBeatmapStore()
    await store.save_beatmapset_snapshot(first)
    await store.save_beatmapset_snapshot(second)
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=20, score=2.0),
                DirectSearchCandidate(beatmapset_id=10, score=1.0),
            ),
            has_more=False,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="",
        listing=DirectSearchListing.TOP_RATED,
    )

    result = await DirectSearchQuery(store.query_repository, backend).execute(request)

    assert backend.search_requests == [request]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [20, 10]
    assert result.stable_result_count == 2


async def test_excludes_unusable_metadata_without_false_more_results_sentinel() -> None:
    """欠損又は利用不能なmetadataを除外した不完全pageにmore-results sentinelを出さない.

    childless, inactive, not submittedの候補を混ぜ、usableなsetだけが返り、backendのhas_moreが
    Trueでも返却件数がpage size未満なら実件数を返すことを確認する.

    Returns:
        None: metadata除外と実件数を検証して完了する.
    """
    store = InMemoryBeatmapStore()
    await store.save_beatmapset_snapshot(_beatmapset(10))
    await store.save_beatmapset_snapshot(_beatmapset(20, beatmaps=()))
    await store.save_beatmapset_snapshot(_beatmapset(30, status=BeatmapRankStatus.GRAVEYARD))
    await store.save_beatmapset_snapshot(_beatmapset(40, status=BeatmapRankStatus.NOT_SUBMITTED))
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=tuple(
                DirectSearchCandidate(beatmapset_id=beatmapset_id, score=0.0)
                for beatmapset_id in (999, 20, 30, 40, 10)
            ),
            has_more=True,
        )
    )

    result = await DirectSearchQuery(store.query_repository, backend).execute(
        DirectSearchRequest(authenticated_user_id=1, query_text="Camellia")
    )

    assert [beatmapset.id for beatmapset in result.beatmapsets] == [10]
    assert result.stable_result_count == 1


async def test_uses_more_results_sentinel_for_full_hydrated_page() -> None:
    """100件のstable-ready結果と次page候補がある場合に`101` sentinelを返す契約を検証する.

    backendが次pageありを示し、候補全件をmetadataからhydrateできた場合だけstable互換の
    count sentinelを返すことを確認する.

    Returns:
        None: full pageのstable count sentinelを検証して完了する.
    """
    store = InMemoryBeatmapStore()
    candidates = tuple(
        DirectSearchCandidate(beatmapset_id=beatmapset_id, score=0.0)
        for beatmapset_id in range(1, 101)
    )
    for candidate in candidates:
        await store.save_beatmapset_snapshot(_beatmapset(candidate.beatmapset_id))
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(candidates=candidates, has_more=True)
    )

    result = await DirectSearchQuery(store.query_repository, backend).execute(
        DirectSearchRequest(authenticated_user_id=1, query_text="Camellia")
    )

    assert len(result.beatmapsets) == 100
    assert result.stable_result_count == STABLE_DIRECT_MORE_RESULTS_SENTINEL


async def test_returns_empty_result_without_triggering_metadata_fetch() -> None:
    """Free-text missがbackend候補なしの空結果となりmetadata fetchを起動しない契約を検証する.

    query use-caseがread-only backendとrepositoryだけで完結するため、空候補時にupstream
    metadata取得のための追加collaboratorを必要としないことを確認する.

    Returns:
        None: 空のstable-ready結果を検証して完了する.
    """
    backend = DirectSearchBackendStub(DirectSearchBackendResult(candidates=(), has_more=False))
    request = DirectSearchRequest(authenticated_user_id=1, query_text="not in catalog")

    result = await DirectSearchQuery(InMemoryBeatmapStore().query_repository, backend).execute(
        request
    )

    assert backend.search_requests == [request]
    assert result.beatmapsets == ()
    assert result.stable_result_count == 0


async def test_point_lookup_resolves_known_set_by_supported_targets() -> None:
    """Point lookupがset ID,beatmap ID,checksum,link targetで同じsetを返す契約を検証する.

    保存済みmetadataに対して4種類のdirect point lookup requestを実行し、いずれも同じ
    stable-ready beatmapsetを返すことを確認する.

    Returns:
        None: target種別ごとのmetadata解決を検証して完了する.
    """
    store = InMemoryBeatmapStore()
    beatmapset = _beatmapset(10)
    await store.save_beatmapset_snapshot(beatmapset)
    query = _point_lookup_query(store)

    requests = (
        DirectPointLookupRequest.beatmapset_id(
            authenticated_user_id=1,
            beatmapset_id=beatmapset.id,
        ),
        DirectPointLookupRequest.beatmap_id(
            authenticated_user_id=1,
            beatmap_id=beatmapset.beatmaps[0].id,
        ),
        DirectPointLookupRequest.checksum(
            authenticated_user_id=1,
            checksum_md5=beatmapset.beatmaps[0].checksum_md5,
        ),
        DirectPointLookupRequest.beatmap_link(
            authenticated_user_id=1,
            beatmapset_id=beatmapset.id,
            beatmap_id=beatmapset.beatmaps[0].id,
        ),
    )

    results = [await query.execute(request) for request in requests]

    assert [result.beatmapset.id if result.beatmapset else None for result in results] == [
        beatmapset.id,
        beatmapset.id,
        beatmapset.id,
        beatmapset.id,
    ]
    assert requests[-1].target_kind is DirectPointLookupTargetKind.BEATMAP_ID


async def test_point_lookup_omits_unusable_metadata() -> None:
    """Point lookupがchildless,inactive,not submitted metadataを空結果へ変換する契約を検証する.

    cacheにmetadataが存在してもstable direct rowへ安全に変換できないsetは返さないことを確認する.

    Returns:
        None: unusable metadataの除外を検証して完了する.
    """
    store = InMemoryBeatmapStore()
    await store.save_beatmapset_snapshot(_beatmapset(20, beatmaps=()))
    await store.save_beatmapset_snapshot(_beatmapset(30, status=BeatmapRankStatus.GRAVEYARD))
    await store.save_beatmapset_snapshot(_beatmapset(40, status=BeatmapRankStatus.NOT_SUBMITTED))
    query = _point_lookup_query(store)

    results = [
        await query.execute(
            DirectPointLookupRequest.beatmapset_id(
                authenticated_user_id=1,
                beatmapset_id=beatmapset_id,
            )
        )
        for beatmapset_id in (20, 30, 40)
    ]

    assert [result.beatmapset for result in results] == [None, None, None]


async def test_point_lookup_miss_enqueues_metadata_and_returns_empty_after_timeout() -> None:
    """Point lookup missがmetadata fetchを要求し、bounded wait後に空結果を返す契約を検証する.

    未保存set IDを極短いwaitで解決し、background fetch targetが残り、stable formatter向けには
    beatmapsetなしの結果になることを確認する.

    Returns:
        None: miss時のfetch要求とempty resultを検証して完了する.
    """
    enqueue_spy: list[BeatmapFetchTarget] = []
    query = _point_lookup_query(
        InMemoryBeatmapStore(),
        enqueue_spy=enqueue_spy,
        bounded_wait_seconds=0.001,
    )

    result = await query.execute(
        DirectPointLookupRequest.beatmapset_id(
            authenticated_user_id=1,
            beatmapset_id=999,
        )
    )

    assert result.beatmapset is None
    assert len(enqueue_spy) == 1
    assert enqueue_spy[0].kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID
    assert enqueue_spy[0].target_key == "999"


async def test_point_lookup_default_wait_is_five_seconds() -> None:
    """Direct point lookupの既定bounded waitが5秒である契約を検証する.

    resolver stubに渡されたBeatmapResolveOptionsを観測し、設定未指定時にdirect用default timeoutを
    使うことを確認する.

    Returns:
        None: default bounded wait秒数を検証して完了する.
    """
    resolver = DirectPointLookupResolverStub()
    query = DirectPointLookupQuery(resolver)

    result = await query.execute(
        DirectPointLookupRequest.beatmapset_id(
            authenticated_user_id=1,
            beatmapset_id=999,
        )
    )

    assert result.beatmapset is None
    assert resolver.calls[0][0] == "beatmapset_id"
    options = resolver.calls[0][2]
    assert options is not None
    assert options.wait_timeout_seconds == 5.0
    assert options.require_osu_file is False


def _beatmapset(
    beatmapset_id: int,
    *,
    status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    beatmaps: tuple[Beatmap, ...] | None = None,
) -> BeatmapSet:
    """Direct searchのmetadata hydrationに使うbeatmapsetを作る.

    Args:
        beatmapset_id (int): 作るbeatmapsetの識別子.
        status (BeatmapRankStatus): setとdefault childに設定する公開status.
        beatmaps (tuple[Beatmap, ...] | None): 明示するchild列. Noneならusable childを1件作る.

    Returns:
        BeatmapSet: 指定statusとchild構成を持つread-only metadata.
    """
    return BeatmapSet(
        id=beatmapset_id,
        artist="Camellia",
        title=f"Title {beatmapset_id}",
        creator="Mapper",
        artist_unicode=None,
        title_unicode=None,
        official_status=status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=_beatmaps_for(beatmapset_id, status) if beatmaps is None else beatmaps,
        last_fetched_at=datetime.now(UTC),
        next_refresh_at=None,
    )


def _point_lookup_query(
    store: InMemoryBeatmapStore,
    *,
    enqueue_spy: list[BeatmapFetchTarget] | None = None,
    bounded_wait_seconds: float = 5.0,
) -> DirectPointLookupQuery:
    """Direct point lookup queryをmemory store上に作る.

    Args:
        store (InMemoryBeatmapStore): metadata repositoryを提供するin-memory store.
        enqueue_spy (list[BeatmapFetchTarget] | None): fetch targetを記録するoptionalな列.
        bounded_wait_seconds (float): direct point lookupへ設定するwait上限秒数.

    Returns:
        DirectPointLookupQuery: Beatmap Mirror resolverを使うdirect point lookup query.
    """

    async def _enqueue(target: BeatmapFetchTarget) -> None:
        """Fetch targetを任意の観測用列へ記録する.

        Args:
            target (BeatmapFetchTarget): Beatmap Mirror serviceから要求されたfetch target.

        Returns:
            None: targetを記録して値を返さずに完了する.
        """
        if enqueue_spy is not None:
            enqueue_spy.append(target)

    resolver = BeatmapMirrorService(
        repository=store.query_repository,
        eligibility_service=BeatmapEligibilityService(),
        freshness_policy=BeatmapFreshnessPolicy(
            ranked_refresh_interval=timedelta(days=30),
            pending_refresh_interval=timedelta(days=1),
            graveyard_refresh_interval=timedelta(days=30),
            mirror_refresh_interval=timedelta(days=1),
        ),
        enqueue_refresh=_enqueue if enqueue_spy is not None else None,
    )
    return DirectPointLookupQuery(resolver, bounded_wait_seconds=bounded_wait_seconds)


def _empty_set_result() -> BeatmapSetResolveResult:
    """Resolver stub用の未解決set結果を作る.

    Returns:
        BeatmapSetResolveResult: pending metadata状態の空set結果.
    """
    return BeatmapSetResolveResult(
        beatmapset=None,
        metadata_status=BeatmapFetchState.PENDING_FETCH,
        source=None,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="pending_fetch",
    )


def _empty_beatmap_result() -> BeatmapResolveResult:
    """Resolver stub用の未解決beatmap結果を作る.

    Returns:
        BeatmapResolveResult: pending metadata状態の空beatmap結果.
    """
    return BeatmapResolveResult(
        beatmap=None,
        beatmapset=None,
        eligibility=None,
        metadata_status=BeatmapFetchState.PENDING_FETCH,
        file_status=BeatmapFileState.MISSING,
        source=None,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="pending_fetch",
    )


def _beatmaps_for(beatmapset_id: int, status: BeatmapRankStatus) -> tuple[Beatmap, ...]:
    """指定setのusable child beatmapを1件作る.

    Args:
        beatmapset_id (int): 所属beatmapsetの識別子.
        status (BeatmapRankStatus): childに設定する公開status.

    Returns:
        tuple[Beatmap, ...]: 指定setに属する単一child beatmap列.
    """
    return (
        Beatmap(
            id=beatmapset_id * 10,
            beatmapset_id=beatmapset_id,
            checksum_md5=f"{beatmapset_id:032x}",
            mode=BeatmapMode.OSU,
            version="Normal",
            total_length=120,
            hit_length=100,
            max_combo=500,
            bpm=180.0,
            cs=4.0,
            od=8.0,
            ar=9.0,
            hp=6.0,
            difficulty_rating=5.0,
            official_status=status,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            local_status_override=None,
            metadata_fetch_state=BeatmapFetchState.FRESH,
            file_state=BeatmapFileState.MISSING,
            file_attachment=None,
            last_fetched_at=datetime.now(UTC),
            next_refresh_at=None,
        ),
    )
