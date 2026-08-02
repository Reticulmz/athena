"""Have I Been Pwned password range APIを利用するsecurity adapterを提供するmodule.

SHA-1 hashのprefixだけを送るk-anonymity requestで漏洩passwordを照会する.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

import httpx

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"


@runtime_checkable
class HIBPClient(Protocol):
    """HIBP k-anonymity API clientの抽象Protocol.

    外部serviceの障害時にFalseを返す実装は, 漏洩passwordを未検知として許可し得るfail-openである.
    """

    async def is_password_compromised(self, password: str) -> bool:
        """passwordがHIBP databaseに漏洩済みか判定する.

        Args:
            password (str): 漏洩照会する平文password.

        Returns:
            bool: 漏洩済みならTrue. 外部serviceの通信失敗時はFalseとなるfail-open判定.
        """
        ...


class HTTPHIBPClient:
    """HIBP k-anonymity API clientのHTTP実装.

    SHA-1 hashの先頭5文字だけを外部へ送信し, responseのsuffixと照合する.
    APIに到達できない場合はregistrationを阻害しないためFalseを返すfail-open実装である.
    このfallbackは漏洩済みpasswordを未検知として許可し得る.

    Attributes:
        _http_client (httpx.AsyncClient): HIBP range endpointへrequestを送るHTTP client.
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        """HIBP requestに使う非同期HTTP clientを保持する.

        Args:
            http_client (httpx.AsyncClient): lifecycleを呼出側が所有するHTTP client.
        """
        self._http_client: httpx.AsyncClient = http_client

    async def is_password_compromised(self, password: str) -> bool:
        """passwordがHIBP databaseに漏洩済みか判定する.

        Args:
            password (str): SHA-1 hash化して照会する平文password.

        Returns:
            bool: HIBP responseに同じhash suffixがあればTrue. 通信失敗時はFalseとなるfail-open判定.

        Notes:
            password全体やSHA-1 hash全体は外部へ送らず, 5文字のprefixだけを送る.
            HTTP障害時のFalseは漏洩passwordを未検知として許可し得る.
        """
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
