"""プロセス内イベント配信の契約を定義します."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

TEvent = TypeVar("TEvent", bound=object)


@runtime_checkable
class LocalEventBus(Protocol):
    """プロセス内イベントを同一プロセスの購読者へ配信する契約です.

    Notes:
        実装は cross-replica、worker、durability、replay の保証を提供しません.
        同一プロセス内の非クリティカルな fanout にだけ使用します.
    """

    async def fire(self, event: object) -> None:
        """イベントの具象型を購読する全ローカル handler へ通知します.

        Args:
            event (object): 配信するイベント値です.

        Returns:
            None: 通知処理が完了したことを表します.
        """
        ...

    def subscribe(
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], Awaitable[None]],
    ) -> None:
        """具象イベント型に対する非同期ローカル handler を登録します.

        Args:
            event_type (type[TEvent]): 購読する具象イベント型です.
            handler (Callable[[TEvent], Awaitable[None]]): 該当イベントを受け取り
                非同期で処理する handler です.

        Returns:
            None: handler の登録が完了したことを表します.
        """
        ...
