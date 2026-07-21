"""CloudflareのCF-IPCountry headerから国コードを取得するmodule.

reverse proxyが付与するheaderを, Athena内部で使う2文字の国コードへ適応する.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class CloudflareCountryResolver:
    """Cloudflare reverse proxyが付与する``CF-IPCountry`` headerから国コードを解決する.

    ``CF-IPCountry``がないrequestは, 不明を表す``"XX"``へ解決する.
    """

    def resolve(self, headers: Mapping[str, str]) -> str:
        """HTTP headerから2文字の国コードを返す.

        Args:
            headers (Mapping[str, str]): Cloudflare headerを含むrequest header.

        Returns:
            str: ``CF-IPCountry``の値. headerがない場合は``"XX"``.
        """
        return headers.get("CF-IPCountry", "XX")
