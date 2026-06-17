from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    StableSurface,
    SurfaceResult,
    VerificationStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from athena_cli.stable_verification.models import GetscoresProbeCase


@dataclass(frozen=True, slots=True)
class OsuPyProbePrerequisites:
    version: str | None
    executable_sha256: str | None
    credentials_present: bool

    def missing_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.version is None:
            missing.append("version")
        if self.executable_sha256 is None:
            missing.append("executable_sha256")
        if not self.credentials_present:
            missing.append("credentials")

        return tuple(missing)


class OsuPyProbe:
    def __init__(
        self,
        *,
        import_osu: Callable[[], object] | None = None,
        executor: Callable[[object, GetscoresProbeCase], SurfaceResult] | None = None,
    ) -> None:
        self._import_osu: Callable[[], object] = import_osu or _import_osu_module
        self._executor: Callable[[object, GetscoresProbeCase], SurfaceResult] = (
            executor or _missing_executor
        )

    def probe_getscores(
        self,
        case: GetscoresProbeCase,
        prerequisites: OsuPyProbePrerequisites,
    ) -> SurfaceResult:
        missing_prerequisites = prerequisites.missing_fields()
        if missing_prerequisites:
            return _optional_result(
                VerificationStatus.SKIP,
                "osu.py probe prerequisites missing: " + ", ".join(missing_prerequisites),
            )

        try:
            osu_module = self._import_osu()
        except ModuleNotFoundError as exc:
            if exc.name == "osu":
                return _optional_result(
                    VerificationStatus.SKIP,
                    "osu.py package is not installed",
                )
            return _optional_result(
                VerificationStatus.UNAVAILABLE,
                f"osu.py import failed: {exc.__class__.__name__}",
            )

        try:
            return self._executor(osu_module, case)
        except Exception as exc:
            return _optional_result(
                VerificationStatus.UNAVAILABLE,
                f"osu.py getscores probe failed: {exc.__class__.__name__}",
            )


def _import_osu_module() -> object:
    return importlib.import_module("osu")


def _missing_executor(
    osu_module: object,
    case: GetscoresProbeCase,
) -> SurfaceResult:
    _ = (osu_module, case)
    return _optional_result(
        VerificationStatus.UNAVAILABLE,
        "osu.py getscores executor is not configured",
    )


def _optional_result(status: VerificationStatus, message: str) -> SurfaceResult:
    return SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=status,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference="optional:osu.py getscores probe",
    )


__all__ = [
    "OsuPyProbe",
    "OsuPyProbePrerequisites",
]
