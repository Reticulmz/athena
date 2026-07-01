"""Score domain events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.events import Event

if TYPE_CHECKING:
    from osu_server.domain.scores import Playstyle, Ruleset
    from osu_server.domain.scores.user_stats import UserCurrentStats


@dataclass(frozen=True, slots=True)
class CurrentUserStatsUpdated(Event):
    """current UserStats が更新されたことを同一 process 内へ通知する event。"""

    user_id: int
    ruleset: Ruleset
    playstyle: Playstyle
    current_stats: UserCurrentStats | None = None


__all__ = ["CurrentUserStatsUpdated"]
