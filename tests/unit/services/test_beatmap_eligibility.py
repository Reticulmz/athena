from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmap import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)
from osu_server.services.beatmap_eligibility import (
    BeatmapEligibilityService,
    BeatmapStatusResolver,
)

_NOW = datetime(2026, 6, 4, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)


def _make_beatmap(
    status: BeatmapRankStatus,
    *,
    local_status_override: LocalBeatmapStatus | None = None,
    source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
) -> Beatmap:
    return Beatmap(
        id=2_000,
        beatmapset_id=1_000,
        checksum_md5="0123456789abcdef0123456789abcdef",
        mode="osu",
        version="Another",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=status,
        official_status_source=source,
        official_status_verified=verified,
        local_status_override=local_status_override,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def test_status_resolver_uses_official_status_when_no_local_override() -> None:
    beatmap = _make_beatmap(BeatmapRankStatus.APPROVED)

    assert BeatmapStatusResolver().effective_status(beatmap) is BeatmapRankStatus.APPROVED


def test_status_resolver_uses_local_override_when_present() -> None:
    beatmap = _make_beatmap(
        BeatmapRankStatus.PENDING,
        local_status_override=LocalBeatmapStatus.RANKED,
    )

    assert BeatmapStatusResolver().effective_status(beatmap) is BeatmapRankStatus.RANKED


def test_status_resolver_rejects_approved_local_override() -> None:
    with pytest.raises(ValueError, match="Approved"):
        BeatmapStatusResolver().validate_local_override(BeatmapRankStatus.APPROVED)


@pytest.mark.parametrize("status", [BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED])
def test_ranked_and_approved_award_ranked_pp(status: BeatmapRankStatus) -> None:
    eligibility = BeatmapEligibilityService().evaluate(_make_beatmap(status))

    assert eligibility.accepts_scores is True
    assert eligibility.has_leaderboard is True
    assert eligibility.awards_ranked_pp is True
    assert eligibility.awards_loved_pp is False
    assert eligibility.requires_osu_file_for_pp is True
    assert eligibility.is_officially_verified is True
    assert eligibility.accepts_failed_scores is True
    assert eligibility.failed_scores_have_leaderboard is False
    assert eligibility.failed_scores_update_best_score is False
    assert eligibility.failed_scores_award_ranked_pp is False
    assert eligibility.failed_scores_award_loved_pp is False
    assert eligibility.is_mirror_derived is False
    assert eligibility.denial_reason is None


def test_loved_awards_loved_pp_without_ranked_pp() -> None:
    eligibility = BeatmapEligibilityService().evaluate(_make_beatmap(BeatmapRankStatus.LOVED))

    assert eligibility.accepts_scores is True
    assert eligibility.has_leaderboard is True
    assert eligibility.awards_ranked_pp is False
    assert eligibility.awards_loved_pp is True
    assert eligibility.requires_osu_file_for_pp is True
    assert eligibility.accepts_failed_scores is True


def test_qualified_accepts_scores_without_pp() -> None:
    eligibility = BeatmapEligibilityService().evaluate(_make_beatmap(BeatmapRankStatus.QUALIFIED))

    assert eligibility.accepts_scores is True
    assert eligibility.has_leaderboard is True
    assert eligibility.awards_ranked_pp is False
    assert eligibility.awards_loved_pp is False
    assert eligibility.requires_osu_file_for_pp is False
    assert eligibility.accepts_failed_scores is True


@pytest.mark.parametrize(
    "status",
    [
        BeatmapRankStatus.PENDING,
        BeatmapRankStatus.WIP,
        BeatmapRankStatus.GRAVEYARD,
        BeatmapRankStatus.NOT_SUBMITTED,
        BeatmapRankStatus.UNKNOWN,
    ],
)
def test_ineligible_statuses_reject_scores_and_pp(status: BeatmapRankStatus) -> None:
    eligibility = BeatmapEligibilityService().evaluate(_make_beatmap(status))

    assert eligibility.accepts_scores is False
    assert eligibility.has_leaderboard is False
    assert eligibility.awards_ranked_pp is False
    assert eligibility.awards_loved_pp is False
    assert eligibility.accepts_failed_scores is False
    assert eligibility.denial_reason == "status_not_eligible"


def test_untrusted_mirror_status_does_not_grant_eligibility() -> None:
    eligibility = BeatmapEligibilityService().evaluate(
        _make_beatmap(
            BeatmapRankStatus.RANKED,
            source=BeatmapMetadataSource.MIRROR,
            verified=BeatmapSourceVerification.UNVERIFIED,
        )
    )

    assert eligibility.accepts_scores is False
    assert eligibility.has_leaderboard is False
    assert eligibility.awards_ranked_pp is False
    assert eligibility.accepts_failed_scores is False
    assert eligibility.is_officially_verified is False
    assert eligibility.is_mirror_derived is True
    assert eligibility.denial_reason == "untrusted_mirror_status"


def test_trusted_mirror_status_can_grant_eligibility_but_remains_unverified() -> None:
    eligibility = BeatmapEligibilityService().evaluate(
        _make_beatmap(
            BeatmapRankStatus.RANKED,
            source=BeatmapMetadataSource.MIRROR,
            verified=BeatmapSourceVerification.UNVERIFIED,
        ),
        mirror_trust_enabled=True,
    )

    assert eligibility.accepts_scores is True
    assert eligibility.has_leaderboard is True
    assert eligibility.awards_ranked_pp is True
    assert eligibility.is_officially_verified is False
    assert eligibility.is_mirror_derived is True
    assert eligibility.denial_reason is None


def test_local_override_can_grant_eligibility_for_untrusted_mirror_metadata() -> None:
    eligibility = BeatmapEligibilityService().evaluate(
        _make_beatmap(
            BeatmapRankStatus.PENDING,
            local_status_override=LocalBeatmapStatus.RANKED,
            source=BeatmapMetadataSource.MIRROR,
            verified=BeatmapSourceVerification.UNVERIFIED,
        )
    )

    assert eligibility.accepts_scores is True
    assert eligibility.has_leaderboard is True
    assert eligibility.awards_ranked_pp is True
    assert eligibility.is_officially_verified is False
    assert eligibility.is_mirror_derived is False
    assert eligibility.denial_reason is None
