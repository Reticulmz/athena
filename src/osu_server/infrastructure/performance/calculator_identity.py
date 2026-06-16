"""Calculator identity adapter that does not import calculator runtime code."""

from __future__ import annotations

from importlib import metadata
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from collections.abc import Callable

_PACKAGE_NAME = "rosu-pp-py"
_CALCULATOR_NAME = "rosu-pp-py"


@final
class InstalledPackagePerformanceCalculatorIdentity:
    """Read approved calculator provenance from package metadata only."""

    def __init__(
        self,
        version_reader: Callable[[str], str] = metadata.version,
    ) -> None:
        self._calculator_version = version_reader(_PACKAGE_NAME)

    def calculator_name(self) -> str:
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        return self._calculator_version


__all__ = ("InstalledPackagePerformanceCalculatorIdentity",)
