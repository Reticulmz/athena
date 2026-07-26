"""BanchoBot の !help command を検証する test module.

利用可能な command の一覧と登録順が response に反映される契約を対象とする.
"""

from __future__ import annotations

import pytest

from osu_server.domain.chat.commands import (
    CommandContext,
    CommandDestination,
    CommandMetadata,
)
from osu_server.services.commands.chat.bancho_bot.commands.general import setup_general
from osu_server.services.commands.chat.bancho_bot.registry import (
    CommandDefinition,
    CommandRegistry,
)


@pytest.fixture
def help_def() -> CommandDefinition:
    """登録済みの help definition を general command registry から提供する.

    Returns:
        CommandDefinition: handler 呼び出しに使用する help command definition.
    """
    registry = CommandRegistry()
    setup_general(registry)
    resolved = registry.resolve("help")
    assert resolved is not None
    return resolved


def _make_ctx(*commands: CommandMetadata) -> CommandContext:
    """指定した command metadata を含む help 用 context を生成する.

    Args:
        commands (CommandMetadata): available_commands へ含める metadata の並び.

    Returns:
        CommandContext: help handler へ渡す command context.
    """
    return CommandContext(
        sender_id=1,
        sender_name="testuser",
        target="#osu",
        command_name="help",
        args=(),
        destination=CommandDestination.CHANNEL,
        available_commands=tuple(commands),
    )


class TestHelpSingleCommand:
    """単一 command の !help response を検証する.

    command metadata の name が player-visible 一覧へ反映される契約を対象とする.
    """

    async def test_single_command(self, help_def: CommandDefinition) -> None:
        """単一の roll metadata から期待する help response が得られることを検証する.

        Args:
            help_def (CommandDefinition): 登録済み help command definition.

        Returns:
            None: !roll だけを含む response を検証して完了する.
        """
        roll = CommandMetadata(name="roll", description="Roll a random number")
        result = await help_def.handler(_make_ctx(roll))
        assert result == "Available commands: !roll"


class TestHelpMultipleCommands:
    """複数 command の !help response を検証する.

    available_commands の順序が一覧 response の順序になる契約を対象とする.
    """

    async def test_multiple_preserves_order(self, help_def: CommandDefinition) -> None:
        """複数 command が supplied order のまま一覧になることを検証する.

        Args:
            help_def (CommandDefinition): 登録済み help command definition.

        Returns:
            None: roll と help の response 順序を検証して完了する.
        """
        roll = CommandMetadata(name="roll", description="Roll a random number")
        help_cmd = CommandMetadata(name="help", description="Show available commands")
        result = await help_def.handler(_make_ctx(roll, help_cmd))
        assert result == "Available commands: !roll, !help"

    async def test_order_matches_available_commands(self, help_def: CommandDefinition) -> None:
        """入力 metadata の順序を反転すると response 順序も反転することを検証する.

        Args:
            help_def (CommandDefinition): 登録済み help command definition.

        Returns:
            None: available_commands と response の順序一致を検証して完了する.
        """
        help_cmd = CommandMetadata(name="help", description="Show available commands")
        roll = CommandMetadata(name="roll", description="Roll a random number")
        result = await help_def.handler(_make_ctx(help_cmd, roll))
        assert result == "Available commands: !help, !roll"


class TestHelpEmptyCommands:
    """空の command list に対する !help response を検証する.

    利用可能な command がない場合も有効な response prefix を返す契約を対象とする.
    """

    async def test_empty_available_commands(self, help_def: CommandDefinition) -> None:
        """空の available_commands でも有効な help message を返すことを検証する.

        Args:
            help_def (CommandDefinition): 登録済み help command definition.

        Returns:
            None: command 名を含まない response を検証して完了する.
        """
        result = await help_def.handler(_make_ctx())
        assert result == "Available commands: "
