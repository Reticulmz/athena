"""BanchoBot registered command handlers and builtin catalog.

Provides `create_builtin_registry()` for composition roots to obtain a
deterministically ordered registry of builtin player-visible commands.
"""

from __future__ import annotations

from osu_server.services.bancho_bot.commands.help import help_handler
from osu_server.services.bancho_bot.commands.roll import roll_handler
from osu_server.services.bancho_bot.registry import CommandRegistry, command


def create_builtin_registry() -> CommandRegistry:
    """Create a registry pre-populated with builtin player-visible commands.

    Registration order (roll then help) is deterministic and determines
    !help output ordering.

    Returns:
        A new CommandRegistry with roll and help registered.
    """
    registry = CommandRegistry()

    roll_cmd = command("roll", description="Roll a random number")
    registry.register(roll_cmd(roll_handler))

    help_cmd = command("help", description="Show available commands")
    registry.register(help_cmd(help_handler))

    return registry
