"""osu!direct検索queryのunit testを定義する."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from structlog.testing import capture_logs
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
    DirectCoverageKind,
    DirectCoverageRecord,
    DirectCoverageStatusScope,
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
    DirectSearchUpstreamResult,
)
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from osu_server.domain.beatmaps import BeatmapFetchRecord, BeatmapFileAttachment


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


class DirectSearchUpstreamProviderStub:
    """固定のexternal search候補を返しrequestを記録するtest double.

    Attributes:
        result (DirectSearchUpstreamResult): search呼び出しで返す候補結果.
        delay_seconds (float): search応答前に待機する秒数.
        requests (list[DirectSearchRequest]): searchへ渡されたrequestの記録.
    """

    result: DirectSearchUpstreamResult
    delay_seconds: float
    requests: list[DirectSearchRequest]

    def __init__(
        self,
        result: DirectSearchUpstreamResult,
        *,
        delay_seconds: float = 0.0,
    ) -> None:
        """固定結果と任意delayを持つupstream provider stubを初期化する.

        Args:
            result (DirectSearchUpstreamResult): 各search呼び出しで返すexternal候補.
            delay_seconds (float): timeout検証用の応答delay秒数.
        """
        self.result = result
        self.delay_seconds = delay_seconds
        self.requests = []

    async def search(self, request: DirectSearchRequest) -> DirectSearchUpstreamResult:
        """受信requestを記録し固定external候補を返す.

        Args:
            request (DirectSearchRequest): query use-caseから渡された検索条件.

        Returns:
            DirectSearchUpstreamResult: 初期化時に指定したexternal候補.
        """
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return self.result


class FailingDirectSearchUpstreamProviderStub:
    """External search失敗を返すtest double.

    Attributes:
        requests (list[DirectSearchRequest]): searchへ渡されたrequestの記録.
    """

    requests: list[DirectSearchRequest]

    def __init__(self) -> None:
        """空のrequest記録を持つ失敗providerを初期化する."""
        self.requests = []

    async def search(self, request: DirectSearchRequest) -> DirectSearchUpstreamResult:
        """受信requestを記録して外部検索失敗を送出する.

        Args:
            request (DirectSearchRequest): query use-caseから渡された検索条件.

        Returns:
            DirectSearchUpstreamResult: 常に例外を送出するため返らない.

        Raises:
            RuntimeError: upstream全失敗時のdegrade動作を検証するため常に発生する.
        """
        self.requests.append(request)
        raise RuntimeError("upstream unavailable")


class BatchBeatmapQueryRepositoryStub:
    """Direct search hydrateのrepository呼び出し形を記録するtest double.

    Attributes:
        beatmapsets_by_id (dict[int, BeatmapSet]): 返却可能なbeatmapset.
        get_beatmapset_calls (list[int]): 単体hydrateで呼ばれたID列.
        list_beatmapsets_by_ids_calls (list[tuple[int, ...]]): batch hydrateで呼ばれたID列.
    """

    beatmapsets_by_id: dict[int, BeatmapSet]
    get_beatmapset_calls: list[int]
    list_beatmapsets_by_ids_calls: list[tuple[int, ...]]

    def __init__(self, beatmapsets: tuple[BeatmapSet, ...]) -> None:
        """返却するbeatmapset列を保持する.

        Args:
            beatmapsets (tuple[BeatmapSet, ...]): repositoryから返せるbeatmapset列.
        """
        self.beatmapsets_by_id = {beatmapset.id: beatmapset for beatmapset in beatmapsets}
        self.get_beatmapset_calls = []
        self.list_beatmapsets_by_ids_calls = []

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """このtestで使わないbeatmap lookupを空で返す.

        Args:
            beatmap_id (int): 検索対象beatmap ID.

        Returns:
            Beatmap | None: 常にNone.
        """
        _ = beatmap_id
        return None

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """単体hydrate呼び出しを記録してbeatmapsetを返す.

        Args:
            beatmapset_id (int): 検索対象beatmapset ID.

        Returns:
            BeatmapSet | None: 登録済みbeatmapset. 未登録ならNone.
        """
        self.get_beatmapset_calls.append(beatmapset_id)
        return self.beatmapsets_by_id.get(beatmapset_id)

    async def list_beatmapsets_by_ids(
        self,
        beatmapset_ids: tuple[int, ...],
    ) -> tuple[BeatmapSet, ...]:
        """Batch hydrate呼び出しを記録して入力順のbeatmapset列を返す.

        Args:
            beatmapset_ids (tuple[int, ...]): 検索対象beatmapset ID列.

        Returns:
            tuple[BeatmapSet, ...]: 登録済みbeatmapsetだけを入力順で返す.
        """
        self.list_beatmapsets_by_ids_calls.append(beatmapset_ids)
        return tuple(
            beatmapset
            for beatmapset_id in beatmapset_ids
            if (beatmapset := self.beatmapsets_by_id.get(beatmapset_id)) is not None
        )

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """このtestで使わないchecksum lookupを空で返す.

        Args:
            checksum_md5 (str): 検索対象checksum.

        Returns:
            Beatmap | None: 常にNone.
        """
        _ = checksum_md5
        return None

    async def get_beatmap_by_filename_in_beatmapset(
        self,
        beatmapset_id: int,
        original_filename: str,
    ) -> Beatmap | None:
        """このtestで使わないfilename lookupを空で返す.

        Args:
            beatmapset_id (int): 検索対象beatmapset ID.
            original_filename (str): 検索対象filename.

        Returns:
            Beatmap | None: 常にNone.
        """
        _ = (beatmapset_id, original_filename)
        return None

    async def get_current_file_attachment(
        self,
        beatmap_id: int,
    ) -> BeatmapFileAttachment | None:
        """このtestで使わないattachment lookupを空で返す.

        Args:
            beatmap_id (int): 検索対象beatmap ID.

        Returns:
            BeatmapFileAttachment | None: 常にNone.
        """
        _ = beatmap_id
        return None

    async def get_fetch_state(
        self,
        target: BeatmapFetchTarget,
    ) -> BeatmapFetchRecord | None:
        """このtestで使わないfetch state lookupを空で返す.

        Args:
            target (BeatmapFetchTarget): 検索対象fetch target.

        Returns:
            BeatmapFetchRecord | None: 常にNone.
        """
        _ = target
        return None

    async def list_completed_direct_search_coverages(
        self,
        status_scopes: tuple[DirectCoverageStatusScope, ...],
        *,
        feed_sort_key: str,
        feed_window_key: str,
    ) -> tuple[DirectCoverageRecord, ...]:
        """このtestで使わないcoverage lookupを空で返す.

        Args:
            status_scopes (tuple[DirectCoverageStatusScope, ...]): 対象status scope列.
            feed_sort_key (str): feed coverage sort key.
            feed_window_key (str): feed coverage window key.

        Returns:
            tuple[DirectCoverageRecord, ...]: 常に空tuple.
        """
        _ = (status_scopes, feed_sort_key, feed_window_key)
        return ()


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

    childless, graveyard, not submittedの候補を混ぜ、directで表示可能なsetだけが返り、
    backendのhas_moreがTrueでも返却件数がpage size未満なら実件数を返すことを確認する.

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

    assert [beatmapset.id for beatmapset in result.beatmapsets] == [30, 10]
    assert result.stable_result_count == 2


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


async def test_direct_search_hydrates_backend_candidates_in_batch() -> None:
    """Full page候補hydrateが候補ごとのrepository lookupを使わない契約を検証する.

    100件候補を検索したときに単体hydrateではなくbatch hydrateが1回だけ使われることを確認する.

    Returns:
        None: direct search hydrateのN+1防止契約を検証して完了する.
    """
    beatmapsets = tuple(_beatmapset(beatmapset_id) for beatmapset_id in range(1, 101))
    repository = BatchBeatmapQueryRepositoryStub(beatmapsets)
    candidates = tuple(
        DirectSearchCandidate(beatmapset_id=beatmapset.id, score=0.0) for beatmapset in beatmapsets
    )
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(candidates=candidates, has_more=False)
    )

    with capture_logs() as logs:
        result = await DirectSearchQuery(repository, backend).execute(
            DirectSearchRequest(authenticated_user_id=1, query_text="Camellia")
        )

    assert [beatmapset.id for beatmapset in result.beatmapsets] == list(range(1, 101))
    assert repository.list_beatmapsets_by_ids_calls == [tuple(range(1, 101))]
    assert repository.get_beatmapset_calls == []
    event = next(log for log in logs if log["event"] == "osu_direct_search_query_completed")
    assert event["backend_candidate_count"] == 100
    assert event["hydrated_candidate_count"] == 100
    assert event["final_result_count"] == 100
    assert event["upstream_requested"] is True
    assert event["upstream_provider_configured"] is False
    assert event["upstream_succeeded"] is False
    assert isinstance(event["hydrate_ms"], float)


async def test_uses_more_results_sentinel_for_short_upstream_page_with_more() -> None:
    """短い外部検索pageでも次pageありなら`101` sentinelを返す契約を検証する.

    Hinamizawa aeris互換ではcount lineが`101`で本文が50行のpageがあるため、hydrate後の行数が
    page size未満でもupstreamのhas_moreをstable countへ保持する.

    Returns:
        None: short upstream pageのstable count sentinelを検証して完了する.
    """
    backend = DirectSearchBackendStub(DirectSearchBackendResult(candidates=(), has_more=False))
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=tuple(_beatmapset(beatmapset_id) for beatmapset_id in range(1, 51)),
            has_more=True,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Camellia",
        page=1,
        page_size=100,
    )

    result = await DirectSearchQuery(
        InMemoryBeatmapStore().query_repository,
        backend,
        upstream_provider=upstream,
    ).execute(request)

    assert upstream.requests == [request]
    assert len(result.beatmapsets) == 50
    assert result.stable_result_count == STABLE_DIRECT_MORE_RESULTS_SENTINEL


async def test_newest_search_does_not_stop_at_short_local_page_when_upstream_has_more() -> None:
    """Newestのlocal 48件pageをexternal最新候補で置き換えて`101` sentinelを返す契約を検証する.

    Stable `q=Newest&r=0&m=-1&p=0`でlocal catalogが48件しかhydrateできない条件でも,
    upstreamが次pageありを示す場合はlocalだけで打ち切らずupstreamの最新順を返すことを確認する.

    Returns:
        None: local不足pageのupstream優先順序とstable count sentinelを検証して完了する.
    """
    store = InMemoryBeatmapStore()
    local_ids = range(1, 49)
    for beatmapset_id in local_ids:
        await store.save_beatmapset_snapshot(_beatmapset(beatmapset_id))
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=tuple(
                DirectSearchCandidate(beatmapset_id=beatmapset_id, score=0.0)
                for beatmapset_id in local_ids
            ),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=tuple(_beatmapset(beatmapset_id) for beatmapset_id in range(49, 149)),
            has_more=True,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="",
        statuses=(BeatmapRankStatus.RANKED,),
        listing=DirectSearchListing.NEWEST,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
    ).execute(request)

    assert upstream.requests == [request]
    assert len(result.beatmapsets) == 100
    assert [beatmapset.id for beatmapset in result.beatmapsets[:3]] == [49, 50, 51]
    assert [beatmapset.id for beatmapset in result.beatmapsets[-3:]] == [146, 147, 148]
    assert result.stable_result_count == STABLE_DIRECT_MORE_RESULTS_SENTINEL


async def test_newest_search_prefers_upstream_when_local_page_is_full() -> None:
    """Newestのfull local pageでもexternal最新候補をresponse先頭へ出す契約を検証する.

    Stable `q=Newest&r=8&m=0&p=0`でlocal catalogが古い100件を返せる条件でも、初回refreshで
    upstreamが返したLoved最新順をresponseとして採用することを確認する.

    Returns:
        None: full local pageでupstream最新順がlocal候補に潰されないことを検証して完了する.
    """
    store = InMemoryBeatmapStore()
    local_ids = range(1, 101)
    for beatmapset_id in local_ids:
        await store.save_beatmapset_snapshot(
            _beatmapset(beatmapset_id, status=BeatmapRankStatus.LOVED)
        )
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=tuple(
                DirectSearchCandidate(beatmapset_id=beatmapset_id, score=0.0)
                for beatmapset_id in local_ids
            ),
            has_more=True,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=tuple(
                _beatmapset(beatmapset_id, status=BeatmapRankStatus.LOVED)
                for beatmapset_id in range(1001, 1101)
            ),
            has_more=True,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="",
        statuses=(BeatmapRankStatus.LOVED,),
        mode=BeatmapMode.OSU,
        listing=DirectSearchListing.NEWEST,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
    ).execute(request)

    assert upstream.requests == [request]
    assert [beatmapset.id for beatmapset in result.beatmapsets[:3]] == [1001, 1002, 1003]
    assert [beatmapset.id for beatmapset in result.beatmapsets[-3:]] == [1098, 1099, 1100]
    assert result.stable_result_count == STABLE_DIRECT_MORE_RESULTS_SENTINEL


async def test_newest_search_merges_upstream_and_local_without_duplicates() -> None:
    """Newestのexternal候補とlocal候補をID重複なしで統合する契約を検証する.

    Upstreamがlocalにも存在するbeatmapsetを返す条件で、upstream順を優先しつつlocalの残り候補を
    後ろへ補充し、同じbeatmapset IDが2回出ないことを確認する.

    Returns:
        None: Newest検索のupstream-first mergeと重複排除を検証して完了する.
    """
    store = InMemoryBeatmapStore()
    for beatmapset_id in (10, 20, 30):
        await store.save_beatmapset_snapshot(
            _beatmapset(beatmapset_id, status=BeatmapRankStatus.LOVED)
        )
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=10, score=3.0),
                DirectSearchCandidate(beatmapset_id=20, score=2.0),
                DirectSearchCandidate(beatmapset_id=30, score=1.0),
            ),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=(
                _beatmapset(20, status=BeatmapRankStatus.LOVED),
                _beatmapset(40, status=BeatmapRankStatus.LOVED),
            ),
            has_more=False,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="",
        statuses=(BeatmapRankStatus.LOVED,),
        page_size=4,
        listing=DirectSearchListing.NEWEST,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
    ).execute(request)

    assert upstream.requests == [request]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [20, 40, 10, 30]
    assert result.stable_result_count == 4


async def test_newest_search_respects_first_page_refresh_interval() -> None:
    """Newestはcoverage保存済みでもpage 0 refresh間隔でexternal検索を抑制する.

    Stable `q=Newest&r=8&m=0&p=0` は最新feedの表示なので、前回のupstream coverage保存後でも
    短時間の再検索ではupstreamを再実行せず、interval経過後は再実行することを確認する.

    Returns:
        None: coverage保存後のNewest page 0でupstream検索がintervalに従うことを検証して完了する.
    """
    store = InMemoryBeatmapStore()
    for beatmapset_id in (10, 20):
        await store.save_beatmapset_snapshot(
            _beatmapset(beatmapset_id, status=BeatmapRankStatus.LOVED)
        )
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=10, score=2.0),
                DirectSearchCandidate(beatmapset_id=20, score=1.0),
            ),
            has_more=True,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=(
                _beatmapset(30, status=BeatmapRankStatus.LOVED),
                _beatmapset(40, status=BeatmapRankStatus.LOVED),
            ),
            has_more=True,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="",
        statuses=(BeatmapRankStatus.LOVED,),
        mode=BeatmapMode.OSU,
        page_size=2,
        listing=DirectSearchListing.NEWEST,
    )
    current_time = [datetime(2026, 1, 1, tzinfo=UTC)]
    query = DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
        coverage_reader=store.query_repository,
        first_page_refresh_seconds=10.0,
        clock=lambda: current_time[0],
    )

    first = await query.execute(request)
    assert first.coverage_record is not None
    async with store.uow_factory() as uow:
        await uow.beatmaps.record_direct_coverage(first.coverage_record)
        await uow.commit()
    second = await query.execute(request)
    current_time[0] += timedelta(seconds=11)
    third = await query.execute(request)

    assert upstream.requests == [request, request]
    assert [beatmapset.id for beatmapset in second.beatmapsets] == [10, 20]
    assert second.coverage_record is None
    assert [beatmapset.id for beatmapset in third.beatmapsets] == [30, 40]
    assert third.coverage_record is not None


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


async def test_merges_external_search_results_when_local_page_is_incomplete() -> None:
    """Local候補がpageを満たさない場合にexternal search候補をstable結果へmergeする.

    local backendが1件だけ返し、外部検索が未保存setを返す条件で、local候補を先頭に保ったまま
    外部候補が追加され、追加候補のmetadata fetchが要求されることを確認する.

    Returns:
        None: hybrid searchのmerge順序とlocal化wakeを検証して完了する.
    """
    store = InMemoryBeatmapStore()
    await store.save_beatmapset_snapshot(_beatmapset(10))
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(DirectSearchCandidate(beatmapset_id=10, score=1.0),),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(beatmapsets=(_beatmapset(20),), has_more=False)
    )
    woken_ids: list[int] = []
    request = DirectSearchRequest(authenticated_user_id=1, query_text="Camellia")

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
        metadata_wake=_append_metadata_wake(woken_ids),
    ).execute(request)

    assert upstream.requests == [request]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [10, 20]
    assert result.stable_result_count == 2
    assert woken_ids == [20]


async def test_external_search_results_are_filtered_and_deduplicated() -> None:
    """External search候補をlocal候補と同じ公開status/mode条件でfilterして重複排除する.

    外部検索がlocal重複、Graveyard、mode不一致、有効候補を返す条件で、requestのstatus条件に
    合う未保存候補だけがstable結果に追加されることを確認する.

    Returns:
        None: external候補のdedupeとfilterを検証して完了する.
    """
    store = InMemoryBeatmapStore()
    await store.save_beatmapset_snapshot(_beatmapset(10))
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(DirectSearchCandidate(beatmapset_id=10, score=1.0),),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=(
                _beatmapset(10),
                _beatmapset(20, status=BeatmapRankStatus.GRAVEYARD),
                _beatmapset(30, beatmaps=_beatmaps_for_mode(30, BeatmapMode.TAIKO)),
                _beatmapset(40),
            ),
            has_more=False,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Camellia",
        statuses=(BeatmapRankStatus.RANKED,),
        mode=BeatmapMode.OSU,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
    ).execute(request)

    assert [beatmapset.id for beatmapset in result.beatmapsets] == [10, 40]


async def test_graveyard_external_search_results_are_accepted() -> None:
    """Graveyard filterのexternal検索候補をstable結果へ追加する契約を検証する.

    Stable directの`r=5`はGraveyard検索なので、upstreamが返したGraveyard候補がdirect eligibilityで
    落ちずに結果へ残ることを確認する.

    Returns:
        None: Graveyard external候補が結果へmergeされることを検証して完了する.
    """
    store = InMemoryBeatmapStore()
    backend = DirectSearchBackendStub(DirectSearchBackendResult(candidates=(), has_more=False))
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=(_beatmapset(20, status=BeatmapRankStatus.GRAVEYARD),),
            has_more=False,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="",
        statuses=(BeatmapRankStatus.GRAVEYARD,),
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
    ).execute(request)

    assert upstream.requests == [request]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [20]


async def test_external_search_timeout_returns_local_results() -> None:
    """External searchがbounded waitを超えた場合にlocal結果だけを返す契約を検証する.

    external providerを極短いtimeoutより長く遅延させ、timeoutがstable search response全体の失敗に
    ならずlocal候補を返すことを確認する.

    Returns:
        None: upstream timeout時のdegrade動作を検証して完了する.
    """
    store = InMemoryBeatmapStore()
    await store.save_beatmapset_snapshot(_beatmapset(10))
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(DirectSearchCandidate(beatmapset_id=10, score=1.0),),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(beatmapsets=(_beatmapset(20),), has_more=False),
        delay_seconds=0.05,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
        upstream_wait_seconds=0.001,
    ).execute(DirectSearchRequest(authenticated_user_id=1, query_text="Camellia"))

    assert [beatmapset.id for beatmapset in result.beatmapsets] == [10]
    assert result.stable_result_count == 1


async def test_external_search_failure_does_not_record_completed_empty_coverage() -> None:
    """External search失敗時にsynthetic empty coverageを返さないことを検証する.

    Local page不足でupstream検索が必要な条件を作り, provider失敗時はlocal empty結果へdegradeしても
    coverage_recordがNoneのままになることを確認する.

    Returns:
        None: 失敗したexternal searchが完了coverageとして保存されないことを検証する.
    """
    store = InMemoryBeatmapStore()
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(candidates=(), has_more=False),
    )
    upstream = FailingDirectSearchUpstreamProviderStub()
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Camellia",
        page=1,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
    ).execute(request)

    assert upstream.requests == [request]
    assert result.beatmapsets == ()
    assert result.coverage_record is None


async def test_coverage_missing_triggers_external_search_for_full_local_page() -> None:
    """Coverageがないfull local pageで外部検索を併用しlocal候補を優先する契約を検証する.

    Page 1でlocal backendがpageを満たしていてもID range coverageが未記録の場合、外部検索を
    実行しつつresponseではlocal候補を維持することを確認する.

    Returns:
        None: coverage欠落時のupstream呼出とlocal優先順序を検証して完了する.
    """
    store = InMemoryBeatmapStore()
    for beatmapset_id in (10, 20):
        await store.save_beatmapset_snapshot(
            _beatmapset(beatmapset_id, status=BeatmapRankStatus.LOVED)
        )
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=10, score=2.0),
                DirectSearchCandidate(beatmapset_id=20, score=1.0),
            ),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=(_beatmapset(30), _beatmapset(40)),
            has_more=False,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Camellia",
        page=1,
        page_size=3,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
        coverage_reader=store.query_repository,
    ).execute(request)

    assert upstream.requests == [request]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [10, 20, 30]
    assert result.coverage_record is not None


async def test_upstream_search_coverage_suppresses_repeated_external_search() -> None:
    """External検索成功coverageがfull local pageの再取得を抑制する契約を検証する.

    初回検索でcoverageが欠落しているため外部検索を実行し、返されたcoverage recordを保存する.
    同じ条件の2回目検索ではlocal pageが満杯なら保存済みcoverageにより外部検索しないことを確認する.

    Returns:
        None: coverage保存後のfull local pageでupstream再取得抑制を検証して完了する.
    """
    store = InMemoryBeatmapStore()
    for beatmapset_id in (10, 20):
        await store.save_beatmapset_snapshot(_beatmapset(beatmapset_id))
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=10, score=2.0),
                DirectSearchCandidate(beatmapset_id=20, score=1.0),
            ),
            has_more=False,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Camellia",
        page=1,
        page_size=2,
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(beatmapsets=(_beatmapset(30),), has_more=False)
    )
    query = DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
        coverage_reader=store.query_repository,
    )

    first = await query.execute(request)
    assert first.coverage_record is not None
    async with store.uow_factory() as uow:
        await uow.beatmaps.record_direct_coverage(first.coverage_record)
        await uow.commit()
    second = await query.execute(request)

    assert upstream.requests == [request]
    assert [beatmapset.id for beatmapset in first.beatmapsets] == [10, 20]
    assert [beatmapset.id for beatmapset in second.beatmapsets] == [10, 20]
    assert second.coverage_record is None


async def test_covered_short_local_page_skips_external_search() -> None:
    """Coverage保存済みのpage 1以降はlocal pageが短くてもexternal検索しない契約を検証する.

    Loved listingのようにlocal catalogがpage size未満しか返せない条件でも、同じ検索範囲の
    upstream coverage保存後は再度外部候補を取りに行かないことを確認する.

    Returns:
        None: short local pageでcoverageがupstream再取得を抑制することを検証して完了する.
    """
    store = InMemoryBeatmapStore()
    for beatmapset_id in (10, 20):
        await store.save_beatmapset_snapshot(
            _beatmapset(beatmapset_id, status=BeatmapRankStatus.LOVED)
        )
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=10, score=2.0),
                DirectSearchCandidate(beatmapset_id=20, score=1.0),
            ),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=(_beatmapset(30, status=BeatmapRankStatus.LOVED),),
            has_more=False,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Camellia",
        statuses=(BeatmapRankStatus.LOVED,),
        page=1,
        page_size=3,
    )
    query = DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
        coverage_reader=store.query_repository,
    )

    first = await query.execute(request)
    assert first.coverage_record is not None
    async with store.uow_factory() as uow:
        await uow.beatmaps.record_direct_coverage(first.coverage_record)
        await uow.commit()
    second = await query.execute(request)

    assert upstream.requests == [request]
    assert [beatmapset.id for beatmapset in second.beatmapsets] == [10, 20]
    assert second.coverage_record is None


async def test_completed_id_range_coverage_skips_external_search_for_covered_page() -> None:
    """Local候補がcoverage範囲内ならshort pageでも外部検索しない契約を検証する.

    完了済みID range coverageがlocal候補IDを含む条件で、local pageが満たされていない場合でも
    providerを呼ばずlocal結果だけを返すことを確認する.

    Returns:
        None: coverage内pageのcache-only検索を検証して完了する.
    """
    store = InMemoryBeatmapStore()
    for beatmapset_id in (10, 20):
        await store.save_beatmapset_snapshot(_beatmapset(beatmapset_id))
    await _record_completed_id_range_coverage(store, from_id=1, to_id=100)
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=10, score=2.0),
                DirectSearchCandidate(beatmapset_id=20, score=1.0),
            ),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(beatmapsets=(_beatmapset(30),), has_more=False)
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Camellia",
        page=1,
        page_size=3,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
        coverage_reader=store.query_repository,
    ).execute(request)

    assert upstream.requests == []
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [10, 20]
    assert result.stable_result_count == 2


async def test_out_of_range_local_candidate_triggers_external_search() -> None:
    """Coverage範囲外IDを含むfull local pageで外部検索を併用する契約を検証する.

    完了済みcoverageが一部local候補を含まない条件で、外部検索を実行しつつlocal候補を優先することを
    確認する.

    Returns:
        None: coverage範囲外判定とlocal優先mergeを検証して完了する.
    """
    store = InMemoryBeatmapStore()
    for beatmapset_id in (10, 20):
        await store.save_beatmapset_snapshot(_beatmapset(beatmapset_id))
    await _record_completed_id_range_coverage(store, from_id=1, to_id=15)
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=10, score=2.0),
                DirectSearchCandidate(beatmapset_id=20, score=1.0),
            ),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=(_beatmapset(30), _beatmapset(40)),
            has_more=False,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Camellia",
        page=1,
        page_size=2,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
        coverage_reader=store.query_repository,
    ).execute(request)

    assert upstream.requests == [request]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [10, 20]


async def test_first_page_refresh_runs_external_search_once_per_interval() -> None:
    """Page 0のfull local pageで外部検索を一定間隔に抑制する契約を検証する.

    同じ検索条件を短時間に繰り返す場合、初回だけ外部検索し、interval経過後に再度外部検索することを
    fake clockで確認する.

    Returns:
        None: page 0 refresh間隔の発火と抑制を検証して完了する.
    """
    store = InMemoryBeatmapStore()
    for beatmapset_id in (10, 20):
        await store.save_beatmapset_snapshot(_beatmapset(beatmapset_id))
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=10, score=2.0),
                DirectSearchCandidate(beatmapset_id=20, score=1.0),
            ),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=(_beatmapset(30), _beatmapset(40)),
            has_more=False,
        )
    )
    current_time = [datetime(2026, 1, 1, tzinfo=UTC)]
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Camellia",
        page=0,
        page_size=2,
    )
    query = DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
        first_page_refresh_seconds=10.0,
        clock=lambda: current_time[0],
    )

    first = await query.execute(request)
    second = await query.execute(request)
    current_time[0] += timedelta(seconds=11)
    third = await query.execute(request)

    assert [beatmapset.id for beatmapset in first.beatmapsets] == [10, 20]
    assert [beatmapset.id for beatmapset in second.beatmapsets] == [10, 20]
    assert [beatmapset.id for beatmapset in third.beatmapsets] == [10, 20]
    assert upstream.requests == [request, request]


async def test_first_page_refresh_does_not_evict_full_local_page_results() -> None:
    """Page 0 refreshの外部検索がfull local pageを押し出さない契約を検証する.

    exact difficulty検索でlocal上位にある譜面が外部検索結果で隠れないよう、local pageが満杯の
    場合でもresponse順序はlocal backend候補を維持することを確認する.

    Returns:
        None: full local pageでのlocal優先mergeを検証して完了する.
    """
    store = InMemoryBeatmapStore()
    for beatmapset_id in (10, 20):
        await store.save_beatmapset_snapshot(_beatmapset(beatmapset_id))
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=10, score=1_000_000.0),
                DirectSearchCandidate(beatmapset_id=20, score=1.0),
            ),
            has_more=True,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(
            beatmapsets=(_beatmapset(30), _beatmapset(40)),
            has_more=True,
        )
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Lustful Desire and Love Magic that goes beyond Infinity",
        page=0,
        page_size=2,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
    ).execute(request)

    assert upstream.requests == [request]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [10, 20]
    assert result.stable_result_count == STABLE_DIRECT_MORE_RESULTS_SENTINEL


async def test_non_first_page_does_not_periodically_refresh_external_search() -> None:
    """Page 1以降はperiodic refreshだけでは外部検索しない契約を検証する.

    Coverage readerを渡さずlocal full pageを返す条件で、page 1検索はproviderを呼ばずlocal結果だけを
    返すことを確認する.

    Returns:
        None: page 1のperiodic refresh非対象契約を検証して完了する.
    """
    store = InMemoryBeatmapStore()
    for beatmapset_id in (10, 20):
        await store.save_beatmapset_snapshot(_beatmapset(beatmapset_id))
    backend = DirectSearchBackendStub(
        DirectSearchBackendResult(
            candidates=(
                DirectSearchCandidate(beatmapset_id=10, score=2.0),
                DirectSearchCandidate(beatmapset_id=20, score=1.0),
            ),
            has_more=False,
        )
    )
    upstream = DirectSearchUpstreamProviderStub(
        DirectSearchUpstreamResult(beatmapsets=(_beatmapset(30),), has_more=False)
    )
    request = DirectSearchRequest(
        authenticated_user_id=1,
        query_text="Camellia",
        page=1,
        page_size=2,
    )

    result = await DirectSearchQuery(
        store.query_repository,
        backend,
        upstream_provider=upstream,
    ).execute(request)

    assert upstream.requests == []
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [10, 20]


def _append_metadata_wake(woken_ids: list[int]) -> Callable[[int], Awaitable[None]]:
    """External候補のlocal化要求をlistへ記録するcallbackを作る.

    Args:
        woken_ids (list[int]): wake対象beatmapset IDを記録するlist.

    Returns:
        Callable[[int], Awaitable[None]]: DirectSearchQueryへ渡すasync callback.
    """

    async def _wake(beatmapset_id: int) -> None:
        """Wake要求を副作用として記録する.

        Args:
            beatmapset_id (int): external候補のbeatmapset ID.

        Returns:
            None: IDを記録して値を返さず完了する.
        """
        woken_ids.append(beatmapset_id)

    return _wake


async def _record_completed_id_range_coverage(
    store: InMemoryBeatmapStore,
    *,
    from_id: int,
    to_id: int,
) -> None:
    """In-memory storeへ完了済みID range coverageを記録する.

    Args:
        store (InMemoryBeatmapStore): coverageを保存する共有store.
        from_id (int): coverage開始beatmapset ID.
        to_id (int): coverage終了beatmapset ID.

    Returns:
        None: coverageをcommitして値を返さず完了する.
    """
    async with store.uow_factory() as uow:
        await uow.beatmaps.record_direct_coverage(
            DirectCoverageRecord(
                coverage_kind=DirectCoverageKind.ID_RANGE,
                source=BeatmapMetadataSource.OFFICIAL,
                status_scope=DirectCoverageStatusScope.ALL,
                sort_key="id",
                window_key=f"{from_id}-{to_id}",
                from_beatmapset_id=from_id,
                to_beatmapset_id=to_id,
                cursor=None,
                completed_at=datetime(2026, 1, 1, tzinfo=UTC),
                failed_at=None,
                failure_reason=None,
            )
        )
        await uow.commit()


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
    """Point lookupがchildless,not submitted metadataを空結果へ変換する契約を検証する.

    cacheにmetadataが存在してもstable direct rowへ安全に変換できないsetは返さない一方で、
    Graveyard setはdirect表示対象として返すことを確認する.

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

    assert [result.beatmapset.id if result.beatmapset else None for result in results] == [
        None,
        30,
        None,
    ]


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


