"""Beatmap leaderboard domain policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.score import Playstyle, Ruleset


@dataclass(slots=True, frozen=True)
class ScoreRankKey:
    """Score-priority ordering key for Beatmap Leaderboard candidates."""

    score: int
    submitted_at: datetime
    score_id: int

    def __post_init__(self) -> None:
        if self.score < 0:
            msg = "score must not be negative"
            raise ValueError(msg)
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)

    @property
    def ordering_key(self) -> tuple[int, datetime, int]:
        """Return a sortable key for score desc, submitted_at asc, score_id asc."""
        return (-self.score, self.submitted_at, self.score_id)


@dataclass(slots=True, frozen=True)
class LeaderboardScope:
    """Beatmap Leaderboard の基本 scope を表す値オブジェクト.

    Attributes:
        beatmap_id (int): 対象 Beatmap ID. 正の値でなければならない.
        ruleset (Ruleset): 対象 ruleset.
        playstyle (Playstyle): 対象 playstyle.
    """

    beatmap_id: int
    ruleset: Ruleset
    playstyle: Playstyle

    def __post_init__(self) -> None:
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)


def score_beats_current(candidate: ScoreRankKey, current: ScoreRankKey | None) -> bool:
    """候補 score が現在の代表 score より上位か判定する.

    Args:
        candidate (ScoreRankKey): 比較する候補 score の順位キー.
        current (ScoreRankKey | None): 現在の代表 score. 未登録時は None.

    Returns:
        bool: 候補を代表 score として採用すべき場合は True.
    """
    if current is None:
        return True
    return candidate.ordering_key < current.ordering_key


__all__ = [
    "LeaderboardScope",
    "ScoreRankKey",
    "score_beats_current",
]
