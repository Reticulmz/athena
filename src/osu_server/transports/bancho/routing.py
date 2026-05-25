"""RouteGroup — declarative routing infrastructure for handlers and listeners.

Provides a ``@route(key)`` decorator and ``RouteGroup`` base class that
auto-collects decorated methods at class-definition time via
``__init_subclass__``.

Design ref: RouteGroup component in c2s-handlers design.md
Requirements: 1.1, 1.2, 1.3, 1.4
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from typing import ClassVar, TypeVar

_F = TypeVar("_F", bound=Callable[..., object])

_ROUTE_KEYS: dict[Callable[..., object], object] = {}
"""Module-level registry mapping decorated functions to their route keys.

Populated by ``@route(key)`` at decoration time, consumed by
``RouteGroup.__init_subclass__`` at class-definition time.
"""


def get_route_registry() -> dict[Callable[..., object], object]:
    """Return a read-only snapshot of the route registry.

    Intended for **testing only** — production code should rely on
    :meth:`RouteGroup.get_routes` instead.
    """
    return dict(_ROUTE_KEYS)


def route(key: object) -> Callable[[_F], _F]:
    """Declare a route key for a method.

    Registers the function in :data:`_ROUTE_KEYS`.  Does **not** add any
    attributes to the function itself — the module-level dict is the sole
    source of truth.
    """

    def decorator(func: _F) -> _F:
        _ROUTE_KEYS[func] = key
        return func

    return decorator


class RouteGroup:
    """Base class that auto-collects ``@route``-decorated methods.

    On subclass creation, ``__init_subclass__`` scans ``vars(cls)`` (own
    class only — no inheritance) against :data:`_ROUTE_KEYS` and builds
    ``__routes__``, a ``ClassVar`` mapping route keys to method names.

    At runtime, :meth:`get_routes` yields ``(key, bound_method)`` tuples
    for the instance.
    """

    __routes__: ClassVar[dict[object, str]]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        routes: dict[object, str] = {}
        cls_dict: dict[str, object] = dict(vars(cls))
        for name, attr in cls_dict.items():
            if callable(attr) and attr in _ROUTE_KEYS:
                routes[_ROUTE_KEYS[attr]] = name
        cls.__routes__ = routes

    def get_routes(self) -> Iterator[tuple[object, Callable[..., Awaitable[None]]]]:
        """Yield ``(key, bound_method)`` for all declared routes."""
        for key, method_name in self.__routes__.items():
            yield key, getattr(self, method_name)
