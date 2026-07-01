"""Valkey stable user status store tests。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from osu_server.domain.compatibility.stable import StableUserStatus
from osu_server.infrastructure.state.valkey.stable_user_status_store import (
    ValkeyStableUserStatusStore,
)

if TYPE_CHECKING:
    from glide import GlideClient


class FakeGlideClient:
    """Valkey command usage を記録する typed fake。"""

    def __init__(self) -> None:
        self.values_by_key: dict[str, str] = {}
        self.get_calls: list[str] = []
        self.mget_calls: list[list[str]] = []
        self.set_calls: list[tuple[str, str]] = []
        self.expire_calls: list[tuple[str, int]] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.values_by_key.get(key)

    async def mget(self, keys: list[str]) -> list[str | None]:
        self.mget_calls.append(keys)
        return [self.values_by_key.get(key) for key in keys]

    async def set(self, key: str, value: str, *, expiry: object) -> str:
        _ = expiry
        self.set_calls.append((key, value))
        self.values_by_key[key] = value
        return "OK"

    async def expire(self, key: str, seconds: int) -> bool:
        self.expire_calls.append((key, seconds))
        return True


async def test_get_statuses_reads_all_requested_statuses_with_one_mget() -> None:
    client = FakeGlideClient()
    store = _store(client)
    first = StableUserStatus(
        status=2,
        status_text="Playing",
        beatmap_md5="abc",
        mods=0,
        play_mode=0,
        beatmap_id=10,
    )
    third = StableUserStatus(
        status=4,
        status_text="Editing",
        beatmap_md5="def",
        mods=8,
        play_mode=1,
        beatmap_id=30,
    )
    await store.set_status(1, first)
    await store.set_status(3, third)

    result = await store.get_statuses((1, 2, 3))

    assert result == {1: first, 3: third}
    assert client.mget_calls == [
        [
            "test:stable_user_status:1:status",
            "test:stable_user_status:2:status",
            "test:stable_user_status:3:status",
        ]
    ]
    assert client.get_calls == []


async def test_get_statuses_returns_empty_without_valkey_call_for_empty_request() -> None:
    client = FakeGlideClient()
    store = _store(client)

    result = await store.get_statuses(())

    assert result == {}
    assert client.mget_calls == []
    assert client.get_calls == []


def _store(client: FakeGlideClient) -> ValkeyStableUserStatusStore:
    return ValkeyStableUserStatusStore(
        cast("GlideClient", cast("object", client)),
        key_prefix="test:",
    )
