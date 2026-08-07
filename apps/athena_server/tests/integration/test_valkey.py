"""Valkey connection infrastructureの実service integration contractを検証する.

Notes:
    VALKEY_URL environment variableで指定する実Valkey instanceへの接続を必要とする.
"""

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, cast

import pytest
from glide import ExpirySet, ExpiryType, GlideClient

if TYPE_CHECKING:
    from glide_shared.constants import TEncodable

from osu_server.infrastructure.cache.valkey_client import create_valkey_client
from tests.support.service_availability import require_tcp_service_url

_KEY_PREFIX = "athena_test:"


def _get_valkey_url() -> str:
    """Integration testで使用するValkey connection URLを取得する.

    Returns:
        str: TCP接続可能なVALKEY_URL.

    Raises:
        pytest.skip.Exception: VALKEY_URLが未設定またはValkey serviceが利用不能な場合.
    """
    return require_tcp_service_url("VALKEY_URL", default_port=6379)


@pytest.fixture
async def valkey_client() -> AsyncGenerator[GlideClient]:
    """実Valkey instanceへ接続するGlide clientを提供する.

    Yields:
        GlideClient: test keyのread/writeに使用するValkey client.

    Raises:
        pytest.skip.Exception: VALKEY_URLまたはValkey serviceが利用不能な場合.

    Notes:
        fixture終了時にathena_test prefixのkeyをcleanupしてconnectionをcloseする.
    """
    client = await create_valkey_client(_get_valkey_url())
    yield client
    # Clean up any test keys
    cursor: str = "0"
    while True:
        next_cursor, keys = await client.scan(cursor, match=f"{_KEY_PREFIX}*", count=100)
        if keys:
            _ = await client.delete(cast("list[TEncodable]", keys))
        cursor = next_cursor.decode() if isinstance(next_cursor, bytes) else str(next_cursor)
        if cursor == "0":
            break
    await client.close()


class TestValkeyConnection:
    """Valkey clientの生成とconnection contractを検証する."""

    async def test_create_valkey_client_returns_glide_instance(
        self,
        valkey_client: GlideClient,
    ) -> None:
        """Valkey client fixtureがGlideClient instanceを返すcontractを検証する.

        Args:
            valkey_client (GlideClient): 実Valkeyへ接続したfixture client.

        Returns:
            None: fixture clientのruntime type確認を完了する.
        """
        assert isinstance(valkey_client, GlideClient)

    async def test_valkey_client_connects_to_server(
        self,
        valkey_client: GlideClient,
    ) -> None:
        """Glide clientが実Valkey serverへPINGできるcontractを検証する.

        Args:
            valkey_client (GlideClient): 実Valkeyへ接続したfixture client.

        Returns:
            None: PING resultがbinary responseであることを確認して完了する.
        """
        result = await valkey_client.ping()
        assert isinstance(result, bytes)


class TestValkeyOperations:
    """Valkeyのbasic async key operation contractを検証する."""

    async def test_set_and_get(
        self,
        valkey_client: GlideClient,
    ) -> None:
        """SET後のGETが同じbinary valueを返すcontractを検証する.

        Args:
            valkey_client (GlideClient): 実Valkeyへ接続したfixture client.

        Returns:
            None: test keyに書いたvalueをGETできることを確認して完了する.
        """
        key = f"{_KEY_PREFIX}test_set_get"
        _ = await valkey_client.set(key, "hello")
        value = await valkey_client.get(key)
        assert value == b"hello"

    async def test_get_nonexistent_key_returns_none(
        self,
        valkey_client: GlideClient,
    ) -> None:
        """Missing keyのGETがNoneを返すcontractを検証する.

        Args:
            valkey_client (GlideClient): 実Valkeyへ接続したfixture client.

        Returns:
            None: 未保存test keyのGET resultがNoneであることを確認して完了する.
        """
        value = await valkey_client.get(f"{_KEY_PREFIX}nonexistent")
        assert value is None

    async def test_delete_removes_key(
        self,
        valkey_client: GlideClient,
    ) -> None:
        """DELETEがstored keyを削除してsubsequent GETをNoneにするcontractを検証する.

        Args:
            valkey_client (GlideClient): 実Valkeyへ接続したfixture client.

        Returns:
            None: delete countとmissing GET resultを確認して完了する.
        """
        key = f"{_KEY_PREFIX}test_delete"
        _ = await valkey_client.set(key, "to_delete")
        deleted_count = await valkey_client.delete([key])
        assert deleted_count == 1
        value = await valkey_client.get(key)
        assert value is None

    async def test_set_with_expiry(
        self,
        valkey_client: GlideClient,
    ) -> None:
        """SET expiryがtest keyへpositive TTLを設定するcontractを検証する.

        Args:
            valkey_client (GlideClient): 実Valkeyへ接続したfixture client.

        Returns:
            None: expiry設定後のTTLが正のintegerであることを確認して完了する.
        """
        key = f"{_KEY_PREFIX}test_expiry"
        _ = await valkey_client.set(key, "expires", expiry=ExpirySet(ExpiryType.SEC, 3600))
        ttl = await valkey_client.ttl(key)
        assert isinstance(ttl, int)
        assert ttl > 0


class TestValkeyClose:
    """Valkey client close behaviorを検証する."""

    async def test_close_closes_connection(self) -> None:
        """Connected Valkey clientがexplicit closeを完了できるcontractを検証する.

        Returns:
            None: PING成功後にclient closeを完了する.

        Raises:
            pytest.skip.Exception: VALKEY_URLまたはValkey serviceが利用不能な場合.
        """
        client = await create_valkey_client(_get_valkey_url())
        # Verify connectivity first
        result = await client.ping()
        assert isinstance(result, bytes)
        await client.close()
