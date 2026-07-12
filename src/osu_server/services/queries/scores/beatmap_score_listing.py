"""Stable score listing adapter query use-case."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.compatibility.stable.getscores import (
    GetscoresOutcomeKind,
    GetscoresPersonalBest,
    GetscoresRequest,
    GetscoresResolvedHeader,
    GetscoresResolveOutcome,
    GetscoresResolveReason,
)
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.services.queries.scores.beatmap_leaderboards import (
    BeatmapLeaderboardOutcomeKind,
    BeatmapLeaderboardQuery,
    BeatmapLeaderboardRequest,
    BeatmapLeaderboardResolveReason,
    BeatmapLeaderboardResult,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
        BeatmapLeaderboardRow,
    )


class BeatmapScoreListingQuery:
    """Adapt stable getscores requests to the Beatmap Leaderboard query boundary."""

    _leaderboard_query: BeatmapLeaderboardQuery

    def __init__(self, leaderboard_query: BeatmapLeaderboardQuery) -> None:
        self._leaderboard_query = leaderboard_query

    async def resolve(
        self,
        request: GetscoresRequest,
        *,
        user_id: int | None = None,
    ) -> GetscoresResolveOutcome:
        """Resolve a parsed stable getscores request without command-side mutation."""
        result = await self._leaderboard_query.execute(
            _leaderboard_request_from_getscores(request, user_id=user_id)
        )
        return _to_getscores_outcome(result)

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
    ) -> GetscoresResolveOutcome:
        """Resolve beatmap by checksum for a stable getscores-compatible response."""
        result = await self._leaderboard_query.execute(
            BeatmapLeaderboardRequest(
                beatmap_checksum=checksum_md5,
                filename=None,
                beatmapset_id_hint=None,
                viewer_user_id=None,
                ruleset=None,
                playstyle=Playstyle.VANILLA,
                category=None,
                selected_mods=None,
                header_only=True,
            )
        )
        return _to_getscores_outcome(result)

    async def resolve_by_filename_in_beatmapset(
        self,
        beatmapset_id: int,
        filename: str,
    ) -> GetscoresResolveOutcome:
        """Resolve beatmap by filename within a beatmapset."""
        result = await self._leaderboard_query.execute(
            BeatmapLeaderboardRequest(
                beatmap_checksum=None,
                filename=filename,
                beatmapset_id_hint=beatmapset_id,
                viewer_user_id=None,
                ruleset=None,
                playstyle=Playstyle.VANILLA,
                category=None,
                selected_mods=None,
                header_only=True,
            )
        )
        return _to_getscores_outcome(result)


def _leaderboard_request_from_getscores(
    request: GetscoresRequest,
    *,
    user_id: int | None,
) -> BeatmapLeaderboardRequest:
    selection = request.leaderboard_selection
    return BeatmapLeaderboardRequest(
        beatmap_checksum=request.checksum_md5,
        filename=request.filename,
        beatmapset_id_hint=request.beatmapset_id_hint,
        viewer_user_id=user_id,
        ruleset=_ruleset_from_request(request),
        playstyle=Playstyle.VANILLA,
        category=None if selection is None else selection.category,
        selected_mods=None if selection is None else selection.selected_mods,
        header_only=True if selection is None else selection.header_only,
    )


def _ruleset_from_request(request: GetscoresRequest) -> Ruleset | None:
    if request.mode is None:
        return None
    try:
        return Ruleset(request.mode)
    except ValueError:
        return None


def _to_getscores_outcome(result: BeatmapLeaderboardResult) -> GetscoresResolveOutcome:
    kind = _to_getscores_kind(result.kind)
    reason = _to_getscores_reason(result.reason)
    if result.header is None:
        return GetscoresResolveOutcome(
            kind=kind,
            header=None,
            reason=reason,
        )

    return GetscoresResolveOutcome(
        kind=kind,
        header=GetscoresResolvedHeader(
            beatmap=result.header.beatmap,
            beatmapset=result.header.beatmapset,
            personal_best=(
                None
                if result.personal_best is None
                else _leaderboard_row_to_getscores_row(result.personal_best)
            ),
            score_rows=tuple(_leaderboard_row_to_getscores_row(row) for row in result.rows),
        ),
        reason=reason,
    )


def _to_getscores_kind(kind: BeatmapLeaderboardOutcomeKind) -> GetscoresOutcomeKind:
    return {
        BeatmapLeaderboardOutcomeKind.HEADER: GetscoresOutcomeKind.HEADER,
        BeatmapLeaderboardOutcomeKind.UNAVAILABLE: GetscoresOutcomeKind.UNAVAILABLE,
        BeatmapLeaderboardOutcomeKind.UPDATE_AVAILABLE: GetscoresOutcomeKind.UPDATE_AVAILABLE,
    }[kind]


def _to_getscores_reason(
    reason: BeatmapLeaderboardResolveReason,
) -> GetscoresResolveReason:
    return {
        BeatmapLeaderboardResolveReason.KNOWN_CHECKSUM: GetscoresResolveReason.KNOWN_CHECKSUM,
        BeatmapLeaderboardResolveReason.KNOWN_FILENAME_IN_SET: (
            GetscoresResolveReason.KNOWN_FILENAME_IN_SET
        ),
        BeatmapLeaderboardResolveReason.NOT_SUBMITTED: GetscoresResolveReason.NOT_SUBMITTED,
        BeatmapLeaderboardResolveReason.NOT_FOUND: GetscoresResolveReason.NOT_FOUND,
        BeatmapLeaderboardResolveReason.PENDING_FETCH: GetscoresResolveReason.PENDING_FETCH,
        BeatmapLeaderboardResolveReason.FAILED_METADATA: GetscoresResolveReason.FAILED_METADATA,
        BeatmapLeaderboardResolveReason.UPDATE_AVAILABLE: GetscoresResolveReason.UPDATE_AVAILABLE,
    }[reason]


def _leaderboard_row_to_getscores_row(
    row: BeatmapLeaderboardRow,
) -> GetscoresPersonalBest:
    return GetscoresPersonalBest(
        score_id=row.score_id,
        user_id=row.user_id,
        username=row.username,
        beatmap_id=row.beatmap_id,
        ruleset=row.ruleset,
        playstyle=row.playstyle,
        score=row.score,
        max_combo=row.max_combo,
        n50=row.hit_counts.n50,
        n100=row.hit_counts.n100,
        n300=row.hit_counts.n300,
        miss=row.hit_counts.miss,
        katu=row.hit_counts.katu,
        geki=row.hit_counts.geki,
        perfect=row.perfect,
        mods=row.displayed_mods.to_persistence_bitmask(),
        rank=row.rank,
        submitted_at=row.submitted_at,
        has_replay=row.has_replay,
    )


__all__ = ["BeatmapScoreListingQuery"]
