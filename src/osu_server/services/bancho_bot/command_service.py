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

from osu_server.domain.chat import ChatAuthorization, ChatCommandResponse
from osu_server.domain.role import Privileges, has_privilege
from osu_server.services.bancho_bot.context import CommandContext, CommandDestination

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

    @staticmethod
    def _unknown_response(target: str) -> tuple[ChatCommandResponse, ...]:
        """Return the standard unknown-command response for *target*."""
        return (
            ChatCommandResponse(
                target=target,
                content="Unknown command. Type !help for available commands.",
            ),
        )

    @staticmethod
    def _check_destination_gating(
        allowed_dest: CommandDestination,
        destination: CommandDestination,
        command_name: str,
        response_target: str,
        sender_name: str,
    ) -> tuple[ChatCommandResponse, ...] | None:
        """Return gating responses when *destination* is not allowed, or ``None``.

        Must only be called after privilege checks have passed.
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
        """Parse *content* and, when it names a registered command, execute it.

        Returns an empty tuple for non-command messages, prefix-only content,
        empty command names, and commands whose handler returns ``None``.
        Returns a single-element tuple with an unknown-command response for
        unregistered or unauthorized commands.
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

        ctx = CommandContext(
            sender_id=sender_id,
            sender_name=sender_name,
            target=target,
            command_name=cmd_name,
            args=args,
            destination=destination,
            available_commands=self._registry.commands(),
        )
        response = await definition.handler(ctx)
        if response is None:
            return ()

        return (ChatCommandResponse(target=response_target, content=response),)
