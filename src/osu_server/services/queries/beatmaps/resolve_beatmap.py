"""beatmapをread-onlyに解決するquery use-caseを定義する.

表示と互換workflow向けにbeatmap dataを読み取る. command-side mutationやrefresh workflowは
起動しない.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import BeatmapFetchState, BeatmapFetchTarget, BeatmapFileState

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapResolveOptions,
        BeatmapSet,
    )
    from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository


@dataclass(frozen=True, slots=True)
class BeatmapResolveQueryResult:
    """beatmap解決queryのread-only結果を表す.

    Attributes:
        beatmap (Beatmap | None): checksumまたはIDに一致したbeatmap. 未発見時はNone.
        beatmapset (BeatmapSet | None): 一致beatmapに対応するbeatmapset. 未発見時はNone.
        metadata_status (BeatmapFetchState): metadataの取得または利用可能状態.
        file_status (BeatmapFileState): osu fileの利用可能状態.
    """

    beatmap: Beatmap | None
    beatmapset: BeatmapSet | None
    metadata_status: BeatmapFetchState
    file_status: BeatmapFileState


class ResolveBeatmapByIdQuery:
    """beatmap IDからread-onlyにbeatmapとbeatmapsetを解決する.

    Attributes:
        _repository (BeatmapQueryRepository): beatmapとfetch stateを読み取るrepository.
    """

    _repository: BeatmapQueryRepository

    def __init__(self, repository: BeatmapQueryRepository) -> None:
        """beatmap解決に使うquery repositoryを保持する.

        Args:
            repository (BeatmapQueryRepository): beatmapとbeatmapsetをread-onlyに取得する
                repository.
        """
        self._repository = repository

    async def execute(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None,
    ) -> BeatmapResolveQueryResult:
        """Beatmap IDからmutationを起こさずにbeatmapを解決する.

        Args:
            beatmap_id (int): 解決するbeatmapのID.
            options (BeatmapResolveOptions | None): 将来のfilterまたはprojection用option.

        Returns:
            BeatmapResolveQueryResult: 一致したbeatmapまたは未発見時のfetch stateを持つ結果.

        Notes:
            optionsは現在のread modelに影響せず将来の拡張のため受け取る.
        """
        del options  # Reserved for future filtering/projection

        beatmap = await self._repository.get_beatmap(beatmap_id)

        if beatmap is None:
            return await _unavailable_result(
                self._repository,
                BeatmapFetchTarget.metadata_by_beatmap_id(beatmap_id),
            )

        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)

        return BeatmapResolveQueryResult(
            beatmap=beatmap,
            beatmapset=beatmapset,
            metadata_status=beatmap.metadata_fetch_state,
            file_status=beatmap.file_state,
        )


class ResolveBeatmapByChecksumQuery:
    """beatmap checksumからread-onlyにbeatmapとbeatmapsetを解決する.

    Attributes:
        _repository (BeatmapQueryRepository): beatmapとfetch stateを読み取るrepository.
    """

    _repository: BeatmapQueryRepository

    def __init__(self, repository: BeatmapQueryRepository) -> None:
        """beatmap解決に使うquery repositoryを保持する.

        Args:
            repository (BeatmapQueryRepository): beatmapとbeatmapsetをread-onlyに取得する
                repository.
        """
        self._repository = repository

    async def execute(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None,
    ) -> BeatmapResolveQueryResult:
        """Beatmap checksumからmutationを起こさずにbeatmapを解決する.

        Args:
            checksum_md5 (str): 解決するbeatmap contentのMD5 checksum.
            options (BeatmapResolveOptions | None): 将来のfilterまたはprojection用option.

        Returns:
            BeatmapResolveQueryResult: 一致したbeatmapまたは未発見時のfetch stateを持つ結果.

        Notes:
            optionsは現在のread modelに影響せず将来の拡張のため受け取る.
        """
        del options  # Reserved for future filtering/projection

        beatmap = await self._repository.get_beatmap_by_checksum(checksum_md5)

        if beatmap is None:
            return await _unavailable_result(
                self._repository,
                BeatmapFetchTarget.metadata_by_checksum(checksum_md5),
            )

        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)

        return BeatmapResolveQueryResult(
            beatmap=beatmap,
            beatmapset=beatmapset,
            metadata_status=beatmap.metadata_fetch_state,
            file_status=beatmap.file_state,
        )


async def _unavailable_result(
    repository: BeatmapQueryRepository,
    metadata_target: BeatmapFetchTarget,
) -> BeatmapResolveQueryResult:
    """未発見のbeatmapに対応するread-onlyのunavailable結果を作る.

    Args:
        repository (BeatmapQueryRepository): fetch stateを読み取るquery repository.
        metadata_target (BeatmapFetchTarget): 未発見beatmapのmetadata取得対象.

    Returns:
        BeatmapResolveQueryResult: pendingまたは既知fetch stateとmissing file stateを持つ結果.
    """
    fetch_record = await repository.get_fetch_state(metadata_target)
    return BeatmapResolveQueryResult(
        beatmap=None,
        beatmapset=None,
        metadata_status=(
            BeatmapFetchState.PENDING_FETCH if fetch_record is None else fetch_record.status
        ),
        file_status=BeatmapFileState.MISSING,
    )
