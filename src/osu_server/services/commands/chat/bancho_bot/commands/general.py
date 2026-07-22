"""BanchoBot の一般用途 command `!roll` と `!help` を登録する.

handler は `setup_general()` 内で `registry.command()` decorator により登録される. handler
自体は
registry が保持するため、module から個別に公開しない.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from osu_server.domain.chat.commands import CommandArgument

if TYPE_CHECKING:
    from osu_server.domain.chat.commands import CommandContext
    from osu_server.services.commands.chat.bancho_bot.registry import CommandRegistry


def setup_general(registry: CommandRegistry) -> None:
    """player-visible な一般用途 command を registry へ登録する.

    Args:
        registry (CommandRegistry): `!roll` と `!help` を決定的な順番で受け取る registry.

    Returns:
        None: 2つの builtin handler を登録して完了し、呼び出し側へ値を返さない.
    """

    @registry.command(
        "roll",
        description="Roll a random number",
        usage="!roll [max]",
        arguments=(
            CommandArgument(
                name="max", required=False, description="Maximum roll value (default: 100)"
            ),
        ),
    )
    async def roll_handler(ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction] -- captured by decorator
        """`!roll` command の response text を作成する.

        Args:
            ctx (CommandContext):
                sender name と optional maximum argument を含む command context.

        Returns:
            str | None: sender name と0以上の roll result を含む response text. 現在の handler
            は常にstrを返す.

        Notes:
            先頭 argument が数値なら maximum として使い、0以下の数値は1へ丸める.
            数値以外または argument なしでは100を使う.
        """
        max_val = 100
        if ctx.args and ctx.args[0].isdigit():
            max_val = int(ctx.args[0])
            max_val = max(max_val, 1)
        result = random.randint(0, max_val)
        return f"{ctx.sender_name} rolls {result} point(s)"

    @registry.command("help", description="Show available commands", usage="!help [--all]")
    async def help_handler(ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction] -- captured by decorator
        """`!help` command の response text を作成する.

        Args:
            ctx (CommandContext):
                visibility filter 済み available command と argument を含む command context.

        Returns:
            str | None: `--all`なら description 付きの command list、それ以外なら command name
            list. 現在の
            handler は常にstrを返す.
        """
        if ctx.args and ctx.args[0] == "--all":
            lines = ["Available commands:"]
            lines.extend(f"  !{cmd.name} - {cmd.description}" for cmd in ctx.available_commands)
            return "\n".join(lines)
        available = ", ".join(f"!{cmd.name}" for cmd in ctx.available_commands)
        return f"Available commands: {available}"
