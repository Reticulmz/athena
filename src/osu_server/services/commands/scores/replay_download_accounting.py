"""Replay download accounting command policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol, cast

import structlog

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.infrastructure.state.interfaces.replay_download_accounting_gate import (
        ReplayDownloadAccountingGate,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_REPLAY_VIEW_DUPLICATE_COOLDOWN_SECONDS: Final = 86_400
_LATEST_ACTIVITY_THROTTLE_SECONDS: Final = 300

_logger: structlog.stdlib.BoundLogger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)


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


class LatestActivityAccountingOutcome(StrEnum):
    """Latest activity 更新の結果。"""

    TOUCHED = "touched"
    THROTTLED = "throttled"
    FAILED = "failed"


class _GateClaimOutcome(StrEnum):
    """Temporary gate claim の内部判定結果。"""

    OPEN = "open"
    CLOSED = "closed"
    FAILED_OPEN = "failed_open"
    FAILED_CLOSED = "failed_closed"


@dataclass(slots=True, frozen=True)
class ReplayDownloadAccountingResult:
    """Replay download accounting command の結果。

    Args:
        replay_view_outcome: Replay View Count branch の結果。
        latest_activity_outcome: Latest activity branch の結果。

    Returns:
        なし。

    Raises:
        なし。

    Constraints:
        Replay View Count と latest activity の結果は独立して表現する。
    """

    replay_view_outcome: ReplayViewAccountingOutcome
    latest_activity_outcome: LatestActivityAccountingOutcome


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
        """Replay download accounting policy を適用する。

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            Replay View Count と latest activity branch の結果。

        Raises:
            なし。temporary gate や durable 更新の失敗は result に畳み込む。

        Constraints:
            self-view は count せず、non-owner は 24h duplicate cooldown が open の時だけ
            score-scoped Replay View Count を 1 増やす。latest activity は self-view と
            duplicate cooldown hit を含むすべての成功 replay download で評価する。
        """
        replay_view_outcome = await self._apply_replay_view_policy(input_data)
        latest_activity_outcome = await self._apply_latest_activity_policy(input_data)
        return ReplayDownloadAccountingResult(
            replay_view_outcome=replay_view_outcome,
            latest_activity_outcome=latest_activity_outcome,
        )

    async def _apply_replay_view_policy(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> ReplayViewAccountingOutcome:
        """Replay view count 更新 policy を適用する。

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            self-view skip、duplicate cooldown skip、失敗、または increment 成功の結果。

        Raises:
            なし。gate や durable 更新の失敗は outcome に畳み込む。
        """
        if input_data.viewer_user_id == input_data.score_owner_user_id:
            return ReplayViewAccountingOutcome.SKIPPED_SELF_VIEW

        cooldown_claim = await self._claim_replay_view(input_data)
        if cooldown_claim is _GateClaimOutcome.CLOSED:
            return ReplayViewAccountingOutcome.SKIPPED_DUPLICATE
        if cooldown_claim is _GateClaimOutcome.FAILED_CLOSED:
            return ReplayViewAccountingOutcome.FAILED

        incremented = await self._increment_replay_view_count(input_data)
        if not incremented:
            await self._release_replay_view_if_claimed(input_data, cooldown_claim)
            return ReplayViewAccountingOutcome.FAILED

        return ReplayViewAccountingOutcome.INCREMENTED

    async def _apply_latest_activity_policy(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> LatestActivityAccountingOutcome:
        """Latest activity 更新 policy を適用する。

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            throttle skip、touch 成功、または失敗の結果。

        Raises:
            なし。gate や durable 更新の失敗は outcome に畳み込む。
        """
        throttle_claim = await self._claim_latest_activity(input_data)
        if throttle_claim is _GateClaimOutcome.CLOSED:
            return LatestActivityAccountingOutcome.THROTTLED

        touched = await self._touch_latest_activity(input_data)
        if not touched:
            await self._release_latest_activity_if_claimed(input_data, throttle_claim)
            return LatestActivityAccountingOutcome.FAILED

        return LatestActivityAccountingOutcome.TOUCHED

    async def _claim_replay_view(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> _GateClaimOutcome:
        """Replay view duplicate marker を claim する.

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            Claim の成功、既存 marker、または fail-closed error を表す内部結果。

        Raises:
            なし。gate 例外は fail-closed 結果と warning log に畳み込む。
        """
        try:
            claimed = await self._accounting_gate.claim_replay_view(
                viewer_user_id=input_data.viewer_user_id,
                score_id=input_data.score_id,
                ttl_seconds=_REPLAY_VIEW_DUPLICATE_COOLDOWN_SECONDS,
            )
        except Exception as exc:
            _log_accounting_failure(
                "replay_download_accounting_cooldown_gate_failed",
                input_data=input_data,
                operation="cooldown_gate",
                outcome="failed_closed",
                exception=exc,
            )
            return _GateClaimOutcome.FAILED_CLOSED
        if claimed:
            return _GateClaimOutcome.OPEN
        return _GateClaimOutcome.CLOSED

    async def _claim_latest_activity(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> _GateClaimOutcome:
        """Latest activity throttle marker を claim する.

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            Claim の成功、既存 marker、または fail-open error を表す内部結果。

        Raises:
            なし。gate 例外は fail-open 結果と warning log に畳み込む。
        """
        try:
            claimed = await self._accounting_gate.claim_latest_activity(
                viewer_user_id=input_data.viewer_user_id,
                ttl_seconds=_LATEST_ACTIVITY_THROTTLE_SECONDS,
            )
        except Exception as exc:
            _log_accounting_failure(
                "replay_download_accounting_activity_gate_failed",
                input_data=input_data,
                operation="activity_gate",
                outcome="opened",
                exception=exc,
            )
            return _GateClaimOutcome.FAILED_OPEN
        if claimed:
            return _GateClaimOutcome.OPEN
        return _GateClaimOutcome.CLOSED

    async def _release_replay_view_if_claimed(
        self,
        input_data: ReplayDownloadAccountingInput,
        claim_outcome: _GateClaimOutcome,
    ) -> None:
        """Replay view durable 更新失敗時に marker を best-effort で戻す.

        Args:
            input_data: replay download 成功後の accounting 入力。
            claim_outcome: 直前の replay view marker claim 結果。

        Returns:
            None。

        Raises:
            なし。release 失敗は warning log に畳み込む。
        """
        if claim_outcome is not _GateClaimOutcome.OPEN:
            return

        try:
            await self._accounting_gate.release_replay_view(
                viewer_user_id=input_data.viewer_user_id,
                score_id=input_data.score_id,
            )
        except Exception as exc:
            _log_accounting_failure(
                "replay_download_accounting_cooldown_release_failed",
                input_data=input_data,
                operation="cooldown_gate_release",
                outcome="release_failed",
                exception=exc,
            )

    async def _release_latest_activity_if_claimed(
        self,
        input_data: ReplayDownloadAccountingInput,
        claim_outcome: _GateClaimOutcome,
    ) -> None:
        """Latest activity durable 更新失敗時に marker を best-effort で戻す.

        Args:
            input_data: replay download 成功後の accounting 入力。
            claim_outcome: 直前の latest activity marker claim 結果。

        Returns:
            None。

        Raises:
            なし。release 失敗は warning log に畳み込む。
        """
        if claim_outcome is not _GateClaimOutcome.OPEN:
            return

        try:
            await self._accounting_gate.release_latest_activity(
                viewer_user_id=input_data.viewer_user_id,
            )
        except Exception as exc:
            _log_accounting_failure(
                "replay_download_accounting_activity_release_failed",
                input_data=input_data,
                operation="activity_gate_release",
                outcome="release_failed",
                exception=exc,
            )

    async def _increment_replay_view_count(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> bool:
        """Score の replay view count を 1 増やす。

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            更新に成功した場合は True。score が存在しない、または例外が発生した
            場合は False。

        Raises:
            なし。例外は warning log に畳み込み False を返す。
        """
        try:
            async with self._unit_of_work_factory() as uow:
                score_exists = await uow.scores.increment_replay_view_count(input_data.score_id)
                if not score_exists:
                    _log_accounting_failure(
                        "replay_download_accounting_replay_view_failed",
                        input_data=input_data,
                        operation="replay_view_count",
                        outcome="failed",
                        exception_type="ScoreNotFound",
                    )
                    return False
                await uow.commit()
        except Exception as exc:
            _log_accounting_failure(
                "replay_download_accounting_replay_view_failed",
                input_data=input_data,
                operation="replay_view_count",
                outcome="failed",
                exception=exc,
            )
            return False
        return True

    async def _touch_latest_activity(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> bool:
        """Viewer の latest activity を更新する。

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            更新に成功した場合は True。user が存在しない、または例外が発生した
            場合は False。

        Raises:
            なし。例外は warning log に畳み込み False を返す。
        """
        try:
            async with self._unit_of_work_factory() as uow:
                user_exists = await uow.users.touch_latest_activity(
                    input_data.viewer_user_id,
                    input_data.occurred_at,
                )
                if not user_exists:
                    _log_accounting_failure(
                        "replay_download_accounting_latest_activity_failed",
                        input_data=input_data,
                        operation="latest_activity",
                        outcome="failed",
                        exception_type="UserNotFound",
                    )
                    return False
                await uow.commit()
        except Exception as exc:
            _log_accounting_failure(
                "replay_download_accounting_latest_activity_failed",
                input_data=input_data,
                operation="latest_activity",
                outcome="failed",
                exception=exc,
            )
            return False
        return True


class ReplayDownloadAccountingPublisher(Protocol):
    """Replay download accounting work を非同期実行境界へ発行する port。"""

    async def publish(self, input_data: ReplayDownloadAccountingInput) -> None:
        """Accounting work を best-effort に発行する。

        Args:
            input_data: replay download 成功後の accounting 入力。

        Returns:
            None。

        Raises:
            実装依存。transport 側は best-effort 境界として例外を握り、ログに残す。

        Constraints:
            実装は replay download response body の生成や永続更新を直接行わない。
        """
        ...


def _validate_positive_id(name: str, value: int) -> None:
    """id が正の整数であることを検証する。

    Args:
        name: 検証対象の引数名。
        value: 検証する整数値。

    Returns:
        None。

    Raises:
        ValueError: value が 0 以下の場合。
    """
    if value <= 0:
        msg = f"{name} must be positive"
        raise ValueError(msg)


def _log_accounting_failure(
    event: str,
    *,
    input_data: ReplayDownloadAccountingInput,
    operation: str,
    outcome: str,
    exception: BaseException | None = None,
    exception_type: str | None = None,
) -> None:
    """Accounting 失敗を sanitize した warning log として記録する。

    Args:
        event: structlog event 名。
        input_data: replay download 成功後の accounting 入力。
        operation: 失敗した操作名。
        outcome: 失敗時の outcome 分類。
        exception: 発生した例外。例外 message は log に含めない。
        exception_type: 例外型名の明示上書き。

    Returns:
        None。

    Raises:
        なし。
    """
    _logger.warning(
        event,
        operation=operation,
        score_id=input_data.score_id,
        viewer_user_id=input_data.viewer_user_id,
        score_owner_user_id=input_data.score_owner_user_id,
        outcome=outcome,
        exception_type=exception_type or type(exception).__name__,
    )


__all__ = [
    "LatestActivityAccountingOutcome",
    "ReplayDownloadAccountingInput",
    "ReplayDownloadAccountingPublisher",
    "ReplayDownloadAccountingResult",
    "ReplayDownloadAccountingUseCase",
    "ReplayViewAccountingOutcome",
]
