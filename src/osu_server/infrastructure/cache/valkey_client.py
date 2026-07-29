"""Valkey serverへ接続するGlide async clientを生成する."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from glide import GlideClient, GlideClientConfiguration, NodeAddress
from glide_shared.commands.core_options import PubSubMsg

type ValkeyPubSubCallback = Callable[[PubSubMsg, object], None]


def parse_valkey_database_id(path: str) -> int | None:
    """Valkey URL pathからoptional database IDを解析する.

    Args:
        path (str): URL parserが返すpath. 空文字列または ``/`` はdatabase未指定を表す.

    Returns:
        int | None: 単一のdecimal path componentを整数化したdatabase ID. 未指定なら ``None``.

    Raises:
        ValueError: pathが複数component,または単一のdecimal値でない場合.
    """
    if not path or path == "/":
        return None

    raw_database_id = path.removeprefix("/")
    if "/" in raw_database_id or not raw_database_id.isdecimal():
        msg = f"Invalid Valkey database path: {path!r}"
        raise ValueError(msg)

    return int(raw_database_id)


async def create_valkey_client(valkey_url: str) -> GlideClient:
    """Valkey URLから通常command用のconnected GlideClientを生成する.

    Args:
        valkey_url (str): host,optional port,optional database pathを含むValkey connection URL.

    Returns:
        GlideClient: URLのhost,port,database IDで接続済みのclient.

    Raises:
        ValueError: URLのportまたはdatabase pathが不正な場合.
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
    """Pub/Sub callbackを設定したconnected GlideClientを生成する.

    Args:
        valkey_url (str): host,optional port,optional database pathを含むValkey connection URL.
        callback (ValkeyPubSubCallback): Pub/Sub messageとcontextを受け取るcallback.

    Returns:
        GlideClient: exact channel subscriptionsとcallbackを設定して接続済みのclient.

    Raises:
        ValueError: URLのportまたはdatabase pathが不正な場合.
    """
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
