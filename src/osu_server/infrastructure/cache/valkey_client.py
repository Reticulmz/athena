"""Valkey async client factory.

Creates a GlideClient for connecting to a Valkey server.
"""

from __future__ import annotations

from urllib.parse import urlparse

from glide import GlideClient, GlideClientConfiguration, NodeAddress


async def create_valkey_client(valkey_url: str) -> GlideClient:
    """Create a GlideClient from a ``redis://`` DSN.

    Args:
        valkey_url: Valkey connection URL (e.g. ``redis://localhost:6379``).

    Returns:
        A connected GlideClient instance.
    """
    parsed = urlparse(valkey_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379

    config = GlideClientConfiguration(
        addresses=[NodeAddress(host=host, port=port)],
    )
    return await GlideClient.create(config)
