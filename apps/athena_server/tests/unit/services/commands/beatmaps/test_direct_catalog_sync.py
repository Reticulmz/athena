"""osu!direct catalog schedulerの共有budgetと優先度契約を検証するmodule."""

import asyncio
from dataclasses import dataclass

from structlog.testing import capture_logs

from osu_server.services.commands.beatmaps.direct_catalog_sync import (
    DirectCatalogScheduleOutcome,
    DirectCatalogScheduler,
    DirectCatalogWorkKind,
)


@dataclass(slots=True)
class RecordingCatalogWork:
    """Scheduler testで実行済みworkの順序を記録するcallableを提供する.

    Attributes:
        label (str): workが実行されたときに記録する識別子.
        calls (list[str]): 実行順を保存する共有list.
    """

    label: str
    calls: list[str]

    async def __call__(self) -> None:
        """Work実行を共有listへ記録する.

        Returns:
            None: labelを追加して完了し, 呼び出し側へ値を返さない.
        """
        self.calls.append(self.label)


@dataclass(slots=True)
class FailingCatalogWork:
    """Scheduler testでsanitize対象の例外を送出するcallableを提供する.

    Attributes:
        secret_value (str): exception messageへ混ぜる機密値のsentinel.
    """

    secret_value: str = "secret-token full upstream body"

    async def __call__(self) -> None:
        """Catalog work失敗を再現する.

        Returns:
            None: 正常終了せず例外を送出する.

        Raises:
            RuntimeError: schedulerのfailure diagnosticsを検証するため常に発生する.
        """
        raise RuntimeError(self.secret_value)


async def test_concurrent_point_lookup_consumes_budget_before_catalog_crawl() -> None:
    """同時に競合するpoint lookupがcatalog crawlより先に共有budgetを使う契約を検証する.

    Returns:
        None: point lookupのみが実行され,catalog crawlがretry可能なdelayになることを確認する.
    """
    calls: list[str] = []
    scheduler = DirectCatalogScheduler(request_budget_per_minute=1)

    crawl_task = asyncio.create_task(
        scheduler.run(
            DirectCatalogWorkKind.ID_RANGE_CRAWL,
            RecordingCatalogWork("crawl", calls),
        )
    )
    point_task = asyncio.create_task(
        scheduler.run(
            DirectCatalogWorkKind.POINT_LOOKUP,
            RecordingCatalogWork("point", calls),
        )
    )

    point_result, crawl_result = await asyncio.gather(point_task, crawl_task)

    assert point_result.outcome is DirectCatalogScheduleOutcome.COMPLETED
    assert crawl_result.outcome is DirectCatalogScheduleOutcome.DELAYED
    assert crawl_result.retry_eligible is True
    assert crawl_result.retry_after_seconds is not None
    assert crawl_result.retry_after_seconds > 0
    assert calls == ["point"]


async def test_shared_budget_delays_catalog_work_with_operator_retry_diagnostics() -> None:
    """Point lookupが消費した共有budgetによりcatalog workがdelay診断を返す契約を検証する.

    Returns:
        None: feed syncとrange crawlが同じbudget枯渇を観測し, retry stateをlogへ出すことを確認する.
    """
    calls: list[str] = []
    scheduler = DirectCatalogScheduler(request_budget_per_minute=1)

    point_result = await scheduler.run(
        DirectCatalogWorkKind.POINT_LOOKUP,
        RecordingCatalogWork("point", calls),
    )
    with capture_logs() as logs:
        feed_result = await scheduler.run(
            DirectCatalogWorkKind.FEED_SYNC,
            RecordingCatalogWork("feed", calls),
        )
        range_result = await scheduler.run(
            DirectCatalogWorkKind.ID_RANGE_CRAWL,
            RecordingCatalogWork("range", calls),
        )

    assert point_result.outcome is DirectCatalogScheduleOutcome.COMPLETED
    assert feed_result.outcome is DirectCatalogScheduleOutcome.DELAYED
    assert range_result.outcome is DirectCatalogScheduleOutcome.DELAYED
    assert calls == ["point"]

    events = [entry for entry in logs if entry["event"] == "osu_direct_catalog_sync_delayed"]
    assert {event["work_kind"] for event in events} == {"feed_sync", "id_range_crawl"}
    assert all(event["retry_eligible"] is True for event in events)
    assert all(event["retry_after_seconds"] > 0 for event in events)


async def test_catalog_failure_returns_sanitized_retry_diagnostics() -> None:
    """Catalog work失敗をsanitize済みのoperator向けretry診断へ変換する契約を検証する.

    Returns:
        None: raw upstream bodyを結果やlogへ含めず,失敗とretry可否を返すことを確認する.
    """
    scheduler = DirectCatalogScheduler(request_budget_per_minute=1)

    with capture_logs() as logs:
        result = await scheduler.run(
            DirectCatalogWorkKind.FEED_SYNC,
            FailingCatalogWork(),
        )

    assert result.outcome is DirectCatalogScheduleOutcome.FAILED
    assert result.retry_eligible is True
    assert result.failure_reason == "RuntimeError: catalog work failed"
    assert result.retry_after_seconds is None
    assert "secret-token" not in repr(result)
    assert "upstream body" not in repr(result)

    events = [entry for entry in logs if entry["event"] == "osu_direct_catalog_sync_failed"]
    assert len(events) == 1
    assert events[0]["work_kind"] == "feed_sync"
    assert events[0]["exception_type"] == "RuntimeError"
    assert events[0]["retry_eligible"] is True
    assert events[0]["failure_reason"] == "RuntimeError: catalog work failed"
    assert "secret-token" not in repr(logs)
    assert "upstream body" not in repr(logs)
