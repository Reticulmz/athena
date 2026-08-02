"""BanchoBot command の実行,登録,metadata を扱う公開 namespace を提供する.

この module は chat command use-case が利用する command service と registry の安定した
import surface を再 export する. handler の実装と builtin catalog は下位 module に閉じる.
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
