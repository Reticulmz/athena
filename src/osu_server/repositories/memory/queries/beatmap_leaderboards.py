"""In-memory query-side Beatmap Leaderboard repository."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.leaderboard_visibility import is_leaderboard_visible_user
from osu_server.domain.scores.leaderboards import ALL_MODS_FILTER_KEY
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    BeatmapLeaderboardRow,
    ScoreHitCounts,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from osu_server.domain.identity.users import User
    from osu_server.domain.scores.score import Score
    from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
        BeatmapLeaderboardUserBest,
    )
    from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
        LeaderboardReadScope,
    )
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

_VISIBLE_BEATMAP_STATUSES = frozenset(
    {
        BeatmapRankStatus.RANKED,
        BeatmapRankStatus.APPROVED,
        BeatmapRankStatus.LOVED,
        BeatmapRankStatus.QUALIFIED,
    }
)
_PP_VISIBLE_BEATMAP_STATUSES = frozenset(
    {
        BeatmapRankStatus.RANKED,
        BeatmapRankStatus.APPROVED,
    }
)
_MAX_QUERY_LIMIT = 50


@dataclass(slots=True, frozen=True)
class _LeaderboardCandidate:
    projection: BeatmapLeaderboardUserBest
    score: Score
    user: User


class InMemoryBeatmapLeaderboardQueryRepository:
    """Read-only Beatmap Leaderboard adapter over committed memory state."""

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        state = self._factory.snapshot()
        candidates = _ranked_candidates(state, scope)
        capped_limit = min(max(limit, 0), _MAX_QUERY_LIMIT)
        return tuple(
            _candidate_to_row(state=state, candidate=candidate, rank=rank)
            for rank, candidate in enumerate(candidates[:capped_limit], start=1)
        )

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        state = self._factory.snapshot()
        candidates = _ranked_candidates(state, scope)
        for rank, candidate in enumerate(candidates, start=1):
            if candidate.projection.scope.user_id == viewer_user_id:
                return _candidate_to_row(state=state, candidate=candidate, rank=rank)
        return None


def _ranked_candidates(
    state: InMemoryCommandRepositoryState,
    scope: LeaderboardReadScope,
) -> tuple[_LeaderboardCandidate, ...]:
    if not _beatmap_is_currently_visible(state, scope):
        return ()

    candidates = [
        candidate
        for row in state.beatmap_leaderboard_user_bests_by_id.values()
        if (candidate := _candidate_from_projection(state, scope, row)) is not None
    ]
    candidates.sort(key=lambda candidate: candidate.projection.rank_key.ordering_key)
    return tuple(candidates)


def _beatmap_is_currently_visible(
    state: InMemoryCommandRepositoryState,
    scope: LeaderboardReadScope,
) -> bool:
    beatmap = state.beatmaps_by_id.get(scope.beatmap_id)
    if beatmap is None:
        return False
    return (
        beatmap.checksum_md5 == scope.beatmap_checksum
        and beatmap.effective_status in _VISIBLE_BEATMAP_STATUSES
    )


def _candidate_from_projection(
    state: InMemoryCommandRepositoryState,
    scope: LeaderboardReadScope,
    projection: BeatmapLeaderboardUserBest,
) -> _LeaderboardCandidate | None:
    if not _projection_matches_scope(projection, scope):
        return None

    score = state.scores_by_id.get(projection.score_id)
    if score is None or score.id is None:
        return None
    user = state.users_by_id.get(score.user_id)
    if user is None:
        return None
    if (
        not _score_is_currently_eligible(state, scope, score)
        or not _user_is_visible(state, user.id)
        or not _passes_category_filter(scope, user.id, user.country)
    ):
        return None
    return _LeaderboardCandidate(projection=projection, score=score, user=user)


def _projection_matches_scope(
    projection: BeatmapLeaderboardUserBest,
    scope: LeaderboardReadScope,
) -> bool:
    projection_scope = projection.scope
    required_mod_filter_key = (
        scope.mod_filter_key
        if scope.category is LeaderboardCategory.SELECTED_MODS
        else ALL_MODS_FILTER_KEY
    )
    return (
        projection_scope.beatmap_id == scope.beatmap_id
        and projection_scope.ruleset is scope.ruleset
        and projection_scope.playstyle is scope.playstyle
        and projection_scope.mod_filter_key == required_mod_filter_key
    )


def _score_is_currently_eligible(
    state: InMemoryCommandRepositoryState,
    scope: LeaderboardReadScope,
    score: Score,
) -> bool:
    score_id = score.id
    if score_id is None:
        return False
    return (
        score.beatmap_id == scope.beatmap_id
        and score.beatmap_checksum == scope.beatmap_checksum
        and score.ruleset is scope.ruleset
        and score.playstyle is scope.playstyle
        and score.passed
        and state.score_leaderboard_eligibility_by_id.get(score_id, False)
    )


def _user_is_visible(state: InMemoryCommandRepositoryState, user_id: int) -> bool:
    privileges = Privileges.NONE
    for role_id in state.role_ids_by_user_id.get(user_id, set()):
        role = state.roles_by_id.get(role_id)
        if role is not None:
            privileges |= role.permissions
    return is_leaderboard_visible_user(privileges)


def _passes_category_filter(
    scope: LeaderboardReadScope,
    user_id: int,
    country: str,
) -> bool:
    if scope.category is LeaderboardCategory.COUNTRY:
        return scope.country is not None and scope.country != "XX" and country == scope.country
    if scope.category is LeaderboardCategory.FRIENDS:
        return scope.eligible_user_ids is not None and user_id in scope.eligible_user_ids
    return True


def _candidate_to_row(
    *,
    state: InMemoryCommandRepositoryState,
    candidate: _LeaderboardCandidate,
    rank: int,
) -> BeatmapLeaderboardRow:
    score = candidate.score
    assert score.id is not None
    return BeatmapLeaderboardRow(
        score_id=score.id,
        user_id=score.user_id,
        username=candidate.user.username,
        beatmap_id=score.beatmap_id,
        ruleset=score.ruleset,
        playstyle=score.playstyle,
        score=score.score,
        max_combo=score.max_combo,
        hit_counts=ScoreHitCounts(
            n50=score.n50,
            n100=score.n100,
            n300=score.n300,
            miss=score.miss,
            katu=score.katu,
            geki=score.geki,
        ),
        perfect=score.perfect,
        displayed_mods=score.mods,
        rank=rank,
        submitted_at=score.submitted_at,
        has_replay=any(replay.score_id == score.id for replay in state.replays_by_id.values()),
        pp=_current_pp_for_score(state, score),
    )


def _current_pp_for_score(
    state: InMemoryCommandRepositoryState,
    score: Score,
) -> Decimal | None:
    if score.id is None:
        return None
    beatmap = state.beatmaps_by_id.get(score.beatmap_id)
    if beatmap is None or beatmap.effective_status not in _PP_VISIBLE_BEATMAP_STATUSES:
        return None

    calculation_id = state.current_performance_calculation_id_by_score_id.get(score.id)
    if calculation_id is None:
        return None
    calculation = state.performance_calculations_by_id.get(calculation_id)
    if calculation is None or calculation.score_id != score.id or not calculation.is_current:
        return None
    return calculation.pp


__all__ = ["InMemoryBeatmapLeaderboardQueryRepository"]
