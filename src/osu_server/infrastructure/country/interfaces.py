"""CountryResolver Protocol — リクエストから国コードを検出する抽象インターフェース。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from starlette.requests import Request


@runtime_checkable
class CountryResolver(Protocol):
    """リクエストから2文字の ISO 3166-1 alpha-2 国コードを返す。

    検出不能時は ``"XX"`` を返す。
    """

    def resolve(self, request: Request) -> str:
        """国コードを返す。検出不能時は ``"XX"``。"""
        ...
