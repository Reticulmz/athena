"""beatmap HTTP client interfaceのconcrete implementation契約を検証するmodule."""

from __future__ import annotations

from typing import assert_type

from osu_server.infrastructure.http.beatmap_http_client import (
    BeatmapHttpClient as ConcreteBeatmapHttpClient,
)
from osu_server.infrastructure.http.interfaces import BeatmapHttpClient, HttpFetchResult


def test_beatmap_http_client_concrete_satisfies_protocol() -> None:
    """Concrete BeatmapHttpClientをProtocol型へ代入できることを検証する.

    Returns:
        None: protocol代入後のinstance identityを検証して値を返さず完了する.
    """
    client = ConcreteBeatmapHttpClient()
    protocol_client: BeatmapHttpClient = client

    assert protocol_client is client


def test_http_fetch_result_is_exported_interface_value() -> None:
    """export済みHttpFetchResultを生成しcontentとfilenameを検証する.

    Returns:
        None: interface valueのfieldを検証して値を返さず完了する.
    """
    result = HttpFetchResult(content=b"osu", filename="100.osu")

    _ = assert_type(result, HttpFetchResult)
    assert result.content == b"osu"
    assert result.filename == "100.osu"
