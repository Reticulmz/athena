"""Tests for BanchoBot command registry and decorator contract.

Requirements covered:
- Req 2.1: case-insensitive command resolution
- Req 3.1: standard registration contract via decorator
- Req 4.1: help lists visible commands
- Req 4.2: added command reflected in help
- Req 4.3: metadata includes command name for help output
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from osu_server.services.bancho_bot.context import CommandContext, CommandMetadata
from osu_server.services.bancho_bot.registry import (
    CommandDefinition,
    CommandRegistry,
    command,
)


class TestCommandDefinition:
    """CommandDefinition creates an immutable binding between metadata and handler."""

    def test_create_definition(self) -> None:
        """Creating a CommandDefinition with metadata and handler succeeds."""
        meta = CommandMetadata(name="roll", description="Roll a random number")

        async def handler(_ctx: CommandContext) -> str | None:
            return "result"

        definition = CommandDefinition(metadata=meta, handler=handler)
        assert definition.metadata == meta
        assert definition.handler is handler

    def test_is_immutable(self) -> None:
        """CommandDefinition is frozen."""
        meta = CommandMetadata(name="roll", description="roll")

        async def handler(_ctx: CommandContext) -> str | None:
            return None

        definition = CommandDefinition(metadata=meta, handler=handler)
        with pytest.raises(FrozenInstanceError):
            definition.metadata = CommandMetadata(name="x", description="x")  # pyright: ignore[reportAttributeAccessIssue]

    def test_handler_is_callable(self) -> None:
        """The handler field holds a callable matching CommandHandler signature."""
        meta = CommandMetadata(name="test", description="test")

        async def test_handler(ctx: CommandContext) -> str | None:
            return f"{ctx.command_name} ran"

        definition = CommandDefinition(metadata=meta, handler=test_handler)
        assert callable(definition.handler)

    def test_handler_is_async(self) -> None:
        """The handler is async and awaits without issue."""
        meta = CommandMetadata(name="async", description="test")

        async def async_handler(_ctx: CommandContext) -> str | None:
            return "async result"

        _ = CommandDefinition(metadata=meta, handler=async_handler)

        result = asyncio.run(
            async_handler(
                CommandContext(
                    sender_id=1,
                    sender_name="u",
                    target="#o",
                    command_name="async",
                    args=(),
                    available_commands=(),
                )
            )
        )
        assert result == "async result"


class TestCommandRegistry:
    """Req 2.1, 4.1, 4.2: registry stores, resolves, and lists commands."""

    @staticmethod
    def _make_definition(name: str, description: str = "") -> CommandDefinition:
        async def handler(_ctx: CommandContext) -> str | None:
            return None

        return CommandDefinition(
            metadata=CommandMetadata(name=name, description=description),
            handler=handler,
        )

    def test_register_and_resolve(self) -> None:
        """Registering a definition makes it resolvable by name."""
        registry = CommandRegistry()
        definition = self._make_definition("roll", "Roll a number")
        registry.register(definition)

        resolved = registry.resolve("roll")
        assert resolved is definition

    def test_resolve_returns_none_for_unknown(self) -> None:
        """Resolving an unregistered name returns None."""
        registry = CommandRegistry()
        assert registry.resolve("unknown") is None

    def test_resolve_is_case_insensitive(self) -> None:
        """Req 2.1: resolve accepts mixed-case names and returns canonical definition."""
        registry = CommandRegistry()
        definition = self._make_definition("roll", "Roll")
        registry.register(definition)

        assert registry.resolve("ROLL") is definition
        assert registry.resolve("Roll") is definition
        assert registry.resolve("rOLL") is definition

    def test_register_preserves_case(self) -> None:
        """
        After registration, the command is stored by canonical lower-case name.
        This is an implementation detail: the name passed during registration
        becomes the canonical lower-case key.
        """
        registry = CommandRegistry()
        definition = self._make_definition("roll")
        registry.register(definition)

        # Resolving by any case form returns the same definition
        assert registry.resolve("ROLL") is definition
        assert registry.resolve("roll") is definition

    def test_reject_duplicate_name(self) -> None:
        """Registering the same command name twice raises an error."""
        registry = CommandRegistry()
        registry.register(self._make_definition("roll"))

        with pytest.raises(ValueError, match="roll"):
            registry.register(self._make_definition("roll"))

    def test_reject_duplicate_name_case_insensitive(self) -> None:
        """Registering a different-case variant of an existing name raises an error."""
        registry = CommandRegistry()
        registry.register(self._make_definition("roll"))

        with pytest.raises(ValueError, match="roll"):
            registry.register(self._make_definition("ROLL"))

    def test_visible_commands_empty_initially(self) -> None:
        """A new registry has no visible commands."""
        registry = CommandRegistry()
        assert registry.visible_commands() == ()

    def test_visible_commands_lists_visible_only(self) -> None:
        """Req 4.1: visible_commands returns only player-visible metadata."""
        registry = CommandRegistry()
        registry.register(self._make_definition("roll", "Roll"))
        registry.register(self._make_definition("help", "Help"))
        # Register a hidden command
        hidden_def = CommandDefinition(
            metadata=CommandMetadata(name="hidden", description="Hidden", visible=False),
            handler=lambda _: None,  # pyright: ignore[reportArgumentType]
        )
        registry.register(hidden_def)

        visible = registry.visible_commands()
        assert len(visible) == 2
        assert visible[0].name == "roll"
        assert visible[1].name == "help"

    def test_visible_commands_preserves_registration_order(self) -> None:
        """Req 4.1, 4.2: visible_commands preserves insertion order."""
        registry = CommandRegistry()
        registry.register(self._make_definition("help", "Help"))
        registry.register(self._make_definition("roll", "Roll"))
        registry.register(self._make_definition("stats", "Stats"))

        visible = registry.visible_commands()
        assert visible[0].name == "help"
        assert visible[1].name == "roll"
        assert visible[2].name == "stats"

    def test_visible_commands_returns_tuple(self) -> None:
        """visible_commands returns a tuple (immutable)."""
        registry = CommandRegistry()
        assert isinstance(registry.visible_commands(), tuple)

    def test_registry_is_isolated(self) -> None:
        """Req 3.1: each registry instance is independent, no global state."""
        reg1 = CommandRegistry()
        reg2 = CommandRegistry()

        reg1.register(self._make_definition("roll"))
        assert reg1.resolve("roll") is not None
        assert reg2.resolve("roll") is None

    def test_reject_non_empty_name(self) -> None:
        """Registration rejects empty command name."""
        registry = CommandRegistry()
        with pytest.raises(ValueError, match="empty"):
            registry.register(self._make_definition(""))


class TestCommandDecorator:
    """Req 3.1: @command decorator produces correct CommandDefinition."""

    def test_decorator_returns_definition(self) -> None:
        """Using @command on a handler returns a CommandDefinition."""
        deco = command("roll", description="Roll a random number")

        async def roll_handler(_ctx: CommandContext) -> str | None:
            return "rolled"

        result = deco(roll_handler)
        assert isinstance(result, CommandDefinition)
        assert result.metadata.name == "roll"
        assert result.metadata.description == "Roll a random number"
        assert result.metadata.visible is True

    def test_decorator_handler_preserved(self) -> None:
        """The decorator preserves the original handler callable."""
        deco = command("help", description="Help")

        async def help_handler(_ctx: CommandContext) -> str | None:
            return "help text"

        definition = deco(help_handler)
        assert definition.handler is help_handler

    def test_decorator_registers_in_registry(self) -> None:
        """A definition created by @command can be registered and resolved."""
        registry = CommandRegistry()
        deco = command("roll", description="Roll a number")

        async def roll_handler(_ctx: CommandContext) -> str | None:
            return "rolled"

        definition = deco(roll_handler)
        registry.register(definition)

        resolved = registry.resolve("roll")
        assert resolved is definition

    def test_registration_via_decorator_function(self) -> None:
        """Verify the decorator pattern: define command, register, resolve, invoke."""
        registry = CommandRegistry()

        deco = command("greet", description="Greet someone")

        async def greet_handler(ctx: CommandContext) -> str | None:
            if ctx.args:
                return f"Hello, {ctx.args[0]}!"
            return "Hello!"

        definition = deco(greet_handler)
        registry.register(definition)

        resolved = registry.resolve("greet")
        assert resolved is not None
        assert resolved.metadata.description == "Greet someone"
        assert callable(resolved.handler)

    def test_visible_false(self) -> None:
        """@command(visible=False) creates a hidden command definition."""
        deco = command("internal", description="Internal only", visible=False)

        async def internal_handler(_ctx: CommandContext) -> str | None:
            return None

        definition = deco(internal_handler)
        assert definition.metadata.visible is False
