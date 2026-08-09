"""osu!direct候補をmetadataからstable-ready結果へhydrateするquery use-caseを定義する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import is_direct_searchable_beatmapset
from osu_server.domain.compatibility.stable.direct import STABLE_DIRECT_MORE_RESULTS_SENTINEL

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        BeatmapSet,
        DirectSearchBackend,
        DirectSearchRequest,
    )
    from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository


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


__all__ = ["DirectSearchQuery", "DirectSearchQueryResult"]
