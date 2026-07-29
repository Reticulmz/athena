"""BanchoBot command text を解析し,登録済み handler の response へ変換する.

service は `!` prefix,command name,argument を抽出し,case-insensitive な registry から
handler
を解決する. handler が出力する場合は immutable `CommandContext` と `ChatCommandResponse`
を作る.
BanchoBot の author identity は transport layer の責務であり,この module は所有しない.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.chat import ChatAuthorization, ChatCommandResponse
from osu_server.domain.chat.commands import (
    CommandContext,
    CommandDestination,
    CommandMetadata,
)
from osu_server.domain.identity.authorization import Privileges, has_privilege

if TYPE_CHECKING:
    from osu_server.services.commands.chat.bancho_bot.registry import CommandRegistry


class CommandService:
    """chat content を解析し,登録済み BanchoBot command を実行する.

    command name の解決は case-insensitive である. channel target は channel へ response
    を返し,
    PM target は sender username へ response を返す.

    Attributes:
        _registry (CommandRegistry): command metadata と async handler を解決する registry.
        _HELP_HELP_CONTENT (str): `!help --help` に返す固定の usage text.
    """

    def __init__(self, registry: CommandRegistry) -> None:
        """Command 実行に使用する registry を設定する.

        Args:
            registry (CommandRegistry):
                case-insensitive な command lookup と登録順 metadata を提供する registry.

        """
        self._registry: CommandRegistry = registry

    @staticmethod
    def _unknown_response(target: str) -> tuple[ChatCommandResponse, ...]:
        """Target 向けの標準 unknown-command response を作成する.

        Args:
            target (str): response を送信する channel name または sender username.

        Returns:
            tuple[ChatCommandResponse, ...]: unknown command を案内する1件の response.
        """
        return (
            ChatCommandResponse(
                target=target,
                content="Unknown command. Type !help for available commands.",
            ),
        )

    @staticmethod
    def _is_command_visible(
        meta: CommandMetadata,
        privileges: int,
        destination: CommandDestination,
    ) -> bool:
        """Metadata の command が privilege と destination で可視かを判定する.

        Args:
            meta (CommandMetadata): 必要 privilege と許可 destination を持つ command metadata.
            privileges (int): caller の server-side privilege bitset.
            destination (CommandDestination):
                command を実行しようとする channel または PM destination.

        Returns:
            bool: privilege を満たし,metadata が destination を許可する場合はTrue.
        """
        if meta.required_privileges != Privileges.NONE and not has_privilege(
            privileges, meta.required_privileges
        ):
            return False
        return meta.allowed_destinations in (CommandDestination.BOTH, destination)

    @staticmethod
    def _detail_help_response(
        meta: CommandMetadata,
        target: str,
    ) -> tuple[ChatCommandResponse, ...]:
        """Metadata の common detail help を target 向けに作成する.

        Args:
            meta (CommandMetadata): usage と argument description を持つ command metadata.
            target (str): detail help response を送信する channel name または sender username.

        Returns:
            tuple[ChatCommandResponse, ...]: usage と argument の required status を含む1件の
            response.
        """
        lines = [f"Usage: {meta.usage}"]
        if meta.arguments:
            lines.append("Arguments:")
            for arg in meta.arguments:
                req = "required" if arg.required else "optional"
                lines.append(f"  {arg.name} ({req}) - {arg.description}")
        return (ChatCommandResponse(target=target, content="\n".join(lines)),)

    _HELP_HELP_CONTENT: str = (
        "Usage: !help [--all]\nOptions:\n  --all  Show all available commands with descriptions"
    )

    @staticmethod
    def _try_common_help(
        args: tuple[str, ...],
        cmd_name: str,
        meta: CommandMetadata,
        target: str,
    ) -> tuple[ChatCommandResponse, ...] | None:
        """先頭 argument が`--help`の場合に common help response を返す.

        Args:
            args (tuple[str, ...]): command name の後ろに解析された argument 群.
            cmd_name (str): case-normalized された command name.
            meta (CommandMetadata): help を作成する command metadata.
            target (str): help response を送信する channel name または sender username.

        Returns:
            tuple[ChatCommandResponse, ...] | None: `--help` が先頭なら help response.
            それ以外はNone.
        """
        if not args or args[0] != "--help":
            return None
        if cmd_name == "help":
            return (
                ChatCommandResponse(
                    target=target,
                    content=CommandService._HELP_HELP_CONTENT,
                ),
            )
        return CommandService._detail_help_response(meta, target)

    @staticmethod
    def _check_destination_gating(
        allowed_dest: CommandDestination,
        destination: CommandDestination,
        command_name: str,
        response_target: str,
        sender_name: str,
    ) -> tuple[ChatCommandResponse, ...] | None:
        """Destination が許可されない場合に guidance response を返す.

        Args:
            allowed_dest (CommandDestination): metadata が許可する destination.
            destination (CommandDestination): caller が command を実行した destination.
            command_name (str): guidance text に表示する command name.
            response_target (str): channel または PM へ返す primary response target.
            sender_name (str): channel から PM guidance を送る sender username.

        Returns:
            tuple[ChatCommandResponse, ...] | None: destination が不許可なら unknown response
            または
            guidance response. 許可される場合はNone.

        Notes:
            caller privilege の検証が済んだ後だけ呼び出す. channel で PM-only command
            を使った場合は channel の unknown
            response と sender への PM guidance を返す.
        """
        if allowed_dest == CommandDestination.BOTH:
            return None
        if destination == allowed_dest:
            return None

        guidance = f"The !{command_name} command can only be used in {allowed_dest.value}."
        if destination == CommandDestination.CHANNEL:
            # PM-only command in public channel: unknown to channel + PM guidance
            return (
                ChatCommandResponse(
                    target=response_target,
                    content="Unknown command. Type !help for available commands.",
                ),
                ChatCommandResponse(target=sender_name, content=guidance),
            )
        # Channel-only command in PM: sender PM guidance only
        return (ChatCommandResponse(target=response_target, content=guidance),)

    async def execute(
        self,
        sender_id: int,
        sender_name: str,
        target: str,
        content: str,
        authorization: ChatAuthorization,
    ) -> tuple[ChatCommandResponse, ...]:
        """Content を解析し,登録済み command なら handler を実行する.

        Args:
            sender_id (int): command を送信した user の識別子.
            sender_name (str): PM response target と `CommandContext` に使う sender username.
            target (str): 先頭が`#`なら channel,それ以外なら PM と扱う送信先.
            content (str): `!` prefix を含む可能性がある chat message text.
            authorization (ChatAuthorization):
                command visibility を判定する privilege と role snapshot.

        Returns:
            tuple[ChatCommandResponse, ...]: non-command,空 command,handler のNone
            outputなら空 tuple.
            未登録または未認可なら unknown response. 実行成功なら handler output の response.

        Notes:
            PM の response target は input target ではなく sender name になる. destination
            gating は
            privilege check の後に行い,未認可 command の存在を guidance で漏らさない.
        """
        if not content.startswith("!"):
            return ()

        parts = content[1:].strip().split()
        if not parts:
            return ()

        cmd_name = parts[0].lower()
        args = tuple(parts[1:])

        destination = (
            CommandDestination.CHANNEL if target.startswith("#") else CommandDestination.PM
        )

        response_target = target
        if not target.startswith("#"):
            # BanchoBot PM: reply target is the sender's username.
            response_target = sender_name

        definition = self._registry.resolve(cmd_name)
        if definition is None or (
            definition.metadata.required_privileges != Privileges.NONE
            and not has_privilege(
                authorization.privileges, definition.metadata.required_privileges
            )
        ):
            return self._unknown_response(response_target)

        # Check destination gating (after privilege check per Req 2.8)
        gating = self._check_destination_gating(
            definition.metadata.allowed_destinations,
            destination,
            definition.metadata.name,
            response_target,
            sender_name,
        )
        if gating is not None:
            return gating

        # Common --help handling (Req 4.5): intercept before handler execution
        help_response = self._try_common_help(args, cmd_name, definition.metadata, response_target)
        if help_response is not None:
            return help_response

        ctx = CommandContext(
            sender_id=sender_id,
            sender_name=sender_name,
            target=target,
            command_name=cmd_name,
            args=args,
            destination=destination,
            available_commands=tuple(
                meta
                for meta in self._registry.commands()
                if self._is_command_visible(meta, authorization.privileges, destination)
            ),
        )
        response = await definition.handler(ctx)
        return (
            ()
            if response is None
            else (ChatCommandResponse(target=response_target, content=response),)
        )
