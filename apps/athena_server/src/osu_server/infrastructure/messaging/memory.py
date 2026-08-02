"""メモリ内で完結するローカルイベント配信を実装します."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)
TEvent = TypeVar("TEvent", bound=object)


class InMemoryLocalEventBus:
    """メモリ内のローカルイベント配信を提供します.

    Attributes:
        _handlers (dict[type[object], list[Callable[[object], Awaitable[None]]]]):
            具象イベント型ごとに登録順で保持する非同期 handler の一覧です.

    Notes:
        handler は具象イベント型ごとに登録順で呼び出します. handler の例外は記録し,
        後続 handler の配信を止めません.
    """

    def __init__(self) -> None:
        """空の handler 登録でイベントバスを初期化します."""
        self._handlers: dict[type[object], list[Callable[[object], Awaitable[None]]]] = (
            defaultdict(list)
        )

    async def fire(self, event: object) -> None:
        """イベント型に登録された全ローカル handler へ通知します.

        Args:
            event (object): 配信するイベント値です.

        Returns:
            None: 登録済み handler の通知試行が完了したことを表します.

        Notes:
            handler 例外は log に記録して隔離します.
        """
        for handler in self._handlers.get(type(event), []):
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "LocalEventBus handler %s failed for %s",
                    getattr(handler, "__name__", repr(handler)),
                    type(event).__name__,
                )

    def subscribe(
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], Awaitable[None]],
    ) -> None:
        """具象イベント型に対するローカル handler を登録します.

        Args:
            event_type (type[TEvent]): 購読する具象イベント型です.
            handler (Callable[[TEvent], Awaitable[None]]): 該当イベントを非同期で
                処理する handler です.

        Returns:
            None: handler の登録が完了したことを表します.
        """
        self._handlers[event_type].append(cast("Callable[[object], Awaitable[None]]", handler))
