"""private message を durable storage へ保存する command use-case を提供する.

この workflow は Unit of Work が利用可能な場合に private message write を transaction
内で実行する.
runtime が未構成または storage operation が失敗した場合は、例外を返さず
`ChatPersistenceResult` の failure として返す.
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
class PersistPrivateMessageCommand:
    """durable storage に保存する private message を表す command.

    Attributes:
        sender_id (int): message を送信した user の識別子.
        target_id (int): message を受信する user の識別子.
        content (str): 保存する message text.
    """

    sender_id: int
    target_id: int
    content: str


class PersistPrivateMessageUseCase:
    """private message を Unit of Work 経由で永続化する use-case.

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
                private message write を行う transaction factory. None の場合は runtime
                unavailable result
                を返す.

        """
        self._uow_factory: UnitOfWorkFactory | None = uow_factory

    async def execute(self, command: PersistPrivateMessageCommand) -> ChatPersistenceResult:
        """Private message を保存し、commit または failure result を返す.

        Args:
            command (PersistPrivateMessageCommand):
                sender、target、保存する text を含む command.

        Returns:
            ChatPersistenceResult: 保存成功、runtime unavailable、または storage error
            を表す結果.

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
                target_id=command.target_id,
                reason=ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE.value,
            )
            return result

        try:
            async with self._uow_factory() as uow:
                result = await uow.chat.save_private_message(
                    sender_id=command.sender_id,
                    target_id=command.target_id,
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
                target_id=command.target_id,
                reason=ChatPersistenceFailureReason.STORAGE_ERROR.value,
            )
            return ChatPersistenceResult.failure(ChatPersistenceFailureReason.STORAGE_ERROR)

        if not result.success:
            logger.warning(
                "chat_persistence_failed",
                sender_id=command.sender_id,
                target_id=command.target_id,
                reason=result.reason.value if result.reason is not None else None,
            )

        return result
