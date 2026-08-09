"""osu!direct候補をmetadataからstable-ready結果へhydrateするquery use-caseを定義する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, cast

from osu_server.domain.beatmaps import (
    BeatmapResolveOptions,
    DirectPointLookupTargetKind,
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
    """

    beatmapsets: tuple[BeatmapSet, ...]
    stable_result_count: int


class DirectSearchQuery:
    """Backend候補をBeatmap Mirror metadataからhydrateするread-only query use-case.

    Attributes:
        _repository (BeatmapQueryRepository): metadata source of truthを読むquery repository.
        _backend (DirectSearchBackend): 候補IDとranking scoreだけを返す検索backend.
    """

    _repository: BeatmapQueryRepository
    _backend: DirectSearchBackend

    def __init__(
        self,
        repository: BeatmapQueryRepository,
        backend: DirectSearchBackend,
    ) -> None:
        """Metadata repositoryと候補検索backendを保持する.

        Args:
            repository (BeatmapQueryRepository): hydrated metadataを読むrepository.
            backend (DirectSearchBackend): candidate IDを返す検索backend.
        """
        self._repository = repository
        self._backend = backend

    async def execute(self, request: DirectSearchRequest) -> DirectSearchQueryResult:
        """候補をmetadata source of truthからhydrateしてstable-ready結果を返す.

        Args:
            request (DirectSearchRequest): authentication済みかつparse済みのdirect検索条件.

        Returns:
            DirectSearchQueryResult: 利用可能なmetadata列とstable count値.

        Notes:
            free-text候補なし又はmetadata欠損時にupstream fetchを要求しない.
        """
        backend_result = await self._backend.search(request)
        beatmapsets: list[BeatmapSet] = []
        for candidate in backend_result.candidates:
            beatmapset = await self._repository.get_beatmapset(candidate.beatmapset_id)
            if beatmapset is not None and is_direct_searchable_beatmapset(beatmapset):
                beatmapsets.append(beatmapset)

        return DirectSearchQueryResult(
            beatmapsets=tuple(beatmapsets),
            stable_result_count=(
                STABLE_DIRECT_MORE_RESULTS_SENTINEL
                if backend_result.has_more and len(beatmapsets) == request.page_size
                else len(beatmapsets)
            ),
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


__all__ = [
    "DirectPointLookupQuery",
    "DirectPointLookupQueryResult",
    "DirectPointLookupResolver",
    "DirectSearchQuery",
    "DirectSearchQueryResult",
]
