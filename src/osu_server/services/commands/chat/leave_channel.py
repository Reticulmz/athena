"""chat channel から user を退出させる command use-case を提供する.

この module は volatile channel membership state だけを更新する. channel definition と ACL は
join
workflow で確認済みであることを前提にする.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.channel_state_store import (
        ChannelStateStore,
    )

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class LeaveChannelCommand:
    """channel 退出に必要な user と channel の識別子を表す command.

    Attributes:
        user_id (int): channel から削除する user の識別子.
        channel_name (str): 退出対象の channel name.
    """

    user_id: int
    channel_name: str


class LeaveChannelUseCase:
    """user を channel の volatile membership state から削除する use-case.

    Attributes:
        _channel_state (ChannelStateStore):
            channel membership を保持し削除操作を提供する state store.
    """

    def __init__(self, *, channel_state: ChannelStateStore) -> None:
        """Channel membership を削除する state store を設定する.

        Args:
            channel_state (ChannelStateStore):
                user と channel の membership を管理する volatile state store.

        """
        self._channel_state: ChannelStateStore = channel_state

    async def execute(self, command: LeaveChannelCommand) -> None:
        """Command の user を指定 channel から削除する.

        Args:
            command (LeaveChannelCommand): 削除する user と channel name を含む command.

        Returns:
            None: membership 削除を要求して log を記録し、呼び出し側へ値を返さずに完了する.
        """
        await self._channel_state.remove_member(command.channel_name, command.user_id)
        logger.info("leave", user_id=command.user_id, channel=command.channel_name)
