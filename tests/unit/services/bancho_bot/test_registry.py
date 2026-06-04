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

from osu_server.domain.bancho_bot import (
    CommandContext,
    CommandDestination,
    CommandMetadata,
)
from osu_server.domain.role import Privileges
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
                    destination=CommandDestination.CHANNEL,
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

    def test_commands_empty_initially(self) -> None:
        """A new registry has no commands."""
        registry = CommandRegistry()
        assert registry.commands() == ()

    def test_commands_lists_all(self) -> None:
        """commands returns all registered command metadata."""
        registry = CommandRegistry()
        registry.register(self._make_definition("roll", "Roll"))
        registry.register(self._make_definition("help", "Help"))
        # Register a third command
        third_def = CommandDefinition(
            metadata=CommandMetadata(name="third", description="Third"),
            handler=lambda _: None,  # pyright: ignore[reportArgumentType]
        )
        registry.register(third_def)

        all_cmds = registry.commands()
        assert len(all_cmds) == 3
        assert all_cmds[0].name == "roll"
        assert all_cmds[1].name == "help"
        assert all_cmds[2].name == "third"

    def test_commands_preserves_registration_order(self) -> None:
        """Req 4.1, 4.2: commands preserves insertion order."""
        registry = CommandRegistry()
        registry.register(self._make_definition("help", "Help"))
        registry.register(self._make_definition("roll", "Roll"))
        registry.register(self._make_definition("stats", "Stats"))

        all_cmds = registry.commands()
        assert all_cmds[0].name == "help"
        assert all_cmds[1].name == "roll"
        assert all_cmds[2].name == "stats"

    def test_commands_returns_tuple(self) -> None:
        """commands returns a tuple (immutable)."""
        registry = CommandRegistry()
        assert isinstance(registry.commands(), tuple)

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

    def test_commands_includes_moderator_privileged_metadata(self) -> None:
        """Registered MODERATOR-privilege command metadata is accessible via commands()."""
        registry = CommandRegistry()
        definition = CommandDefinition(
            metadata=CommandMetadata(
                name="modcmd",
                description="Moderator command",
                required_privileges=Privileges.MODERATOR,
            ),
            handler=lambda _: None,  # pyright: ignore[reportArgumentType]
        )
        registry.register(definition)

        all_cmds = registry.commands()
        assert len(all_cmds) == 1
        assert all_cmds[0].name == "modcmd"
        assert all_cmds[0].required_privileges == Privileges.MODERATOR

    def test_commands_includes_pm_destination_metadata(self) -> None:
        """A command registered with PM-only destination has metadata accessible via commands()."""
        registry = CommandRegistry()
        definition = CommandDefinition(
            metadata=CommandMetadata(
                name="pmcmd",
                description="PM-only command",
                allowed_destinations=CommandDestination.PM,
            ),
            handler=lambda _: None,  # pyright: ignore[reportArgumentType]
        )
        registry.register(definition)

        all_cmds = registry.commands()
        assert len(all_cmds) == 1
        assert all_cmds[0].name == "pmcmd"
        assert all_cmds[0].allowed_destinations == CommandDestination.PM

    def test_commands_returns_all_regardless_of_privileges_or_destinations(self) -> None:
        """commands() returns all commands, regardless of their privileges or destinations."""
        registry = CommandRegistry()
        registry.register(
            CommandDefinition(
                metadata=CommandMetadata(name="pub", description="Public"),
                handler=lambda _: None,  # pyright: ignore[reportArgumentType]
            )
        )
        registry.register(
            CommandDefinition(
                metadata=CommandMetadata(
                    name="mod",
                    description="Moderator",
                    required_privileges=Privileges.MODERATOR,
                ),
                handler=lambda _: None,  # pyright: ignore[reportArgumentType]
            )
        )
        registry.register(
            CommandDefinition(
                metadata=CommandMetadata(
                    name="admin",
                    description="Admin",
                    required_privileges=Privileges.ADMIN,
                ),
                handler=lambda _: None,  # pyright: ignore[reportArgumentType]
            )
        )
        registry.register(
            CommandDefinition(
                metadata=CommandMetadata(
                    name="pm_only",
                    description="PM only",
                    allowed_destinations=CommandDestination.PM,
                ),
                handler=lambda _: None,  # pyright: ignore[reportArgumentType]
            )
        )
        registry.register(
            CommandDefinition(
                metadata=CommandMetadata(
                    name="channel_only",
                    description="Channel only",
                    allowed_destinations=CommandDestination.CHANNEL,
                ),
                handler=lambda _: None,  # pyright: ignore[reportArgumentType]
            )
        )

        all_cmds = registry.commands()
        assert len(all_cmds) == 5
        names = [cmd.name for cmd in all_cmds]
        assert names == ["pub", "mod", "admin", "pm_only", "channel_only"]


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
        assert result.metadata.required_privileges == Privileges.NONE

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
        """@command(required_privileges=...) creates a privileged command definition."""
        deco = command(
            "internal", description="Internal only", required_privileges=Privileges.ADMIN
        )

        async def internal_handler(_ctx: CommandContext) -> str | None:
            return None

        definition = deco(internal_handler)
        assert definition.metadata.required_privileges == Privileges.ADMIN


