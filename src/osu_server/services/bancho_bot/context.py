"""BanchoBot command context and metadata value objects.

Immutable typed contracts for command invocation (Req 2.2, 3.2, 4.3).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CommandMetadata:
    """Immutable metadata for player-visible command discovery (Req 4.3).

    Each registered command produces one metadata instance that describes
    the command name, its description for help output, and whether it
    should appear in visible command listings.
    """

    name: str
    description: str
    visible: bool = True


@dataclass(slots=True, frozen=True)
class CommandContext:
    """Immutable invocation context for a single command execution (Req 2.2, 3.2).

    Captures sender identity, original target, canonical command name,
    ordered arguments, and a snapshot of visible command metadata at the
    time of invocation.
    """

    sender_id: int
    sender_name: str
    target: str
    command_name: str
    args: tuple[str, ...]
    available_commands: tuple[CommandMetadata, ...]
