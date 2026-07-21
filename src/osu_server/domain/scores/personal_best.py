"""personal best projection と leaderboard category の domain 値を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Playstyle, Ruleset

UNKNOWN_COUNTRY_CODE = "XX"


class LeaderboardCategory(Enum):
    """beatmap leaderboard の表示 category を表す.

    Attributes:
        GLOBAL (LeaderboardCategory): 全 user を対象にする global leaderboard.
        COUNTRY (LeaderboardCategory): country で絞り込む leaderboard.
        SELECTED_MODS (LeaderboardCategory): 選択した mod 組み合わせで絞り込む leaderboard.
        FRIENDS (LeaderboardCategory): eligible な friend user だけを対象にする leaderboard.
    """

    GLOBAL = "global"
    COUNTRY = "country"
    SELECTED_MODS = "selected_mods"
    FRIENDS = "friends"


def country_leaderboard_is_available(country: str | None) -> bool:
    """Country leaderboard read が row を返せるか判定する.

    Args:
        country (str | None): 対象 user の country code. 未設定時は None.

    Returns:
        bool: country が None でも unknown sentinel `XX` でもない場合は True.

    Notes:
        country code の正規化や ISO code としての妥当性は検証しない.
    """
    return country is not None and country != UNKNOWN_COUNTRY_CODE


def friends_leaderboard_is_available(eligible_user_ids: tuple[int, ...] | None) -> bool:
    """Friends leaderboard read が row を返せる候補を持つか判定する.

    Args:
        eligible_user_ids (tuple[int, ...] | None): scope に含められる friend user ID 群.

    Returns:
        bool: ID 群が None ではなく一件以上を含む場合は True.

    Notes:
        user ID の正性や重複はこの predicate で検証しない.
    """
    return bool(eligible_user_ids)


@dataclass(slots=True, frozen=True)
class PersonalBestScope:
    """一つの personal best projection を一意にする scope を表す.

    Attributes:
        user_id (int): personal best を持つ user の正の ID.
        beatmap_id (int): personal best の対象 beatmap の正の ID.
        ruleset (Ruleset): beatmap を play した ruleset.
        playstyle (Playstyle): beatmap を play した playstyle.
        category (LeaderboardCategory): personal best の leaderboard category.
    """

    user_id: int
    beatmap_id: int
    ruleset: Ruleset
    playstyle: Playstyle
    category: LeaderboardCategory

    def __post_init__(self) -> None:
        """Personal best scope の ID が正であることを検証する.

        Returns:
            None: user_id と beatmap_id が有効であることを示す.

        Raises:
            ValueError: user_id または beatmap_id が 0 以下の場合.
        """
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class PersonalBest:
    """一つの personal best scope における現在の代表 score を表す.

    Attributes:
        id (int | None): 永続化後の personal best ID. 未永続化時は None.
        scope (PersonalBestScope): この projection を一意にする user と beatmap の scope.
        score_id (int): 現在の代表 score の正の ID.
        ranking_value (int): 代表 score の順位比較に使う非負値.
    """

    id: int | None
    scope: PersonalBestScope
    score_id: int
    ranking_value: int

    def __post_init__(self) -> None:
        """Personal best の識別子と ranking value を検証する.

        Returns:
            None: ID と ranking_value が domain invariant を満たすことを示す.

        Raises:
            ValueError: 指定された ID が 0 以下、または ranking_value が負の場合.
        """
        if self.id is not None and self.id <= 0:
            msg = "personal best id must be positive"
            raise ValueError(msg)
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.ranking_value < 0:
            msg = "ranking_value must not be negative"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class PersonalBestDelta:
    """score submission 前後の personal best snapshot 差分を表す.

    Attributes:
        before_score_id (int | None): 更新前の代表 score ID. 未登録時は None.
        before_score (int | None): 更新前の代表 score 値. 未登録時は None.
        before_max_combo (int | None): 更新前の代表 score の最大 combo. 未登録時は None.
        before_accuracy (float | None): 更新前の代表 score の accuracy. 未登録時は None.
        after_score_id (int | None): 更新後の代表 score ID. 未登録時は None.
        after_score (int | None): 更新後の代表 score 値. 未登録時は None.
        after_max_combo (int | None): 更新後の代表 score の最大 combo. 未登録時は None.
        after_accuracy (float | None): 更新後の代表 score の accuracy. 未登録時は None.
        updated (bool): submission により personal best が更新された場合は True.

    Notes:
        この差分値自体は score の範囲、ID の正性、before/after の整合性を検証しない.
    """

    before_score_id: int | None
    before_score: int | None
    before_max_combo: int | None
    before_accuracy: float | None
    after_score_id: int | None
    after_score: int | None
    after_max_combo: int | None
    after_accuracy: float | None
    updated: bool


def score_beats_personal_best(candidate_value: int, current_value: int | None) -> bool:
    """候補 ranking value が現在の personal best を更新するか判定する.

    Args:
        candidate_value (int): 比較する候補 score の ranking value.
        current_value (int | None): 現在の代表 score の ranking value. 未登録時は None.

    Returns:
        bool: 現在値がない、または候補値が現在値より厳密に大きい場合は True.

    Notes:
        同値の候補は既存 personal best を置き換えない. 値の範囲はこの関数で検証しない.
    """
    if current_value is None:
        return True
    return candidate_value > current_value
