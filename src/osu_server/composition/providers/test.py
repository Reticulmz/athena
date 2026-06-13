"""Test-only provider replacement helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, final

from dishka import Provider, Scope

if TYPE_CHECKING:
    from collections.abc import Callable

T_co = TypeVar("T_co", covariant=True)


@dataclass(frozen=True, slots=True)
class ProviderReplacement[T_co]:
    """Typed description of one test provider replacement."""

    provides: type[T_co]
    factory: Callable[[], T_co]
    scope: Scope = Scope.APP


@final
class TestProviderSet(Provider):
    """Provider set that replaces runtime providers for tests."""

    __test__: bool = False

    def __init__(self, *replacements: ProviderReplacement[object]) -> None:
        super().__init__(scope=Scope.APP)
        for replacement in replacements:
            _ = self.provide(
                replacement.factory,
                provides=replacement.provides,
                scope=replacement.scope,
                override=True,
            )


def replace_value[T](
    provides: type[T],
    value: T,
    *,
    scope: Scope = Scope.APP,
) -> ProviderReplacement[T]:
    """Replace a dependency with one existing typed test value."""

    def factory():
        return value

    return ProviderReplacement(provides=provides, factory=factory, scope=scope)


def replace_factory[T](
    provides: type[T],
    factory: Callable[[], T],
    *,
    scope: Scope = Scope.APP,
) -> ProviderReplacement[T]:
    """Replace a dependency with a typed test factory."""
    return ProviderReplacement(provides=provides, factory=factory, scope=scope)
