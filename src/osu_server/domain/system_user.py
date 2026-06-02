from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SystemUserIdentity:
    """Immutable identity for a system user that is not backed by an active session.

    System users (like BanchoBot) appear in online rosters and send messages
    but do not have login/polling/logout lifecycle, SessionData, Repository,
    or DB model.
    """

    user_id: int
    username: str


BANCHO_BOT_IDENTITY = SystemUserIdentity(user_id=1, username="BanchoBot")
