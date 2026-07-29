"""Beatmap performance best projection の command-side repository 契約."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from osu_server.domain.scores.score import Playstyle, Ruleset


@dataclass(frozen=True, slots=True)
class BeatmapPerformanceBestScope:
    """1 user と 1 Beatmap scope に対する performance best の自然キー.

    Attributes:
        user_id (int): Scope を所有する正の User ID.
        beatmap_id (int): Scope が対象とする正の Beatmap ID.
        ruleset (Ruleset): Scope が対象とする ruleset.
        playstyle (Playstyle): Scope が対象とする playstyle.
    """

    user_id: int
    beatmap_id: int
    ruleset: Ruleset
    playstyle: Playstyle

    def __post_init__(self) -> None:
        """Scope の永続化キーとして不正な非正値を拒否する.

        Returns:
            None: user_id と beatmap_id が自然キーの制約を満たすことを示す.

        Raises:
            ValueError: user_id または beatmap_id が正でない場合に送出する.
        """
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if self.beatmap_id <= 0:
            msg = "beatmap_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapPerformanceBest:
    """PP 優先で選ばれた 1 user と 1 Beatmap scope の projection row.

    Attributes:
        id (int | None): 永続化済み row の正の識別子.未保存時は None.
        scope (BeatmapPerformanceBestScope): Row が代表する自然キー.
        score_id (int): Row が参照する正の Score ID.
        performance_calculation_id (int): Row の PP を提供した正の calculation ID.
        pp (Decimal): 非負の performance point.
        accuracy (float): 0から1までの accuracy.
        score (int): 非負の score 値.
        submitted_at (datetime): Score の submission 日時.
    """

    id: int | None
    scope: BeatmapPerformanceBestScope
    score_id: int
    performance_calculation_id: int
    pp: Decimal
    accuracy: float
    score: int
    submitted_at: datetime

    def __post_init__(self) -> None:
        """Projection row として永続化できない値を拒否する.

        Returns:
            None: Row の識別子と数値が永続化制約を満たすことを示す.

        Raises:
            ValueError: 識別子,PP,accuracy,または score が許容範囲外の場合に送出する.
        """
        _validate_projection_values(
            row_id=self.id,
            score_id=self.score_id,
            performance_calculation_id=self.performance_calculation_id,
            pp=self.pp,
            accuracy=self.accuracy,
            score=self.score,
        )


@dataclass(frozen=True, slots=True)
class UpsertBeatmapPerformanceBest:
    """候補が現在 row より上位のときだけ projection row を置き換える command.

    Attributes:
        scope (BeatmapPerformanceBestScope): 比較対象となる自然キー.
        score_id (int): 候補が参照する正の Score ID.
        performance_calculation_id (int): 候補の PP を提供した正の calculation ID.
        pp (Decimal): 比較に使う非負の performance point.
        accuracy (float): 比較に使う0から1までの accuracy.
        score (int): 比較に使う非負の score 値.
        submitted_at (datetime): Tie-break に使う Score の submission 日時.
    """

    scope: BeatmapPerformanceBestScope
    score_id: int
    performance_calculation_id: int
    pp: Decimal
    accuracy: float
    score: int
    submitted_at: datetime

    def __post_init__(self) -> None:
        """Upsert 候補として永続化できない値を拒否する.

        Returns:
            None: 候補の識別子と数値が永続化制約を満たすことを示す.

        Raises:
            ValueError: 識別子,PP,accuracy,または score が許容範囲外の場合に送出する.
        """
        _validate_projection_values(
            row_id=None,
            score_id=self.score_id,
            performance_calculation_id=self.performance_calculation_id,
            pp=self.pp,
            accuracy=self.accuracy,
            score=self.score,
        )


@dataclass(frozen=True, slots=True)
class BeatmapPerformanceBestUserProjectionSlice:
    """1 user 分を rebuild するときに置き換える projection slice.

    Attributes:
        user_id (int): 再構築する正の User ID.
    """

    user_id: int

    def __post_init__(self) -> None:
        """Slice key として不正な非正 user_id を拒否する.

        Returns:
            None: user_id が projection slice の制約を満たすことを示す.

        Raises:
            ValueError: user_id が正でない場合に送出する.
        """
        if self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BeatmapPerformanceBestBeatmapProjectionSlice:
    """1つ以上の Beatmap 分を rebuild するときに置き換える projection slice.

    Attributes:
        beatmap_ids (tuple[int, ...]): 再構築する1件以上の正の Beatmap ID.
    """

    beatmap_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        """Slice key として不正な空値または非正 beatmap_id を拒否する.

        Returns:
            None: beatmap_ids が projection slice の制約を満たすことを示す.

        Raises:
            ValueError: beatmap_ids が空の場合,または非正の ID を含む場合に送出する.
        """
        if len(self.beatmap_ids) == 0:
            msg = "beatmap_ids must not be empty"
            raise ValueError(msg)
        if any(beatmap_id <= 0 for beatmap_id in self.beatmap_ids):
            msg = "beatmap_ids must be positive"
            raise ValueError(msg)


type BeatmapPerformanceBestProjectionSlice = (
    BeatmapPerformanceBestUserProjectionSlice | BeatmapPerformanceBestBeatmapProjectionSlice
)


class BeatmapPerformanceBestCommandRepository(Protocol):
    """Performance best projection の mutation と consistency check の port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def lock_scope(self, scope: BeatmapPerformanceBestScope) -> None:
        """同一 performance best scope の refresh を transaction 内で直列化する.

        Args:
            scope (BeatmapPerformanceBestScope): 排他制御する自然キー.

        Returns:
            None: Transaction 終了まで scope lock を保持したことを示す.
        """
        ...

    async def get_best(
        self,
        scope: BeatmapPerformanceBestScope,
    ) -> BeatmapPerformanceBest | None:
        """指定 scope の現在の performance best row を返す.

        Args:
            scope (BeatmapPerformanceBestScope): 取得する自然キー.

        Returns:
            BeatmapPerformanceBest | None: 現在の row.未登録時は None.
        """
        ...

    async def upsert_if_better(
        self,
        command: UpsertBeatmapPerformanceBest,
    ) -> BeatmapPerformanceBest:
        """候補が PP 優先順で現在 row より上位なら永続化して現在 row を返す.

        Args:
            command (UpsertBeatmapPerformanceBest): 比較して保存する候補.

        Returns:
            BeatmapPerformanceBest: Upsert 後に scope を代表する row.
        """
        ...

    async def replace_projection_slice(
        self,
        slice_: BeatmapPerformanceBestProjectionSlice,
        rows: Iterable[UpsertBeatmapPerformanceBest],
    ) -> None:
        """Rebuild 済み slice 内の projection rows を supplied rows で置き換える.

        Args:
            slice_ (BeatmapPerformanceBestProjectionSlice): 置換する projection の範囲.
            rows (Iterable[UpsertBeatmapPerformanceBest]): 範囲内の置換後 row 群.

        Returns:
            None: 範囲の置換が完了したことを示す.

        Raises:
            ValueError: rows に slice 外の scope が含まれる場合に送出する.
        """
        ...

    async def replace_scope(
        self,
        scope: BeatmapPerformanceBestScope,
        row: UpsertBeatmapPerformanceBest | None,
    ) -> BeatmapPerformanceBest | None:
        """1 scope の projection row を supplied winner で置換し,winner がなければ削除する.

        Args:
            scope (BeatmapPerformanceBestScope): 置換する自然キー.
            row (UpsertBeatmapPerformanceBest | None): 新しい winner.None の場合は削除する.

        Returns:
            BeatmapPerformanceBest | None: 置換後の row.削除時は None.

        Raises:
            ValueError: row が None でなく,scope と異なる natural key を持つ場合に送出する.
        """
        ...

    async def list_user_bests(
        self,
        *,
        user_id: int,
        ruleset: Ruleset,
        playstyle: Playstyle,
    ) -> tuple[BeatmapPerformanceBest, ...]:
        """指定 user/mode の current performance best rows を返す.

        Args:
            user_id (int): 取得対象 user の識別子.
            ruleset (Ruleset): 絞り込む ruleset.
            playstyle (Playstyle): 絞り込む playstyle.

        Returns:
            tuple[BeatmapPerformanceBest, ...]: 現在の performance best row 群.
        """
        ...


