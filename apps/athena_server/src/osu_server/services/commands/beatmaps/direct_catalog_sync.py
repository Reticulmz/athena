"""osu!direct catalog同期の共有upstream budget schedulerを提供するmodule."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import structlog

_UPSTREAM_BUDGET_WINDOW_SECONDS = 60

_logger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)

type DirectCatalogWork = Callable[[], Awaitable[None]]
type TimeFunc = Callable[[], float]


class DirectCatalogWorkKind(StrEnum):
    """共有upstream budgetを使うosu!direct work種別を表す.

    Attributes:
        POINT_LOOKUP (DirectCatalogWorkKind): stable requestのpoint lookup用work.
        FEED_SYNC (DirectCatalogWorkKind): background catalog feed同期work.
        ID_RANGE_CRAWL (DirectCatalogWorkKind): background id range crawl work.
    """

    POINT_LOOKUP = "point_lookup"
    FEED_SYNC = "feed_sync"
    ID_RANGE_CRAWL = "id_range_crawl"


class DirectCatalogScheduleOutcome(StrEnum):
    """DirectCatalogSchedulerがworkへ与えた実行結果を表す.

    Attributes:
        COMPLETED (DirectCatalogScheduleOutcome): budgetを取得してworkが完了した.
        DELAYED (DirectCatalogScheduleOutcome): budget枯渇によりretry可能なdelayになった.
        FAILED (DirectCatalogScheduleOutcome): work実行中に失敗しretry可能な状態を返した.
    """

    COMPLETED = "completed"
    DELAYED = "delayed"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class DirectCatalogScheduleResult:
    """Shared upstream budget schedulerのwork単位結果を表す.

    Attributes:
        work_kind (DirectCatalogWorkKind): schedulerへ渡されたwork種別.
        outcome (DirectCatalogScheduleOutcome): workの実行結果.
        retry_eligible (bool): 呼び出し側が後続retry対象にしてよいか.
        retry_after_seconds (int | None): delay時に次回試行まで待つ推奨秒数.
        failure_reason (str | None): operator向けにsanitize済みの失敗理由.
    """

    work_kind: DirectCatalogWorkKind
    outcome: DirectCatalogScheduleOutcome
    retry_eligible: bool
    retry_after_seconds: int | None = None
    failure_reason: str | None = None


class DirectCatalogScheduler:
    """Point lookupを優先するosu!direct upstream work scheduler.

    Attributes:
        _request_budget_per_minute (int): 1分間に許可するupstream request数.
        _time_func (TimeFunc): budget window判定用clock.
        _lock (asyncio.Lock): 同時reserveを直列化するlock.
        _window_started_at (float): 現在のbudget window開始時刻.
        _used_budget (int): 現在windowで消費済みのrequest数.
    """

    _request_budget_per_minute: int
    _time_func: TimeFunc
    _lock: asyncio.Lock
    _window_started_at: float
    _used_budget: int

    def __init__(
        self,
        *,
        request_budget_per_minute: int,
        time_func: TimeFunc | None = None,
    ) -> None:
        """Schedulerの共有budgetとclockを初期化する.

        Args:
            request_budget_per_minute (int): 1分間に許可するupstream request数.
            time_func (TimeFunc | None): budget window判定に使う秒単位clock.

        Raises:
            ValueError: request_budget_per_minuteが正でない場合.
        """
        if request_budget_per_minute <= 0:
            msg = "request_budget_per_minute must be positive"
            raise ValueError(msg)
        self._request_budget_per_minute = request_budget_per_minute
        self._time_func = time_func or time.monotonic
        self._lock = asyncio.Lock()
        self._window_started_at = self._time_func()
        self._used_budget = 0

    async def run(
        self,
        work_kind: DirectCatalogWorkKind,
        work: DirectCatalogWork,
    ) -> DirectCatalogScheduleResult:
        """Shared budgetを取得できた場合だけupstream workを実行する.

        Args:
            work_kind (DirectCatalogWorkKind): 実行するworkの種別.
            work (DirectCatalogWork): budget取得後に呼び出す非同期work.

        Returns:
            DirectCatalogScheduleResult: 完了, delay, failureのいずれかを表す結果.
        """
        if _is_catalog_work(work_kind):
            # ponytail: one event-loop tick is enough priority for current worker concurrency.
            await asyncio.sleep(0)

        retry_after_seconds = await self._reserve_budget()
        if retry_after_seconds is not None:
            result = DirectCatalogScheduleResult(
                work_kind=work_kind,
                outcome=DirectCatalogScheduleOutcome.DELAYED,
                retry_eligible=True,
                retry_after_seconds=retry_after_seconds,
            )
            self._log_delay(result)
            return result

        try:
            await work()
        except Exception as exc:
            result = DirectCatalogScheduleResult(
                work_kind=work_kind,
                outcome=DirectCatalogScheduleOutcome.FAILED,
                retry_eligible=True,
                failure_reason=_sanitize_failure_reason(work_kind, exc),
            )
            self._log_failure(result, exc)
            return result

        result = DirectCatalogScheduleResult(
            work_kind=work_kind,
            outcome=DirectCatalogScheduleOutcome.COMPLETED,
            retry_eligible=False,
        )
        self._log_completion(result)
        return result

    async def _reserve_budget(self) -> int | None:
        """現在windowのbudgetを1件予約し,枯渇時はretry秒数を返す.

        Returns:
            int | None: budget枯渇時はretryまでの秒数. 予約できた場合はNone.
        """
        async with self._lock:
            now = self._time_func()
            window_age = now - self._window_started_at
            if window_age >= _UPSTREAM_BUDGET_WINDOW_SECONDS:
                self._window_started_at = now
                self._used_budget = 0
                window_age = 0

            if self._used_budget >= self._request_budget_per_minute:
                retry_after_seconds = math.ceil(_UPSTREAM_BUDGET_WINDOW_SECONDS - window_age)
                return max(1, retry_after_seconds)

            self._used_budget += 1
            return None

    def _log_delay(self, result: DirectCatalogScheduleResult) -> None:
        """Catalog workのdelayとretry stateを構造化logへ出力する.

        Args:
            result (DirectCatalogScheduleResult): delay結果.

        Returns:
            None: log出力のみを行い値を返さない.
        """
        if not _is_catalog_work(result.work_kind):
            return
        _logger.info(
            "osu_direct_catalog_sync_delayed",
            work_kind=result.work_kind.value,
            retry_eligible=result.retry_eligible,
            retry_after_seconds=result.retry_after_seconds,
        )

    def _log_failure(
        self,
        result: DirectCatalogScheduleResult,
        exc: Exception,
    ) -> None:
        """Catalog workの失敗とretry stateを構造化logへ出力する.

        Args:
            result (DirectCatalogScheduleResult): failure結果.
            exc (Exception): sanitize対象の例外.

        Returns:
            None: log出力のみを行い値を返さない.
        """
        if not _is_catalog_work(result.work_kind):
            return
        _logger.warning(
            "osu_direct_catalog_sync_failed",
            work_kind=result.work_kind.value,
            exception_type=type(exc).__name__,
            retry_eligible=result.retry_eligible,
            failure_reason=result.failure_reason,
        )

    def _log_completion(self, result: DirectCatalogScheduleResult) -> None:
        """Catalog workの完了状態を構造化logへ出力する.

        Args:
            result (DirectCatalogScheduleResult): completed結果.

        Returns:
            None: catalog workであれば完了eventを出力して値を返さない.
        """
        if not _is_catalog_work(result.work_kind):
            return
        _logger.info(
            "osu_direct_catalog_sync_completed",
            work_kind=result.work_kind.value,
        )


def _is_catalog_work(work_kind: DirectCatalogWorkKind) -> bool:
    """Work種別がbackground catalog workか判定する.

    Args:
        work_kind (DirectCatalogWorkKind): 判定するwork種別.

    Returns:
        bool: feed syncまたはid range crawlならTrue.
    """
    return work_kind is not DirectCatalogWorkKind.POINT_LOOKUP


def _sanitize_failure_reason(work_kind: DirectCatalogWorkKind, exc: Exception) -> str:
    """例外をoperator向けの固定messageへ変換する.

    Args:
        work_kind (DirectCatalogWorkKind): 失敗したwork種別.
        exc (Exception): workから送出された例外.

    Returns:
        str: credentialやupstream bodyを含まない失敗理由.
    """
    category = "catalog" if _is_catalog_work(work_kind) else "point lookup"
    return f"{type(exc).__name__}: {category} work failed"


__all__ = [
    "DirectCatalogScheduleOutcome",
    "DirectCatalogScheduleResult",
    "DirectCatalogScheduler",
    "DirectCatalogWork",
    "DirectCatalogWorkKind",
]
