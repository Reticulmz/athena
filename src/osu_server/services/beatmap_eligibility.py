from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from osu_server.domain.beatmap import (
    Beatmap,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)

_SCORE_ACCEPTING_STATUSES: Final = frozenset(
    {
        BeatmapRankStatus.RANKED,
        BeatmapRankStatus.APPROVED,
        BeatmapRankStatus.LOVED,
        BeatmapRankStatus.QUALIFIED,
    }
)
_RANKED_PP_STATUSES: Final = frozenset({BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED})
_LOVED_PP_STATUSES: Final = frozenset({BeatmapRankStatus.LOVED})


@dataclass(slots=True, frozen=True)
class BeatmapEligibility:
    accepts_scores: bool
    has_leaderboard: bool
    awards_ranked_pp: bool
    awards_loved_pp: bool
    requires_osu_file_for_pp: bool
    is_officially_verified: bool
    is_mirror_derived: bool
    accepts_failed_scores: bool
    failed_scores_have_leaderboard: bool
    failed_scores_update_best_score: bool
    failed_scores_award_ranked_pp: bool
    failed_scores_award_loved_pp: bool
    denial_reason: str | None


class BeatmapStatusResolver:
    def effective_status(self, beatmap: Beatmap) -> BeatmapRankStatus:
        return beatmap.effective_status

    def validate_local_override(self, status: object) -> None:
        if status is None:
            return
        if status is BeatmapRankStatus.APPROVED:
            msg = "Approved cannot be used as a local override"
            raise ValueError(msg)
        if not isinstance(status, LocalBeatmapStatus):
            msg = "local override must be a LocalBeatmapStatus or None"
            raise TypeError(msg)


class BeatmapEligibilityService:
    def __init__(self, status_resolver: BeatmapStatusResolver | None = None) -> None:
        self._status_resolver: BeatmapStatusResolver = status_resolver or BeatmapStatusResolver()

    def evaluate(
        self,
        beatmap: Beatmap,
        *,
        mirror_trust_enabled: bool = False,
    ) -> BeatmapEligibility:
        status = self._status_resolver.effective_status(beatmap)
        is_mirror_sourced = beatmap.official_status_source is BeatmapMetadataSource.MIRROR
        is_mirror_derived = is_mirror_sourced and beatmap.local_status_override is None
        is_officially_verified = (
            beatmap.official_status_verified is BeatmapSourceVerification.VERIFIED
            and not is_mirror_sourced
        )

        if is_mirror_derived and not mirror_trust_enabled:
            return _denied_eligibility(
                denial_reason="untrusted_mirror_status",
                is_officially_verified=is_officially_verified,
                is_mirror_derived=True,
            )

        if status not in _SCORE_ACCEPTING_STATUSES:
            return _denied_eligibility(
                denial_reason="status_not_eligible",
                is_officially_verified=is_officially_verified,
                is_mirror_derived=is_mirror_derived,
            )

        awards_ranked_pp = status in _RANKED_PP_STATUSES
        awards_loved_pp = status in _LOVED_PP_STATUSES
        requires_osu_file_for_pp = awards_ranked_pp or awards_loved_pp

        return BeatmapEligibility(
            accepts_scores=True,
            has_leaderboard=True,
            awards_ranked_pp=awards_ranked_pp,
            awards_loved_pp=awards_loved_pp,
            requires_osu_file_for_pp=requires_osu_file_for_pp,
            is_officially_verified=is_officially_verified,
            is_mirror_derived=is_mirror_derived,
            accepts_failed_scores=True,
            failed_scores_have_leaderboard=False,
            failed_scores_update_best_score=False,
            failed_scores_award_ranked_pp=False,
            failed_scores_award_loved_pp=False,
            denial_reason=None,
        )


def _denied_eligibility(
    *,
    denial_reason: str,
    is_officially_verified: bool,
    is_mirror_derived: bool,
) -> BeatmapEligibility:
    return BeatmapEligibility(
        accepts_scores=False,
        has_leaderboard=False,
        awards_ranked_pp=False,
        awards_loved_pp=False,
        requires_osu_file_for_pp=False,
        is_officially_verified=is_officially_verified,
        is_mirror_derived=is_mirror_derived,
        accepts_failed_scores=False,
        failed_scores_have_leaderboard=False,
        failed_scores_update_best_score=False,
        failed_scores_award_ranked_pp=False,
        failed_scores_award_loved_pp=False,
        denial_reason=denial_reason,
    )
