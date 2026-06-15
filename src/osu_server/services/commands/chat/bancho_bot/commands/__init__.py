"""BanchoBot registered command handlers and builtin catalog.

Provides `create_builtin_registry()` for composition roots to obtain a
deterministically ordered registry of builtin player-visible commands.
"""

from __future__ import annotations

from osu_server.services.commands.chat.bancho_bot.commands.general import setup_general
from osu_server.services.commands.chat.bancho_bot.registry import CommandRegistry


def create_builtin_registry() -> CommandRegistry:
    """Create a registry pre-populated with builtin player-visible commands.

    Registration order is determined by the order of ``setup_*()`` calls.
    Currently only ``setup_general()`` registers ``!roll`` then ``!help``.

    Returns:
        A new CommandRegistry with all builtin commands registered.
    """
    registry = CommandRegistry()
    setup_general(registry)
    return registry
