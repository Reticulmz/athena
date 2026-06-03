"""Tests for BanchoBot command context and metadata value objects.

Requirements covered:
- Req 2.2: argument order preservation in CommandContext.args
- Req 3.2: invocation context with sender identity, destination, command name, arguments
- Req 4.3: metadata includes command name for help output
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from osu_server.services.bancho_bot.context import CommandContext, CommandMetadata


class TestCommandMetadata:
    """Req 4.3: CommandMetadata provides command name, description, and visibility flag."""

    def test_create_minimal(self) -> None:
        """Creating metadata with only name and description succeeds."""
        meta = CommandMetadata(name="roll", description="Roll a random number")
        assert meta.name == "roll"
        assert meta.description == "Roll a random number"

    def test_default_visible(self) -> None:
        """Default visible is True."""
        meta = CommandMetadata(name="help", description="Show help")
        assert meta.visible is True

    def test_explicit_not_visible(self) -> None:
        """Setting visible=False removes it from visible commands."""
        meta = CommandMetadata(name="hidden", description="Hidden command", visible=False)
        assert meta.visible is False

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
            available_commands=available,
        )
        assert ctx.sender_id == 100
        assert ctx.sender_name == "User"
        assert ctx.target == "#osu"
        assert ctx.command_name == "roll"
        assert ctx.args == ("50",)
        assert ctx.available_commands == available

    def test_args_preserves_order(self) -> None:
        """Req 2.2: arguments preserve their original order in CommandContext.args."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="dummy",
            args=("first", "second", "100", "last"),
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
            available_commands=available,
        )
        assert ctx_channel.target == "#osu"

        ctx_pm = CommandContext(
            sender_id=1,
            sender_name="User",
            target="BanchoBot",
            command_name="roll",
            args=(),
            available_commands=available,
        )
        assert ctx_pm.target == "BanchoBot"

    def test_command_name_captures_canonical_name(self) -> None:
        """Req 3.2: command_name captures the resolved canonical command name."""
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="roll",  # canonical, lower-case
            args=(),
            available_commands=available,
        )
        assert ctx.command_name == "roll"
