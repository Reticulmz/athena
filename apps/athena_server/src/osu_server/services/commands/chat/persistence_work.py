"""受理済み chat message の durable persistence work を発行する boundary を定義する.

message delivery use-case は transaction を直接保持せず,受理した message の immutable work
item を
publisher port へ渡す. job adapter はこの port を実装して delivery-guaranteed な persistence
workflow を起動する.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ChannelMessagePersistenceWork:
    """受理済み channel message を durable storage へ保存する work item を表す.

    Attributes:
        sender_id (int): message を送信した user の識別子.
        sender_name (str): persistence record と diagnostics に使う sender username.
        channel_name (str): message の送信先 channel name.
        content (str): 保存する受理済み message text.
    """

    sender_id: int
    sender_name: str
    channel_name: str
    content: str


@dataclass(frozen=True, slots=True)
class PrivateMessagePersistenceWork:
    """受理済み private message を durable storage へ保存する work item を表す.

    Attributes:
        sender_id (int): message を送信した user の識別子.
        sender_name (str): persistence record と diagnostics に使う sender username.
        target_id (int): message を受信する user の識別子.
        target_name (str): persistence record と diagnostics に使う target username.
        content (str): 保存する受理済み message text.
    """

    sender_id: int
    sender_name: str
    target_id: int
    target_name: str
    content: str


class ChatPersistenceWorkPublisher(Protocol):
    """受理済み chat message の persistence work を開始する publisher port を定義する."""

    async def publish_channel_message(
        self,
        work: ChannelMessagePersistenceWork,
    ) -> None:
        """受理済み channel message の persistence work を発行する.

        Args:
            work (ChannelMessagePersistenceWork):
                sender,channel,受理済み content を含む immutable work item.

        Returns:
            None: durable-work delivery を要求して完了し,呼び出し側へ値を返さない.
        """
        ...

    async def publish_private_message(
        self,
        work: PrivateMessagePersistenceWork,
    ) -> None:
        """受理済み private message の persistence work を発行する.

        Args:
            work (PrivateMessagePersistenceWork):
                sender,target,受理済み content を含む immutable work item.

        Returns:
            None: durable-work delivery を要求して完了し,呼び出し側へ値を返さない.
        """
        ...
