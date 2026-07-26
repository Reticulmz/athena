"""score performance commandのruntime setting contractを検証するtest module."""

from __future__ import annotations

from datetime import timedelta

import pytest

from osu_server.domain.scores.performance import FormulaProfile
from osu_server.domain.scores.score import Playstyle
from osu_server.services.commands.scores.performance import PerformanceRuntimeSettings


def test_runtime_settings_have_operational_defaults() -> None:
    """既定runtime settingがworkerの運用可能な値を持つことを検証する.

    引数なしでsettingを生成する.
    bounded wait, worker chunk size, claim timeout, vanilla formula profileが定められた
    運用defaultと一致することを確認する.

    Returns:
        None: wait時間とchunk sizeとclaim timeoutとvanilla formula profileを検証して完了する.
    """
    settings = PerformanceRuntimeSettings()

    assert settings.bounded_wait == timedelta(seconds=5)
    assert settings.worker_chunk_size == 100
    assert settings.claim_timeout == timedelta(minutes=5)
    assert settings.active_formula_profile_for(Playstyle.VANILLA) is FormulaProfile.VANILLA_RANKED


def test_runtime_settings_copy_formula_profile_mapping() -> None:
    """初期化時にformula profile mappingをcopyして外部mutationを遮断することを検証する.

    vanilla profile mappingでsettingを生成した後に元mappingをclearし setting内のactive profileが
    維持されることを確認する.

    Returns:
        None: 元mappingをclearしてもactive profileが保持されることを検証して完了する.
    """
    profiles = {Playstyle.VANILLA: FormulaProfile.VANILLA_RANKED}

    settings = PerformanceRuntimeSettings(formula_profiles_by_playstyle=profiles)
    profiles.clear()

    assert settings.active_formula_profile_for(Playstyle.VANILLA) is FormulaProfile.VANILLA_RANKED


def test_runtime_settings_reject_missing_vanilla_formula_profile() -> None:
    """Vanilla formula profileがないsettingをValueErrorで拒否することを検証する.

    空のformula profile mappingでsettingを初期化し required vanilla profileを示すvalidation errorが
    送出されることを確認する.

    Returns:
        None: 必須profile欠損時のvalidation errorを検証して完了する.
    """
    with pytest.raises(ValueError, match="vanilla formula profile is required"):
        _ = PerformanceRuntimeSettings(formula_profiles_by_playstyle={})


def test_runtime_settings_reject_non_positive_bounded_wait() -> None:
    """0以下のbounded waitをValueErrorで拒否することを検証する.

    0秒のbounded waitでsettingを初期化する.
    duration fieldを示すvalidation errorが送出されることを確認する.

    Returns:
        None: 不正なwait durationのvalidation errorを検証して完了する.
    """
    with pytest.raises(ValueError, match="bounded_wait"):
        _ = PerformanceRuntimeSettings(bounded_wait=timedelta(seconds=0))


def test_runtime_settings_reject_non_positive_worker_chunk_size() -> None:
    """0以下のworker chunk sizeをValueErrorで拒否することを検証する.

    0のworker chunk sizeでsettingを初期化する.
    chunk size fieldを示すvalidation errorが送出されることを確認する.

    Returns:
        None: 不正なchunk sizeのvalidation errorを検証して完了する.
    """
    with pytest.raises(ValueError, match="worker_chunk_size"):
        _ = PerformanceRuntimeSettings(worker_chunk_size=0)


def test_runtime_settings_reject_non_positive_claim_timeout() -> None:
    """0以下のclaim timeoutをValueErrorで拒否することを検証する.

    0秒のclaim timeoutでsettingを初期化する.
    timeout fieldを示すvalidation errorが送出されることを確認する.

    Returns:
        None: 不正なclaim timeoutのvalidation errorを検証して完了する.
    """
    with pytest.raises(ValueError, match="claim_timeout"):
        _ = PerformanceRuntimeSettings(claim_timeout=timedelta(seconds=0))
