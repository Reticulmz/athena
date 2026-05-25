"""Channel domain model and ChannelType enum.

Defines the Channel entity for DB-managed public persistent channels
and a ChannelType enum with PUBLIC as the active variant plus reserved
variants for future use (MULTIPLAYER, SPECTATOR, TEMPORARY).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

_CHANNEL_NAME_BODY = re.compile(r"^[a-z0-9_-]+$")


class ChannelType(Enum):
    PUBLIC = "public"
    MULTIPLAYER = "multiplayer"  # reserved
    SPECTATOR = "spectator"  # reserved
    TEMPORARY = "temporary"  # reserved


@dataclass(slots=True)
class Channel:
    """A chat channel entity.

    Invariant: ``name`` must start with ``#`` followed by one or more
    characters matching ``[a-z0-9_-]``.
    """

    id: int
    name: str
    topic: str
    channel_type: ChannelType
    read_privileges: int
    write_privileges: int
    manage_privileges: int
    auto_join: bool
    rate_limit_messages: int | None
    rate_limit_window: int | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _validate_channel_name(self.name)


def _validate_channel_name(name: str) -> None:
    """Validate that *name* conforms to ``# + [a-z0-9_-]``."""
    if not name.startswith("#"):
        msg = "Channel name must start with '#'"
        raise ValueError(msg)

    body = name[1:]
    if not body:
        msg = "Channel name must have at least one character after '#'"
        raise ValueError(msg)

    if not _CHANNEL_NAME_BODY.fullmatch(body):
        msg = f"Channel name contains invalid characters: {name!r} (allowed: a-z 0-9 _ -)"
        raise ValueError(msg)
