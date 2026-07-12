from __future__ import annotations

from osu_server.domain.compatibility.stable.getscores import (
    GetscoresRequest,
    StableLeaderboardSelection,
)
from osu_server.domain.scores.mods import Mod
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.transports.stable.web_legacy.mappers import StableGetscoresLeaderboardMapper


def test_local_leaderboard_type_maps_to_global_category() -> None:
    selection = _map(leaderboard_type=1)

    assert selection.category is LeaderboardCategory.GLOBAL
    assert selection.selected_mods is None
    assert selection.header_only is False
    assert selection.unsupported is False


def test_selected_mods_leaderboard_type_preserves_raw_stable_mods() -> None:
    raw_mods = int(Mod.NIGHTCORE | Mod.DOUBLE_TIME)
    selection = _map(leaderboard_type=2, mods=raw_mods)

    assert selection.category is LeaderboardCategory.SELECTED_MODS
    assert selection.selected_mods is not None
    assert selection.selected_mods.to_persistence_bitmask() == raw_mods
    assert selection.header_only is False
    assert selection.unsupported is False


def test_friends_leaderboard_type_maps_to_friends_category() -> None:
    selection = _map(leaderboard_type=3, mods=int(Mod.DOUBLE_TIME))

    assert selection.category is LeaderboardCategory.FRIENDS
    assert selection.selected_mods is None
    assert selection.header_only is False
    assert selection.unsupported is False


def test_country_leaderboard_type_maps_to_country_category() -> None:
    selection = _map(leaderboard_type=4, mods=int(Mod.DOUBLE_TIME))

    assert selection.category is LeaderboardCategory.COUNTRY
    assert selection.selected_mods is None
    assert selection.header_only is False
    assert selection.unsupported is False


def test_unsupported_leaderboard_type_is_header_only_without_global_fallback() -> None:
    selection = _map(leaderboard_type=99)

    assert selection.category is None
    assert selection.selected_mods is None
    assert selection.header_only is True
    assert selection.unsupported is True


def test_song_select_request_is_header_only() -> None:
    selection = _map(leaderboard_type=1, song_select=True)

    assert selection.category is LeaderboardCategory.GLOBAL
    assert selection.header_only is True
    assert selection.unsupported is False


def test_mirror_selected_mods_filter_uses_exact_raw_bitflag() -> None:
    selection = _map(leaderboard_type=2, mods=int(Mod.MIRROR))

    assert selection.category is LeaderboardCategory.SELECTED_MODS
    assert selection.selected_mods is not None
    assert selection.selected_mods.to_persistence_bitmask() == int(Mod.MIRROR)
    assert selection.header_only is False
    assert selection.unsupported is False


def _map(
    *,
    leaderboard_type: int | None,
    mods: int | None = 0,
    song_select: bool | None = False,
) -> StableLeaderboardSelection:
    return StableGetscoresLeaderboardMapper().map_request(
        GetscoresRequest(
            checksum_md5="0123456789abcdef0123456789abcdef",
            filename=None,
            beatmapset_id_hint=None,
            mode=0,
            mods=mods,
            leaderboard_type=leaderboard_type,
            leaderboard_version=4,
            song_select=song_select,
        )
    )
