"""Committed in-memory state から getscores Personal Best を読む adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.compatibility.stable.getscores import GetscoresPersonalBest

if TYPE_CHECKING:
    from osu_server.domain.scores.personal_best import LeaderboardCategory
    from osu_server.domain.scores.score import Playstyle, Ruleset, Score
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryPersonalBestQueryRepository:
    """Committed in-memory Personal Best projection を読む read-only repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        各 query は snapshot だけを読み, Personal Best, Score, Replay state を変更しない.
    """

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.
        """
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
        """指定 scope の User Personal Best を getscores read model に変換する.

        Args:
            user_id (int): Personal Best を取得する User の ID.
            beatmap_id (int): Personal Best の Beatmap ID.
            ruleset (Ruleset): 絞り込む ruleset.
            playstyle (Playstyle): 絞り込む playstyle.
            category (LeaderboardCategory): 絞り込む leaderboard category.

        Returns:
            GetscoresPersonalBest | None: scope に対応する score, username, rank, replay 有無を含む
            read model. projection, score, score ID, または User がなければ None.

        Notes:
            rank は同じ Beatmap/ruleset/playstyle/category で ranking_value がより大きい
            projection の件数に 1 を加えて算出する. Replay は score ID が一致する record が一件でも
            あれば存在する.
        """
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
    """Domain Score を getscores Personal Best read model に変換する.

    Args:
        score (Score): ID が設定済みの Personal Best Score.
        username (str): score owner の username.
        rank (int): scope 内で算出済みの順位.
        has_replay (bool): score に対応する Replay の有無.

    Returns:
        GetscoresPersonalBest: Score field と指定された presentation field を転記した read model.

    Raises:
        AssertionError: score.id が None の場合.
    """
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
