"""score ingestionで使うbeatmap eligibilityをread-onlyに判定するserviceを定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog

from osu_server.domain.beatmaps import (
    BeatmapEligibility,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class BeatmapStatusResolver:
    """beatmapのeffective statusとlocal overrideの妥当性を判定する.

    Notes:
        APPROVEDはofficial status専用でありlocal overrideとしては受け付けない.
    """

    def effective_status(self, beatmap: Beatmap) -> BeatmapRankStatus:
        """beatmapに適用されるeffective rank statusを返す.

        Args:
            beatmap (Beatmap): effective statusを取得するbeatmap.

        Returns:
            BeatmapRankStatus: official statusとlocal overrideから決定済みのstatus.
        """
        return beatmap.effective_status

    def validate_local_override(self, status: object) -> None:
        """Local status overrideに許容される値か検証する.

        Args:
            status (object): local overrideとして保存する候補値.

        Returns:
            None: 許容されるNoneまたはLocalBeatmapStatusを検証して値を返さない.

        Raises:
            ValueError: statusがAPPROVEDの場合.
            TypeError: statusがNoneでもLocalBeatmapStatusでもない場合.
        """
        if status is None:
            return
        if status is BeatmapRankStatus.APPROVED:
            msg = "Approved cannot be used as a local override"
            raise ValueError(msg)
        if not isinstance(status, LocalBeatmapStatus):
            msg = "local override must be a LocalBeatmapStatus or None"
            raise TypeError(msg)


class BeatmapEligibilityService:
    """beatmap statusとsource trustからscore submissionのeligibilityを投影する.

    Attributes:
        _status_resolver (BeatmapStatusResolver): effective statusを解決するpolicy.
    """

    def __init__(self, status_resolver: BeatmapStatusResolver | None = None) -> None:
        """optionalなstatus resolverを保持し未指定時は既定resolverを作る.

        Args:
            status_resolver (BeatmapStatusResolver | None): status判定に使うresolver.
                Noneの場合は新しいBeatmapStatusResolverを使う.
        """
        self._status_resolver: BeatmapStatusResolver = status_resolver or BeatmapStatusResolver()

    def evaluate(
        self,
        beatmap: Beatmap,
        *,
        mirror_trust_enabled: bool = False,
    ) -> BeatmapEligibility:
        """beatmapがscoreを受け付ける条件とleaderboard条件を評価する.

        Args:
            beatmap (Beatmap): eligibilityを計算するbeatmap.
            mirror_trust_enabled (bool): mirror由来statusをscore受付に利用するか.

        Returns:
            BeatmapEligibility: score受付とPP付与とleaderboard利用可否を持つ投影結果.

        Notes:
            mirror由来かつlocal overrideのないstatusはmirror trustが無効なら拒否する.
        """
        status = self._status_resolver.effective_status(beatmap)
        is_mirror_sourced = beatmap.official_status_source is BeatmapMetadataSource.MIRROR
        is_mirror_derived = is_mirror_sourced and beatmap.local_status_override is None
        is_officially_verified = (
            beatmap.official_status_verified is BeatmapSourceVerification.VERIFIED
            and not is_mirror_sourced
        )

        if is_mirror_derived and not mirror_trust_enabled:
            logger.info(
                "beatmap_eligibility_denied",
                beatmap_id=beatmap.id,
                denial_reason="untrusted_mirror_status",
                effective_status=status.value,
                is_officially_verified=is_officially_verified,
                is_mirror_derived=True,
            )
            return _denied_eligibility(
                denial_reason="untrusted_mirror_status",
                is_officially_verified=is_officially_verified,
                is_mirror_derived=True,
            )

        if status not in _SCORE_ACCEPTING_STATUSES:
            logger.info(
                "beatmap_eligibility_denied",
                beatmap_id=beatmap.id,
                denial_reason="status_not_eligible",
                effective_status=status.value,
                is_officially_verified=is_officially_verified,
                is_mirror_derived=is_mirror_derived,
            )
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


def _denied_eligibility(
    *,
    denial_reason: str,
    is_officially_verified: bool,
    is_mirror_derived: bool,
) -> BeatmapEligibility:
    """score受付を拒否する一貫したeligibility投影を作る.

    Args:
        denial_reason (str): clientまたはdiagnosticへ返す拒否理由.
        is_officially_verified (bool): sourceがofficialに検証済みか.
        is_mirror_derived (bool): statusがmirror由来かつlocal overrideなしで決まったか.

    Returns:
        BeatmapEligibility: score受付とleaderboardとPP付与を全て拒否した結果.
    """
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
