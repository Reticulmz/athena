"""System user identity values for the identity bounded context."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SystemUserIdentity:
    """Immutable identity for a system user without an active session."""

    user_id: int
    username: str
