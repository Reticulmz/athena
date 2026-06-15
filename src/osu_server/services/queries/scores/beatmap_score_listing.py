"""Beatmap score listing query use-case.

Query-side beatmap resolution for score listing compatibility. This use-case
provides read-only beatmap resolution without triggering command-side mutations
or background fetch workflows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.compatibility.stable.getscores import (
    GetscoresOutcomeKind,
    GetscoresRequest,
    GetscoresResolvedHeader,
    GetscoresResolveOutcome,
    GetscoresResolveReason,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap
    from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
        BeatmapScoreListingQueryRepository,
    )


_DISPLAYABLE_STATUSES = {
    BeatmapRankStatus.PENDING,
    BeatmapRankStatus.WIP,
    BeatmapRankStatus.GRAVEYARD,
    BeatmapRankStatus.RANKED,
    BeatmapRankStatus.APPROVED,
    BeatmapRankStatus.QUALIFIED,
    BeatmapRankStatus.LOVED,
}


class BeatmapScoreListingQuery:
    """Score listing beatmap resolution query use-case (read-only)."""

    _repository: BeatmapScoreListingQueryRepository

    def __init__(self, repository: BeatmapScoreListingQueryRepository) -> None:
        self._repository = repository

    async def resolve(self, request: GetscoresRequest) -> GetscoresResolveOutcome:
        """Resolve a parsed getscores request without command-side mutation."""
        if request.checksum_md5 is not None:
            beatmap = await self._repository.find_by_checksum(request.checksum_md5)
            if beatmap is not None:
                return await self._evaluate_beatmap(
                    beatmap,
                    reason=GetscoresResolveReason.KNOWN_CHECKSUM,
                )

            if request.filename is not None and request.beatmapset_id_hint is not None:
                return await self._resolve_update_available(
                    checksum_md5=request.checksum_md5,
                    beatmapset_id=request.beatmapset_id_hint,
                    filename=request.filename,
                )

            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if request.filename is not None and request.beatmapset_id_hint is not None:
            return await self.resolve_by_filename_in_beatmapset(
                beatmapset_id=request.beatmapset_id_hint,
                filename=request.filename,
            )

        return _unavailable(GetscoresResolveReason.NOT_FOUND)

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
    ) -> GetscoresResolveOutcome:
        """Resolve beatmap by checksum for getscores response."""
        beatmap = await self._repository.find_by_checksum(checksum_md5)

        if beatmap is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        return await self._evaluate_beatmap(
            beatmap,
            reason=GetscoresResolveReason.KNOWN_CHECKSUM,
        )

    async def resolve_by_filename_in_beatmapset(
        self,
        beatmapset_id: int,
        filename: str,
    ) -> GetscoresResolveOutcome:
        """Resolve beatmap by filename within a beatmapset."""
        beatmap = await self._repository.find_by_filename_in_beatmapset(
            beatmapset_id,
            filename,
        )

        if beatmap is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        return await self._evaluate_beatmap(
            beatmap,
            reason=GetscoresResolveReason.KNOWN_FILENAME_IN_SET,
        )

    async def _evaluate_beatmap(
        self,
        beatmap: Beatmap,
        *,
        reason: GetscoresResolveReason,
    ) -> GetscoresResolveOutcome:
        """Evaluate a found beatmap for getscores header."""
        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)

        if beatmapset is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if not _is_displayable_in_score_listing(beatmap):
            return _unavailable(GetscoresResolveReason.NOT_SUBMITTED)

        return GetscoresResolveOutcome(
            kind=GetscoresOutcomeKind.HEADER,
            header=GetscoresResolvedHeader(
                beatmap=beatmap,
                beatmapset=beatmapset,
            ),
            reason=reason,
        )

    async def _resolve_update_available(
        self,
        *,
        checksum_md5: str,
        beatmapset_id: int,
        filename: str,
    ) -> GetscoresResolveOutcome:
        beatmap = await self._repository.find_by_filename_in_beatmapset(
            beatmapset_id,
            filename,
        )
        if beatmap is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if beatmap.checksum_md5 == checksum_md5:
            return await self._evaluate_beatmap(
                beatmap,
                reason=GetscoresResolveReason.KNOWN_FILENAME_IN_SET,
            )

        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)
        if beatmapset is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if not _is_displayable_in_score_listing(beatmap):
            return _unavailable(GetscoresResolveReason.NOT_SUBMITTED)

        return GetscoresResolveOutcome(
            kind=GetscoresOutcomeKind.UPDATE_AVAILABLE,
            header=GetscoresResolvedHeader(
                beatmap=beatmap,
                beatmapset=beatmapset,
            ),
            reason=GetscoresResolveReason.UPDATE_AVAILABLE,
        )


def _unavailable(reason: GetscoresResolveReason) -> GetscoresResolveOutcome:
    """Build an unavailable outcome."""
    return GetscoresResolveOutcome(
        kind=GetscoresOutcomeKind.UNAVAILABLE,
        header=None,
        reason=reason,
    )


def _is_displayable_in_score_listing(beatmap: Beatmap) -> bool:
    """Return whether the beatmap can produce a score listing header."""
    return beatmap.effective_status in _DISPLAYABLE_STATUSES
