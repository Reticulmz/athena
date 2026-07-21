"""Beatmap leaderboard projection の command-side repository 契約."""

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
    """Mod を問わない user leaderboard scope を表す.

    Attributes:
        beatmap_id (int): 対象 Beatmap ID. 正の値でなければならない.
        beatmap_checksum (str): Projection が表す32文字小文字16進数の current checksum.
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
        """Scope を永続化キーとして検証する.

        Returns:
            None: 値が永続化キーの制約を満たすことを確認したことを示す.

        Raises:
            ValueError: beatmap_id または user_id が正でない場合、あるいは checksum が
                32文字の小文字 MD5 hexadecimal string でない場合に送出する.
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
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardUserBestScope(BeatmapLeaderboardUserScope):
    """Raw Mod bitflag ごとの user 最高 score scope を表す.

    Attributes:
        mods (ModCombination): Score に保存された raw Mod bitflag.
    """

    mods: ModCombination


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardUserBest:
    """1 user の Raw Mod scope に対応する score-priority projection row.

    Attributes:
        id (int | None): 永続化済み row の正の識別子。未保存時は None.
        scope (BeatmapLeaderboardUserBestScope): Row が代表する user と Mod の自然キー.
        score_id (int): Row が参照する正の Score ID.
        rank_key (ScoreRankKey): Score priority を決める rank key。score_id と一致する.
    """

    id: int | None
    scope: BeatmapLeaderboardUserBestScope
    score_id: int
    rank_key: ScoreRankKey

    def __post_init__(self) -> None:
        """Projection row の識別子と rank key の整合性を検証する.

        Returns:
            None: Row の識別子と rank key が整合していることを示す.

        Raises:
            ValueError: 存在する id または score_id が正でない場合、あるいは rank_key の
                score_id が score_id と一致しない場合に送出する.
        """
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
    """候補が上位の場合に Raw Mod scope の projection row を置換する command.

    Attributes:
        scope (BeatmapLeaderboardUserBestScope): 比較対象となる user と Mod の自然キー.
        score_id (int): 候補となる正の Score ID.
        rank_key (ScoreRankKey): 候補の score priority を決める key。score_id と一致する.
    """

    scope: BeatmapLeaderboardUserBestScope
    score_id: int
    rank_key: ScoreRankKey

    def __post_init__(self) -> None:
        """Upsert 候補の score 識別子と rank key の整合性を検証する.

        Returns:
            None: 候補の score 識別子と rank key が整合していることを示す.

        Raises:
            ValueError: score_id が正でない場合、または rank_key の score_id が score_id と
                一致しない場合に送出する.
        """
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.rank_key.score_id != self.score_id:
            msg = "rank_key score_id must match score_id"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardUserProjectionSlice:
    """単一 user に対して再構築する projection slice.

    Attributes:
        user_id (int): 再構築対象 user の正の識別子.
    """

    user_id: int

    def __post_init__(self) -> None:
        """User projection slice の識別子を検証する.

        Returns:
            None: user_id が projection slice の制約を満たすことを示す.

        Raises:
            ValueError: user_id が正でない場合に送出する.
        """
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapLeaderboardBeatmapProjectionSlice:
    """1件以上の beatmap に対して再構築する projection slice.

    Attributes:
        beatmap_ids (tuple[int, ...]): 再構築対象となる正の Beatmap ID 群.
    """

    beatmap_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        """Beatmap projection slice の対象を検証する.

        Returns:
            None: beatmap_ids が projection slice の制約を満たすことを示す.

        Raises:
            ValueError: beatmap_ids が空の場合、または非正の ID を含む場合に送出する.
        """
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
    """Raw Mod scope ごとの user 最高 score を更新する command port.

    Notes:
        Runtime 実装は command Unit of Work から取得する。各操作は同じ Unit of Work が
        所有する transaction に参加し、この repository 自身は commit または rollback を
        実行しない.
    """

    async def lock_rebuild(self) -> None:
        """Projection rebuild を submit 更新と transaction 内で直列化する.

        Returns:
            None: Transaction 終了まで exclusive rebuild lock を保持したことを示す.
        """
        ...

    async def lock_scope(self, scope: BeatmapLeaderboardUserScope) -> None:
        """Submit 更新を rebuild および同一 scope 更新と transaction 内で直列化する.

        Args:
            scope (BeatmapLeaderboardUserScope): Mod を含まない serialization scope.

        Returns:
            None: Shared rebuild guard と exclusive scope lock を保持したことを示す.
        """
        ...

    async def get_user_best(
        self,
        scope: BeatmapLeaderboardUserBestScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """指定 Raw Mod scope の現在の最高 score を返す.

        Args:
            scope (BeatmapLeaderboardUserBestScope): 検索する Raw Mod scope.

        Returns:
            BeatmapLeaderboardUserBest | None: 保存済みの最高 score. 未登録時は None.
        """
        ...

    async def get_global_user_best(
        self,
        scope: BeatmapLeaderboardUserScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """全 Raw Mod scope から user の Global 最高 score を返す.

        Args:
            scope (BeatmapLeaderboardUserScope): Mod を含まない検索 scope.

        Returns:
            BeatmapLeaderboardUserBest | None: Global 最高 score。未登録時は None.
        """
        ...

    async def upsert_if_better(
        self,
        command: UpsertBeatmapLeaderboardUserBest,
    ) -> BeatmapLeaderboardUserBest:
        """候補が現在値より上位の場合だけ保存する.

        Args:
            command (UpsertBeatmapLeaderboardUserBest): 比較して保存する候補 score.

        Returns:
            BeatmapLeaderboardUserBest: upsert 後の最高 score.

        Raises:
            ValueError: score_id が別の leaderboard projection scope で既に使用されている場合に
                送出する.
        """
        ...

    async def replace_projection_slice(
        self,
        slice_: BeatmapLeaderboardProjectionSlice,
        rows: Iterable[UpsertBeatmapLeaderboardUserBest],
    ) -> None:
        """再構築対象 slice の row を指定された Mod 別 best で置換する.

        Args:
            slice_ (BeatmapLeaderboardProjectionSlice): User または Beatmap の再構築範囲.
            rows (Iterable[UpsertBeatmapLeaderboardUserBest]): 置換後の最高 score 群.

        Returns:
            None: Projection slice の置換が完了したことを示す.

        Raises:
            ValueError: rows に slice 外の scope が含まれる場合、または score_id が別の
                leaderboard projection scope で既に使用されている場合に送出する.
        """
        ...
