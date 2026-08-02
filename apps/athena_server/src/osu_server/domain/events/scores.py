"""Score contextが発行するdomain eventを定義するmodule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.events import Event

if TYPE_CHECKING:
    from osu_server.domain.scores import Playstyle, Ruleset
    from osu_server.domain.scores.user_stats import UserCurrentStats


@dataclass(frozen=True, slots=True)
class CurrentUserStatsUpdated(Event):
    """Current UserStatsの更新を同一process内へ通知するeventを表す.

    Attributes:
        user_id (int): 更新対象userのID.
        ruleset (Ruleset): 更新されたscore ruleset.
        playstyle (Playstyle): 更新されたplaystyle.
        current_stats (UserCurrentStats | None): 更新後のcurrent stats. 統計が存在しない場合はNone.
    """

    user_id: int
    ruleset: Ruleset
    playstyle: Playstyle
    current_stats: UserCurrentStats | None = None


__all__ = ["CurrentUserStatsUpdated"]
