"""Valkey stable user status storeのbatch retrieval契約を検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from osu_server.domain.compatibility.stable import StableUserStatus
from osu_server.infrastructure.state.valkey.stable_user_status_store import (
    ValkeyStableUserStatusStore,
)

if TYPE_CHECKING:
    from glide import GlideClient


class FakeGlideClient:
    """Valkey command usageを記録するtyped Glide client fake."""

    def __init__(self) -> None:
        """key別の値と全Valkey command呼出履歴を空で初期化する."""
        self.values_by_key: dict[str, str] = {}
        self.get_calls: list[str] = []
        self.mget_calls: list[list[str]] = []
        self.set_calls: list[tuple[str, str]] = []
        self.expire_calls: list[tuple[str, int]] = []

    async def get(self, key: str) -> str | None:
        """指定keyの値を取得しsingle get呼出を記録する.

        Args:
            key (str): 取得対象のValkey key.

        Returns:
            str | None: 保存値または存在しない場合のNone.
        """
        self.get_calls.append(key)
        return self.values_by_key.get(key)

    async def mget(self, keys: list[str]) -> list[str | None]:
        """key列の値を順序どおり取得しbatch get呼出を記録する.

        Args:
            keys (list[str]): 一括取得するValkey key列.

        Returns:
            list[str | None]: 各keyに対応する保存値またはNoneの列.
        """
        self.mget_calls.append(keys)
        return [self.values_by_key.get(key) for key in keys]

    async def set(self, key: str, value: str, *, expiry: object) -> str:
        """keyへ値を保存しset呼出を記録する.

        Args:
            key (str): 保存先のValkey key.
            value (str): 保存するserialized status値.
            expiry (object): API互換のexpiry値でfakeでは使用しない.

        Returns:
            str: Valkey成功応答としてのOK.
        """
        _ = expiry
        self.set_calls.append((key, value))
        self.values_by_key[key] = value
        return "OK"

    async def expire(self, key: str, seconds: int) -> bool:
        """expiry設定呼出を記録して成功を返す.

        Args:
            key (str): expiryを設定するValkey key.
            seconds (int): 保存するTTL秒数.

        Returns:
            bool: fakeがexpiry設定を受理したことを示すTrue.
        """
        self.expire_calls.append((key, seconds))
        return True


async def test_get_statuses_reads_all_requested_statuses_with_one_mget() -> None:
    """3userを照会したとき1回のmgetで存在する2statusだけを返すことを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
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
    """空user列を照会したときValkeyを呼ばず空mappingを返すことを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
    client = FakeGlideClient()
    store = _store(client)

    result = await store.get_statuses(())

    assert result == {}
    assert client.mget_calls == []
    assert client.get_calls == []


def _store(client: FakeGlideClient) -> ValkeyStableUserStatusStore:
    """Test key prefixを固定したstable user status storeを構築する.

    Args:
        client (FakeGlideClient): Valkey operationを記録するtyped fake.

    Returns:
        ValkeyStableUserStatusStore: batch retrievalを検証するstore.
    """
    return ValkeyStableUserStatusStore(
        cast("GlideClient", cast("object", client)),
        key_prefix="test:",
    )
