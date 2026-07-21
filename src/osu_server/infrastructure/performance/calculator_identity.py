"""calculator runtime を import せず package metadata から identity を読み取ります."""

from __future__ import annotations

from importlib import metadata
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from collections.abc import Callable

_PACKAGE_NAME = "rosu-pp-py"
_CALCULATOR_NAME = "rosu-pp-py"


@final
class InstalledPackagePerformanceCalculatorIdentity:
    """承認済み calculator の provenance を package metadata だけから読み取ります.

    Attributes:
        _calculator_version (str): 初期化時に固定する installed package の version です.
    """

    def __init__(
        self,
        version_reader: Callable[[str], str] = metadata.version,
    ) -> None:
        """Package metadata reader から calculator version を初期化します.

        Args:
            version_reader (Callable[[str], str]): package 名を受け取り installed version を
                返す reader です.

        Raises:
            metadata.PackageNotFoundError: 既定 reader が calculator package を発見できない場合.
        """
        self._calculator_version = version_reader(_PACKAGE_NAME)

    def calculator_name(self) -> str:
        """Calculator provenance に記録する安定した calculator 名を返します.

        Returns:
            str: 承認済み calculator package の表示名です.
        """
        return _CALCULATOR_NAME

    def calculator_version(self) -> str:
        """初期化時に読み取った calculator package version を返します.

        Returns:
            str: installed calculator package の version です.
        """
        return self._calculator_version


__all__ = ("InstalledPackagePerformanceCalculatorIdentity",)
