"""Tests for the !help BanchoBot registered command.

Requirements covered:
- Req 1.3: !help response lists available commands
- Req 4.1: help lists all commands from registry
- Req 4.2: added command reflected in help output
- Req 4.3: metadata includes command name for help output
"""

from __future__ import annotations

import pytest

from osu_server.services.bancho_bot.commands.general import setup_general
from osu_server.services.bancho_bot.context import (
    CommandContext,
    CommandDestination,
    CommandMetadata,
)
from osu_server.services.bancho_bot.registry import CommandDefinition, CommandRegistry


@pytest.fixture
def help_def() -> CommandDefinition:
    """Return the registered help CommandDefinition."""
    registry = CommandRegistry()
    setup_general(registry)
    resolved = registry.resolve("help")
    assert resolved is not None
    return resolved


def _make_ctx(*commands: CommandMetadata) -> CommandContext:
    """Helper to construct a CommandContext with given available_commands."""
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
    """Req 1.3, 4.3: !help lists a single command."""

    async def test_single_command(self, help_def: CommandDefinition) -> None:
        """Single command produces 'Available commands: !roll'."""
        roll = CommandMetadata(name="roll", description="Roll a random number")
        result = await help_def.handler(_make_ctx(roll))
        assert result == "Available commands: !roll"


class TestHelpMultipleCommands:
    """Req 4.1, 4.2: !help lists multiple commands in registration order."""

    async def test_multiple_preserves_order(self, help_def: CommandDefinition) -> None:
        """Commands appear in registration order from available_commands."""
        roll = CommandMetadata(name="roll", description="Roll a random number")
        help_cmd = CommandMetadata(name="help", description="Show available commands")
        result = await help_def.handler(_make_ctx(roll, help_cmd))
        assert result == "Available commands: !roll, !help"

    async def test_order_matches_available_commands(self, help_def: CommandDefinition) -> None:
        """Reversing registration order changes output order."""
        help_cmd = CommandMetadata(name="help", description="Show available commands")
        roll = CommandMetadata(name="roll", description="Roll a random number")
        result = await help_def.handler(_make_ctx(help_cmd, roll))
        assert result == "Available commands: !help, !roll"


class TestHelpEmptyCommands:
    """Req 1.3: !help with empty available_commands still returns valid message."""

    async def test_empty_available_commands(self, help_def: CommandDefinition) -> None:
        """No available commands produces valid message."""
        result = await help_def.handler(_make_ctx())
        assert result == "Available commands: "
