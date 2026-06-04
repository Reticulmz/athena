"""Tests for BanchoBot command context and metadata value objects.

Requirements covered:
- Req 1.1: command metadata includes name, description, usage, arguments,
  required_privileges, allowed_destinations
- Req 2.2: argument order preservation in CommandContext.args
- Req 3.2: invocation context with sender identity, destination, command name, arguments
- Req 4.3: metadata includes command name for help output
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from osu_server.domain.bancho_bot import (
    CommandArgument,
    CommandContext,
    CommandDestination,
    CommandMetadata,
)
from osu_server.domain.role import Privileges


class TestCommandDestination:
    """CommandDestination enum has CHANNEL, PM, and BOTH values."""

    def test_channel_value(self) -> None:
        assert CommandDestination.CHANNEL == "channel"

    def test_pm_value(self) -> None:
        assert CommandDestination.PM == "pm"

    def test_both_value(self) -> None:
        assert CommandDestination.BOTH == "both"

    def test_is_str_enum(self) -> None:
        assert isinstance(CommandDestination.CHANNEL, str)


class TestCommandArgument:
    """CommandArgument is an immutable value object for argument metadata."""

    def test_create(self) -> None:
        arg = CommandArgument(name="max", required=False, description="Maximum value")
        assert arg.name == "max"
        assert arg.required is False
        assert arg.description == "Maximum value"

    def test_required_arg(self) -> None:
        arg = CommandArgument(name="username", required=True, description="Target user")
        assert arg.required is True

    def test_is_immutable(self) -> None:
        arg = CommandArgument(name="max", required=False, description="Maximum value")
        with pytest.raises(FrozenInstanceError):
            arg.name = "min"  # pyright: ignore[reportAttributeAccessIssue]


class TestCommandMetadata:
    """Req 1.1, 4.3: CommandMetadata provides command name, description, usage,
    arguments, required_privileges, and allowed_destinations."""

    def test_create_minimal(self) -> None:
        """Creating metadata with only name and description succeeds."""
        meta = CommandMetadata(name="roll", description="Roll a random number")
        assert meta.name == "roll"
        assert meta.description == "Roll a random number"

    def test_default_usage_is_empty(self) -> None:
        """Default usage is empty string."""
        meta = CommandMetadata(name="help", description="Show help")
        assert meta.usage == ""

    def test_default_arguments_is_empty(self) -> None:
        """Default arguments is empty tuple."""
        meta = CommandMetadata(name="help", description="Show help")
        assert meta.arguments == ()

    def test_default_required_privileges_is_none(self) -> None:
        """Default required_privileges is Privileges.NONE (public command)."""
        meta = CommandMetadata(name="help", description="Show help")
        assert meta.required_privileges == Privileges.NONE

    def test_default_allowed_destinations_is_both(self) -> None:
        """Default allowed_destinations is BOTH (channel and PM)."""
        meta = CommandMetadata(name="help", description="Show help")
        assert meta.allowed_destinations == CommandDestination.BOTH

    def test_explicit_required_privileges(self) -> None:
        """Setting required_privileges restricts command to specific privilege."""
        meta = CommandMetadata(
            name="admin_cmd",
            description="Admin only",
            required_privileges=Privileges.ADMIN,
        )
        assert meta.required_privileges == Privileges.ADMIN

    def test_explicit_allowed_destinations(self) -> None:
        """Setting allowed_destinations restricts where command can run."""
        meta = CommandMetadata(
            name="pm_only",
            description="PM only",
            allowed_destinations=CommandDestination.PM,
        )
        assert meta.allowed_destinations == CommandDestination.PM

    def test_with_usage(self) -> None:
        """Usage string is stored correctly."""
        meta = CommandMetadata(name="roll", description="Roll", usage="!roll [max]")
        assert meta.usage == "!roll [max]"

    def test_with_arguments(self) -> None:
        """Arguments tuple is stored correctly."""
        args = (CommandArgument(name="max", required=False, description="Max"),)
        meta = CommandMetadata(name="roll", description="Roll", arguments=args)
        assert meta.arguments == args

    def test_is_immutable(self) -> None:
        """CommandMetadata is frozen and cannot be mutated after creation."""
        meta = CommandMetadata(name="roll", description="roll")
        with pytest.raises(FrozenInstanceError):
            meta.name = "new_name"  # pyright: ignore[reportAttributeAccessIssue]


class TestCommandContext:
    """Req 2.2, 3.2: CommandContext provides immutable typed input to command handlers."""

    @staticmethod
    def _make_available_commands() -> tuple[CommandMetadata, ...]:
        return (
            CommandMetadata(name="roll", description="Roll a random number"),
            CommandMetadata(name="help", description="Show available commands"),
        )

    def test_create_with_all_fields(self) -> None:
        """Creating context with all required fields succeeds."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=100,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=("50",),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.sender_id == 100
        assert ctx.sender_name == "User"
        assert ctx.target == "#osu"
        assert ctx.command_name == "roll"
        assert ctx.args == ("50",)
        assert ctx.destination == CommandDestination.CHANNEL
        assert ctx.available_commands == available

    def test_destination_channel_when_target_has_hash(self) -> None:
        """Context destination is CHANNEL when target starts with #."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.destination == CommandDestination.CHANNEL

    def test_destination_pm_when_target_no_hash(self) -> None:
        """Context destination is PM when target does not start with #."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="BanchoBot",
            command_name="roll",
            args=(),
            destination=CommandDestination.PM,
            available_commands=available,
        )
        assert ctx.destination == CommandDestination.PM

    def test_args_preserves_order(self) -> None:
        """Req 2.2: arguments preserve their original order in CommandContext.args."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="dummy",
            args=("first", "second", "100", "last"),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.args == ("first", "second", "100", "last")
        assert ctx.args[0] == "first"
        assert ctx.args[1] == "second"
        assert ctx.args[2] == "100"
        assert ctx.args[3] == "last"

    def test_empty_args(self) -> None:
        """Args can be an empty tuple."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="help",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.args == ()

    def test_is_immutable(self) -> None:
        """CommandContext is frozen and cannot be mutated after creation."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=100,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        with pytest.raises(FrozenInstanceError):
            ctx.sender_id = 999  # pyright: ignore[reportAttributeAccessIssue]

    def test_is_immutable_args(self) -> None:
        """CommandContext.args is a tuple and cannot be mutated."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=100,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=("a", "b"),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        with pytest.raises(TypeError):
            ctx.args[0] = "x"  # pyright: ignore[reportIndexIssue]

    def test_is_immutable_available_commands(self) -> None:
        """CommandContext.available_commands is a tuple and cannot be mutated."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=100,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        with pytest.raises(TypeError):
            ctx.available_commands[0] = CommandMetadata(name="x", description="x")  # pyright: ignore[reportIndexIssue]

    def test_sender_identity_captures_id_and_name(self) -> None:
        """Req 3.2: context captures sender_id and sender_name for handler use."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=42,
            sender_name="PlayerOne",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.sender_id == 42
        assert ctx.sender_name == "PlayerOne"

    def test_destination_captured_in_target(self) -> None:
        """Req 3.2: target field captures destination (channel name or PM target)."""
        available = self._make_available_commands()
        ctx_channel = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx_channel.target == "#osu"
        assert ctx_channel.destination == CommandDestination.CHANNEL

        ctx_pm = CommandContext(
            sender_id=1,
            sender_name="User",
            target="BanchoBot",
            command_name="roll",
            args=(),
            destination=CommandDestination.PM,
            available_commands=available,
        )
        assert ctx_pm.target == "BanchoBot"
        assert ctx_pm.destination == CommandDestination.PM

    def test_command_name_captures_canonical_name(self) -> None:
        """Req 3.2: command_name captures the resolved canonical command name."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="roll",  # canonical, lower-case
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.command_name == "roll"
