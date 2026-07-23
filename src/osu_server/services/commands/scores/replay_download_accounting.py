"""replay download成功後の閲覧数と活動時刻を集計するcommand policyを定義する."""

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
    """replay download成功後にaccountingへ渡す入力を表す.

    Attributes:
        score_id (int): downloadされたreplayに対応するscore ID.
        score_owner_user_id (int): 対象scoreを所有するuser ID.
        viewer_user_id (int): replayを閲覧した認証済みuser ID.
        occurred_at (datetime): download成功時刻を表すtimezone-awareな日時.

    Notes:
        重複閲覧のidentityはviewer_user_idとscore_idの組だけで判定する.
    """

    score_id: int
    score_owner_user_id: int
    viewer_user_id: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        """accounting入力の識別子と時刻の前提条件を検証する.

        Returns:
            None: 値を変更せず検証を完了する.

        Raises:
            ValueError: いずれかのIDが正でないかoccurred_atがtimezone-awareでない場合.
        """
        _validate_positive_id("score_id", self.score_id)
        _validate_positive_id("score_owner_user_id", self.score_owner_user_id)
        _validate_positive_id("viewer_user_id", self.viewer_user_id)
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            msg = "occurred_at must be timezone-aware"
            raise ValueError(msg)


class ReplayViewAccountingOutcome(StrEnum):
    """replay view count更新branchの結果を表す.

    Attributes:
        INCREMENTED (str): replay view countを1増やした状態.
        SKIPPED_SELF_VIEW (str): owner自身の閲覧のため更新しなかった状態.
        SKIPPED_DUPLICATE (str): cooldown中の重複閲覧のため更新しなかった状態.
        FAILED (str): gateまたはdurable更新の失敗により更新できなかった状態.
    """

    INCREMENTED = "incremented"
    SKIPPED_SELF_VIEW = "skipped_self_view"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    FAILED = "failed"


class LatestActivityAccountingOutcome(StrEnum):
    """latest activity更新branchの結果を表す.

    Attributes:
        TOUCHED (str): viewerのlatest activityを更新した状態.
        THROTTLED (str): throttle中のためactivity更新を抑止した状態.
        FAILED (str): gateまたはdurable更新の失敗により更新できなかった状態.
    """

    TOUCHED = "touched"
    THROTTLED = "throttled"
    FAILED = "failed"


class _GateClaimOutcome(StrEnum):
    """temporary gate claimの内部判定結果を表す.

    Attributes:
        OPEN (str): 呼び出しがmarkerを新規にclaimした状態.
        CLOSED (str): 既存markerによりclaimが拒否された状態.
        FAILED_OPEN (str): gate失敗を許容して後続処理を継続する状態.
        FAILED_CLOSED (str): gate失敗により後続処理を抑止する状態.
    """

    OPEN = "open"
    CLOSED = "closed"
    FAILED_OPEN = "failed_open"
    FAILED_CLOSED = "failed_closed"


@dataclass(slots=True, frozen=True)
class ReplayDownloadAccountingResult:
    """replay download accounting commandの二つのbranch結果を表す.

    Attributes:
        replay_view_outcome (ReplayViewAccountingOutcome): score閲覧数更新の結果.
        latest_activity_outcome (LatestActivityAccountingOutcome): viewer活動時刻更新の結果.

    Notes:
        二つのbranchは独立して処理されるため一方の失敗が他方の結果を上書きしない.
    """

    replay_view_outcome: ReplayViewAccountingOutcome
    latest_activity_outcome: LatestActivityAccountingOutcome


