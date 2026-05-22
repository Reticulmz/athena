"""CloudflareCountryResolver — Cloudflare の CF-IPCountry ヘッダから国コードを取得する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request


class CloudflareCountryResolver:
    """Cloudflare リバースプロキシが付与する ``CF-IPCountry`` ヘッダから国コードを取得する。

    ヘッダが存在しない場合は ``"XX"`` (不明) を返す。
    """

    def resolve(self, request: Request) -> str:
        """リクエストヘッダから2文字の国コードを返す。"""
        return request.headers.get("CF-IPCountry", "XX")
