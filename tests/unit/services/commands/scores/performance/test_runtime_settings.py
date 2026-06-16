"""Runtime settings tests for score performance commands."""

from __future__ import annotations

from datetime import timedelta

import pytest

from osu_server.domain.scores.performance import FormulaProfile
from osu_server.domain.scores.score import Playstyle
from osu_server.services.commands.scores.performance import PerformanceRuntimeSettings


def test_runtime_settings_have_operational_defaults() -> None:
    settings = PerformanceRuntimeSettings()

    assert settings.bounded_wait == timedelta(seconds=5)
    assert settings.worker_chunk_size == 100
    assert settings.claim_timeout == timedelta(minutes=5)
    assert settings.active_formula_profile_for(Playstyle.VANILLA) is FormulaProfile.VANILLA_RANKED


def test_runtime_settings_copy_formula_profile_mapping() -> None:
    profiles = {Playstyle.VANILLA: FormulaProfile.VANILLA_RANKED}

    settings = PerformanceRuntimeSettings(formula_profiles_by_playstyle=profiles)
    profiles.clear()

    assert settings.active_formula_profile_for(Playstyle.VANILLA) is FormulaProfile.VANILLA_RANKED


def test_runtime_settings_reject_missing_vanilla_formula_profile() -> None:
    with pytest.raises(ValueError, match="vanilla formula profile is required"):
        _ = PerformanceRuntimeSettings(formula_profiles_by_playstyle={})


def test_runtime_settings_reject_non_positive_bounded_wait() -> None:
    with pytest.raises(ValueError, match="bounded_wait"):
        _ = PerformanceRuntimeSettings(bounded_wait=timedelta(seconds=0))


def test_runtime_settings_reject_non_positive_worker_chunk_size() -> None:
    with pytest.raises(ValueError, match="worker_chunk_size"):
        _ = PerformanceRuntimeSettings(worker_chunk_size=0)


def test_runtime_settings_reject_non_positive_claim_timeout() -> None:
    with pytest.raises(ValueError, match="claim_timeout"):
        _ = PerformanceRuntimeSettings(claim_timeout=timedelta(seconds=0))
