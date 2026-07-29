"""BanchoBot の builtin handler と command catalog を構成する.

composition root は `create_builtin_registry()` を通じて,決定的な登録順を持つ
player-visible command registry を取得する.
"""

from __future__ import annotations

from osu_server.services.commands.chat.bancho_bot.commands.general import setup_general
from osu_server.services.commands.chat.bancho_bot.registry import CommandRegistry


def create_builtin_registry() -> CommandRegistry:
    """Builtin の player-visible command を登録済みの registry を作成する.

    登録順は `setup_*()` 呼び出しの順番で決まり,現在は `setup_general()` が `!roll` と
    `!help` をこの順で登録する.

    Returns:
        CommandRegistry: 全 builtin command を決定的な順番で登録した新しい registry.
    """
    registry = CommandRegistry()
    setup_general(registry)
    return registry