class TestCommandDecoratorSyntax:
    """Req 3.1: @command(...) decorator syntax produces correct CommandDefinition."""

    def test_at_syntax_creates_definition(self) -> None:
        """Using @command(...) as a decorator on a handler creates a CommandDefinition."""

        @command("greet", description="Greet someone")
        async def greet(_ctx: CommandContext) -> str | None:
            return "Hello!"

        assert isinstance(greet, CommandDefinition)
        assert greet.metadata.name == "greet"
        assert greet.metadata.description == "Greet someone"
        assert greet.metadata.required_privileges == Privileges.NONE

    def test_at_syntax_preserves_handler(self) -> None:
        """The decorated function's handler is preserved and callable."""

        @command("echo", description="Echo input")
        async def echo(_ctx: CommandContext) -> str | None:
            return "echo"

        assert callable(echo.handler)

    async def test_at_syntax_handler_invocable(self) -> None:
        """The handler inside a @command-decorated function is invocable."""

        @command("add", description="Add numbers")
        async def add(ctx: CommandContext) -> str | None:
            if ctx.args:
                return f"sum={ctx.args[0]}"
            return None

        ctx = CommandContext(
            sender_id=1,
            sender_name="u",
            target="#o",
            command_name="add",
            args=("42",),
            destination=CommandDestination.CHANNEL,
            available_commands=(),
        )
        result = await add.handler(ctx)
        assert result == "sum=42"

    def test_at_syntax_registers_in_registry(self) -> None:
        """A @command-decorated handler can be registered and resolved."""

        @command("ping", description="Ping the bot")
        async def ping(_ctx: CommandContext) -> str | None:
            return "pong"

        registry = CommandRegistry()
        registry.register(ping)

        resolved = registry.resolve("ping")
        assert resolved is not None
        assert resolved is ping
        assert resolved.metadata.name == "ping"

    def test_at_syntax_hidden_command(self) -> None:
        """@command(required_privileges=...) via decorator syntax sets privileges."""

        @command("secret", description="Secret", required_privileges=Privileges.ADMIN)
        async def secret(_ctx: CommandContext) -> str | None:
            return None

        registry = CommandRegistry()
        registry.register(secret)

        assert registry.commands()[0].required_privileges == Privileges.ADMIN


class TestRegistryCommandMethod:
    """Req 3.1: CommandRegistry.command() auto-registers the decorated handler."""

    def test_auto_registers_handler(self) -> None:
        """@registry.command() registers the definition in the registry."""
        registry = CommandRegistry()

        @registry.command("greet", description="Greet someone")
        async def greet(_ctx: CommandContext) -> str | None:
            return "Hello!"

        resolved = registry.resolve("greet")
        assert resolved is not None
        assert resolved is greet
        assert resolved.metadata.name == "greet"

    def test_auto_registered_is_resolvable(self) -> None:
        """After @registry.command(), resolve() returns the definition."""
        registry = CommandRegistry()

        @registry.command("ping", description="Ping")
        async def ping(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            return "pong"

        assert registry.resolve("ping") is not None
        assert registry.resolve("PING") is not None

    def test_auto_registered_appears_in_commands(self) -> None:
        """Auto-registered commands appear in commands()."""
        registry = CommandRegistry()

        @registry.command("first", description="First")
        async def first(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            return None

        @registry.command("second", description="Second")
        async def second(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            return None

        all_cmds = registry.commands()
        assert len(all_cmds) == 2
        assert all_cmds[0].name == "first"
        assert all_cmds[1].name == "second"

    def test_auto_register_hidden_command(self) -> None:
        """@registry.command(required_privileges=...) auto-registers with privileges."""
        registry = CommandRegistry()

        @registry.command("secret", description="Secret", required_privileges=Privileges.ADMIN)
        async def secret(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            return None

        assert registry.resolve("secret") is not None
        assert registry.commands()[0].required_privileges == Privileges.ADMIN

    def test_auto_register_preserves_insertion_order(self) -> None:
        """Auto-registration preserves the order of @registry.command() calls."""
        registry = CommandRegistry()

        @registry.command("c", description="C")
        async def c(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            return None

        @registry.command("a", description="A")
        async def a(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            return None

        @registry.command("b", description="B")
        async def b(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            return None

        all_cmds = registry.commands()
        assert [cmd.name for cmd in all_cmds] == ["c", "a", "b"]

    def test_auto_register_pm_only_command(self) -> None:
        """@registry.command(allowed_destinations=PM) auto-registers with PM-only destination."""
        registry = CommandRegistry()

        @registry.command(
            "pmcmd", description="PM only", allowed_destinations=CommandDestination.PM
        )
        async def pmcmd(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            return None

        assert registry.resolve("pmcmd") is not None
        assert registry.commands()[0].allowed_destinations == CommandDestination.PM

    def test_auto_register_rejects_duplicate(self) -> None:
        """@registry.command() with duplicate name raises ValueError."""
        registry = CommandRegistry()

        @registry.command("dup", description="First")
        async def first(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            return None

        with pytest.raises(ValueError, match="dup"):

            @registry.command("dup", description="Second")
            async def second(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
                return None
