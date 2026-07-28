"""Getscores read-only queryがfetchを開始せずunavailable outcomeを返すcontractを検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.compatibility.stable.getscores import (
    GetscoresOutcomeKind,
    GetscoresRequest,
    GetscoresResolveReason,
)
from osu_server.services.queries.scores.beatmap_leaderboards import BeatmapLeaderboardQuery
from osu_server.services.queries.scores.beatmap_score_listing import BeatmapScoreListingQuery

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapSet,
    )
    from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
        BeatmapLeaderboardRow,
        LeaderboardReadScope,
    )


class EmptyBeatmapScoreListingRepository:
    """常にbeatmap dataを返さないscore listing repository fakeを提供する."""

    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """Checksum lookupを常にnot foundとして返す.

        Args:
            checksum_md5 (str): lookupするbeatmap checksum.

        Returns:
            Beatmap | None: 常にNone. 既存beatmapがない状態を再現する.
        """
        _ = checksum_md5
        return None

    async def find_by_filename_in_beatmapset(
        self,
        beatmapset_id: int,
        original_filename: str,
    ) -> Beatmap | None:
        """Filenameとbeatmapsetによるlookupを常にnot foundとして返す.

        Args:
            beatmapset_id (int): lookupを制限するbeatmapset ID.
            original_filename (str): lookupするoriginal osu file名.

        Returns:
            Beatmap | None: 常にNone. filename fallbackが失敗する状態を再現する.
        """
        _ = (beatmapset_id, original_filename)
        return None

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Beatmapset lookupを常にnot foundとして返す.

        Args:
            beatmapset_id (int): lookupするbeatmapset ID.

        Returns:
            BeatmapSet | None: 常にNone. beatmapset metadataがない状態を再現する.
        """
        _ = beatmapset_id
        return None

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Fetch state lookupを常にnot foundとして返す.

        Args:
            target (BeatmapFetchTarget): fetch stateを要求するbeatmap target.

        Returns:
            BeatmapFetchRecord | None: 常にNone. background fetchを記録しない状態を再現する.
        """
        _ = target
        return None


class EmptyBeatmapLeaderboardRepository:
    """常にscore rowを返さないleaderboard repository fakeを提供する."""

    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        """Leaderboard top rowを常にempty tupleとして返す.

        Args:
            scope (LeaderboardReadScope): query対象のleaderboard scope.
            limit (int): 返却を要求する最大row数.

        Returns:
            tuple[BeatmapLeaderboardRow, ...]: 常にempty tuple. score rowがない状態を再現する.
        """
        _ = (scope, limit)
        return ()

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        """Viewerのpersonal bestを常にnot foundとして返す.

        Args:
            scope (LeaderboardReadScope): query対象のleaderboard scope.
            viewer_user_id (int): personal bestを取得するviewer user ID.

        Returns:
            BeatmapLeaderboardRow | None: 常にNone. personal bestがない状態を再現する.
        """
        _ = (scope, viewer_user_id)
        return None


async def test_getscores_query_returns_unavailable_without_starting_fetch() -> None:
    """Beatmap不在時にread-only getscores queryがfetchを開始しないcontractを検証する.

    Returns:
        None: NOT_FOUND reasonを持つUNAVAILABLE outcomeを確認して完了する.
    """
    query = BeatmapScoreListingQuery(
        BeatmapLeaderboardQuery(
            EmptyBeatmapScoreListingRepository(),
            EmptyBeatmapLeaderboardRepository(),
        )
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
