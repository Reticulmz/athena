"""Handler と listener の route を宣言して class 定義時に収集する."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from typing import ClassVar, TypeVar

_F = TypeVar("_F", bound=Callable[..., object])

_ROUTE_KEYS: dict[Callable[..., object], object] = {}
"""装飾済み関数から route key への module level registry.

route(key) が decoration 時に登録し, RouteGroup.__init_subclass__ が class 定義時に参照する.
"""


def get_route_registry() -> dict[Callable[..., object], object]:
    """登録済み route registry の snapshot を返す.

    Returns:
        dict[Callable[..., object], object]: 関数から route key への独立した辞書.

    Notes:
        test 用の inspection API である. production code は RouteGroup.get_routes を使う.
    """
    return dict(_ROUTE_KEYS)


def route(key: object) -> Callable[[_F], _F]:
    """対象 method の route key を module registry へ登録する decorator を作る.

    Args:
        key (object): 対象 method に対応付ける route key.

    Returns:
        Callable[[_F], _F]: 元の関数を変更せず registry へ登録する decorator.

    Notes:
        route key は関数 attribute ではなく module level registry にだけ保存する.
    """

    def decorator(func: _F) -> _F:
        """関数と route key の対応を registry に保存する.

        Args:
            func (_F): route key に対応付ける元の関数.

        Returns:
            _F: attribute を追加せずそのまま返す元の関数.
        """
        _ROUTE_KEYS[func] = key
        return func

    return decorator


class RouteGroup:
    """route decorator 付き method を class ごとに収集する基底 class.

    Attributes:
        __routes__ (ClassVar[dict[object, str]]): route key から class 自身の method 名への対応.

    Notes:
        継承元の route は再収集しない. instance では get_routes が bound method を返す.
    """

    __routes__: ClassVar[dict[object, str]]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """派生 class 自身が宣言した route decorator 付き method を収集する.

        Args:
            kwargs (object): 基底 class へ渡す class 作成時の keyword argument.

        Returns:
            None: __routes__ を設定して class 作成を完了し値を返さない.
        """
        super().__init_subclass__(**kwargs)
        routes: dict[object, str] = {}
        cls_dict: dict[str, object] = dict(vars(cls))
        for name, attr in cls_dict.items():
            if callable(attr) and attr in _ROUTE_KEYS:
                routes[_ROUTE_KEYS[attr]] = name
        cls.__routes__ = routes

    def get_routes(self) -> Iterator[tuple[object, Callable[..., Awaitable[None]]]]:
        """宣言済み route の key と bound method を順に生成する.

        Yields:
            tuple[object, Callable[..., Awaitable[None]]]: route key と bound 済み handler.
        """
        for key, method_name in self.__routes__.items():
            yield key, getattr(self, method_name)
