"""BanchoBot command registry and decorator contract.

Provides registration, resolution, and metadata listing for BanchoBot
commands with deterministic insertion order (Req 2.1, 3.1, 4.1, 4.2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from osu_server.domain.role import Privileges
from osu_server.services.bancho_bot.context import (
    CommandArgument,
    CommandContext,
    CommandDestination,
    CommandMetadata,
)

CommandHandler = Callable[[CommandContext], Awaitable[str | None]]


@dataclass(slots=True, frozen=True)
class CommandDefinition:
    """Immutable binding between metadata and an async handler (Req 3.1).

    Created by the `@command` decorator and registered in `CommandRegistry`.
    """

    metadata: CommandMetadata
    handler: CommandHandler


class CommandRegistry:
    """Stores and resolves typed command definitions (Req 2.1, 4.1, 4.2, 5.1).

    Commands are stored by canonical lower-case name, with insertion order
    preserved. Duplicate command names are rejected at registration time.
    Each registry instance is isolated -- no global mutable state.
    """

    def __init__(self) -> None:
        self._definitions: dict[str, CommandDefinition] = {}
        self._insertion_order: list[str] = []

    def register(self, definition: CommandDefinition) -> None:
        """Register a command definition.

        Raises ValueError if the command name is empty or already registered
        (case-insensitive).

        Args:
            definition: The CommandDefinition to register.

        Raises:
            ValueError: If the command name is empty or a duplicate.
        """
        name = definition.metadata.name
        canonical = name.lower()

        if not canonical:
            raise ValueError("Command name must not be empty")

        if canonical in self._definitions:
            raise ValueError(f"Command '{canonical}' is already registered")

        self._definitions[canonical] = definition
        self._insertion_order.append(canonical)

    def resolve(self, name: str) -> CommandDefinition | None:
        """Resolve a command by name (case-insensitive) (Req 2.1).

        Args:
            name: The command name to resolve (any case).

        Returns:
            The CommandDefinition if found, None otherwise.
        """
        return self._definitions.get(name.lower())

    def commands(self) -> tuple[CommandMetadata, ...]:
        """Return all command metadata in registration order (Req 4.1, 4.2).

        Returns:
            A tuple of CommandMetadata for all registered commands, preserving
            insertion order.
        """
        return tuple(self._definitions[name].metadata for name in self._insertion_order)

    def command(
        self,
        name: str,
        *,
        description: str,
        usage: str = "",
        arguments: tuple[CommandArgument, ...] = (),
        required_privileges: Privileges = Privileges.NONE,
        allowed_destinations: CommandDestination = CommandDestination.BOTH,
    ) -> Callable[[CommandHandler], CommandDefinition]:
        """Decorator that creates a CommandDefinition and registers it (Req 3.1).

        Usage:
            registry = CommandRegistry()

            @registry.command("roll", description="Roll a random number")
            async def roll_handler(ctx: CommandContext) -> str | None:
                ...

        Args:
            name: The canonical command name (lower-case recommended).
            description: Human-readable description for help output.
            usage: Usage string for help output (e.g. "!roll [max]").
            arguments: Tuple of CommandArgument describing accepted arguments.
            required_privileges: Required Privileges to execute this command.
            allowed_destinations: Where this command can be executed.

        Returns:
            A decorator that wraps the handler into a CommandDefinition
            and registers it in this registry.
        """

        def decorate(handler: CommandHandler) -> CommandDefinition:
            definition = CommandDefinition(
                metadata=CommandMetadata(
                    name=name,
                    description=description,
                    usage=usage,
                    arguments=arguments,
                    required_privileges=required_privileges,
                    allowed_destinations=allowed_destinations,
                ),
                handler=handler,
            )
            self.register(definition)
            return definition

        return decorate


def command(
    name: str,
    *,
    description: str,
    usage: str = "",
    arguments: tuple[CommandArgument, ...] = (),
    required_privileges: Privileges = Privileges.NONE,
    allowed_destinations: CommandDestination = CommandDestination.BOTH,
) -> Callable[[CommandHandler], CommandDefinition]:
    """Create a CommandDefinition from a handler function (Req 3.1).

    Standard registration contract via decorator. Returns a callable that
    wraps the handler into a CommandDefinition.

    Usage:
        @command("roll", description="Roll a random number")
        async def roll_handler(ctx: CommandContext) -> str | None:
            ...

    Args:
        name: The canonical command name (lower-case recommended).
        description: Human-readable description for help output.
        usage: Usage string for help output (e.g. "!roll [max]").
        arguments: Tuple of CommandArgument describing accepted arguments.
        required_privileges: Required Privileges to execute this command.
        allowed_destinations: Where this command can be executed.

    Returns:
        A callable that accepts a CommandHandler and returns a CommandDefinition.
    """

    def decorate(handler: CommandHandler) -> CommandDefinition:
        return CommandDefinition(
            metadata=CommandMetadata(
                name=name,
                description=description,
                usage=usage,
                arguments=arguments,
                required_privileges=required_privileges,
                allowed_destinations=allowed_destinations,
            ),
            handler=handler,
        )

    return decorate
