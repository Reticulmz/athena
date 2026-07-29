"""beatmap leaderboard の順位比較と scope を表す domain 値を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.score import Playstyle, Ruleset


@dataclass(slots=True, frozen=True)
class ScoreRankKey:
    """beatmap leaderboard 候補 score の順位比較キーを表す.

    Attributes:
        score (int): 降順で比較する非負の score 値.
        submitted_at (datetime): 同 score 時に昇順で比較する送信日時.
        score_id (int): 同日時時に昇順で比較する正の score ID.
    """

    score: int
    submitted_at: datetime
    score_id: int

    def __post_init__(self) -> None:
        """順位比較に使う score と score ID の範囲を検証する.

        Returns:
            None: scoreとscore_idの検証を完了し, 呼び出し側へ値を返さずに終了する.

        Raises:
            ValueError: score が負,または score_id が 0 以下の場合.
        """
        if self.score < 0:
            msg = "score must not be negative"
            raise ValueError(msg)
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)

    @property
    def ordering_key(self) -> tuple[int, datetime, int]:
        """Score 降順,送信日時昇順,score ID 昇順の sort key を返す.

        Returns:
            tuple[int, datetime, int]: score を負にした値,submitted_at,score_id の順の key.

        Notes:
            Python の昇順 sort に渡すことで score の大きい候補を先頭に置ける.
        """
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
        """Leaderboard scope の beatmap ID が正であることを検証する.

        Returns:
            None: beatmap_idの検証を完了し, 呼び出し側へ値を返さずに終了する.

        Raises:
            ValueError: beatmap_id が 0 以下の場合.
        """
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
