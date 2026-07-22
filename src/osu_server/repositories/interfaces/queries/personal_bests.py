"""Score listing 用 personal best read-only repository contract を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.compatibility.stable.getscores import GetscoresPersonalBest
    from osu_server.domain.scores.personal_best import LeaderboardCategory
    from osu_server.domain.scores.score import Playstyle, Ruleset


class PersonalBestQueryRepository(Protocol):
    """Score listing view 用 personal best projection read を定義する.

    Notes:
        この Protocol は current personal best projection を返すだけである. Projection を更新せず
        Command Unit of Work を開始または commit/rollback しない.
    """

    async def get_personal_best(
        self,
        *,
        user_id: int,
        beatmap_id: int,
        ruleset: Ruleset,
        playstyle: Playstyle,
        category: LeaderboardCategory,
    ) -> GetscoresPersonalBest | None:
        """一つの leaderboard scope の current personal best score listing を返す.

        Args:
            user_id (int): Personal best owner の User ID.
            beatmap_id (int): 対象 Beatmap ID.
            ruleset (Ruleset): 対象 ruleset.
            playstyle (Playstyle): 対象 playstyle.
            category (LeaderboardCategory): Score listing の leaderboard category.

        Returns:
            GetscoresPersonalBest | None: Current personal best listing. 該当しない場合は `None`.
        """
        ...
