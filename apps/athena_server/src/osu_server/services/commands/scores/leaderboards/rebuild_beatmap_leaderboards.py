"""source scoreからbeatmap leaderboard projectionを再構築するuse-caseを定義する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.scores.leaderboards import (
    ScoreRankKey,
    score_beats_current,
)
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardBeatmapProjectionSlice,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
    UpsertBeatmapLeaderboardUserBest,
)

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.score import Score
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


@dataclass(slots=True, frozen=True)
class RebuildBeatmapLeaderboardsForUserCommand:
    """一人のuserが所有する全scoreのleaderboard projection再構築を要求する.

    Attributes:
        user_id (int): 再構築対象userのID.
        reason (str): 再構築を要求した契機を示す空でない診断値.
    """

    user_id: int
    reason: str

    def __post_init__(self) -> None:
        """対象user IDと再構築理由の入力制約を検証する.

        Returns:
            None: 有効なcommandを保持したまま検証を完了する.

        Raises:
            ValueError: user_idが非正,またはreasonが空文字列の場合.
        """
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if not self.reason:
            msg = "reason must not be empty"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class RebuildBeatmapLeaderboardsForBeatmapsetCommand:
    """一つのbeatmapsetに含まれる全beatmapのleaderboard projection再構築を要求する.

    Attributes:
        beatmapset_id (int): 再構築対象beatmapsetのID.
        reason (str): 再構築を要求した契機を示す空でない診断値.
    """

    beatmapset_id: int
    reason: str

    def __post_init__(self) -> None:
        """対象beatmapset IDと再構築理由の入力制約を検証する.

        Returns:
            None: 有効なcommandを保持したまま検証を完了する.

        Raises:
            ValueError: beatmapset_idが非正,またはreasonが空文字列の場合.
        """
        if self.beatmapset_id <= 0:
            msg = "beatmapset_id must be positive"
            raise ValueError(msg)
        if not self.reason:
            msg = "reason must not be empty"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class RebuildBeatmapLeaderboardsResult:
    """一回のleaderboard projection再構築の集計結果を表す.

    Attributes:
        target_found (bool): 要求されたuserまたはbeatmapsetが存在したか.
        source_score_count (int): 再構築時に読み込んだsource score数.
        projection_row_count (int): 置換したprojection row数.
    """

    target_found: bool
    source_score_count: int
    projection_row_count: int


class RebuildBeatmapLeaderboardsForUserUseCase:
    """一人のuserに属するbeatmap leaderboard projection sliceを再構築する.

    Attributes:
        _unit_of_work_factory (UnitOfWorkFactory): projection更新のtransactionを作るfactory.
    """

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        """projection再構築に使うUnit of Work factoryを保持する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): command transactionを開始するfactory.
        """
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForUserCommand,
    ) -> RebuildBeatmapLeaderboardsResult:
        """指定userのsource scoreからleaderboard projectionを置換する.

        Args:
            command (RebuildBeatmapLeaderboardsForUserCommand): 対象userと再構築理由.

        Returns:
            RebuildBeatmapLeaderboardsResult: 読み込んだscore数と置換したrow数.
        """
        async with self._unit_of_work_factory() as uow:
            await uow.beatmap_leaderboards.lock_rebuild()
            scores = await uow.scores.list_leaderboard_rebuild_candidates_for_user(command.user_id)
            rows = _projection_rows_from_scores(scores)
            await uow.beatmap_leaderboards.replace_projection_slice(
                BeatmapLeaderboardUserProjectionSlice(user_id=command.user_id),
                rows,
            )
            await uow.commit()
        return RebuildBeatmapLeaderboardsResult(
            target_found=True,
            source_score_count=len(scores),
            projection_row_count=len(rows),
        )


class RebuildBeatmapLeaderboardsForBeatmapsetUseCase:
    """一つのbeatmapsetに含まれる全beatmapのleaderboard projectionを再構築する.

    Attributes:
        _unit_of_work_factory (UnitOfWorkFactory): projection更新のtransactionを作るfactory.
    """

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        """projection再構築に使うUnit of Work factoryを保持する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): command transactionを開始するfactory.
        """
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    ) -> RebuildBeatmapLeaderboardsResult:
        """beatmapsetに含まれるscoreからleaderboard projectionを置換する.

        Args:
            command (RebuildBeatmapLeaderboardsForBeatmapsetCommand): 対象beatmapsetと再構築理由.

        Returns:
            RebuildBeatmapLeaderboardsResult: targetの存在と再構築したrow数.
        """
        async with self._unit_of_work_factory() as uow:
            beatmapset = await uow.beatmaps.get_beatmapset(command.beatmapset_id)
            if beatmapset is None:
                return RebuildBeatmapLeaderboardsResult(
                    target_found=False,
                    source_score_count=0,
                    projection_row_count=0,
                )

            beatmap_ids = tuple(beatmap.id for beatmap in beatmapset.beatmaps)
            if len(beatmap_ids) == 0:
                return RebuildBeatmapLeaderboardsResult(
                    target_found=True,
                    source_score_count=0,
                    projection_row_count=0,
                )

            await uow.beatmap_leaderboards.lock_rebuild()
            scores = await uow.scores.list_leaderboard_rebuild_candidates_for_beatmap_ids(
                beatmap_ids
            )
            rows = _projection_rows_from_scores(scores)
            await uow.beatmap_leaderboards.replace_projection_slice(
                BeatmapLeaderboardBeatmapProjectionSlice(beatmap_ids=beatmap_ids),
                rows,
            )
            await uow.commit()
        return RebuildBeatmapLeaderboardsResult(
            target_found=True,
            source_score_count=len(scores),
            projection_row_count=len(rows),
        )


def _projection_rows_from_scores(
    scores: tuple[Score, ...],
) -> tuple[UpsertBeatmapLeaderboardUserBest, ...]:
    """score群から各user/beatmap/mod scopeの最良projection rowを選択する.

    Args:
        scores (tuple[Score, ...]): leaderboard候補として読み込んだscore列.

    Returns:
        tuple[UpsertBeatmapLeaderboardUserBest, ...]: 決定的な順序で並べたscopeごとの最良row.
    """
    best_by_scope: dict[
        BeatmapLeaderboardUserBestScope,
        UpsertBeatmapLeaderboardUserBest,
    ] = {}
    for score in scores:
        if not _can_project_score(score):
            continue
        assert score.id is not None
        rank_key = ScoreRankKey(
            score=score.score,
            submitted_at=score.submitted_at,
            score_id=score.id,
        )
        scope = BeatmapLeaderboardUserBestScope(
            beatmap_id=score.beatmap_id,
            beatmap_checksum=score.beatmap_checksum,
            ruleset=score.ruleset,
            playstyle=score.playstyle,
            user_id=score.user_id,
            mods=score.mods,
        )
        current = best_by_scope.get(scope)
        if current is None or score_beats_current(rank_key, current.rank_key):
            best_by_scope[scope] = UpsertBeatmapLeaderboardUserBest(
                scope=scope,
                score_id=score.id,
                rank_key=rank_key,
            )
    return tuple(sorted(best_by_scope.values(), key=_projection_row_sort_key))


def _can_project_score(score: Score) -> bool:
    """scoreがleaderboard projectionの候補として利用可能か判定する.

    Args:
        score (Score): projection候補として検査するscore.

    Returns:
        bool: 永続IDを持ち,passedかつsubmission時にleaderboard eligibleならTrue.
    """
    return score.id is not None and score.passed and score.leaderboard_eligible_at_submission


def _projection_row_sort_key(
    row: UpsertBeatmapLeaderboardUserBest,
) -> tuple[int, int, int, int, tuple[int, datetime, int]]:
    """対象projection rowを決定的に並べるためのsort keyを返す.

    Args:
        row (UpsertBeatmapLeaderboardUserBest): 並べ替え対象のprojection row.

    Returns:
        tuple[int, int, int, int, tuple[int, datetime, int]]: scopeとrank keyから作る昇順key.
    """
    return (
        row.scope.beatmap_id,
        row.scope.ruleset.value,
        row.scope.playstyle.value,
        row.scope.user_id,
        row.rank_key.ordering_key,
    )
