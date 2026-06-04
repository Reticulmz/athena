"""General-purpose BanchoBot commands (!roll, !help).

Registered via ``registry.command()`` decorator inside ``setup_general()``.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.services.bancho_bot.context import CommandContext
    from osu_server.services.bancho_bot.registry import CommandRegistry


def setup_general(registry: CommandRegistry) -> None:
    """Register general-purpose player-visible commands on *registry*."""

    @registry.command("roll", description="Roll a random number", usage="!roll [max]")
    async def roll_handler(ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction] -- captured by decorator
        max_val = 100
        if ctx.args and ctx.args[0].isdigit():
            max_val = int(ctx.args[0])
            max_val = max(max_val, 1)
        result = random.randint(0, max_val)
        return f"{ctx.sender_name} rolls {result} point(s)"

    @registry.command("help", description="Show available commands", usage="!help [--all]")
    async def help_handler(ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction] -- captured by decorator
        available = ", ".join(f"!{cmd.name}" for cmd in ctx.available_commands)
        return f"Available commands: {available}"
