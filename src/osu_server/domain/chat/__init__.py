"""Chat use-caseが受け渡す送信入力と結果のdomain modelを定義するmodule."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Self


class ChatPersistenceFailureReason(Enum):
    """受理済みchat履歴を永続化できない理由を表す閉集合.

    Attributes:
        CHANNEL_NOT_FOUND (str): channelが永続化時点で見つからないことを示す値.
        STORAGE_ERROR (str): storage層の失敗で永続化できないことを示す値.
        RUNTIME_UNAVAILABLE (str): 必要なruntime依存が利用できないことを示す値.
    """

    CHANNEL_NOT_FOUND = "channel_not_found"
    STORAGE_ERROR = "storage_error"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class PrivateMessageDeliveryStatus(StrEnum):
    """プレイヤー発private messageの宛先配信状態を表す閉集合.

    Attributes:
        DELIVERABLE (str): 宛先へ配信できることを示す値.
        OFFLINE (str): 宛先がofflineであることを示す値.
        TARGET_NOT_FOUND (str): 宛先userが存在しないことを示す値.
        BLOCKED_BY_FRIEND_ONLY (str): 宛先のfriend-only設定により拒否されたことを示す値.
    """

    DELIVERABLE = "deliverable"
    OFFLINE = "offline"
    TARGET_NOT_FOUND = "target_not_found"
    BLOCKED_BY_FRIEND_ONLY = "blocked_by_friend_only"


@dataclass(slots=True, frozen=True)
class ChatSender:
    """Chat messageを送信するuserの識別情報を表す.

    Attributes:
        user_id (int): 送信者の永続user ID.
        username (str): 送信時点の送信者名.
    """

    user_id: int
    username: str


@dataclass(slots=True, frozen=True)
class ChannelChatDestination:
    """Channel messageの宛先を表す.

    Attributes:
        name (str): 宛先channel名.
    """

    name: str


@dataclass(slots=True, frozen=True)
class PrivateChatDestination:
    """Private messageの宛先を表す.

    Attributes:
        username (str): 宛先user名.
    """

    username: str


@dataclass(slots=True, frozen=True)
class ChatAuthorization:
    """Chat送信時のauthorization snapshotを表す.

    Attributes:
        privileges (int): 送信者に付与されたprivilege bitmask.
        role_ids (tuple[int, ...]): 送信者に割り当てられたrole IDの不変列.
    """

    privileges: int = 0
    role_ids: tuple[int, ...] = ()


@dataclass(slots=True, frozen=True)
class SendChannelMessageInput:
    """Channel message送信use-caseの入力を表す.

    Attributes:
        sender (ChatSender): messageを送信するuser.
        destination (ChannelChatDestination): messageを送るchannel.
        content (str): 送信するmessage本文.
        authorization (ChatAuthorization): channel ACL判定に使う送信者authorization snapshot.
    """

    sender: ChatSender
    destination: ChannelChatDestination
    content: str
    authorization: ChatAuthorization = field(default_factory=ChatAuthorization)


@dataclass(slots=True, frozen=True)
class SendPrivateMessageInput:
    """Private message送信use-caseの入力を表す.

    Attributes:
        sender (ChatSender): messageを送信するuser.
        destination (PrivateChatDestination): messageを送るuser.
        content (str): 送信するmessage本文.
        authorization (ChatAuthorization): command処理へ渡す送信者authorization snapshot.
    """

    sender: ChatSender
    destination: PrivateChatDestination
    content: str
    authorization: ChatAuthorization = field(default_factory=ChatAuthorization)


@dataclass(slots=True, frozen=True)
class ChatPersistenceResult:
    """受理済みchat履歴の永続化結果を表す.

    Attributes:
        success (bool): 永続化が成功したか.
        reason (ChatPersistenceFailureReason | None): 失敗理由. 成功時はNone.

    Notes:
        successがTrueならreasonはNoneであり、Falseならreasonを必ず指定する.
    """

    success: bool
    reason: ChatPersistenceFailureReason | None = None

    def __post_init__(self) -> None:
        """成功可否と失敗理由の組み合わせを検証する.

        Returns:
            None: 結果の不変条件を検証して完了する.

        Raises:
            ValueError: successとreasonの組み合わせが不変条件に反する場合.
        """
        if self.success and self.reason is not None:
            msg = "successful chat persistence cannot have a reason"
            raise ValueError(msg)
        if not self.success and self.reason is None:
            msg = "failed chat persistence requires a reason"
            raise ValueError(msg)

    @classmethod
    def success_result(cls) -> Self:
        """失敗理由を持たない成功結果を作成する.

        Returns:
            Self: successがTrueでreasonがNoneの結果.
        """
        return cls(success=True)

    @classmethod
    def failure(cls, reason: ChatPersistenceFailureReason) -> Self:
        """指定した理由を持つ失敗結果を作成する.

        Args:
            reason (ChatPersistenceFailureReason): 永続化に失敗した理由.

        Returns:
            Self: successがFalseで指定reasonを持つ結果.
        """
        return cls(success=False, reason=reason)


@dataclass(slots=True)
class ChatCommandResponse:
    """Chat commandが返す宛先別responseを表す.

    Attributes:
        target (str): responseを送るchannelまたはuser名.
        content (str): response本文.
    """

    target: str
    content: str


@dataclass(slots=True)
class ChannelMessageResult:
    """Channel message配信の結果を表す.

    Attributes:
        delivered_to (set[int] | None): 配信先user ID集合. 配信先が確定しない場合はNone.
        content (str): 配信するmessage本文.
        command_responses (tuple[ChatCommandResponse, ...]): command処理で生成した追加response.
    """

    delivered_to: set[int] | None
    content: str
    command_responses: tuple[ChatCommandResponse, ...] = ()


@dataclass(slots=True)
class PrivateMessageResult:
    """Private message配信の結果を表す.

    Attributes:
        target_id (int | None): 解決した宛先user ID. 宛先未発見時はNone.
        is_online (bool): 宛先がonlineか.
        content (str): 配信するmessage本文.
        command_responses (tuple[ChatCommandResponse, ...]): command処理で生成した追加response.
        delivery_status (PrivateMessageDeliveryStatus): 宛先へ配信できるかを示す状態.
    """

    target_id: int | None
    is_online: bool
    content: str
    command_responses: tuple[ChatCommandResponse, ...] = ()
    delivery_status: PrivateMessageDeliveryStatus = PrivateMessageDeliveryStatus.DELIVERABLE
