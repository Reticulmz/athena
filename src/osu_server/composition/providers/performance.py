"""Performance subsystem providers shared by app and worker graphs."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.domain.scores.performance import FormulaProfilePolicy
from osu_server.services.commands.scores.performance import PerformanceRuntimeSettings

_DISHKA_RUNTIME_HINTS = (FormulaProfilePolicy, PerformanceRuntimeSettings)


@final
class PerformanceProviderSet(Provider):
    """Providers for score performance runtime defaults and policies."""

    scope = Scope.APP

    @provide
    def performance_runtime_settings(self) -> PerformanceRuntimeSettings:
        return PerformanceRuntimeSettings()

    @provide
    def formula_profile_policy(
        self,
        settings: PerformanceRuntimeSettings,
    ) -> FormulaProfilePolicy:
        return FormulaProfilePolicy(settings.formula_profiles_by_playstyle)
