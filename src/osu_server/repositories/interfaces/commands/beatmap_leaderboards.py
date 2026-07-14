"""Command-side beatmap leaderboard projection repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from osu_server.shared.checksums import MD5_HEX_LENGTH, is_lowercase_md5_hexdigest

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.scores.leaderboards import ScoreRankKey
    from osu_server.domain.scores.mods import ModCombination
    from osu_server.domain.scores.score import Playstyle, Ruleset


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardUserScope:
    """Mod を問わないユーザー leaderboard scope を表す.

    Attributes:
        beatmap_id (int): 対象 Beatmap ID. 正の値でなければならない.
        beatmap_checksum (str): projectionが表す32文字小文字16進数のcurrent checksum.
        ruleset (Ruleset): 対象 ruleset.
        playstyle (Playstyle): 対象 playstyle.
        user_id (int): score owner の User ID. 正の値でなければならない.
    """

    beatmap_id: int
    beatmap_checksum: str
    ruleset: Ruleset
    playstyle: Playstyle
    user_id: int

    def __post_init__(self) -> None:
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)
        if not is_lowercase_md5_hexdigest(self.beatmap_checksum):
            msg = (
                f"beatmap_checksum must be a {MD5_HEX_LENGTH}-character "
                "lowercase hexadecimal string"
            )
            raise ValueError(msg)
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardUserBestScope(BeatmapLeaderboardUserScope):
    """raw Mod bitflag ごとのユーザー最高 score scope を表す.

    Attributes:
        mods (ModCombination): score に保存された raw Mod bitflag.
    """

    mods: ModCombination


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardUserBest:
    """1ユーザーの raw Mod scope に対応する score-priority projection 行."""

    id: int | None
    scope: BeatmapLeaderboardUserBestScope
    score_id: int
    rank_key: ScoreRankKey

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            msg = "id must be positive when present"
            raise ValueError(msg)
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.rank_key.score_id != self.score_id:
            msg = "rank_key score_id must match score_id"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class UpsertBeatmapLeaderboardUserBest:
    """候補が上位の場合に raw Mod scope の projection 行を置換する command."""

    scope: BeatmapLeaderboardUserBestScope
    score_id: int
    rank_key: ScoreRankKey

    def __post_init__(self) -> None:
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.rank_key.score_id != self.score_id:
            msg = "rank_key score_id must match score_id"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardUserProjectionSlice:
    """Projection slice rebuilt for a single user."""

    user_id: int

    def __post_init__(self) -> None:
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardBeatmapProjectionSlice:
    """Projection slice rebuilt for one or more beatmaps."""

    beatmap_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.beatmap_ids) == 0:
            msg = "beatmap_ids must not be empty"
            raise ValueError(msg)
        if any(beatmap_id <= 0 for beatmap_id in self.beatmap_ids):
            msg = "beatmap_ids must be positive"
            raise ValueError(msg)


type BeatmapLeaderboardProjectionSlice = (
    BeatmapLeaderboardUserProjectionSlice | BeatmapLeaderboardBeatmapProjectionSlice
)


class BeatmapLeaderboardCommandRepository(Protocol):
    """raw Mod scope ごとのユーザー最高 score を更新する command port."""

    async def lock_rebuild(self) -> None:
        """projection rebuildをsubmit更新とtransaction内で直列化する.

        Returns:
            None: transaction終了までexclusive rebuild lockを保持したことを示す.
        """
        ...

    async def lock_scope(self, scope: BeatmapLeaderboardUserScope) -> None:
        """submit更新をrebuildおよび同一scope更新とtransaction内で直列化する.

        Args:
            scope (BeatmapLeaderboardUserScope): Modを含まないserialization scope.

        Returns:
            None: shared rebuild guardとexclusive scope lockを保持したことを示す.
        """
        ...

    async def get_user_best(
        self,
        scope: BeatmapLeaderboardUserBestScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """指定 raw Mod scope の現在の最高 score を返す.

        Args:
            scope (BeatmapLeaderboardUserBestScope): 検索する raw Mod scope.

        Returns:
            BeatmapLeaderboardUserBest | None: 保存済みの最高 score. 未登録時は None.
        """
        ...

    async def get_global_user_best(
        self,
        scope: BeatmapLeaderboardUserScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """全 raw Mod scope からユーザーの Global 最高 score を返す.

        Args:
            scope (BeatmapLeaderboardUserScope): Mod を含まない検索 scope.

        Returns:
            BeatmapLeaderboardUserBest | None: Global 最高 score. 未登録時は None.
        """
        ...

    async def upsert_if_better(
        self,
        command: UpsertBeatmapLeaderboardUserBest,
    ) -> BeatmapLeaderboardUserBest:
        """候補が現在値より上位の場合だけ保存する.

        Args:
            command (UpsertBeatmapLeaderboardUserBest): 比較対象の候補 score.

        Returns:
            BeatmapLeaderboardUserBest: upsert 後の最高 score.
        """
        ...

    async def replace_projection_slice(
        self,
        slice_: BeatmapLeaderboardProjectionSlice,
        rows: Iterable[UpsertBeatmapLeaderboardUserBest],
    ) -> None:
        """再構築対象 slice の行を指定された Mod別 best で置換する.

        Args:
            slice_ (BeatmapLeaderboardProjectionSlice): user または Beatmap の再構築範囲.
            rows (Iterable[UpsertBeatmapLeaderboardUserBest]): 置換後の最高 score 群.

        Returns:
            None: 永続化が完了したことを示す.
        """
        ...
