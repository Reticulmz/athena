from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

import httpx

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"


@runtime_checkable
class HIBPClient(Protocol):
    """HIBP k-Anonymity API クライアントの Protocol 抽象インターフェース。"""

    async def is_password_compromised(self, password: str) -> bool:
        """パスワードが HIBP データベースに漏洩済みか判定する。

        Args:
            password: 平文パスワード。

        Returns:
            True なら漏洩済み。エラー時は False。
        """
        ...


class HTTPHIBPClient:
    """HIBP k-Anonymity API クライアントの HTTP 実装。

    SHA-1 の先頭5文字のみ外部に送信し、レスポンスのサフィックスと照合する。
    API 到達不能時は False を返す(フォールバック: 登録を阻害しない)。
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client: httpx.AsyncClient = http_client

    async def is_password_compromised(self, password: str) -> bool:
        """パスワードが HIBP データベースに漏洩済みか判定する。"""
        sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
        prefix = sha1[:5]
        suffix = sha1[5:]

        try:
            response = await self._http_client.get(f"{_HIBP_RANGE_URL}{prefix}")
            _ = response.raise_for_status()
        except httpx.HTTPError:
            return False

        for line in response.text.splitlines():
            parts = line.split(":")
            if parts[0].upper() == suffix:
                return True

        return False
