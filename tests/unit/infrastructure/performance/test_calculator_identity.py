"""installed performance calculator identityの契約を検証するmodule."""

from __future__ import annotations

import inspect

from osu_server.infrastructure.performance import calculator_identity
from osu_server.infrastructure.performance.calculator_identity import (
    InstalledPackagePerformanceCalculatorIdentity,
)


def test_calculator_identity_reads_installed_package_metadata_without_calculator_import() -> None:
    """Package metadataからcalculator identityを取得しadapter importなしを検証する.

    Returns:
        None: identity値とversion reader呼び出しを検証して値を返さず完了する.
    """
    version_calls: list[str] = []

    def fake_version(package_name: str) -> str:
        """指定packageの固定versionを返すmetadata reader fakeを提供する.

        Args:
            package_name (str): version照会されたpackage名.

        Returns:
            str: rosu-pp-pyの固定version文字列.
        """
        version_calls.append(package_name)
        return "4.0.2"

    identity = InstalledPackagePerformanceCalculatorIdentity(version_reader=fake_version)

    assert identity.calculator_name() == "rosu-pp-py"
    assert identity.calculator_version() == "4.0.2"
    assert version_calls == ["rosu-pp-py"]


def test_calculator_identity_module_does_not_import_calculator() -> None:
    """Identity module sourceにcalculator implementation importがないことを検証する.

    Returns:
        None: source文字列を検証して値を返さず完了する.
    """
    source = inspect.getsource(calculator_identity)

    assert "rosu_pp_py" not in source
    assert "rosu_calculator" not in source
    assert "RosuPerformanceCalculator" not in source
