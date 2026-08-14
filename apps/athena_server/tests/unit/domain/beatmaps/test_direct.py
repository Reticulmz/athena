"""osu!direct検索projection domain契約を検証するmodule."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
    build_beatmapset_search_document,
    is_direct_searchable_beatmapset,
    map_external_status,
)

_UPDATED_AT = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


def test_search_document_activates_complete_usable_beatmapset() -> None:
    """UsableなBeatmapSetがactive検索projectionになる契約を検証する.

    Returns:
        None: 検索documentのactive状態と検索fieldを検証して完了する.
    """
    beatmapset = _beatmapset(beatmaps=(_beatmap(),))

    document = build_beatmapset_search_document(beatmapset, updated_at=_UPDATED_AT)

    assert is_direct_searchable_beatmapset(beatmapset) is True
    assert document.beatmapset_id == beatmapset.id
    assert document.is_active is True
    assert document.difficulty_names == "Normal"
    assert document.modes == (BeatmapMode.OSU,)
    assert document.status is BeatmapRankStatus.RANKED
    assert document.last_update_at == _UPDATED_AT


def test_search_document_prefers_set_level_last_updated_at() -> None:
    """Set-level更新日時がchild更新日時より優先されるdirect projection契約を検証する.

    Returns:
        None: BeatmapSet.official_last_updated_atがdocumentへ入ることを確認して完了する.
    """
    set_updated_at = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
    beatmapset = _beatmapset(
        beatmaps=(_beatmap(),),
        official_last_updated_at=set_updated_at,
    )

    document = build_beatmapset_search_document(beatmapset, updated_at=_UPDATED_AT)

    assert document.last_update_at == set_updated_at


def test_search_document_disables_childless_beatmapset() -> None:
    """ChildlessなBeatmapSetがinactive検索projectionになる契約を検証する.

    Returns:
        None: childがない場合のactive状態とfallback fieldを検証して完了する.
    """
    beatmapset = _beatmapset(beatmaps=())

    document = build_beatmapset_search_document(beatmapset, updated_at=_UPDATED_AT)

    assert is_direct_searchable_beatmapset(beatmapset) is False
    assert document.is_active is False
    assert document.difficulty_names == ""
    assert document.modes == (BeatmapMode.UNKNOWN,)


@pytest.mark.parametrize(
    "status",
    [
        BeatmapRankStatus.NOT_SUBMITTED,
        map_external_status("deleted"),
    ],
    ids=["not-submitted", "deleted"],
)
def test_search_document_disables_unusable_statuses(status: BeatmapRankStatus) -> None:
    """Deleted, not submitted状態がinactive projectionになる契約を検証する.

    Args:
        status (BeatmapRankStatus): 検証対象のcanonical BeatmapSet status.

    Returns:
        None: usable childがあってもset statusで検索対象外になることを確認して完了する.
    """
    beatmapset = _beatmapset(status=status, beatmaps=(_beatmap(status=status),))

    document = build_beatmapset_search_document(beatmapset, updated_at=_UPDATED_AT)

    assert is_direct_searchable_beatmapset(beatmapset) is False
    assert document.is_active is False
    assert document.status is status


def test_search_document_activates_graveyard_beatmapset() -> None:
    """GraveyardのBeatmapSetがdirect検索projectionに残る契約を検証する.

    Stable directにはGraveyard filterがあるため、usable childを持つgraveyard setは検索対象として
    `is_active`を維持することを確認する.

    Returns:
        None: Graveyard setのactive状態とstatusを検証して完了する.
    """
    beatmapset = _beatmapset(
        status=BeatmapRankStatus.GRAVEYARD,
        beatmaps=(_beatmap(status=BeatmapRankStatus.GRAVEYARD),),
    )

    document = build_beatmapset_search_document(beatmapset, updated_at=_UPDATED_AT)

    assert is_direct_searchable_beatmapset(beatmapset) is True
    assert document.is_active is True
    assert document.status is BeatmapRankStatus.GRAVEYARD


def _beatmapset(
    *,
    status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    beatmaps: tuple[Beatmap, ...],
    official_last_updated_at: datetime | None = None,
) -> BeatmapSet:
    """Projection test用のBeatmapSetを作る.

    Args:
        status (BeatmapRankStatus): BeatmapSetへ設定する公式公開状態.
        beatmaps (tuple[Beatmap, ...]): BeatmapSetに含めるchild beatmap列.
        official_last_updated_at (datetime | None): set-level更新日時. 未提供ならNone.

    Returns:
        BeatmapSet: 指定statusとchild構成を持つmetadata snapshot.
    """
    return BeatmapSet(
        id=1_000,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="Realazy",
        artist_unicode="かめりあ",
        title_unicode=None,
        official_status=status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=beatmaps,
        last_fetched_at=_UPDATED_AT,
        next_refresh_at=None,
        official_last_updated_at=official_last_updated_at,
    )


def _beatmap(
    *,
    status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    mode: BeatmapMode = BeatmapMode.OSU,
) -> Beatmap:
    """Projection test用のchild Beatmapを作る.

    Args:
        status (BeatmapRankStatus): Beatmapへ設定する公式公開状態.
        mode (BeatmapMode): Beatmapへ設定するgame mode.

    Returns:
        Beatmap: direct検索projectionで評価できるchild metadata.
    """
    return Beatmap(
        id=2_000,
        beatmapset_id=1_000,
        checksum_md5="0123456789abcdef0123456789abcdef",
        mode=mode,
        version="Normal",
        total_length=120,
        hit_length=100,
        max_combo=500,
        bpm=180.0,
        cs=4.0,
        od=8.0,
        ar=9.0,
        hp=6.0,
        difficulty_rating=4.5,
        official_status=status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_UPDATED_AT,
        next_refresh_at=None,
        official_last_updated_at=_UPDATED_AT,
    )
