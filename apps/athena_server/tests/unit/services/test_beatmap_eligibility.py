"""Beatmap eligibilityの状態判定とdeny log契約を検証する.

official status. local override. mirror信頼設定から導かれるscore受理と
構造化observability eventを対象にする.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from structlog.testing import capture_logs

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)
from osu_server.services.queries.beatmaps.mirror import (
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
    """eligibility判定用のbeatmapを指定状態で生成する.

    Args:
        status (BeatmapRankStatus): official statusとして設定する状態.
        local_status_override (LocalBeatmapStatus | None): 公式状態へ重ねるlocal状態.
        source (BeatmapMetadataSource): status metadataの取得source.
        verified (BeatmapSourceVerification): sourceの検証状態.

    Returns:
        Beatmap: eligibility serviceへ渡す固定属性のbeatmap.
    """
    return Beatmap(
        id=2_000,
        beatmapset_id=1_000,
        checksum_md5="0123456789abcdef0123456789abcdef",
        mode=BeatmapMode.OSU,
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
    """Local overrideがない場合にofficial statusを返すことを検証する.

    Returns:
        None: APPROVEDのofficial statusを返すことを検証して完了する.
    """
    beatmap = _make_beatmap(BeatmapRankStatus.APPROVED)

    assert BeatmapStatusResolver().effective_status(beatmap) is BeatmapRankStatus.APPROVED


def test_status_resolver_uses_local_override_when_present() -> None:
    """Local overrideがある場合にその状態を優先することを検証する.

    Returns:
        None: RANKED overrideをeffective statusとして返すことを検証して完了する.
    """
    beatmap = _make_beatmap(
        BeatmapRankStatus.PENDING,
        local_status_override=LocalBeatmapStatus.RANKED,
    )

    assert BeatmapStatusResolver().effective_status(beatmap) is BeatmapRankStatus.RANKED


def test_status_resolver_rejects_approved_local_override() -> None:
    """APPROVEDをlocal overrideとして拒否することを検証する.

    Returns:
        None: ValueErrorを送出する入力制約を検証して完了する.
    """
    with pytest.raises(ValueError, match="Approved"):
        BeatmapStatusResolver().validate_local_override(BeatmapRankStatus.APPROVED)


def test_status_resolver_uses_domain_local_override_validation() -> None:
    """Status resolverがdomain modelと同じlocal override制約を使うことを検証する.

    Returns:
        None: 不正な型がdomain共通messageのTypeErrorになることを検証して完了する.
    """
    with pytest.raises(
        TypeError,
        match="local_status_override must be a LocalBeatmapStatus or None",
    ):
        BeatmapStatusResolver().validate_local_override("ranked")


@pytest.mark.parametrize("status", [BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED])
def test_ranked_and_approved_award_ranked_pp(status: BeatmapRankStatus) -> None:
    """ranked扱いの状態がranked PPを許可することを検証する.

    Args:
        status (BeatmapRankStatus): RANKEDまたはAPPROVEDの公式状態.

    Returns:
        None: score受理. leaderboard. ranked PPのprojectionを検証して完了する.
    """
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
    """LOVED状態がloved PPだけを許可することを検証する.

    Returns:
        None: score受理とloved PPのprojectionを検証して完了する.
    """
    eligibility = BeatmapEligibilityService().evaluate(_make_beatmap(BeatmapRankStatus.LOVED))

    assert eligibility.accepts_scores is True
    assert eligibility.has_leaderboard is True
    assert eligibility.awards_ranked_pp is False
    assert eligibility.awards_loved_pp is True
    assert eligibility.requires_osu_file_for_pp is True
    assert eligibility.accepts_failed_scores is True


def test_qualified_accepts_scores_without_pp() -> None:
    """QUALIFIED状態がscoreを受理しPPを許可しないことを検証する.

    Returns:
        None: leaderboardとPP flagのprojectionを検証して完了する.
    """
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
    """対象外の公式状態がscoreとPPを拒否することを検証する.

    Args:
        status (BeatmapRankStatus): score対象外として扱う公式状態.

    Returns:
        None: status_not_eligible理由を含む拒否projectionを検証して完了する.
    """
    eligibility = BeatmapEligibilityService().evaluate(_make_beatmap(status))

    assert eligibility.accepts_scores is False
    assert eligibility.has_leaderboard is False
    assert eligibility.awards_ranked_pp is False
    assert eligibility.awards_loved_pp is False
    assert eligibility.accepts_failed_scores is False
    assert eligibility.denial_reason == "status_not_eligible"


def test_untrusted_mirror_status_does_not_grant_eligibility() -> None:
    """未信頼mirrorのstatusがeligibilityを付与しないことを検証する.

    Returns:
        None: untrusted_mirror_status理由の拒否projectionを検証して完了する.
    """
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
    """信頼設定したmirror statusが未検証のままeligibilityを付与することを検証する.

    Returns:
        None: mirror由来かつ未検証の許可projectionを検証して完了する.
    """
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
    """Local overrideが未信頼mirror metadataへeligibilityを付与できることを検証する.

    Returns:
        None: local判断による許可projectionを検証して完了する.
    """
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


# ---------------------------------------------------------------------------
# Eligibility observability logging tests (16.5)
# ---------------------------------------------------------------------------


class TestEligibilityLogging:
    """BeatmapEligibilityServiceの構造化eligibility logを検証する."""

    def test_logs_eligibility_denied_for_ineligible_status(self) -> None:
        """対象外statusの拒否時にeventを記録することを検証する.

        Returns:
            None: beatmap IDとstatus_not_eligible理由を持つeventを検証して完了する.
        """
        beatmap = _make_beatmap(BeatmapRankStatus.GRAVEYARD)
        service = BeatmapEligibilityService()

        with capture_logs() as logs:
            _ = service.evaluate(beatmap)

        denied = [e for e in logs if e.get("event") == "beatmap_eligibility_denied"]
        assert len(denied) == 1
        assert denied[0]["beatmap_id"] == beatmap.id
        assert denied[0]["denial_reason"] == "status_not_eligible"
        assert denied[0]["effective_status"] == BeatmapRankStatus.GRAVEYARD.value

    def test_logs_eligibility_denied_for_untrusted_mirror(self) -> None:
        """未信頼mirror statusの拒否時にeventを記録することを検証する.

        Returns:
            None: mirror由来を示す拒否eventを検証して完了する.
        """
        beatmap = _make_beatmap(
            BeatmapRankStatus.RANKED,
            source=BeatmapMetadataSource.MIRROR,
            verified=BeatmapSourceVerification.UNVERIFIED,
        )
        service = BeatmapEligibilityService()

        with capture_logs() as logs:
            _ = service.evaluate(beatmap)

        denied = [e for e in logs if e.get("event") == "beatmap_eligibility_denied"]
        assert len(denied) == 1
        assert denied[0]["beatmap_id"] == beatmap.id
        assert denied[0]["denial_reason"] == "untrusted_mirror_status"
        assert denied[0]["is_mirror_derived"] is True

    def test_no_log_when_eligibility_granted(self) -> None:
        """eligibilityを付与した場合に拒否eventを記録しないことを検証する.

        Returns:
            None: deny eventが空であることを検証して完了する.
        """
        beatmap = _make_beatmap(BeatmapRankStatus.RANKED)
        service = BeatmapEligibilityService()

        with capture_logs() as logs:
            _ = service.evaluate(beatmap)

        denied = [e for e in logs if e.get("event") == "beatmap_eligibility_denied"]
        assert len(denied) == 0

    def test_denial_log_includes_official_verification_state(self) -> None:
        """拒否logが公式sourceの検証状態を含むことを検証する.

        Returns:
            None: official verificationとmirror由来flagを検証して完了する.
        """
        beatmap = _make_beatmap(
            BeatmapRankStatus.PENDING,
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
        )
        service = BeatmapEligibilityService()

        with capture_logs() as logs:
            _ = service.evaluate(beatmap)

        denied = [e for e in logs if e.get("event") == "beatmap_eligibility_denied"]
        assert len(denied) == 1
        assert denied[0]["is_officially_verified"] is True
        assert denied[0]["is_mirror_derived"] is False
