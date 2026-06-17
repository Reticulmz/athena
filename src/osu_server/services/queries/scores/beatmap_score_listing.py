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
    GetscoresPersonalBest,
    GetscoresRequest,
    GetscoresResolvedHeader,
    GetscoresResolveOutcome,
    GetscoresResolveReason,
)
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.domain.scores.score import Playstyle, Ruleset

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap
    from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
        BeatmapScoreListingQueryRepository,
    )
    from osu_server.repositories.interfaces.queries.personal_bests import (
        PersonalBestQueryRepository,
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
    _personal_bests: PersonalBestQueryRepository

    def __init__(
        self,
        repository: BeatmapScoreListingQueryRepository,
        personal_bests: PersonalBestQueryRepository,
    ) -> None:
        self._repository = repository
        self._personal_bests = personal_bests

    async def resolve(
        self,
        request: GetscoresRequest,
        *,
        user_id: int | None = None,
    ) -> GetscoresResolveOutcome:
        """Resolve a parsed getscores request without command-side mutation."""
        if request.checksum_md5 is not None:
            beatmap = await self._repository.find_by_checksum(request.checksum_md5)
            if beatmap is not None:
                return await self._evaluate_beatmap(
                    beatmap,
                    reason=GetscoresResolveReason.KNOWN_CHECKSUM,
                    request=request,
                    user_id=user_id,
                )

            if request.filename is not None and request.beatmapset_id_hint is not None:
                return await self._resolve_update_available(
                    checksum_md5=request.checksum_md5,
                    beatmapset_id=request.beatmapset_id_hint,
                    filename=request.filename,
                    request=request,
                    user_id=user_id,
                )

            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if request.filename is not None and request.beatmapset_id_hint is not None:
            return await self._resolve_by_filename_in_beatmapset(
                beatmapset_id=request.beatmapset_id_hint,
                filename=request.filename,
                request=request,
                user_id=user_id,
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
            request=None,
            user_id=None,
        )

    async def resolve_by_filename_in_beatmapset(
        self,
        beatmapset_id: int,
        filename: str,
    ) -> GetscoresResolveOutcome:
        """Resolve beatmap by filename within a beatmapset."""
        return await self._resolve_by_filename_in_beatmapset(
            beatmapset_id=beatmapset_id,
            filename=filename,
            request=None,
            user_id=None,
        )

    async def _resolve_by_filename_in_beatmapset(
        self,
        *,
        beatmapset_id: int,
        filename: str,
        request: GetscoresRequest | None,
        user_id: int | None,
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
            request=request,
            user_id=user_id,
        )

    async def _evaluate_beatmap(
        self,
        beatmap: Beatmap,
        *,
        reason: GetscoresResolveReason,
        request: GetscoresRequest | None,
        user_id: int | None,
    ) -> GetscoresResolveOutcome:
        """Evaluate a found beatmap for getscores header."""
        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)

        if beatmapset is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if not _is_displayable_in_score_listing(beatmap):
            return _unavailable(GetscoresResolveReason.NOT_SUBMITTED)

        personal_best = await self._resolve_personal_best(
            request=request,
            beatmap=beatmap,
            user_id=user_id,
        )
        return GetscoresResolveOutcome(
            kind=GetscoresOutcomeKind.HEADER,
            header=GetscoresResolvedHeader(
                beatmap=beatmap,
                beatmapset=beatmapset,
                personal_best=personal_best,
            ),
            reason=reason,
        )

    async def _resolve_update_available(
        self,
        *,
        checksum_md5: str,
        beatmapset_id: int,
        filename: str,
        request: GetscoresRequest,
        user_id: int | None,
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
                request=request,
                user_id=user_id,
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

    async def _resolve_personal_best(
        self,
        *,
        request: GetscoresRequest | None,
        beatmap: Beatmap,
        user_id: int | None,
    ) -> GetscoresPersonalBest | None:
        if request is None or user_id is None or request.song_select is True:
            return None

        ruleset = _ruleset_from_request(request)
        if ruleset is None:
            return None

        return await self._personal_bests.get_personal_best(
            user_id=user_id,
            beatmap_id=beatmap.id,
            ruleset=ruleset,
            playstyle=Playstyle.VANILLA,
            category=LeaderboardCategory.GLOBAL,
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


def _ruleset_from_request(request: GetscoresRequest) -> Ruleset | None:
    if request.mode is None:
        return None
    try:
        return Ruleset(request.mode)
    except ValueError:
        return None
