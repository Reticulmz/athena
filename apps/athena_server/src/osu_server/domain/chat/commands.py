"""BanchoBot command invocationの不変metadataとcontextを定義するmodule."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from osu_server.domain.identity.authorization import Privileges


class CommandDestination(StrEnum):
    """Commandを実行できる宛先種別を表す閉集合.

    Attributes:
        CHANNEL (str): channel内での実行を示す値.
        PM (str): private message内での実行を示す値.
        BOTH (str): channelとprivate messageの両方での実行を示す値.
    """

    CHANNEL = "channel"
    PM = "pm"
    BOTH = "both"


@dataclass(slots=True, frozen=True)
class CommandArgument:
    """Command引数の表示metadataを表す.

    Attributes:
        name (str): usageに表示する引数名.
        required (bool): 引数を必須とするか.
        description (str): 引数の利用者向け説明.
    """

    name: str
    required: bool
    description: str


@dataclass(slots=True, frozen=True)
class CommandMetadata:
    """登録済みcommandを発見・実行判定するための不変metadataを表す.

    Attributes:
        name (str): commandのcanonical名.
        description (str): commandの利用者向け説明.
        usage (str): commandのusage表記. 未指定時は空文字列.
        arguments (tuple[CommandArgument, ...]): usageに現れる引数metadataの順序付き列.
        required_privileges (Privileges): command実行に必要なprivilege bitmask.
        allowed_destinations (CommandDestination): commandを受け付ける宛先種別.
    """

    name: str
    description: str
    usage: str = ""
    arguments: tuple[CommandArgument, ...] = ()
    required_privileges: Privileges = Privileges.NONE
    allowed_destinations: CommandDestination = CommandDestination.BOTH


@dataclass(slots=True, frozen=True)
class CommandContext:
    """単一command実行時の不変invocation contextを表す.

    Attributes:
        sender_id (int): commandを送ったuser ID.
        sender_name (str): commandを送ったuser名.
        target (str): 元のchannel名またはprivate message宛先名.
        command_name (str): 解決済みのcanonical command名.
        args (tuple[str, ...]): 入力順を保ったcommand引数列.
        destination (CommandDestination): commandを受け取った宛先種別.
        available_commands (tuple[CommandMetadata, ...]): 実行時点で利用可能なcommand metadataの
            snapshot.
    """

    sender_id: int
    sender_name: str
    target: str
    command_name: str
    args: tuple[str, ...]
    destination: CommandDestination
    available_commands: tuple[CommandMetadata, ...]