def _beatmaps_for(
    beatmapset_id: int,
    status: BeatmapRankStatus,
    *,
    mode: BeatmapMode = BeatmapMode.OSU,
) -> tuple[Beatmap, ...]:
    """指定setのusable child beatmapを1件作る.

    Args:
        beatmapset_id (int): 所属beatmapsetの識別子.
        status (BeatmapRankStatus): childに設定する公開status.
        mode (BeatmapMode): childに設定するgame mode.

    Returns:
        tuple[Beatmap, ...]: 指定setに属する単一child beatmap列.
    """
    return (
        Beatmap(
            id=beatmapset_id * 10,
            beatmapset_id=beatmapset_id,
            checksum_md5=f"{beatmapset_id:032x}",
            mode=mode,
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


def _beatmaps_for_mode(beatmapset_id: int, mode: BeatmapMode) -> tuple[Beatmap, ...]:
    """指定modeを持つusable child beatmapを1件作る.

    Args:
        beatmapset_id (int): 所属beatmapsetの識別子.
        mode (BeatmapMode): childに設定するgame mode.

    Returns:
        tuple[Beatmap, ...]: 指定modeの単一child beatmap列.
    """
    return _beatmaps_for(beatmapset_id, BeatmapRankStatus.RANKED, mode=mode)
