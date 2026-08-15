"""osu!direct catalog work kind を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
    """Direct catalog schedulerがworkへ与えた実行結果を表す.

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


__all__ = [
    "DirectCatalogScheduleOutcome",
    "DirectCatalogScheduleResult",
    "DirectCatalogWorkKind",
]
