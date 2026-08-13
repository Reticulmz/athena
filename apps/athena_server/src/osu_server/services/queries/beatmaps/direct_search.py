"""osu!direct候補をmetadataからstable-ready結果へhydrateするquery use-caseを定義する."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Protocol, cast

import structlog

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapResolveOptions,
    DirectCoverageKind,
    DirectCoverageRecord,
    DirectCoverageStatusScope,
    DirectPointLookupTargetKind,
    DirectSearchUpstreamProvider,
    DirectSearchUpstreamResult,
    is_direct_searchable_beatmapset,
)
from osu_server.domain.compatibility.stable.direct import STABLE_DIRECT_MORE_RESULTS_SENTINEL

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        BeatmapResolveResult,
        BeatmapSet,
        BeatmapSetResolveResult,
        DirectPointLookupRequest,
        DirectSearchBackend,
        DirectSearchRequest,
    )
    from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository

_DEFAULT_DIRECT_POINT_LOOKUP_WAIT_SECONDS: Final = 5.0
_DEFAULT_DIRECT_SEARCH_UPSTREAM_WAIT_SECONDS: Final = 5.0
_DEFAULT_DIRECT_SEARCH_FIRST_PAGE_REFRESH_SECONDS: Final = 300.0
_UPSTREAM_SEARCH_COVERAGE_SORT_KEY: Final = "upstream-search"

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))

type DirectSearchMetadataWake = Callable[[int], Awaitable[None]]
type DirectSearchClock = Callable[[], datetime]


class DirectPointLookupResolver(Protocol):
    """Direct point lookupが使うBeatmap Mirror解決operationを定義する."""

    async def resolve_by_beatmapset_id(
        self,
        beatmapset_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapSetResolveResult:
        """Beatmapset IDからmetadataを解決する.

        Args:
            beatmapset_id (int): 解決するbeatmapset ID.
            options (BeatmapResolveOptions | None): metadata fetchとwaitの制約.

        Returns:
            BeatmapSetResolveResult: 解決済みbeatmapsetまたはunavailable state.
        """
        ...

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Beatmap IDからmetadataを解決する.

        Args:
            beatmap_id (int): 解決するbeatmap ID.
            options (BeatmapResolveOptions | None): metadata fetchとwaitの制約.

        Returns:
            BeatmapResolveResult: 解決済みbeatmapまたはunavailable state.
        """
        ...

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Checksumからmetadataを解決する.

        Args:
            checksum_md5 (str): 解決するbeatmap MD5 checksum.
            options (BeatmapResolveOptions | None): metadata fetchとwaitの制約.

        Returns:
            BeatmapResolveResult: 解決済みbeatmapまたはunavailable state.
        """
        ...


class DirectSearchCoverageReader(Protocol):
    """osu!direct検索がcatalog coverageを読むための最小contractを定義する."""

    async def list_completed_direct_search_coverages(
        self,
        status_scopes: tuple[DirectCoverageStatusScope, ...],
        *,
        feed_sort_key: str,
        feed_window_key: str,
    ) -> tuple[DirectCoverageRecord, ...]:
        """完了済みの検索用coverageを返す.

        Args:
            status_scopes (tuple[DirectCoverageStatusScope, ...]): 対象にするstatus scope列.
            feed_sort_key (str): 検索request由来feed coverageのsort key.
            feed_window_key (str): 検索request由来feed coverageのwindow key.

        Returns:
            tuple[DirectCoverageRecord, ...]: 完了済みID range coverageと一致feed coverage.
        """
        ...


@dataclass(slots=True, frozen=True)
class DirectPointLookupQueryResult:
    """Stable direct formatterへ渡すpoint lookup結果を表す.

    Attributes:
        beatmapset (BeatmapSet | None): stable rowへ変換可能なbeatmapset. 空応答時はNone.
    """

    beatmapset: BeatmapSet | None


@dataclass(slots=True, frozen=True)
class DirectSearchQueryResult:
    """Stable direct formatterへ渡すmetadata hydration済み検索結果を表す.

    Attributes:
        beatmapsets (tuple[BeatmapSet, ...]): stable rowへ変換可能な候補順のbeatmapset列.
        stable_result_count (int): stable count lineへ出力する件数又はmore-results sentinel.
        coverage_record (DirectCoverageRecord | None): upstream検索成功時に保存できるcoverage.
    """

    beatmapsets: tuple[BeatmapSet, ...]
    stable_result_count: int
    coverage_record: DirectCoverageRecord | None = None


class DirectSearchQuery:
    """Backend候補をmetadataからhydrateし不足分を外部検索で補うquery use-case.

    Attributes:
        _repository (BeatmapQueryRepository): metadata source of truthを読むquery repository.
        _backend (DirectSearchBackend): 候補IDとranking scoreだけを返す検索backend.
        _upstream_provider (DirectSearchUpstreamProvider | None): local catalogの不足を補う
            external search provider.
        _coverage_reader (DirectSearchCoverageReader | None): local catalog coverageを読む
            optional collaborator.
        _upstream_wait_seconds (float): external searchを待つ最大秒数.
        _first_page_refresh_seconds (float): page 0で外部検索を再実行する最短間隔.
        _metadata_wake (DirectSearchMetadataWake | None): external候補のlocal化を要求する
            best-effort callback.
        _clock (DirectSearchClock): refresh間隔判定に使う現在時刻provider.
        _first_page_refresh_at_by_key (dict[tuple[object, ...], datetime]): 検索条件ごとの
            直近外部検索試行時刻.
    """

    _repository: BeatmapQueryRepository
    _backend: DirectSearchBackend
    _upstream_provider: DirectSearchUpstreamProvider | None
    _coverage_reader: DirectSearchCoverageReader | None
    _upstream_wait_seconds: float
    _first_page_refresh_seconds: float
    _metadata_wake: DirectSearchMetadataWake | None
    _clock: DirectSearchClock
    _first_page_refresh_at_by_key: dict[tuple[object, ...], datetime]

    def __init__(
        self,
        repository: BeatmapQueryRepository,
        backend: DirectSearchBackend,
        *,
        upstream_provider: DirectSearchUpstreamProvider | None = None,
        coverage_reader: DirectSearchCoverageReader | None = None,
        upstream_wait_seconds: float = _DEFAULT_DIRECT_SEARCH_UPSTREAM_WAIT_SECONDS,
        first_page_refresh_seconds: float = _DEFAULT_DIRECT_SEARCH_FIRST_PAGE_REFRESH_SECONDS,
        metadata_wake: DirectSearchMetadataWake | None = None,
        clock: DirectSearchClock | None = None,
    ) -> None:
        """Metadata repository, local backend, optional external補完を保持する.

        Args:
            repository (BeatmapQueryRepository): hydrated metadataを読むrepository.
            backend (DirectSearchBackend): candidate IDを返す検索backend.
            upstream_provider (DirectSearchUpstreamProvider | None):
                local catalogに不足がある場合だけ使う外部検索provider.
            coverage_reader (DirectSearchCoverageReader | None): local catalog coverageを読む
                optional collaborator.
            upstream_wait_seconds (float): external searchを待つ最大秒数.
            first_page_refresh_seconds (float): page 0で外部検索を再実行する最短間隔.
            metadata_wake (DirectSearchMetadataWake | None):
                external候補のmetadata fetch jobを起動するcallback.
            clock (DirectSearchClock | None): refresh判定に使う時刻provider. NoneならUTC now.

        Raises:
            ValueError: upstream_wait_secondsまたはfirst_page_refresh_secondsが正値でない場合.
        """
        if upstream_wait_seconds <= 0:
            msg = "upstream_wait_seconds must be positive"
            raise ValueError(msg)
        if first_page_refresh_seconds <= 0:
            msg = "first_page_refresh_seconds must be positive"
            raise ValueError(msg)
        self._repository = repository
        self._backend = backend
        self._upstream_provider = upstream_provider
        self._coverage_reader = coverage_reader
        self._upstream_wait_seconds = upstream_wait_seconds
        self._first_page_refresh_seconds = first_page_refresh_seconds
        self._metadata_wake = metadata_wake
        self._clock = clock or _utc_now
        self._first_page_refresh_at_by_key = {}

    async def execute(self, request: DirectSearchRequest) -> DirectSearchQueryResult:
        """Local候補をhydrateし,必要なら外部検索候補をmergeしてstable-ready結果を返す.

        Args:
            request (DirectSearchRequest): authentication済みかつparse済みのdirect検索条件.

        Returns:
            DirectSearchQueryResult: 利用可能なmetadata列とstable count値.

        Notes:
            外部検索は設定済みproviderがあり,local結果不足,coverage欠落/範囲外,page 0 refresh
            のいずれかでbest-effortに実行する. timeoutまたは失敗時はlocal結果だけを返す.
        """
        total_start = time.perf_counter()
        backend_start = time.perf_counter()
        backend_result = await self._backend.search(request)
        backend_ms = _elapsed_ms(backend_start)

        hydrate_start = time.perf_counter()
        beatmapsets: list[BeatmapSet] = []
        candidate_ids = tuple(candidate.beatmapset_id for candidate in backend_result.candidates)
        hydrated_beatmapsets = await self._repository.list_beatmapsets_by_ids(candidate_ids)
        beatmapsets_by_id = {beatmapset.id: beatmapset for beatmapset in hydrated_beatmapsets}
        for candidate in backend_result.candidates:
            beatmapset = beatmapsets_by_id.get(candidate.beatmapset_id)
            if (
                beatmapset is not None
                and is_direct_searchable_beatmapset(beatmapset)
                and _matches_search_filters(beatmapset, request)
            ):
                beatmapsets.append(beatmapset)
        hydrate_ms = _elapsed_ms(hydrate_start)
        local_result_count = len(beatmapsets)

        has_more = backend_result.has_more
        upstream_has_more = False
        upstream_result_count = 0
        coverage_record: DirectCoverageRecord | None = None
        coverage_start = time.perf_counter()
        coverage_requires_upstream = await self._coverage_requires_upstream(request, beatmapsets)
        coverage_ms = _elapsed_ms(coverage_start)
        first_page_refresh_due = self._first_page_refresh_due(request)
        local_page_requires_upstream = (
            len(beatmapsets) < request.page_size and self._coverage_reader is None
        )
        upstream_requested = (
            local_page_requires_upstream or coverage_requires_upstream or first_page_refresh_due
        )
        upstream_ms = 0.0
        merge_ms = 0.0
        upstream_succeeded = False
        if upstream_requested:
            if first_page_refresh_due:
                self._mark_first_page_refresh_attempt(request)
            upstream_start = time.perf_counter()
            upstream_result = await self._search_upstream(request)
            upstream_ms = _elapsed_ms(upstream_start)
            if upstream_result is not None:
                upstream_succeeded = True
                upstream_result_count = len(upstream_result.beatmapsets)
                coverage_record = _upstream_search_coverage_record(
                    request,
                    upstream_result,
                    completed_at=self._clock(),
                )
                has_more = has_more or upstream_result.has_more
                upstream_has_more = upstream_result.has_more
                merge_start = time.perf_counter()
                await self._merge_upstream_results(
                    beatmapsets,
                    upstream_result,
                    request,
                )
                merge_ms = _elapsed_ms(merge_start)

        result = DirectSearchQueryResult(
            beatmapsets=tuple(beatmapsets),
            stable_result_count=(
                STABLE_DIRECT_MORE_RESULTS_SENTINEL
                if (has_more and len(beatmapsets) == request.page_size)
                or (upstream_has_more and beatmapsets)
                else len(beatmapsets)
            ),
            coverage_record=coverage_record,
        )
        logger.info(
            "osu_direct_search_query_completed",
            total_ms=_elapsed_ms(total_start),
            backend_ms=backend_ms,
            hydrate_ms=hydrate_ms,
            coverage_ms=coverage_ms,
            upstream_ms=upstream_ms,
            merge_ms=merge_ms,
            backend_candidate_count=len(backend_result.candidates),
            hydrated_candidate_count=len(hydrated_beatmapsets),
            local_result_count=local_result_count,
            upstream_result_count=upstream_result_count,
            final_result_count=len(result.beatmapsets),
            stable_result_count=result.stable_result_count,
            backend_has_more=backend_result.has_more,
            upstream_has_more=upstream_has_more,
            upstream_requested=upstream_requested,
            upstream_provider_configured=self._upstream_provider is not None,
            upstream_succeeded=upstream_succeeded,
            coverage_requires_upstream=coverage_requires_upstream,
            first_page_refresh_due=first_page_refresh_due,
            local_page_requires_upstream=local_page_requires_upstream,
            listing=request.listing.value,
            page=request.page,
            page_size=request.page_size,
            query_length=len(request.query_text),
            status_count=len(request.statuses),
            mode=request.mode.value if request.mode is not None else None,
        )
        return result

    async def _search_upstream(
        self,
        request: DirectSearchRequest,
    ) -> DirectSearchUpstreamResult | None:
        """Optional external searchをbounded waitで実行する.

        Args:
            request (DirectSearchRequest): external searchへ渡す検索条件.

        Returns:
            DirectSearchUpstreamResult | None: 成功時のexternal候補. 未設定,timeout,失敗時はNone.
        """
        if self._upstream_provider is None:
            return None
        try:
            return await asyncio.wait_for(
                self._upstream_provider.search(request),
                timeout=self._upstream_wait_seconds,
            )
        except TimeoutError:
            logger.warning(
                "osu_direct_search_upstream_timeout",
                timeout_seconds=self._upstream_wait_seconds,
            )
            return None
        except Exception as exc:
            logger.warning(
                "osu_direct_search_upstream_failed",
                exception_type=type(exc).__name__,
            )
            return None

    async def _coverage_requires_upstream(
        self,
        request: DirectSearchRequest,
        beatmapsets: list[BeatmapSet],
    ) -> bool:
        """Local catalog coverageがないか範囲外候補を含む場合に外部検索が必要か返す.

        Args:
            request (DirectSearchRequest): stable direct検索条件.
            beatmapsets (list[BeatmapSet]): local backendからhydrateできた候補.

        Returns:
            bool: 完了済みID range coverageがないか,候補IDがcoverage範囲外ならTrue.
        """
        if self._coverage_reader is None:
            return False
        coverages = await self._coverage_reader.list_completed_direct_search_coverages(
            _coverage_status_scopes(request),
            feed_sort_key=_UPSTREAM_SEARCH_COVERAGE_SORT_KEY,
            feed_window_key=_upstream_search_window_key(request),
        )
        if not coverages:
            return True
        range_coverages = tuple(
            coverage
            for coverage in coverages
            if coverage.coverage_kind is DirectCoverageKind.ID_RANGE
        )
        if range_coverages and any(
            not _is_beatmapset_id_covered(beatmapset.id, range_coverages)
            for beatmapset in beatmapsets
        ):
            return True
        if range_coverages:
            return False
        return not any(
            coverage.coverage_kind is DirectCoverageKind.FEED_WINDOW for coverage in coverages
        )

    def _first_page_refresh_due(self, request: DirectSearchRequest) -> bool:
        """Page 0の外部検索refresh間隔が経過したか返す.

        Args:
            request (DirectSearchRequest): stable direct検索条件.

        Returns:
            bool: page 0かつ未試行または最短間隔を経過していればTrue.
        """
        if request.page != 0:
            return False
        key = _first_page_refresh_key(request)
        previous = self._first_page_refresh_at_by_key.get(key)
        if previous is None:
            return True
        elapsed_seconds = (self._clock() - previous).total_seconds()
        return elapsed_seconds >= self._first_page_refresh_seconds

    def _mark_first_page_refresh_attempt(self, request: DirectSearchRequest) -> None:
        """Page 0外部検索の試行時刻を記録する.

        Args:
            request (DirectSearchRequest): stable direct検索条件.

        Returns:
            None: process localなrefresh時刻を更新して完了する.
        """
        self._first_page_refresh_at_by_key[_first_page_refresh_key(request)] = self._clock()

    async def _merge_upstream_results(
        self,
        beatmapsets: list[BeatmapSet],
        upstream_result: DirectSearchUpstreamResult,
        request: DirectSearchRequest,
    ) -> None:
        """External search候補をlocal候補の後ろへ重複なしで追加する.

        Args:
            beatmapsets (list[BeatmapSet]): 既にhydrate済みのlocal候補. このlistを更新する.
            upstream_result (DirectSearchUpstreamResult): external search候補.
            request (DirectSearchRequest): page sizeとfilterを持つ検索条件.

        Returns:
            None: listを更新し,external候補のmetadata fetchをbest-effortで要求する.
        """
        local_beatmapsets = tuple(beatmapsets)
        beatmapsets.clear()
        beatmapsets.extend(local_beatmapsets)
        await self._append_external_beatmapsets(beatmapsets, upstream_result, request)

    async def _append_external_beatmapsets(
        self,
        beatmapsets: list[BeatmapSet],
        upstream_result: DirectSearchUpstreamResult,
        request: DirectSearchRequest,
    ) -> None:
        """External候補をfilter/dedupeしながら結果listへ追加する.

        Args:
            beatmapsets (list[BeatmapSet]): 更新する検索結果list.
            upstream_result (DirectSearchUpstreamResult): external search候補.
            request (DirectSearchRequest): page sizeとfilterを持つ検索条件.

        Returns:
            None: listを更新し,追加候補のmetadata fetchをbest-effortで要求する.
        """
        seen_ids = {beatmapset.id for beatmapset in beatmapsets}
        for beatmapset in upstream_result.beatmapsets:
            if beatmapset.id in seen_ids:
                continue
            if not is_direct_searchable_beatmapset(beatmapset) or not _matches_search_filters(
                beatmapset,
                request,
            ):
                continue

            if len(beatmapsets) < request.page_size:
                beatmapsets.append(beatmapset)
            seen_ids.add(beatmapset.id)
            await self._wake_metadata_fetch(beatmapset.id)

    async def _wake_metadata_fetch(self, beatmapset_id: int) -> None:
        """External候補をlocal metadataへ取り込むworker taskをbest-effortで起動する.

        Args:
            beatmapset_id (int): local化を要求するbeatmapset ID.

        Returns:
            None: wake未設定またはenqueue失敗時もsearch responseを失敗させずに完了する.
        """
        if self._metadata_wake is None:
            return
        try:
            await self._metadata_wake(beatmapset_id)
        except Exception as exc:
            logger.warning(
                "osu_direct_search_metadata_wake_failed",
                beatmapset_id=beatmapset_id,
                exception_type=type(exc).__name__,
            )


class DirectPointLookupQuery:
    """Beatmap Mirror cache-first resolutionでstable direct point lookupを解決する.

    Attributes:
        _resolver (DirectPointLookupResolver): metadata fetch enqueueとbounded waitを所有する
            resolver.
        _bounded_wait_seconds (float): point lookupでmetadata到着を待つ最大秒数.
    """

    _resolver: DirectPointLookupResolver
    _bounded_wait_seconds: float

    def __init__(
        self,
        resolver: DirectPointLookupResolver,
        *,
        bounded_wait_seconds: float = _DEFAULT_DIRECT_POINT_LOOKUP_WAIT_SECONDS,
    ) -> None:
        """Point lookup用resolverとwait上限を保持する.

        Args:
            resolver (DirectPointLookupResolver): Beatmap Mirror互換のmetadata resolver.
            bounded_wait_seconds (float): metadata到着を待つ最大秒数.

        Raises:
            ValueError: bounded_wait_secondsが負値の場合.
        """
        if bounded_wait_seconds < 0:
            msg = "bounded_wait_seconds must not be negative"
            raise ValueError(msg)
        self._resolver = resolver
        self._bounded_wait_seconds = bounded_wait_seconds

    async def execute(self, request: DirectPointLookupRequest) -> DirectPointLookupQueryResult:
        """Point lookup targetを解決してstable-ready beatmapsetを返す.

        Args:
            request (DirectPointLookupRequest): authentication済みのpoint lookup target.

        Returns:
            DirectPointLookupQueryResult: 利用可能なbeatmapsetまたはempty response用のNone.

        Notes:
            `.osz` package availabilityは要求せず,metadataだけを解決する.
        """
        options = BeatmapResolveOptions(wait_timeout_seconds=self._bounded_wait_seconds)
        beatmapset = await self._resolve_beatmapset(request, options)
        if beatmapset is not None and is_direct_searchable_beatmapset(beatmapset):
            return DirectPointLookupQueryResult(beatmapset=beatmapset)
        return DirectPointLookupQueryResult(beatmapset=None)

    async def _resolve_beatmapset(
        self,
        request: DirectPointLookupRequest,
        options: BeatmapResolveOptions,
    ) -> BeatmapSet | None:
        """Request target種別に応じてBeatmap Mirror resolverを呼ぶ.

        Args:
            request (DirectPointLookupRequest): direct point lookup target.
            options (BeatmapResolveOptions): metadata fetchとwaitの制約.

        Returns:
            BeatmapSet | None: resolverが返したbeatmapset. 未解決時はNone.
        """
        match request.target_kind:
            case DirectPointLookupTargetKind.BEATMAPSET_ID:
                result = await self._resolver.resolve_by_beatmapset_id(
                    cast("int", request.target_value),
                    options,
                )
                return result.beatmapset
            case DirectPointLookupTargetKind.BEATMAP_ID:
                result = await self._resolver.resolve_by_beatmap_id(
                    cast("int", request.target_value),
                    options,
                )
                return result.beatmapset
            case DirectPointLookupTargetKind.CHECKSUM:
                result = await self._resolver.resolve_by_checksum(
                    cast("str", request.target_value),
                    options,
                )
                return result.beatmapset


def _matches_search_filters(beatmapset: BeatmapSet, request: DirectSearchRequest) -> bool:
    """Hydrated metadataがdirect search requestのstatus/mode filterを満たすか返す.

    Args:
        beatmapset (BeatmapSet): localまたはexternalから得たmetadata.
        request (DirectSearchRequest): stable direct検索条件.

    Returns:
        bool: statusとmode filterを満たす場合はTrue.
    """
    if request.statuses and beatmapset.official_status not in request.statuses:
        return False
    if request.mode is None:
        return True
    return any(beatmap.mode is request.mode for beatmap in beatmapset.beatmaps)


def _coverage_status_scopes(
    request: DirectSearchRequest,
) -> tuple[DirectCoverageStatusScope, ...]:
    """検索requestに対応するcoverage status scope列を返す.

    Args:
        request (DirectSearchRequest): stable direct検索条件.

    Returns:
        tuple[DirectCoverageStatusScope, ...]: ALLと明示status scopeの重複なし列.
    """
    scopes = [DirectCoverageStatusScope.ALL]
    for status in request.statuses:
        scope = DirectCoverageStatusScope(status.value)
        if scope not in scopes:
            scopes.append(scope)
    return tuple(scopes)


def _upstream_search_coverage_record(
    request: DirectSearchRequest,
    upstream_result: DirectSearchUpstreamResult,
    *,
    completed_at: datetime,
) -> DirectCoverageRecord:
    """External検索結果から検索窓coverage recordを作る.

    Args:
        request (DirectSearchRequest): stable direct検索条件.
        upstream_result (DirectSearchUpstreamResult): 成功したexternal検索結果.
        completed_at (datetime): coverage完了時刻.

    Returns:
        DirectCoverageRecord: 同一検索条件の再検索抑制に使うfeed coverage record.
    """
    from_id, to_id = _observed_beatmapset_id_range(upstream_result.beatmapsets)
    return DirectCoverageRecord(
        coverage_kind=DirectCoverageKind.FEED_WINDOW,
        source=BeatmapMetadataSource.MIRROR,
        status_scope=_coverage_status_scope(request),
        sort_key=_UPSTREAM_SEARCH_COVERAGE_SORT_KEY,
        window_key=_upstream_search_window_key(request),
        from_beatmapset_id=from_id,
        to_beatmapset_id=to_id,
        cursor=None,
        completed_at=completed_at,
        failed_at=None,
        failure_reason=None,
    )


def _coverage_status_scope(request: DirectSearchRequest) -> DirectCoverageStatusScope:
    """検索requestをcoverage保存用status scopeへ変換する.

    Args:
        request (DirectSearchRequest): stable direct検索条件.

    Returns:
        DirectCoverageStatusScope: 単一statusならそのscope, 複合または無指定ならALL.
    """
    if len(request.statuses) == 1:
        return DirectCoverageStatusScope(request.statuses[0].value)
    return DirectCoverageStatusScope.ALL


def _observed_beatmapset_id_range(beatmapsets: tuple[BeatmapSet, ...]) -> tuple[int, int]:
    """Beatmapset列から観測ID範囲を返す.

    Args:
        beatmapsets (tuple[BeatmapSet, ...]): external検索で得たbeatmapset列.

    Returns:
        tuple[int, int]: IDの最小値と最大値. 空結果では(0, 0).
    """
    if not beatmapsets:
        return (0, 0)
    beatmapset_ids = [beatmapset.id for beatmapset in beatmapsets]
    return (min(beatmapset_ids), max(beatmapset_ids))


def _is_beatmapset_id_covered(
    beatmapset_id: int,
    coverages: tuple[DirectCoverageRecord, ...],
) -> bool:
    """Beatmapset IDがいずれかのcoverage rangeに含まれるか返す.

    Args:
        beatmapset_id (int): coverage判定するbeatmapset ID.
        coverages (tuple[DirectCoverageRecord, ...]): 完了済みID range coverage列.

    Returns:
        bool: いずれかのcoverage rangeに含まれる場合はTrue.
    """
    return any(
        coverage.from_beatmapset_id <= beatmapset_id <= coverage.to_beatmapset_id
        for coverage in coverages
    )


def _upstream_search_window_key(request: DirectSearchRequest) -> str:
    """External検索coverageを同一検索条件で再利用するwindow keyを返す.

    Args:
        request (DirectSearchRequest): stable direct検索条件.

    Returns:
        str: 正規化した検索条件から作った固定長key.
    """
    payload = json.dumps(
        {
            "listing": request.listing.value,
            "query": request.query_text,
            "statuses": [status.value for status in request.statuses],
            "mode": request.mode.value if request.mode is not None else None,
            "page": request.page,
            "page_size": request.page_size,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"search:{digest[:32]}"


def _first_page_refresh_key(request: DirectSearchRequest) -> tuple[object, ...]:
    """Page 0 periodic refreshを区別する検索条件keyを返す.

    Args:
        request (DirectSearchRequest): stable direct検索条件.

    Returns:
        tuple[object, ...]: query/listing/status/mode/page sizeを含むprocess local key.
    """
    return (
        request.listing,
        request.query_text,
        request.statuses,
        request.mode,
        request.page_size,
    )


def _utc_now() -> datetime:
    """現在UTC時刻を返す.

    Returns:
        datetime: timezone-awareな現在UTC時刻.
    """
    return datetime.now(UTC)


def _elapsed_ms(started_at: float) -> float:
    """perf_counter開始値からの経過時間をmillisecondで返す.

    Args:
        started_at (float): time.perf_counter()で取得した開始時刻.

    Returns:
        float: 小数第2位に丸めた経過millisecond.
    """
    return round((time.perf_counter() - started_at) * 1000, 2)


__all__ = [
    "DirectPointLookupQuery",
    "DirectPointLookupQueryResult",
    "DirectPointLookupResolver",
    "DirectSearchCoverageReader",
    "DirectSearchQuery",
    "DirectSearchQueryResult",
    "DirectSearchUpstreamProvider",
    "DirectSearchUpstreamResult",
]
