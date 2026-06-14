"""Legacy getscores query use-case.

Query-side legacy getscores resolution for stable client compatibility.
This use-case provides read-only beatmap resolution without triggering
command-side mutations or background fetch workflows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.legacy_getscores import (
    GetscoresOutcomeKind,
    GetscoresRequest,
    GetscoresResolvedHeader,
    GetscoresResolveOutcome,
    GetscoresResolveReason,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap
    from osu_server.repositories.interfaces.queries.legacy_getscores import (
        LegacyGetscoresQueryRepository,
    )


# Status mapping for stable wire format
_STATUS_TO_WIRE: dict[BeatmapRankStatus, int | None] = {
    BeatmapRankStatus.NOT_SUBMITTED: None,
    BeatmapRankStatus.UNKNOWN: None,
    BeatmapRankStatus.PENDING: 0,
    BeatmapRankStatus.WIP: 0,
    BeatmapRankStatus.GRAVEYARD: 0,
    BeatmapRankStatus.RANKED: 2,
    BeatmapRankStatus.APPROVED: 3,
    BeatmapRankStatus.QUALIFIED: 4,
    BeatmapRankStatus.LOVED: 5,
}


class LegacyGetscoresQuery:
    """Legacy getscores resolution query use-case (read-only)."""

    _repository: LegacyGetscoresQueryRepository

    def __init__(self, repository: LegacyGetscoresQueryRepository) -> None:
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

        # Check if beatmap status is displayable in stable getscores
        if _map_header_status(beatmap) is None:
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

        if _map_header_status(beatmap) is None:
            return _unavailable(GetscoresResolveReason.NOT_SUBMITTED)

        return GetscoresResolveOutcome(
            kind=GetscoresOutcomeKind.UPDATE_AVAILABLE,
            header=GetscoresResolvedHeader(
                beatmap=beatmap,
                beatmapset=beatmapset,
            ),
            reason=GetscoresResolveReason.UPDATE_AVAILABLE,
        )

    def map_header_status(self, beatmap: Beatmap) -> int | None:
        """Map a query result beatmap to stable getscores header status."""
        return _map_header_status(beatmap)


def _unavailable(reason: GetscoresResolveReason) -> GetscoresResolveOutcome:
    """Build an unavailable outcome."""
    return GetscoresResolveOutcome(
        kind=GetscoresOutcomeKind.UNAVAILABLE,
        header=None,
        reason=reason,
    )


def _map_header_status(beatmap: Beatmap) -> int | None:
    """Map beatmap effective status to stable wire status.

    Returns None for statuses that should not be displayed in getscores.
    """
    return _STATUS_TO_WIRE.get(beatmap.effective_status)
