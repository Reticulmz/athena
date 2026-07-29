"""HTTP headerから国コードを解決する抽象interfaceを定義するmodule.

transportがcountry resolver implementationへ依存しないためのProtocolを提供する.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping


@runtime_checkable
class CountryResolver(Protocol):
    """HTTP headerから2文字のISO 3166-1 alpha-2国コードを返すProtocol.

    resolverは国コードを検出できない場合に``"XX"``を返す.
    """

    def resolve(self, headers: Mapping[str, str]) -> str:
        """HTTP headerから国コードを解決する.

        Args:
            headers (Mapping[str, str]): 国コード検出に利用するHTTP header.

        Returns:
            str: 2文字の国コード. 検出不能な場合は``"XX"``.
        """
        ...
