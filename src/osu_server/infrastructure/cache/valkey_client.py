"""Valkey async client factory.

Creates a GlideClient for connecting to a Valkey server.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from glide import GlideClient, GlideClientConfiguration, NodeAddress
from glide_shared.commands.core_options import PubSubMsg

type ValkeyPubSubCallback = Callable[[PubSubMsg, object], None]


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


async def create_valkey_pubsub_client(
    valkey_url: str,
    callback: ValkeyPubSubCallback,
) -> GlideClient:
    """Create a GlideClient configured for Pub/Sub callbacks."""
    parsed = urlparse(valkey_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    database_id = parse_valkey_database_id(parsed.path)

    config = GlideClientConfiguration(
        addresses=[NodeAddress(host=host, port=port)],
        database_id=database_id,
        pubsub_subscriptions=GlideClientConfiguration.PubSubSubscriptions(
            channels_and_patterns={
                GlideClientConfiguration.PubSubChannelModes.Exact: set(),
            },
            callback=callback,
            context=None,
        ),
    )
    return await GlideClient.create(config)
