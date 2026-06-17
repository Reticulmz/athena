"""Getscores read-only query boundary regression tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.compatibility.stable.getscores import (
    GetscoresOutcomeKind,
    GetscoresRequest,
    GetscoresResolveReason,
)
from osu_server.services.queries.scores.beatmap_score_listing import BeatmapScoreListingQuery

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap, BeatmapSet
    from osu_server.domain.compatibility.stable.getscores import GetscoresPersonalBest
    from osu_server.domain.scores.personal_best import LeaderboardCategory
    from osu_server.domain.scores.score import Playstyle, Ruleset


class EmptyBeatmapScoreListingRepository:
    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        _ = checksum_md5
        return None

    async def find_by_filename_in_beatmapset(
        self,
        beatmapset_id: int,
        original_filename: str,
    ) -> Beatmap | None:
        _ = (beatmapset_id, original_filename)
        return None

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        _ = beatmapset_id
        return None


class EmptyPersonalBestRepository:
    async def get_personal_best(
        self,
        *,
        user_id: int,
        beatmap_id: int,
        ruleset: Ruleset,
        playstyle: Playstyle,
        category: LeaderboardCategory,
    ) -> GetscoresPersonalBest | None:
        _ = (user_id, beatmap_id, ruleset, playstyle, category)
        return None


async def test_getscores_query_returns_unavailable_without_starting_fetch() -> None:
    query = BeatmapScoreListingQuery(
        EmptyBeatmapScoreListingRepository(),
        EmptyPersonalBestRepository(),
    )

    outcome = await query.resolve(
        GetscoresRequest(
            checksum_md5="0123456789abcdef0123456789abcdef",
            filename=None,
            beatmapset_id_hint=None,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        )
    )

    assert outcome.kind is GetscoresOutcomeKind.UNAVAILABLE
    assert outcome.header is None
    assert outcome.reason is GetscoresResolveReason.NOT_FOUND