class ReplayDownloadAccountingUseCase:
    """replay download成功をserver-observableなconsumption signalとして集計する.

    Attributes:
        _unit_of_work_factory (UnitOfWorkFactory): durableなscoreとuser更新を開始するfactory.
        _accounting_gate (ReplayDownloadAccountingGate): cooldownとthrottle markerを管理するgate.
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        accounting_gate: ReplayDownloadAccountingGate,
    ) -> None:
        """durable更新用のUnit of Work factoryとtemporary accounting gateを保持する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): score countを更新するcommand UoW factory.
            accounting_gate (ReplayDownloadAccountingGate): duplicate cooldown markerを
                claimするgate.

        Notes:
            durable repositoryとconcrete state backendはこのuse-case内で直接構築しない.
        """
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._accounting_gate: ReplayDownloadAccountingGate = accounting_gate

    async def execute(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> ReplayDownloadAccountingResult:
        """Replay download accounting policyを適用する.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.

        Returns:
            ReplayDownloadAccountingResult: 閲覧数と活動時刻のbranchごとの結果.

        Notes:
            self-viewはcountしない. non-ownerは24h duplicate cooldownがopenのときだけ
            score-scoped replay view countを1増やす. latest activityはself-viewと
            duplicate cooldown hitを含む全ての成功replay downloadで評価する.
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
        """Replay view count更新policyを適用する.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.

        Returns:
            ReplayViewAccountingOutcome: self-view skipとduplicate skipと成功と失敗の結果.

        Notes:
            gateまたはdurable更新の失敗は例外送出せずoutcomeに畳み込む.
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
        """Latest activity更新policyを適用する.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.

        Returns:
            LatestActivityAccountingOutcome: throttle skipとtouch成功と失敗の結果.

        Notes:
            gateまたはdurable更新の失敗は例外送出せずoutcomeに畳み込む.
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
        """Replay view duplicate markerをclaimする.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.

        Returns:
            _GateClaimOutcome: claim成功と既存markerとfail-closed errorの内部結果.

        Notes:
            gate例外はfail-closed結果とwarning logに畳み込む.
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
        """Latest activity throttle markerをclaimする.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.

        Returns:
            _GateClaimOutcome: claim成功と既存markerとfail-open errorの内部結果.

        Notes:
            gate例外はfail-open結果とwarning logに畳み込む.
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
        """Replay view durable更新失敗時にmarkerをbest-effortで戻す.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.
            claim_outcome (_GateClaimOutcome): 直前のreplay view marker claim結果.

        Returns:
            None: markerを戻す必要がある場合だけreleaseを試みる.

        Notes:
            release失敗はwarning logに畳み込み呼び出し元のoutcomeを変更しない.
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
        """Latest activity durable更新失敗時にmarkerをbest-effortで戻す.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.
            claim_outcome (_GateClaimOutcome): 直前のlatest activity marker claim結果.

        Returns:
            None: markerを戻す必要がある場合だけreleaseを試みる.

        Notes:
            release失敗はwarning logに畳み込み呼び出し元のoutcomeを変更しない.
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
        """scoreのreplay view countを1増やす.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.

        Returns:
            bool: score更新に成功した場合はTrue. score不存在または例外発生時はFalse.

        Notes:
            durable更新の例外はwarning logに畳み込みFalseを返す.
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
        """viewerのlatest activityを更新する.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.

        Returns:
            bool: user更新に成功した場合はTrue. user不存在または例外発生時はFalse.

        Notes:
            durable更新の例外はwarning logに畳み込みFalseを返す.
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
    """replay download accounting workを非同期実行境界へ発行するportを定義する."""

    async def publish(self, input_data: ReplayDownloadAccountingInput) -> None:
        """Accounting workをbest-effortに発行する.

        Args:
            input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.

        Returns:
            None: 発行を受け付けた後に値を返さない.

        Notes:
            具体的な例外契約は実装に委ねる. transport側はbest-effort境界として例外を握り
            logに残す. 実装はreplay download response bodyの生成や永続更新を直接行わない.
        """
        ...


def _validate_positive_id(name: str, value: int) -> None:
    """識別子が正の整数であることを検証する.

    Args:
        name (str): 検証対象の引数名.
        value (int): 検証する整数値.

    Returns:
        None: 検証のみを行い正常時は値を返さない.

    Raises:
        ValueError: valueが0以下の場合.
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
    """accounting失敗をsanitizeしたwarning logとして記録する.

    Args:
        event (str): structlog event名.
        input_data (ReplayDownloadAccountingInput): replay download成功後のaccounting入力.
        operation (str): 失敗した操作名.
        outcome (str): 失敗時のoutcome分類.
        exception (BaseException | None): 発生した例外. 例外messageはlogに含めない.
        exception_type (str | None): 例外型名の明示上書き.

    Returns:
        None: warning logの記録だけを行い値を返さない.
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
