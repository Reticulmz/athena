"""Beatmap leaderboard projection の read-only query repository contract を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.shared.checksums import MD5_HEX_LENGTH, is_lowercase_md5_hexdigest

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from osu_server.domain.scores.mods import ModCombination
    from osu_server.domain.scores.score import Playstyle, Ruleset


@dataclass(slots=True, frozen=True)
class ScoreHitCounts:
    """Leaderboard 表示に使う source Score の hit count を表す.

    Attributes:
        n50 (int): 50 hit の件数.
        n100 (int): 100 hit の件数.
        n300 (int): 300 hit の件数.
        miss (int): Miss の件数.
        katu (int): Katu の件数.
        geki (int): Geki の件数.
    """

    n50: int
    n100: int
    n300: int
    miss: int
    katu: int
    geki: int


@dataclass(slots=True, frozen=True)
class BeatmapLeaderboardRow:
    """Beatmap leaderboard listing 用の表示可能な row を表す.

    Attributes:
        score_id (int): Source Score の識別子.
        user_id (int): Score owner の User ID.
        username (str): 表示する owner username.
        beatmap_id (int): 対象 Beatmap ID.
        ruleset (Ruleset): 対象 ruleset.
        playstyle (Playstyle): 対象 playstyle.
        score (int): 表示する score value.
        max_combo (int): Source Score の最大 combo.
        hit_counts (ScoreHitCounts): 表示する hit count.
        perfect (bool): Full combo を表す flag.
        displayed_mods (ModCombination): 表示する canonical mod combination.
        rank (int): Filtered leaderboard 内の actual rank.
        submitted_at (datetime): Score の提出日時.
        has_replay (bool): Replay attachment が利用可能かを表す flag.
        pp (Decimal | None): 算出済み performance point. 未算出時は `None`.
    """

    score_id: int
    user_id: int
    username: str
    beatmap_id: int
    ruleset: Ruleset
    playstyle: Playstyle
    score: int
    max_combo: int
    hit_counts: ScoreHitCounts
    perfect: bool
    displayed_mods: ModCombination
    rank: int
    submitted_at: datetime
    has_replay: bool
    pp: Decimal | None = None


@dataclass(slots=True, frozen=True)
class LeaderboardReadScope:
    """Beatmap Leaderboard の read-time filter を表す.

    Attributes:
        beatmap_id (int): 対象 Beatmap ID. 正の値でなければならない.
        beatmap_checksum (str): 現在の 32 文字小文字 16 進数 Beatmap checksum.
        ruleset (Ruleset): 対象 ruleset.
        playstyle (Playstyle): 対象 playstyle.
        category (LeaderboardCategory): 表示する category.
        selected_mods (ModCombination | None): Selected Mods category の mod combination.
        country (str | None): Country category の owner country filter.
        eligible_user_ids (tuple[int, ...] | None): Friends category の対象 User ID 群.

    Notes:
        `selected_mods` は `SELECTED_MODS` category のときだけ指定する. Country と Friends
        category の追加 filter は caller が適切な値を渡す.
    """

    beatmap_id: int
    beatmap_checksum: str
    ruleset: Ruleset
    playstyle: Playstyle
    category: LeaderboardCategory
    selected_mods: ModCombination | None = None
    country: str | None = None
    eligible_user_ids: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        """Leaderboard scope の不変条件を検証する.

        Returns:
            None: Scope が有効であることを表す.

        Raises:
            ValueError: Beatmap ID が正でない場合.
            ValueError: Beatmap checksum が 32 文字小文字 16 進数でない場合.
            ValueError: Category と `selected_mods` の指定が一致しない場合.
        """
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)
        if not is_lowercase_md5_hexdigest(self.beatmap_checksum):
            msg = (
                f"beatmap_checksum must be a {MD5_HEX_LENGTH}-character "
                "lowercase hexadecimal string"
            )
            raise ValueError(msg)
        is_selected_mods = self.category is LeaderboardCategory.SELECTED_MODS
        if is_selected_mods and self.selected_mods is None:
            msg = "selected-mods scope requires selected_mods"
            raise ValueError(msg)
        if not is_selected_mods and self.selected_mods is not None:
            msg = "selected_mods is only valid for selected-mods scope"
            raise ValueError(msg)


class BeatmapLeaderboardQueryRepository(Protocol):
    """Beatmap leaderboard projection への read-only access を定義する.

    Notes:
        この Protocol は display projection を読むだけであり row や projection state を
        変更しない. Command Unit of Work を開かず commit/rollback も所有しない.
    """

    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        """Filtered scope 内の rank 済み top row を返す.

        Args:
            scope (LeaderboardReadScope): Filter と category を表す read scope.
            limit (int): 返却する最大 row 数.

        Returns:
            tuple[BeatmapLeaderboardRow, ...]: Rank を含む最大 `limit` 件の display row.

        Notes:
            返す row は read projection でありこの operation は projection を更新しない.
        """
        ...

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        """Filtered scope 内の viewer の row と actual rank を返す.

        Args:
            scope (LeaderboardReadScope): Filter と category を表す read scope.
            viewer_user_id (int): Personal best を取得する viewer の User ID.

        Returns:
            BeatmapLeaderboardRow | None: Viewer の row. 該当 score がない場合は `None`.

        Notes:
            この operation は projection を更新せず transaction の commit/rollback を行わない.
        """
        ...


__all__ = [
    "BeatmapLeaderboardQueryRepository",
    "BeatmapLeaderboardRow",
    "LeaderboardReadScope",
    "ScoreHitCounts",
]
