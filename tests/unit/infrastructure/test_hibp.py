"""HTTP HIBP clientの漏洩password判定とfailure fallbackを検証するmodule."""

from __future__ import annotations

import hashlib
from typing import cast

import httpx
import pytest

from osu_server.infrastructure.security.hibp import HTTPHIBPClient


class StubAsyncClient:
    """HTTP responseまたはexceptionを設定できるAsyncClient test stub.

    Attributes:
        response (httpx.Response | Exception | None): get呼び出しで返すresponseまたは
            送出するexception.
        called_url (str | None): get呼び出しで受信したURL.
    """

    def __init__(self) -> None:
        """response設定と受信URL記録を未設定状態で初期化する."""
        self.response: httpx.Response | Exception | None = None
        self.called_url: str | None = None

    async def get(self, url: str) -> httpx.Response:
        """設定済みresponseを返すかexceptionを送出してURLを記録する.

        Args:
            url (str): HIBP clientから要求されたrange API URL.

        Returns:
            httpx.Response: responseに設定されたHTTP response.

        Raises:
            Exception: responseに設定されたexceptionを送出する場合.
            ValueError: responseが未設定の場合.
        """
        self.called_url = url
        if isinstance(self.response, Exception):
            raise self.response
        if isinstance(self.response, httpx.Response):
            return self.response
        raise ValueError("Response not set in StubAsyncClient")


def _make_response(status_code: int, text: str) -> httpx.Response:
    """request付きのHIBP API responseを構築する.

    Args:
        status_code (int): responseに設定するHTTP status code.
        text (str): response bodyへ設定するrange API text.

    Returns:
        httpx.Response: test requestを関連付けたHTTP response.
    """
    return httpx.Response(
        status_code=status_code,
        text=text,
        request=httpx.Request("GET", "https://api.pwnedpasswords.com/range/test"),
    )


