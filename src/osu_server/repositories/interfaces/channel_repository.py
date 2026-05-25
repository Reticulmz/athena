"""ChannelRepository Protocol — abstract interface for channel persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.channel import Channel


@runtime_checkable
class ChannelRepository(Protocol):
    """Protocol for channel CRUD operations.

    Preconditions:
        - ``channel.name`` conforms to ``# + [a-z0-9_-]`` invariant.
    Postconditions:
        - ``create()`` returns a ``Channel`` with an auto-generated ``id``.
        - ``get_all()`` returns only ``ChannelType.PUBLIC`` channels.
        - ``get_auto_join()`` returns only channels with ``auto_join=True``.
    """

    async def create(self, channel: Channel) -> Channel:
        """Persist a new channel and return it with a generated id.

        Raises ``ValueError`` if ``name`` already exists.
        """
        ...

    async def get_by_name(self, name: str) -> Channel | None:
        """Return the channel with *name*, or ``None`` if not found."""
        ...

    async def get_all(self) -> list[Channel]:
        """Return all PUBLIC channels."""
        ...

    async def get_auto_join(self) -> list[Channel]:
        """Return all channels with ``auto_join=True``."""
        ...

    async def update(self, channel: Channel) -> Channel:
        """Update an existing channel and return the updated entity.

        Raises ``ValueError`` if the channel does not exist.
        """
        ...

    async def delete(self, channel_id: int) -> None:
        """Delete the channel with *channel_id*.

        No-op if the channel does not exist.
        """
        ...
