"""BanchoBot command context and metadata value objects.

Immutable typed contracts for command invocation (Req 2.2, 3.2, 4.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from osu_server.domain.role import Privileges


class CommandDestination(StrEnum):
    CHANNEL = "channel"
    PM = "pm"
    BOTH = "both"


@dataclass(slots=True, frozen=True)
class CommandArgument:
    name: str
    required: bool
    description: str


@dataclass(slots=True, frozen=True)
class CommandMetadata:
    """Immutable metadata for command discovery (Req 1.1, 4.3).

    Each registered command produces one metadata instance that describes
    the command name, description, usage, arguments, required privileges,
    and allowed destinations.
    """

    name: str
    description: str
    usage: str = ""
    arguments: tuple[CommandArgument, ...] = ()
    required_privileges: Privileges = Privileges.NONE
    allowed_destinations: CommandDestination = CommandDestination.BOTH


@dataclass(slots=True, frozen=True)
class CommandContext:
    """Immutable invocation context for a single command execution (Req 2.2, 3.2).

    Captures sender identity, original target, canonical command name,
    ordered arguments, destination type, and a snapshot of command metadata
    at the time of invocation.
    """

    sender_id: int
    sender_name: str
    target: str
    command_name: str
    args: tuple[str, ...]
    destination: CommandDestination
    available_commands: tuple[CommandMetadata, ...]