class TestIsPasswordCompromised:
    """HTTPHIBPClientのpassword漏洩判定契約を検証するtest群."""

    @pytest.fixture
    def mock_http_client(self) -> StubAsyncClient:
        """各testへ独立したHTTP client stubを提供する.

        Returns:
            StubAsyncClient: responseを設定できる未使用client stub.
        """
        return StubAsyncClient()

    @pytest.fixture
    def client(self, mock_http_client: StubAsyncClient) -> HTTPHIBPClient:
        """HTTP client stubを注入したHIBP clientを提供する.

        Args:
            mock_http_client (StubAsyncClient): range API responseを再現するclient stub.

        Returns:
            HTTPHIBPClient: injected stubを使用するHIBP client.
        """
        return HTTPHIBPClient(
            http_client=cast("httpx.AsyncClient", cast("object", mock_http_client))
        )

    def _build_hibp_response(self, password: str, *, include: bool) -> str:
        """指定password suffixを含むか選べるHIBP range responseを構築する.

        Args:
            password (str): SHA-1 suffixを生成するpassword文字列.
            include (bool): 対象password suffixをresponseへ含めるか.

        Returns:
            str: 対象または無関係なsuffixを含むrange API response body.
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
        mock_http_client: StubAsyncClient,
    ) -> None:
        """漏洩suffixを含むrange responseでTrueとprefix URLを検証する.

        Args:
            client (HTTPHIBPClient): password漏洩を照会するclient fixture.
            mock_http_client (StubAsyncClient): range responseを設定してURLを記録するstub.

        Returns:
            None: compromise判定と送信prefixを検証して値を返さず完了する.
        """
        password = "password123"
        response_text = self._build_hibp_response(password, include=True)
        mock_http_client.response = _make_response(200, response_text)

        result = await client.is_password_compromised(password)

        assert result is True
        # prefix が正しく送信されていることを検証
        sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
        prefix = sha1[:5]
        assert mock_http_client.called_url == f"https://api.pwnedpasswords.com/range/{prefix}"

    async def test_returns_false_for_safe_password(
        self,
        client: HTTPHIBPClient,
        mock_http_client: StubAsyncClient,
    ) -> None:
        """対象suffixなしのrange responseでFalseを返すことを検証する.

        Args:
            client (HTTPHIBPClient): password漏洩を照会するclient fixture.
            mock_http_client (StubAsyncClient): safe responseを設定するstub.

        Returns:
            None: safe password判定を検証して値を返さず完了する.
        """
        password = "a_very_unique_and_safe_password_12345"
        response_text = self._build_hibp_response(password, include=False)
        mock_http_client.response = _make_response(200, response_text)

        result = await client.is_password_compromised(password)

        assert result is False

    async def test_returns_false_on_timeout(
        self,
        client: HTTPHIBPClient,
        mock_http_client: StubAsyncClient,
    ) -> None:
        """TimeoutExceptionを返すclientでFalse fallbackを検証する.

        Args:
            client (HTTPHIBPClient): password漏洩を照会するclient fixture.
            mock_http_client (StubAsyncClient): timeoutを設定するstub.

        Returns:
            None: timeout fallback判定を検証して値を返さず完了する.
        """
        mock_http_client.response = httpx.TimeoutException("timeout")

        result = await client.is_password_compromised("password123")

        assert result is False

    async def test_returns_false_on_connection_error(
        self,
        client: HTTPHIBPClient,
        mock_http_client: StubAsyncClient,
    ) -> None:
        """ConnectErrorを返すclientでFalse fallbackを検証する.

        Args:
            client (HTTPHIBPClient): password漏洩を照会するclient fixture.
            mock_http_client (StubAsyncClient): connection errorを設定するstub.

        Returns:
            None: connection fallback判定を検証して値を返さず完了する.
        """
        mock_http_client.response = httpx.ConnectError("connection refused")

        result = await client.is_password_compromised("password123")

        assert result is False

    async def test_returns_false_on_http_error(
        self,
        client: HTTPHIBPClient,
        mock_http_client: StubAsyncClient,
    ) -> None:
        """HTTP 500 responseを返すclientでFalse fallbackを検証する.

        Args:
            client (HTTPHIBPClient): password漏洩を照会するclient fixture.
            mock_http_client (StubAsyncClient): server error responseを設定するstub.

        Returns:
            None: HTTP failure fallback判定を検証して値を返さず完了する.
        """
        mock_http_client.response = _make_response(500, "Internal Server Error")

        result = await client.is_password_compromised("password123")

        assert result is False

    async def test_sha1_prefix_is_5_characters(
        self,
        client: HTTPHIBPClient,
        mock_http_client: StubAsyncClient,
    ) -> None:
        """k-AnonymityでSHA-1 prefixの先頭5文字だけを送ることを検証する.

        Args:
            client (HTTPHIBPClient): password漏洩を照会するclient fixture.
            mock_http_client (StubAsyncClient): responseを設定して送信URLを記録するstub.

        Returns:
            None: prefix長とrange API URLを検証して値を返さず完了する.
        """
        password = "test_password"
        expected_prefix_length = 5
        mock_http_client.response = _make_response(200, "0000000000000000000000000000000000A:1")

        _ = await client.is_password_compromised(password)

        sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
        prefix = sha1[:expected_prefix_length]
        assert len(prefix) == expected_prefix_length
        call_url = mock_http_client.called_url
        assert call_url is not None
        assert call_url.endswith(f"/{prefix}")

    async def test_case_insensitive_suffix_matching(
        self,
        client: HTTPHIBPClient,
        mock_http_client: StubAsyncClient,
    ) -> None:
        """小文字suffixを含むrange responseでも漏洩を検出することを検証する.

        Args:
            client (HTTPHIBPClient): password漏洩を照会するclient fixture.
            mock_http_client (StubAsyncClient): lowercase suffix responseを設定するstub.

        Returns:
            None: case-insensitive suffix判定を検証して値を返さず完了する.
        """
        password = "password123"
        sha1 = hashlib.sha1(password.encode()).hexdigest()
        suffix_lower = sha1[5:].lower()

        # レスポンスは小文字で返す(通常は大文字だが、堅牢性テスト)
        response_text = f"{suffix_lower}:10\r\n0000000000000000000000000000000000A:1"
        mock_http_client.response = _make_response(200, response_text)

        result = await client.is_password_compromised(password)

        assert result is True
