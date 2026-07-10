"""Rebuild Beatmap Leaderboard projections from source scores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.scores.leaderboards import (
    ScoreRankKey,
    projection_keys_for_score,
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
    """Request projection rebuild for all scores owned by one user."""

    user_id: int
    reason: str

    def __post_init__(self) -> None:
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if not self.reason:
            msg = "reason must not be empty"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class RebuildBeatmapLeaderboardsForBeatmapsetCommand:
    """Request projection rebuild for every beatmap in one beatmapset."""

    beatmapset_id: int
    reason: str

    def __post_init__(self) -> None:
        if self.beatmapset_id <= 0:
            msg = "beatmapset_id must be positive"
            raise ValueError(msg)
        if not self.reason:
            msg = "reason must not be empty"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class RebuildBeatmapLeaderboardsResult:
    """Summary of one rebuild command execution."""

    target_found: bool
    source_score_count: int
    projection_row_count: int


class RebuildBeatmapLeaderboardsForUserUseCase:
    """Rebuild a user's Beatmap Leaderboard projection slice."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForUserCommand,
    ) -> RebuildBeatmapLeaderboardsResult:
        async with self._unit_of_work_factory() as uow:
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
    """Rebuild projection rows for every beatmap in one beatmapset."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    ) -> RebuildBeatmapLeaderboardsResult:
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
        for mod_filter_key in projection_keys_for_score(score.mods):
            scope = BeatmapLeaderboardUserBestScope(
                beatmap_id=score.beatmap_id,
                ruleset=score.ruleset,
                playstyle=score.playstyle,
                user_id=score.user_id,
                mod_filter_key=mod_filter_key,
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
    return score.id is not None and score.passed and score.leaderboard_eligible_at_submission


def _projection_row_sort_key(
    row: UpsertBeatmapLeaderboardUserBest,
) -> tuple[int, int, int, int, int, tuple[int, datetime, int]]:
    return (
        row.scope.beatmap_id,
        row.scope.ruleset.value,
        row.scope.playstyle.value,
        row.scope.user_id,
        row.scope.mod_filter_key,
        row.rank_key.ordering_key,
    )
