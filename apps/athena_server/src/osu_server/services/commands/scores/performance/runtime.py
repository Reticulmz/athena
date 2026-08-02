"""スコア performance command workflow の実行時設定を定義する."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING

from osu_server.domain.scores.performance import FormulaProfile
from osu_server.domain.scores.score import Playstyle

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_PERFORMANCE_BOUNDED_WAIT = timedelta(seconds=5)
DEFAULT_PERFORMANCE_WORKER_CHUNK_SIZE = 100
DEFAULT_PERFORMANCE_CLAIM_TIMEOUT = timedelta(minutes=5)


def _default_formula_profiles_by_playstyle() -> dict[Playstyle, FormulaProfile]:
    """各 playstyle 別の既定 formula profile を生成する.

    Returns:
        dict[Playstyle, FormulaProfile]:
            VANILLA playstyle を VANILLA_RANKED profile へ対応付けた辞書.
    """
    return {Playstyle.VANILLA: FormulaProfile.VANILLA_RANKED}


@dataclass(slots=True, frozen=True)
class PerformanceRuntimeSettings:
    """スコア performance subsystem の型付き実行時設定を表す.

    Attributes:
        bounded_wait (timedelta): worker が短時間待機するときの上限時間.
        formula_profiles_by_playstyle (Mapping[Playstyle, FormulaProfile]):
            playstyle ごとの有効な formula profile.
        worker_chunk_size (int): 1 worker pass で claim する最大 work item 数.
        claim_timeout (timedelta): claim を stale と見なして再取得可能にするまでの時間.
    """

    bounded_wait: timedelta = DEFAULT_PERFORMANCE_BOUNDED_WAIT
    formula_profiles_by_playstyle: Mapping[Playstyle, FormulaProfile] = field(
        default_factory=_default_formula_profiles_by_playstyle
    )
    worker_chunk_size: int = DEFAULT_PERFORMANCE_WORKER_CHUNK_SIZE
    claim_timeout: timedelta = DEFAULT_PERFORMANCE_CLAIM_TIMEOUT

    def __post_init__(self) -> None:
        """設定値を検証し,formula profile の対応を不変な copy に置き換える.

        Returns:
            None: 設定を検証して正規化し,呼び出し側へ値を返さずに完了する.

        Raises:
            ValueError:
                待機時間,chunk size,claim timeout が非正,または VANILLA profile がない場合.
        """
        if self.bounded_wait <= timedelta(0):
            msg = "bounded_wait must be positive"
            raise ValueError(msg)
        if self.worker_chunk_size <= 0:
            msg = "worker_chunk_size must be positive"
            raise ValueError(msg)
        if self.claim_timeout <= timedelta(0):
            msg = "claim_timeout must be positive"
            raise ValueError(msg)
        profiles = dict(self.formula_profiles_by_playstyle)
        if Playstyle.VANILLA not in profiles:
            msg = "vanilla formula profile is required"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "formula_profiles_by_playstyle",
            MappingProxyType(profiles),
        )

    def active_formula_profile_for(self, playstyle: Playstyle) -> FormulaProfile:
        """指定 playstyle 用の有効 formula profile を返す.

        Args:
            playstyle (Playstyle): performance calculation を行う対象 playstyle.

        Returns:
            FormulaProfile: 設定済みの有効 formula profile.

        Raises:
            ValueError: 指定 playstyle の formula profile が設定されていない場合.
        """
        profile = self.formula_profiles_by_playstyle.get(playstyle)
        if profile is None:
            msg = f"unsupported playstyle for performance calculation: {playstyle!r}"
            raise ValueError(msg)
        return profile
