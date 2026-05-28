from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

import httpx
import pytest

from osu_server.infrastructure.security.hibp import HTTPHIBPClient


def _make_response(status_code: int, text: str) -> httpx.Response:
    """テスト用に request を設定した httpx.Response を生成する。"""
    return httpx.Response(
        status_code=status_code,
        text=text,
        request=httpx.Request("GET", "https://api.pwnedpasswords.com/range/test"),
    )


class TestIsPasswordCompromised:
    """HTTPHIBPClient.is_password_compromised のテスト。"""

    @pytest.fixture
    def mock_http_client(self) -> AsyncMock:
        return AsyncMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def client(self, mock_http_client: AsyncMock) -> HTTPHIBPClient:
        return HTTPHIBPClient(http_client=mock_http_client)

    def _build_hibp_response(self, password: str, *, include: bool) -> str:
        """HIBP API レスポンスボディを構築するヘルパー。

        include=True の場合、対象パスワードのサフィックスを含むレスポンスを生成。
        include=False の場合、無関係なサフィックスのみ。
        """
        sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
        suffix = sha1[5:]

        lines: list[str] = []
        if include:
            lines.append(f"{suffix}:42")
        # 無関係なエントリを追加
        lines.append("0000000000000000000000000000000000A:5")
        lines.append("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:1")
        return "\r\n".join(lines)

    async def test_detects_compromised_password(
        self,
        client: HTTPHIBPClient,
        mock_http_client: AsyncMock,
    ) -> None:
        """漏洩済みパスワードを検出する。"""
        password = "password123"
        response_text = self._build_hibp_response(password, include=True)
        mock_http_client.get.return_value = _make_response(200, response_text)

        result = await client.is_password_compromised(password)

        assert result is True
        # prefix が正しく送信されていることを検証
        sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
        prefix = sha1[:5]
        mock_http_client.get.assert_called_once_with(
            f"https://api.pwnedpasswords.com/range/{prefix}",
        )

    async def test_returns_false_for_safe_password(
        self,
        client: HTTPHIBPClient,
        mock_http_client: AsyncMock,
    ) -> None:
        """漏洩していないパスワードは False を返す。"""
        password = "a_very_unique_and_safe_password_12345"
        response_text = self._build_hibp_response(password, include=False)
        mock_http_client.get.return_value = _make_response(200, response_text)

        result = await client.is_password_compromised(password)

        assert result is False

    async def test_returns_false_on_timeout(
        self,
        client: HTTPHIBPClient,
        mock_http_client: AsyncMock,
    ) -> None:
        """タイムアウト時は False を返す(フォールバック)。"""
        mock_http_client.get.side_effect = httpx.TimeoutException("timeout")

        result = await client.is_password_compromised("password123")

        assert result is False

    async def test_returns_false_on_connection_error(
        self,
        client: HTTPHIBPClient,
        mock_http_client: AsyncMock,
    ) -> None:
        """接続エラー時は False を返す(フォールバック)。"""
        mock_http_client.get.side_effect = httpx.ConnectError("connection refused")

        result = await client.is_password_compromised("password123")

        assert result is False

    async def test_returns_false_on_http_error(
        self,
        client: HTTPHIBPClient,
        mock_http_client: AsyncMock,
    ) -> None:
        """HTTP エラーステータス時は False を返す(フォールバック)。"""
        mock_http_client.get.return_value = _make_response(500, "Internal Server Error")

        result = await client.is_password_compromised("password123")

        assert result is False

    async def test_sha1_prefix_is_5_characters(
        self,
        client: HTTPHIBPClient,
        mock_http_client: AsyncMock,
    ) -> None:
        """k-Anonymity: SHA-1 の先頭5文字のみ送信される。"""
        password = "test_password"
        expected_prefix_length = 5
        mock_http_client.get.return_value = _make_response(
            200, "0000000000000000000000000000000000A:1"
        )

        _ = await client.is_password_compromised(password)

        sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
        prefix = sha1[:expected_prefix_length]
        assert len(prefix) == expected_prefix_length
        call_url = mock_http_client.get.call_args[0][0]
        assert call_url.endswith(f"/{prefix}")

    async def test_case_insensitive_suffix_matching(
        self,
        client: HTTPHIBPClient,
        mock_http_client: AsyncMock,
    ) -> None:
        """サフィックス照合は大文字小文字を区別しない。"""
        password = "password123"
        sha1 = hashlib.sha1(password.encode()).hexdigest()
        suffix_lower = sha1[5:].lower()

        # レスポンスは小文字で返す(通常は大文字だが、堅牢性テスト)
        response_text = f"{suffix_lower}:10\r\n0000000000000000000000000000000000A:1"
        mock_http_client.get.return_value = _make_response(200, response_text)

        result = await client.is_password_compromised(password)

        assert result is True
