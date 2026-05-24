"""CountryResolver Protocol — HTTP ヘッダから国コードを検出する抽象インターフェース。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping


@runtime_checkable
class CountryResolver(Protocol):
    """HTTP ヘッダから2文字の ISO 3166-1 alpha-2 国コードを返す。

    検出不能時は ``"XX"`` を返す。
    """

    def resolve(self, headers: Mapping[str, str]) -> str:
        """国コードを返す。検出不能時は ``"XX"``。"""
        ...
