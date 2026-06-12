"""Valkey async client factory.

Creates a GlideClient for connecting to a Valkey server.
"""

from __future__ import annotations

from urllib.parse import urlparse

from glide import GlideClient, GlideClientConfiguration, NodeAddress


def parse_valkey_database_id(path: str) -> int | None:
    if not path or path == "/":
        return None

    raw_database_id = path.removeprefix("/")
    if "/" in raw_database_id or not raw_database_id.isdecimal():
        msg = f"Invalid Valkey database path: {path!r}"
        raise ValueError(msg)

    return int(raw_database_id)


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
    database_id = parse_valkey_database_id(parsed.path)

    config = GlideClientConfiguration(
        addresses=[NodeAddress(host=host, port=port)],
        database_id=database_id,
    )
    return await GlideClient.create(config)
