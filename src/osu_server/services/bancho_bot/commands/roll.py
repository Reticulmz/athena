"""!roll command -- rolls a random number.

Registered as a player-visible command via the @command decorator.
Uses only CommandContext fields (no session access, no DB).
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.services.bancho_bot.context import CommandContext


async def roll_handler(ctx: CommandContext) -> str | None:
    """Execute the !roll command.

    Parses the first argument as a custom max value (default 100).
    Clamps max to at least 1. Returns the roll result as a formatted string.

    Args:
        ctx: Immutable invocation context with sender and args.

    Returns:
        Formatted roll result string, or None (never returns None for roll).
    """
    max_val = 100
    if ctx.args and ctx.args[0].isdigit():
        max_val = int(ctx.args[0])
        max_val = max(max_val, 1)

    result = random.randint(0, max_val)
    return f"{ctx.sender_name} rolls {result} point(s)"
