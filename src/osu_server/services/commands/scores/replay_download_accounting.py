"""Replay download accounting command policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.infrastructure.state.interfaces.replay_download_accounting_gate import (
        ReplayDownloadAccountingGate,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_REPLAY_VIEW_DUPLICATE_COOLDOWN_SECONDS: Final = 86_400


@dataclass(slots=True, frozen=True)
class ReplayDownloadAccountingInput:
    """Replay download 成功後の accounting 入力。

    Args:
        score_id: replay download 対象 score id。
        score_owner_user_id: 対象 score の owner user id。
        viewer_user_id: 認証済み viewer user id。
        occurred_at: replay download 成功時刻。

    Returns:
        なし。

    Raises:
        ValueError: id が正の整数でない場合、または occurred_at が timezone-aware でない場合。

    Constraints:
        duplicate identity は viewer_user_id と score_id だけを使う。
    """

    score_id: int
    score_owner_user_id: int
    viewer_user_id: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        """入力 precondition を検証する。"""
        _validate_positive_id("score_id", self.score_id)
        _validate_positive_id("score_owner_user_id", self.score_owner_user_id)
        _validate_positive_id("viewer_user_id", self.viewer_user_id)
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            msg = "occurred_at must be timezone-aware"
            raise ValueError(msg)


class ReplayViewAccountingOutcome(StrEnum):
    """Replay View Count 更新の結果。"""

    INCREMENTED = "incremented"
    SKIPPED_SELF_VIEW = "skipped_self_view"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class ReplayDownloadAccountingResult:
    """Replay download accounting command の結果。

    Args:
        replay_view_outcome: Replay View Count branch の結果。

    Returns:
        なし。

    Raises:
        なし。

    Constraints:
        task 3.1 では latest activity outcome を持たず、task 3.2 で拡張する。
    """

    replay_view_outcome: ReplayViewAccountingOutcome


class ReplayDownloadAccountingUseCase:
    """Replay download 成功を server-observable consumption signal として集計する。"""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        accounting_gate: ReplayDownloadAccountingGate,
    ) -> None:
        """UoW factory と temporary accounting gate を受け取る。

        Args:
            unit_of_work_factory: score count を更新する command UoW factory。
            accounting_gate: duplicate cooldown marker を first-claim する gate。

        Returns:
            None。

        Raises:
            なし。

        Constraints:
            durable repository や concrete state backend は直接構築しない。
        """
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._accounting_gate: ReplayDownloadAccountingGate = accounting_gate

    async def execute(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> ReplayDownloadAccountingResult:
        """Replay View Count policy を適用する。

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            Replay View Count branch の結果。

        Raises:
            なし。temporary gate や durable count 更新の失敗は result に畳み込む。

        Constraints:
            self-view は count せず、non-owner は 24h duplicate cooldown が open の時だけ
            score-scoped Replay View Count を 1 増やす。
        """
        if input_data.viewer_user_id == input_data.score_owner_user_id:
            return ReplayDownloadAccountingResult(
                replay_view_outcome=ReplayViewAccountingOutcome.SKIPPED_SELF_VIEW,
            )

        cooldown_open = await self._claim_replay_view_or_open(input_data)
        if not cooldown_open:
            return ReplayDownloadAccountingResult(
                replay_view_outcome=ReplayViewAccountingOutcome.SKIPPED_DUPLICATE,
            )

        incremented = await self._increment_replay_view_count(input_data.score_id)
        if not incremented:
            return ReplayDownloadAccountingResult(
                replay_view_outcome=ReplayViewAccountingOutcome.FAILED,
            )

        return ReplayDownloadAccountingResult(
            replay_view_outcome=ReplayViewAccountingOutcome.INCREMENTED,
        )

    async def _claim_replay_view_or_open(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> bool:
        try:
            return await self._accounting_gate.claim_replay_view(
                viewer_user_id=input_data.viewer_user_id,
                score_id=input_data.score_id,
                ttl_seconds=_REPLAY_VIEW_DUPLICATE_COOLDOWN_SECONDS,
            )
        except Exception:
            return True

    async def _increment_replay_view_count(self, score_id: int) -> bool:
        try:
            async with self._unit_of_work_factory() as uow:
                score_exists = await uow.scores.increment_replay_view_count(score_id)
                if not score_exists:
                    return False
                await uow.commit()
        except Exception:
            return False
        return True


def _validate_positive_id(name: str, value: int) -> None:
    if value <= 0:
        msg = f"{name} must be positive"
        raise ValueError(msg)


__all__ = [
    "ReplayDownloadAccountingInput",
    "ReplayDownloadAccountingResult",
    "ReplayDownloadAccountingUseCase",
    "ReplayViewAccountingOutcome",
]
