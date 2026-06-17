from __future__ import annotations

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    SecretProbeInput,
    StableSurface,
    StableTarget,
    SurfaceResult,
    VerificationRunResult,
    VerificationStatus,
)


def test_verification_status_values_match_stable_reporting_vocabulary() -> None:
    assert {status.value for status in VerificationStatus} == {
        "pass",
        "fail",
        "skip",
        "known_gap",
        "unavailable",
    }


def test_common_result_model_covers_surface_evidence_scope_and_target() -> None:
    target = StableTarget(
        base_url="http://127.0.0.1:8000",
        host_identity="athena.localhost",
        timeout_seconds=2.5,
    )
    diagnostic = DiagnosticSummary(
        message="GET /web/osu-osz2-bmsubmit-getid.php status=200 bytes=12",
        method="GET",
        path="/web/osu-osz2-bmsubmit-getid.php",
        status_code=200,
        response_byte_size=12,
    )
    result = SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=VerificationStatus.PASS,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=diagnostic,
        reference="tests/fixtures/web_legacy/getscores/ranked_response.txt",
    )

    run_result = VerificationRunResult(target=target, results=(result,))

    assert run_result.failed is False
    assert run_result.target == target
    assert run_result.results == (result,)


def test_mandatory_failure_fails_run() -> None:
    result = SurfaceResult(
        surface=StableSurface.SCORE_SUBMIT,
        status=VerificationStatus.FAIL,
        evidence_type=EvidenceType.AUTOMATED_TEST,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=DiagnosticSummary(message="chart response missing pp"),
        reference="tests/unit/transports/web_legacy/test_score_submit_mapper.py",
    )

    run_result = VerificationRunResult(target=None, results=(result,))

    assert result.fails_run is True
    assert run_result.failed is True


def test_optional_unavailable_and_skip_do_not_fail_run() -> None:
    results = (
        SurfaceResult(
            surface=StableSurface.GETSCORES,
            status=VerificationStatus.UNAVAILABLE,
            evidence_type=EvidenceType.HEADLESS_PROBE,
            scope=EvidenceScope.OPTIONAL,
            diagnostic_summary=DiagnosticSummary(message="osu package unavailable"),
            reference="osu.py",
        ),
        SurfaceResult(
            surface=StableSurface.GETSCORES,
            status=VerificationStatus.SKIP,
            evidence_type=EvidenceType.HEADLESS_PROBE,
            scope=EvidenceScope.OPTIONAL,
            diagnostic_summary=DiagnosticSummary(message="probe credentials not configured"),
            reference="osu.py",
        ),
    )

    run_result = VerificationRunResult(target=None, results=results)

    assert [result.fails_run for result in results] == [False, False]
    assert run_result.failed is False


def test_secret_probe_input_is_kept_out_of_reportable_diagnostic_summary() -> None:
    secret_input = SecretProbeInput(
        "password-value",
        "hash-value",
        "token-value",
        b"raw-replay-value",
        {"username": "player", "password": "password-value"},
    )
    diagnostic = DiagnosticSummary(
        message="POST /web/osu-submit-modular-selector.php status=200 bytes=42",
        method="POST",
        path="/web/osu-submit-modular-selector.php",
        status_code=200,
        response_byte_size=42,
    )

    assert secret_input.password in {"password-value"}
    assert "password-value" not in repr(diagnostic)
    assert "hash-value" not in repr(diagnostic)
    assert "token-value" not in repr(diagnostic)
    assert "raw-replay-value" not in repr(diagnostic)
