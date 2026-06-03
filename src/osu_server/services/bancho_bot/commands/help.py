"""!help command handler -- lists player-visible commands (Req 1.3, 4.1, 4.2, 4.3).

Reads visible command metadata from CommandContext.available_commands and
formats them into a human-readable listing in registration order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.services.bancho_bot.context import CommandContext


def help_handler(ctx: CommandContext) -> str | None:
    """Return a formatted list of visible commands.

    Reads ctx.available_commands (tuple of CommandMetadata), filters to
    commands with visible=True, and formats them as a comma-separated list
    preserving registration order.

    Args:
        ctx: The immutable invocation context with available_commands snapshot.

    Returns:
        A string like "Available commands: !roll, !help" or
        "Available commands: " when no visible commands exist.
    """
    visible_names = [cmd.name for cmd in ctx.available_commands if cmd.visible]
    available = ", ".join(f"!{name}" for name in visible_names)
    return f"Available commands: {available}"
