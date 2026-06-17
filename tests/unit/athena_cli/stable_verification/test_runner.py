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
    def execute(request: VerificationRunRequest) -> tuple[SurfaceResult, ...]:
        _ = request
        return results

    return execute


def _executor(
    calls: list[StableSurface],
    *results: SurfaceResult,
) -> Callable[[VerificationRunRequest], tuple[SurfaceResult, ...]]:
    def execute(request: VerificationRunRequest) -> tuple[SurfaceResult, ...]:
        _ = request
        calls.append(results[0].surface)
        return results

    return execute
