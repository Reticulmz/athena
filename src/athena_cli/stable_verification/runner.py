from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from athena_cli.stable_verification.catalog import list_surfaces
from athena_cli.stable_verification.models import VerificationRunResult

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from athena_cli.stable_verification.models import (
        StableSurface,
        StableTarget,
        SurfaceResult,
    )


class StableVerificationRunnerError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerificationRunRequest:
    target: StableTarget | None
    surfaces: tuple[StableSurface, ...]
    require_target: bool = True


if TYPE_CHECKING:
    SurfaceExecutor = Callable[
        [VerificationRunRequest],
        tuple[SurfaceResult, ...],
    ]


class StableVerificationRunner:
    def __init__(
        self,
        *,
        surface_executors: Mapping[StableSurface, SurfaceExecutor],
    ) -> None:
        self._surface_executors: dict[StableSurface, SurfaceExecutor] = dict(surface_executors)

    def run(self, request: VerificationRunRequest) -> VerificationRunResult:
        if request.require_target and request.target is None:
            raise StableVerificationRunnerError(
                "--base-url is required for stable verification probes"
            )

        selected_surfaces = self._select_surfaces(request.surfaces)
        results: list[SurfaceResult] = []
        for surface in selected_surfaces:
            executor = self._surface_executors[surface]
            results.extend(executor(request))

        return VerificationRunResult(
            target=request.target,
            results=tuple(results),
        )

    def _select_surfaces(
        self,
        requested_surfaces: tuple[StableSurface, ...],
    ) -> tuple[StableSurface, ...]:
        if requested_surfaces:
            return requested_surfaces

        return tuple(surface for surface in list_surfaces() if surface in self._surface_executors)


__all__ = [
    "StableVerificationRunner",
    "StableVerificationRunnerError",
    "VerificationRunRequest",
]
