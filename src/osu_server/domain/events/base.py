"""Base event type for domain events."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Event:
    """Base class for all domain events.

    Concrete event types (e.g. ``ChatMessageSent``, ``UserPresenceUpdated``)
    inherit from this and add their own fields.
    """
