"""Beatmap leaderboard domain policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self

from osu_server.domain.scores.mods import Mod, ModCombination

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.score import Playstyle, Ruleset


NO_MOD_FILTER_KEY: Final[int] = 0

_MIRROR_SELECTED_FILTER_KEY: Final[None] = None
_PREFERENCE_ONLY_NO_MODS: Final[Mod] = Mod.SUDDEN_DEATH | Mod.PERFECT | Mod.MIRROR


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


@dataclass(slots=True, frozen=True)
class LeaderboardModFilter:
    """Selected Mods 用の正規化済み filter を表す値オブジェクト.

    Attributes:
        key (int | None): 対応可能な filter の正規化済み非負キー. 対応不能時は None.
        unsupported (bool): stable client の初期 scope で対応しない filter かどうか.
    """

    key: int | None
    unsupported: bool = False

    def __post_init__(self) -> None:
        if self.unsupported and self.key is not None:
            msg = "unsupported mod filter must not expose a key"
            raise ValueError(msg)
        if not self.unsupported and self.key is not None and self.key < 0:
            msg = "mod filter key must be non-negative"
            raise ValueError(msg)

    @classmethod
    def unsupported_filter(cls) -> Self:
        """対応不能な Selected Mods filter を生成する.

        Returns:
            LeaderboardModFilter: key を公開しない対応不能 filter.
        """
        return cls(key=_MIRROR_SELECTED_FILTER_KEY, unsupported=True)

    @property
    def is_supported(self) -> bool:
        """filter を leaderboard query に適用できるか返す.

        Returns:
            bool: key を安全に利用できる場合は True.
        """
        return not self.unsupported

    @property
    def is_no_mod(self) -> bool:
        """NoMod filter かどうか返す.

        Returns:
            bool: 対応可能な key が NoMod を表す場合は True.
        """
        return self.is_supported and self.key == NO_MOD_FILTER_KEY


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


def filter_from_mod_combination(mods: ModCombination) -> LeaderboardModFilter:
    """Selected Mods の入力を正規化済み filter に変換する.

    Args:
        mods (ModCombination): stable client から変換済みの mod 組み合わせ.

    Returns:
        LeaderboardModFilter: DT/NC と SD/PF を統合した filter. Mirror は対応不能になる.
    """
    if mods.has(Mod.MIRROR):
        return LeaderboardModFilter.unsupported_filter()

    return LeaderboardModFilter(key=_canonical_filter_key(mods))


def selected_mod_filter_keys_for_score(mods: ModCombination) -> tuple[int, ...]:
    """score が一致する Selected Mods filter key を返す.

    Args:
        mods (ModCombination): score に保存された actual mods.

    Returns:
        tuple[int, ...]: 重複のない非負 filter key. all-mods scope は含めない.

    Notes:
        NoMod と SD/PF の両方に一致する score は複数 key を返す. これにより score 行を
        scope ごとに複製せず Selected Mods の互換 semantics を表現できる.
    """
    keys: list[int] = []
    if _is_no_mod_candidate(mods):
        keys.append(NO_MOD_FILTER_KEY)

    canonical_key = _canonical_filter_key(mods)
    if canonical_key != NO_MOD_FILTER_KEY and canonical_key not in keys:
        keys.append(canonical_key)

    return tuple(keys)


def score_matches_selected_mod_filter(mods: ModCombination, filter_key: int) -> bool:
    """score が Selected Mods filter に一致するか判定する.

    Args:
        mods (ModCombination): score に保存された actual mods.
        filter_key (int): 正規化済みの非負 filter key.

    Returns:
        bool: score が filter に一致する場合は True.

    Raises:
        ValueError: filter_key が負数の場合.
    """
    if filter_key < 0:
        msg = "filter_key must be non-negative"
        raise ValueError(msg)
    return filter_key in selected_mod_filter_keys_for_score(mods)


def _is_no_mod_candidate(mods: ModCombination) -> bool:
    gameplay_bits = _canonical_filter_key(mods) & ~int(_PREFERENCE_ONLY_NO_MODS)
    return gameplay_bits == 0


def _canonical_filter_key(mods: ModCombination) -> int:
    bits = mods.to_persistence_bitmask()
    if mods.has(Mod.NIGHTCORE):
        bits |= int(Mod.DOUBLE_TIME)
        bits &= ~int(Mod.NIGHTCORE)
    if mods.has(Mod.PERFECT):
        bits |= int(Mod.SUDDEN_DEATH)
        bits &= ~int(Mod.PERFECT)

    bits &= ~int(Mod.MIRROR)
    return bits


__all__ = [
    "NO_MOD_FILTER_KEY",
    "LeaderboardModFilter",
    "LeaderboardScope",
    "ScoreRankKey",
    "filter_from_mod_combination",
    "score_beats_current",
    "score_matches_selected_mod_filter",
    "selected_mod_filter_keys_for_score",
]
