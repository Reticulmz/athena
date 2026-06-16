from __future__ import annotations

import inspect

from osu_server.infrastructure.performance import calculator_identity
from osu_server.infrastructure.performance.calculator_identity import (
    InstalledPackagePerformanceCalculatorIdentity,
)


def test_calculator_identity_reads_installed_package_metadata_without_calculator_import() -> None:
    version_calls: list[str] = []

    def fake_version(package_name: str) -> str:
        version_calls.append(package_name)
        return "4.0.2"

    identity = InstalledPackagePerformanceCalculatorIdentity(version_reader=fake_version)

    assert identity.calculator_name() == "rosu-pp-py"
    assert identity.calculator_version() == "4.0.2"
    assert version_calls == ["rosu-pp-py"]


def test_calculator_identity_module_does_not_import_calculator() -> None:
    source = inspect.getsource(calculator_identity)

    assert "rosu_pp_py" not in source
    assert "rosu_calculator" not in source
    assert "RosuPerformanceCalculator" not in source