def _validate_projection_values(
    *,
    row_id: int | None,
    score_id: int,
    performance_calculation_id: int,
    pp: Decimal,
    accuracy: float,
    score: int,
) -> None:
    """Performance best projection に保存できる数値範囲を検証する.

    Args:
        row_id (int | None): 既存 row の識別子.新規候補では None.
        score_id (int): 対応する score の識別子.
        performance_calculation_id (int): 対応する計算結果の識別子.
        pp (Decimal): 非負でなければならない performance point.
        accuracy (float): 0から1までの accuracy.
        score (int): 非負でなければならない score 値.

    Returns:
        None: 全ての値が projection の永続化制約を満たすことを示す.

    Raises:
        ValueError: いずれかの識別子または数値が永続化制約に違反する場合に送出する.
    """
    if row_id is not None and row_id <= 0:
        msg = "id must be positive when present"
        raise ValueError(msg)
    if score_id <= 0:
        msg = "score_id must be positive"
        raise ValueError(msg)
    if performance_calculation_id <= 0:
        msg = "performance_calculation_id must be positive"
        raise ValueError(msg)
    if pp < Decimal("0"):
        msg = "pp must not be negative"
        raise ValueError(msg)
    if not 0 <= accuracy <= 1:
        msg = "accuracy must be between 0 and 1"
        raise ValueError(msg)
    if score < 0:
        msg = "score must not be negative"
        raise ValueError(msg)
