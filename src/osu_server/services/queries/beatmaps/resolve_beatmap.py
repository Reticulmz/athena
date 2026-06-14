"""Beatmap resolution query use-cases.

Query-side beatmap resolution for display and compatibility workflows.
These use-cases provide read-only access to beatmap data without triggering
command-side mutations or refresh workflows.
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
    """Result of a beatmap resolution query."""

    beatmap: Beatmap | None
    beatmapset: BeatmapSet | None
    metadata_status: BeatmapFetchState
    file_status: BeatmapFileState


class ResolveBeatmapByIdQuery:
    """Resolve a beatmap by its ID (query-side, read-only)."""

    _repository: BeatmapQueryRepository

    def __init__(self, repository: BeatmapQueryRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None,
    ) -> BeatmapResolveQueryResult:
        """Resolve a beatmap by ID without triggering mutations."""
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
    """Resolve a beatmap by checksum (query-side, read-only)."""

    _repository: BeatmapQueryRepository

    def __init__(self, repository: BeatmapQueryRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None,
    ) -> BeatmapResolveQueryResult:
        """Resolve a beatmap by checksum without triggering mutations."""
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
    fetch_record = await repository.get_fetch_state(metadata_target)
    return BeatmapResolveQueryResult(
        beatmap=None,
        beatmapset=None,
        metadata_status=(
            BeatmapFetchState.PENDING_FETCH if fetch_record is None else fetch_record.status
        ),
        file_status=BeatmapFileState.MISSING,
    )
