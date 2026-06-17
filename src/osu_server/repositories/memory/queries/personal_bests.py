"""In-memory query-side personal best repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.compatibility.stable.getscores import GetscoresPersonalBest

if TYPE_CHECKING:
    from osu_server.domain.scores.personal_best import LeaderboardCategory
    from osu_server.domain.scores.score import Playstyle, Ruleset, Score
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryPersonalBestQueryRepository:
    """Read-only personal best projection adapter over committed memory state."""

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def get_personal_best(
        self,
        *,
        user_id: int,
        beatmap_id: int,
        ruleset: Ruleset,
        playstyle: Playstyle,
        category: LeaderboardCategory,
    ) -> GetscoresPersonalBest | None:
        state = self._factory.snapshot()
        personal_best_id = state.personal_best_id_by_scope.get(
            (
                user_id,
                beatmap_id,
                ruleset.value,
                playstyle.value,
                category.value,
            )
        )
        if personal_best_id is None:
            return None

        personal_best = state.personal_bests_by_id.get(personal_best_id)
        if personal_best is None:
            return None

        score = state.scores_by_id.get(personal_best.score_id)
        if score is None or score.id is None:
            return None

        user = state.users_by_id.get(score.user_id)
        if user is None:
            return None

        rank = 1 + sum(
            1
            for other_personal_best in state.personal_bests_by_id.values()
            if other_personal_best.scope.beatmap_id == personal_best.scope.beatmap_id
            and other_personal_best.scope.ruleset is personal_best.scope.ruleset
            and other_personal_best.scope.playstyle is personal_best.scope.playstyle
            and other_personal_best.scope.category is personal_best.scope.category
            and other_personal_best.ranking_value > personal_best.ranking_value
        )
        has_replay = any(replay.score_id == score.id for replay in state.replays_by_id.values())
        return _score_listing_from_domain(
            score=score,
            username=user.username,
            rank=rank,
            has_replay=has_replay,
        )


def _score_listing_from_domain(
    *,
    score: Score,
    username: str,
    rank: int,
    has_replay: bool,
) -> GetscoresPersonalBest:
    assert score.id is not None
    return GetscoresPersonalBest(
        score_id=score.id,
        user_id=score.user_id,
        username=username,
        beatmap_id=score.beatmap_id,
        ruleset=score.ruleset,
        playstyle=score.playstyle,
        score=score.score,
        max_combo=score.max_combo,
        n50=score.n50,
        n100=score.n100,
        n300=score.n300,
        miss=score.miss,
        katu=score.katu,
        geki=score.geki,
        perfect=score.perfect,
        mods=score.mods.to_persistence_bitmask(),
        rank=rank,
        submitted_at=score.submitted_at,
        has_replay=has_replay,
    )
