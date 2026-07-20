"""Stable verification surface executorを選択して集約実行する."""

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
    """stable verification requestが実行前提を満たさない場合に送出する."""


@dataclass(frozen=True, slots=True)
class VerificationRunRequest:
    """Stable verification runnerへ渡す実行条件を表す.

    Attributes:
        target (StableTarget | None): HTTP probeの接続先. fixture-only runではNone.
        surfaces (tuple[StableSurface, ...]): 実行するsurface. 空なら登録済み全surfaceを選ぶ.
        require_target (bool): target未設定を実行前errorとして扱う場合はTrue.
    """

    target: StableTarget | None
    surfaces: tuple[StableSurface, ...]
    require_target: bool = True


if TYPE_CHECKING:
    SurfaceExecutor = Callable[
        [VerificationRunRequest],
        tuple[SurfaceResult, ...],
    ]


class StableVerificationRunner:
    """surface executorをcatalog順に実行してverification runを集約する."""

    def __init__(
        self,
        *,
        surface_executors: Mapping[StableSurface, SurfaceExecutor],
    ) -> None:
        """surfaceごとのexecutor registryを保持する.

        Args:
            surface_executors (Mapping[StableSurface, SurfaceExecutor]): 各stable surfaceを
                VerificationRunRequestからSurfaceResult群へ変換するexecutor mapping.
        """
        self._surface_executors: dict[StableSurface, SurfaceExecutor] = dict(surface_executors)

    def run(self, request: VerificationRunRequest) -> VerificationRunResult:
        """requestに選択されたsurface executorを実行して結果を集約する.

        Args:
            request (VerificationRunRequest): target, surface選択, target必須条件を含む実行request.

        Returns:
            VerificationRunResult: targetと選択surfaceの全executor結果を含むrun結果.

        Raises:
            StableVerificationRunnerError: target必須requestでtargetが未設定の場合.
            KeyError: 明示指定surfaceに登録済みexecutorがない場合.
        """
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
        """明示指定またはcatalog順の登録済みsurfaceを選択する.

        Args:
            requested_surfaces (tuple[StableSurface, ...]): callerが明示的に指定したsurface群.

        Returns:
            tuple[StableSurface, ...]: 明示指定値, またはregistryに存在するcatalog順surface群.
        """
        if requested_surfaces:
            return requested_surfaces

        return tuple(surface for surface in list_surfaces() if surface in self._surface_executors)


__all__ = [
    "StableVerificationRunner",
    "StableVerificationRunnerError",
    "VerificationRunRequest",
]
