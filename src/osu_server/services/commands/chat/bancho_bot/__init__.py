"""BanchoBot command service namespace.

Public API for BanchoBot command invocation, registration, and metadata.
"""

from osu_server.domain.chat.commands import CommandContext, CommandMetadata
from osu_server.services.commands.chat.bancho_bot.command_service import CommandService
from osu_server.services.commands.chat.bancho_bot.registry import (
    CommandDefinition,
    CommandHandler,
    CommandRegistry,
    command,
)

__all__ = [
    "CommandContext",
    "CommandDefinition",
    "CommandHandler",
    "CommandMetadata",
    "CommandRegistry",
    "CommandService",
    "command",
]
