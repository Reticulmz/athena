"""System user identity values for the identity bounded context."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SystemUserIdentity:
    """Immutable identity for a system user without an active session."""

    user_id: int
    username: str


BANCHO_BOT_USER_ID = 1
BANCHO_BOT_DEFAULT_USERNAME = "BanchoBot"
BANCHO_BOT_USERNAME_MIN = 2
BANCHO_BOT_USERNAME_MAX = 15
BANCHO_BOT_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_ -]+$")

BANCHO_BOT_IDENTITY = SystemUserIdentity(
    user_id=BANCHO_BOT_USER_ID,
    username=BANCHO_BOT_DEFAULT_USERNAME,
)


def create_bancho_bot_identity(username: str) -> SystemUserIdentity:
    """Create the runtime BanchoBot identity from a validated display name."""
    return SystemUserIdentity(user_id=BANCHO_BOT_USER_ID, username=username)
