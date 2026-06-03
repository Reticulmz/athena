"""CommandService -- parses chat content, resolves commands, and returns responses.

The service detects the "!" command prefix, extracts the command name and
arguments, resolves the handler case-insensitively through a CommandRegistry,
builds an immutable CommandContext, and returns a ChatCommandResponse when a
handler produces output.

It does NOT own BanchoBot author identity -- that responsibility stays in
the transport layer via BANCHO_BOT_IDENTITY.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.chat import ChatCommandResponse
from osu_server.services.bancho_bot.context import CommandContext

if TYPE_CHECKING:
    from osu_server.services.bancho_bot.registry import CommandRegistry


class CommandService:
    """Parse chat content and execute registered BanchoBot commands.

    Constructor-injected with a CommandRegistry.  Command resolution is
    case-insensitive.  Response target semantics match the existing behaviour:
    channel targets stay channel, PM targets become the sender's username.
    """

    def __init__(self, registry: CommandRegistry) -> None:
        self._registry: CommandRegistry = registry

    async def execute(
        self,
        sender_id: int,
        sender_name: str,
        target: str,
        content: str,
    ) -> ChatCommandResponse | None:
        """Parse *content* and, when it names a registered command, execute it.

        Returns ``None`` for non-command messages, prefix-only content, empty
        command names, unresolved commands whose handler returns ``None``, and
        commands that return ``None`` from their handler.
        """
        if not content.startswith("!"):
            return None

        parts = content[1:].strip().split()
        if not parts:
            return None

        cmd_name = parts[0].lower()
        args = tuple(parts[1:])

        response_target = target
        if not target.startswith("#"):
            # BanchoBot PM: reply target is the sender's username.
            response_target = sender_name

        definition = self._registry.resolve(cmd_name)
        if definition is None:
            return ChatCommandResponse(
                target=response_target,
                content="Unknown command. Type !help for available commands.",
            )

        ctx = CommandContext(
            sender_id=sender_id,
            sender_name=sender_name,
            target=target,
            command_name=cmd_name,
            args=args,
            available_commands=self._registry.visible_commands(),
        )
        response = await definition.handler(ctx)
        if response is None:
            return None

        return ChatCommandResponse(target=response_target, content=response)
