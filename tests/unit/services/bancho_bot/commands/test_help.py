"""Tests for the !help BanchoBot registered command.

Requirements covered:
- Req 1.3: !help response lists available player-visible commands
- Req 4.1: help lists visible commands from registry
- Req 4.2: added command reflected in help output
- Req 4.3: metadata includes command name for help output
"""

from __future__ import annotations

from osu_server.services.bancho_bot.commands.help import help_handler
from osu_server.services.bancho_bot.context import CommandContext, CommandMetadata


def _make_ctx(*commands: CommandMetadata) -> CommandContext:
    """Helper to construct a CommandContext with given available_commands."""
    return CommandContext(
        sender_id=1,
        sender_name="testuser",
        target="#osu",
        command_name="help",
        args=(),
        available_commands=tuple(commands),
    )


class TestHelpSingleVisible:
    """Req 1.3, 4.3: !help lists a single visible command."""

    def test_single_visible_command(self) -> None:
        """Single visible command produces 'Available commands: !roll'."""
        roll = CommandMetadata(name="roll", description="Roll a random number")
        result = help_handler(_make_ctx(roll))
        assert result == "Available commands: !roll"


class TestHelpMultipleVisible:
    """Req 4.1, 4.2: !help lists multiple visible commands in registration order."""

    def test_multiple_visible_preserves_order(self) -> None:
        """Commands appear in registration order from available_commands."""
        roll = CommandMetadata(name="roll", description="Roll a random number")
        help_cmd = CommandMetadata(name="help", description="Show available commands")
        result = help_handler(_make_ctx(roll, help_cmd))
        assert result == "Available commands: !roll, !help"

    def test_order_matches_available_commands(self) -> None:
        """Reversing registration order changes output order."""
        help_cmd = CommandMetadata(name="help", description="Show available commands")
        roll = CommandMetadata(name="roll", description="Roll a random number")
        result = help_handler(_make_ctx(help_cmd, roll))
        assert result == "Available commands: !help, !roll"


class TestHelpHiddenExcluded:
    """Req 4.1: hidden commands are excluded from help output."""

    def test_hidden_command_not_listed(self) -> None:
        """Commands with visible=False do not appear in help."""
        roll = CommandMetadata(name="roll", description="Roll", visible=True)
        secret = CommandMetadata(name="secret", description="Admin only", visible=False)
        result = help_handler(_make_ctx(roll, secret))
        assert result == "Available commands: !roll"

    def test_all_hidden_returns_empty_list(self) -> None:
        """When all commands are hidden, help shows no commands."""
        secret = CommandMetadata(name="secret", description="Hidden", visible=False)
        result = help_handler(_make_ctx(secret))
        assert result == "Available commands: "

    def test_multiple_hidden_excluded(self) -> None:
        """Multiple hidden commands are all excluded."""
        a = CommandMetadata(name="a", description="A", visible=True)
        h1 = CommandMetadata(name="h1", description="H1", visible=False)
        h2 = CommandMetadata(name="h2", description="H2", visible=False)
        result = help_handler(_make_ctx(a, h1, h2))
        assert result == "Available commands: !a"


class TestHelpEmptyCommands:
    """Req 1.3: !help with empty available_commands still returns valid message."""

    def test_empty_available_commands(self) -> None:
        """No available commands produces valid message."""
        result = help_handler(_make_ctx())
        assert result == "Available commands: "
