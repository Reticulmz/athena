"""osu!direct検索queryのunit testを定義する."""

from __future__ import annotations

from datetime import UTC, datetime

from tests.support.beatmaps import InMemoryBeatmapStore

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
    DirectSearchBackendResult,
    DirectSearchCandidate,
    DirectSearchListing,
    DirectSearchRequest,
)
from osu_server.domain.compatibility.stable.direct import STABLE_DIRECT_MORE_RESULTS_SENTINEL
from osu_server.services.queries.beatmaps.direct_search import DirectSearchQuery


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
