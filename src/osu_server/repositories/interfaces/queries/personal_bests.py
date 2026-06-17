"""Query-side personal best repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.compatibility.stable.getscores import GetscoresPersonalBest
    from osu_server.domain.scores.personal_best import LeaderboardCategory
    from osu_server.domain.scores.score import Playstyle, Ruleset


class PersonalBestQueryRepository(Protocol):
    """Read-only personal best projection access for score listing views."""

    async def get_personal_best(
        self,
        *,
        user_id: int,
        beatmap_id: int,
        ruleset: Ruleset,
        playstyle: Playstyle,
        category: LeaderboardCategory,
    ) -> GetscoresPersonalBest | None:
        """Return the current personal best score listing for one scope."""
        ...
