"""Tests for the builtin command catalog (create_builtin_registry).

Requirements covered:
- Req 1.3: builtin registry produces correct help output
- Req 4.1: help lists visible commands from builtin registry
- Req 4.2: registration order preserved in builtin catalog
- Req 5.1: no new player-visible commands beyond roll and help
"""

from __future__ import annotations

from unittest import mock

from osu_server.domain.role import Privileges
from osu_server.services.bancho_bot.commands import create_builtin_registry
from osu_server.services.bancho_bot.context import CommandContext, CommandDestination
from osu_server.services.bancho_bot.registry import CommandRegistry


def _make_help_ctx(registry: CommandRegistry) -> CommandContext:
    """Construct a CommandContext for help command using the registry's commands."""
    return CommandContext(
        sender_id=1,
        sender_name="testuser",
        target="#osu",
        command_name="help",
        args=(),
        destination=CommandDestination.CHANNEL,
        available_commands=registry.commands(),
    )


class TestBuiltinRegistryStructure:
    """Req 5.1: builtin registry contains exactly roll and help, no new commands."""

    def test_returns_command_registry(self) -> None:
        """create_builtin_registry returns a CommandRegistry instance."""
        registry = create_builtin_registry()
        assert isinstance(registry, CommandRegistry)

    def test_exactly_two_commands(self) -> None:
        """Builtin catalog registers exactly two commands."""
        registry = create_builtin_registry()
        all_cmds = registry.commands()
        assert len(all_cmds) == 2

    def test_registration_order_roll_then_help(self) -> None:
        """Req 4.2: roll is registered before help."""
        registry = create_builtin_registry()
        all_cmds = registry.commands()
        assert all_cmds[0].name == "roll"
        assert all_cmds[1].name == "help"

    def test_both_commands_are_public(self) -> None:
        """Both roll and help require no special privileges."""
        registry = create_builtin_registry()
        roll_def = registry.resolve("roll")
        help_def = registry.resolve("help")
        assert roll_def is not None
        assert help_def is not None
        assert roll_def.metadata.required_privileges == Privileges.NONE
        assert help_def.metadata.required_privileges == Privileges.NONE

    def test_no_other_commands_registered(self) -> None:
        """Req 5.1: resolving any name other than roll or help returns None."""
        registry = create_builtin_registry()
        assert registry.resolve("unknown") is None
        assert registry.resolve("admin") is None
        assert registry.resolve("") is None

    def test_roll_resolves_case_insensitively(self) -> None:
        """Roll command resolves regardless of case."""
        registry = create_builtin_registry()
        assert registry.resolve("ROLL") is not None
        assert registry.resolve("Roll") is not None
        assert registry.resolve("rOlL") is not None

    def test_help_resolves_case_insensitively(self) -> None:
        """Help command resolves regardless of case."""
        registry = create_builtin_registry()
        assert registry.resolve("HELP") is not None
        assert registry.resolve("Help") is not None


class TestBuiltinRegistryHelpOutput:
    """Req 1.3, 4.1: builtin registry produces correct help output."""

    async def test_help_output_matches_expected(self) -> None:
        """!help via builtin registry returns 'Available commands: !roll, !help'."""
        registry = create_builtin_registry()
        help_def = registry.resolve("help")
        assert help_def is not None
        ctx = _make_help_ctx(registry)
        result = await help_def.handler(ctx)
        assert result == "Available commands: !roll, !help"

    def test_help_output_uses_registration_order(self) -> None:
        """Help output respects builtin registration order (roll before help)."""
        registry = create_builtin_registry()
        all_cmds = registry.commands()
        names = [cmd.name for cmd in all_cmds]
        assert names == ["roll", "help"]


class TestBuiltinRegistryHandlers:
    """Verify builtin handlers are wired to the correct implementations."""

    async def test_roll_handler_produces_correct_response(self) -> None:
        """The builtin roll handler returns correct roll format."""
        registry = create_builtin_registry()
        roll_def = registry.resolve("roll")
        assert roll_def is not None

        ctx = CommandContext(
            sender_id=1,
            sender_name="Test",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=registry.commands(),
        )
        with mock.patch("random.randint", return_value=50):
            result = await roll_def.handler(ctx)

        assert result == "Test rolls 50 point(s)"

    async def test_help_handler_produces_correct_output(self) -> None:
        """The builtin help handler produces correct help output."""
        registry = create_builtin_registry()
        help_def = registry.resolve("help")
        assert help_def is not None

        ctx = CommandContext(
            sender_id=1,
            sender_name="Test",
            target="#osu",
            command_name="help",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=registry.commands(),
        )
        result = await help_def.handler(ctx)
        assert result == "Available commands: !roll, !help"
