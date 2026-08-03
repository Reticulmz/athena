"""StableVerificationRunnerのsurface選択とrun集約を検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    StableSurface,
    StableTarget,
    SurfaceResult,
    VerificationStatus,
)
from athena_cli.stable_verification.runner import (
    StableVerificationRunner,
    StableVerificationRunnerError,
    VerificationRunRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def test_runner_executes_selected_surface_only() -> None:
    """明示指定したsurfaceだけが対応executorへ渡ることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: executor呼出し, result surface, またはrun failed flagが変化した場合.
    """
    calls: list[StableSurface] = []
    runner = StableVerificationRunner(
        surface_executors={
            StableSurface.GETSCORES: _executor(
                calls,
                _result(StableSurface.GETSCORES, VerificationStatus.PASS),
            ),
            StableSurface.SCORE_SUBMIT: _executor(
                calls,
                _result(StableSurface.SCORE_SUBMIT, VerificationStatus.PASS),
            ),
        }
    )

    result = runner.run(
        VerificationRunRequest(
            target=_target(),
            surfaces=(StableSurface.GETSCORES,),
        )
    )

    assert calls == [StableSurface.GETSCORES]
    assert [surface_result.surface for surface_result in result.results] == [
        StableSurface.GETSCORES
    ]
    assert result.failed is False


def test_runner_aggregates_mandatory_failure_as_failed_run() -> None:
    """Mandatory failureがverification run全体をfailedにすることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: mandatory FAILがrun failedへ集約されない場合.
    """
    runner = StableVerificationRunner(
        surface_executors={
            StableSurface.GETSCORES: _constant_executor(
                _result(StableSurface.GETSCORES, VerificationStatus.FAIL)
            ),
        }
    )

    result = runner.run(
        VerificationRunRequest(
            target=_target(),
            surfaces=(StableSurface.GETSCORES,),
        )
    )

    assert result.failed is True


def test_runner_keeps_optional_unavailable_from_failing_run() -> None:
    """Optional unavailableがrun全体をfailedにしないことを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: optional UNAVAILABLEのresult順またはrun failed flagが変化した場合.
    """
    runner = StableVerificationRunner(
        surface_executors={
            StableSurface.GETSCORES: _constant_executor(
                _result(StableSurface.GETSCORES, VerificationStatus.PASS),
                _result(
                    StableSurface.GETSCORES,
                    VerificationStatus.UNAVAILABLE,
                    scope=EvidenceScope.OPTIONAL,
                    evidence_type=EvidenceType.HEADLESS_PROBE,
                ),
            ),
        }
    )

    result = runner.run(
        VerificationRunRequest(
            target=_target(),
            surfaces=(StableSurface.GETSCORES,),
        )
    )

    assert [surface_result.status for surface_result in result.results] == [
        VerificationStatus.PASS,
        VerificationStatus.UNAVAILABLE,
    ]
    assert result.failed is False


def test_runner_requires_target_for_live_probe_requests() -> None:
    """target必須requestがtargetなしでrunner errorになることを検証する.

    Returns:
        None: Assertionだけを実行する.
    """
    runner = StableVerificationRunner(
        surface_executors={
            StableSurface.GETSCORES: _constant_executor(
                _result(StableSurface.GETSCORES, VerificationStatus.PASS)
            ),
        }
    )

    with pytest.raises(
        StableVerificationRunnerError,
        match="--base-url is required for stable verification probes",
    ):
        _ = runner.run(
            VerificationRunRequest(
                target=None,
                surfaces=(StableSurface.GETSCORES,),
                require_target=True,
            )
        )


def test_runner_all_selection_uses_all_registered_executors_in_catalog_order() -> None:
    """surface未指定時に登録executorをcatalog順で実行することを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: all selectionのexecutor呼出し順がcatalog順と異なる場合.
    """
    calls: list[StableSurface] = []
    runner = StableVerificationRunner(
        surface_executors={
            StableSurface.SCORE_SUBMIT: _executor(
                calls,
                _result(StableSurface.SCORE_SUBMIT, VerificationStatus.PASS),
            ),
            StableSurface.GETSCORES: _executor(
                calls,
                _result(StableSurface.GETSCORES, VerificationStatus.PASS),
            ),
        }
    )

    _ = runner.run(
        VerificationRunRequest(
            target=_target(),
            surfaces=(),
        )
    )

    assert calls == [StableSurface.GETSCORES, StableSurface.SCORE_SUBMIT]


def _target() -> StableTarget:
    """Runner testで使う固定のlocal stable targetを生成する.

    Returns:
        StableTarget: localhost base URLとathena host identityを持つtarget.
    """
    return StableTarget(
        base_url="http://127.0.0.1:8000",
        host_identity="athena.localhost",
        timeout_seconds=1.0,
    )


def _result(
    surface: StableSurface,
    status: VerificationStatus,
    *,
    scope: EvidenceScope = EvidenceScope.MANDATORY,
    evidence_type: EvidenceType = EvidenceType.GOLDEN_FIXTURE,
) -> SurfaceResult:
    """指定surfaceとstatusを持つtest用surface結果を生成する.

    Args:
        surface (StableSurface): executorが返すstable surface.
        status (VerificationStatus): test対象のverification status.
        scope (EvidenceScope): evidenceのmandatory/optional分類.
        evidence_type (EvidenceType): resultを支えるevidence種別.

    Returns:
        SurfaceResult: report-safe diagnosticを含むtest用result.
    """
    return SurfaceResult(
        surface=surface,
        status=status,
        evidence_type=evidence_type,
        scope=scope,
        diagnostic_summary=DiagnosticSummary(message=f"{surface.value} {status.value}"),
    )


def _constant_executor(
    *results: SurfaceResult,
) -> Callable[[VerificationRunRequest], tuple[SurfaceResult, ...]]:
    """常に同じsurface結果を返すexecutorを生成する.

    Args:
        *results (SurfaceResult): 実行ごとに返すsurface結果群.

    Returns:
        Callable[[VerificationRunRequest], tuple[SurfaceResult, ...]]: requestを無視して固定結果を
            返すexecutor.
    """

    def execute(request: VerificationRunRequest) -> tuple[SurfaceResult, ...]:
        """requestを使用せず設定済みの固定結果を返す.

        Args:
            request (VerificationRunRequest): runnerから渡される実行request. testでは使用しない.

        Returns:
            tuple[SurfaceResult, ...]: factoryへ渡した固定結果群.
        """
        _ = request
        return results

    return execute


def _executor(
    calls: list[StableSurface],
    *results: SurfaceResult,
) -> Callable[[VerificationRunRequest], tuple[SurfaceResult, ...]]:
    """呼出しsurfaceを記録して固定結果を返すexecutorを生成する.

    Args:
        calls (list[StableSurface]): 実行順を記録するmutable list.
        *results (SurfaceResult): executorが返す固定surface結果群.

    Returns:
        Callable[[VerificationRunRequest], tuple[SurfaceResult, ...]]: 呼出しを記録するexecutor.
    """

    def execute(request: VerificationRunRequest) -> tuple[SurfaceResult, ...]:
        """先頭結果のsurfaceを記録して設定済み結果を返す.

        Args:
            request (VerificationRunRequest): runnerから渡される実行request. testでは使用しない.

        Returns:
            tuple[SurfaceResult, ...]: factoryへ渡した固定結果群.
        """
        _ = request
        calls.append(results[0].surface)
        return results

    return execute
