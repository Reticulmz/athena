"""Score performance calculation の完了通知 contract を定義する module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.scores.performance import PerformanceCalculationState


@dataclass(frozen=True, slots=True)
class PerformanceCompletionSignalPayload:
    """終端済み score performance calculation の wake-up payload.

    Attributes:
        score_id (int): 完了した score の正の識別子.
        calculation_id (int): 完了した calculation の正の識別子.
        state (PerformanceCalculationState): 終端状態である calculation lifecycle state.

    Notes:
        payload は performance value を運ばず、待機者を再照会へ促す hint だけを表す.
    """

    score_id: int
    calculation_id: int
    state: PerformanceCalculationState

    def __post_init__(self) -> None:
        """Payload の識別子と calculation state が有効かを検証する.

        Returns:
            None: 検証成功後に instance を確定する.

        Raises:
            ValueError: score_id または calculation_id が正でない場合、あるいは state が
                終端でない場合.
        """
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.calculation_id <= 0:
            msg = "calculation_id must be positive"
            raise ValueError(msg)
        if not self.state.is_terminal:
            msg = "performance completion signal state must be terminal"
            raise ValueError(msg)


@runtime_checkable
class PerformanceCompletionSignal(Protocol):
    """Score 単位で performance completion を知らせる best-effort contract.

    Notes:
        signal は durable result ではないため、受信者は score を再照会して最終状態を取得する.
        通知は terminal calculation の durable commit 後に発行する.
    """

    async def notify(self, payload: PerformanceCompletionSignalPayload) -> None:
        """Commit 済み terminal calculation の wake-up hint を通知する.

        Args:
            payload (PerformanceCompletionSignalPayload): 終端 calculation を識別する payload.

        Returns:
            None: 通知発行処理の完了を表す.
        """
        ...

    async def wait(self, score_id: int, timeout: timedelta) -> bool:
        """Score の通知を期限まで待ち、観測結果を返す.

        Args:
            score_id (int): 待機対象となる正の score id.
            timeout (timedelta): 正である最大待機時間.

        Returns:
            bool: 対象 score の通知を観測した場合は True、期限切れなら False.

        Raises:
            ValueError: score_id が正でない場合、または timeout が正でない場合.
        """
        ...


def performance_completion_channel(score_id: int, *, key_prefix: str = "") -> str:
    """Score 単位の deterministic な completion channel 名を返す.

    Args:
        score_id (int): channel に埋め込む正の score id.
        key_prefix (str): 環境または test を分離する任意の prefix.

    Returns:
        str: `{key_prefix}performance_completion:{score_id}` 形式の channel 名.

    Raises:
        ValueError: score_id が正でない場合.
    """
    if score_id <= 0:
        msg = "score_id must be positive"
        raise ValueError(msg)
    return f"{key_prefix}performance_completion:{score_id}"


def validate_performance_completion_timeout(timeout: timedelta) -> None:
    """Performance completion の待機時間が正であることを検証する.

    Args:
        timeout (timedelta): 検証する最大待機時間.

    Returns:
        None: timeout が正であることを表す.

    Raises:
        ValueError: timeout がゼロ以下の場合.
    """
    if timeout <= timedelta(0):
        msg = "timeout must be positive"
        raise ValueError(msg)
