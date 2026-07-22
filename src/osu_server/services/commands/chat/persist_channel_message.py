"""channel message を durable storage へ保存する command use-case を提供する.

この workflow は Unit of Work が利用可能な場合に message write を transaction 内で実行する.
runtime が
未構成または storage operation が失敗した場合は、例外を返さず `ChatPersistenceResult` の
failure として返す.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.chat import (
    ChatPersistenceFailureReason,
    ChatPersistenceResult,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class PersistChannelMessageCommand:
    """durable storage に保存する channel message を表す command.

    Attributes:
        sender_id (int): message を送信した user の識別子.
        channel_name (str): message を保存する channel name.
        content (str): 保存する message text.
    """

    sender_id: int
    channel_name: str
    content: str


class PersistChannelMessageUseCase:
    """channel message を Unit of Work 経由で永続化する use-case.

    Attributes:
        _uow_factory (UnitOfWorkFactory | None):
            message write transaction を作成する factory. runtime 未構成時はNone.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory | None = None,
    ) -> None:
        """Optional な message persistence runtime を設定する.

        Args:
            uow_factory (UnitOfWorkFactory | None):
                channel message write を行う transaction factory. None の場合は runtime
                unavailable result
                を返す.

        """
        self._uow_factory: UnitOfWorkFactory | None = uow_factory

    async def execute(self, command: PersistChannelMessageCommand) -> ChatPersistenceResult:
        """Channel message を保存し、commit または failure result を返す.

        Args:
            command (PersistChannelMessageCommand):
                sender、channel、保存する text を含む command.

        Returns:
            ChatPersistenceResult: 保存成功、channel 不存在などの repository failure、runtime
            unavailable、または
            storage error を表す結果.

        Notes:
            repository が失敗結果を返す場合は rollback する. Unit of Work または storage
            の例外は捕捉して`STORAGE_ERROR`
            resultへ変換する.
        """
        if self._uow_factory is None:
            result = ChatPersistenceResult.failure(
                ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE
            )
            logger.warning(
                "chat_persistence_failed",
                sender_id=command.sender_id,
                channel_name=command.channel_name,
                reason=ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE.value,
            )
            return result

        try:
            async with self._uow_factory() as uow:
                result = await uow.chat.save_channel_message(
                    sender_id=command.sender_id,
                    channel_name=command.channel_name,
                    content=command.content,
                )
                if result.success:
                    await uow.commit()
                else:
                    await uow.rollback()
        except Exception:
            logger.exception(
                "chat_persistence_failed",
                sender_id=command.sender_id,
                channel_name=command.channel_name,
                reason=ChatPersistenceFailureReason.STORAGE_ERROR.value,
            )
            return ChatPersistenceResult.failure(ChatPersistenceFailureReason.STORAGE_ERROR)

        if not result.success:
            event_name = "chat_persistence_failed"
            if result.reason is ChatPersistenceFailureReason.CHANNEL_NOT_FOUND:
                event_name = "chat_persistence_channel_not_found"
            logger.warning(
                event_name,
                sender_id=command.sender_id,
                channel_name=command.channel_name,
                reason=result.reason.value if result.reason is not None else None,
            )

        return result
