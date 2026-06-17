from __future__ import annotations

from pathlib import Path

from athena_cli.stable_verification.models import (
    EvidenceScope,
    EvidenceType,
    StableSurface,
    SurfaceResult,
    VerificationStatus,
)
from athena_cli.stable_verification.parsers import parse_score_submit_response
from athena_cli.stable_verification.score_submit import ScoreSubmitVerifier
from osu_server.services.commands.scores import SubmissionOutcome, SubmissionResult
from osu_server.transports.stable.web_legacy.mappers import StableScoreSubmitMapper

FIXTURE_DIR = (
    Path(__file__).resolve().parents[4]
    / "tests"
    / "fixtures"
    / "stable_compatibility"
    / "score_submit"
)


def test_verify_golden_response_validates_report_safe_request_metadata() -> None:
    result = _result_by_reference(
        ScoreSubmitVerifier(fixture_dir=FIXTURE_DIR).verify_golden_response(),
        "request_metadata.json",
    )

    assert result.surface is StableSurface.SCORE_SUBMIT
    assert result.status is VerificationStatus.PASS
    assert result.evidence_type is EvidenceType.GOLDEN_FIXTURE
    assert result.scope is EvidenceScope.MANDATORY
    assert result.fails_run is False
    assert result.diagnostic_summary.message == (
        "score submit request metadata valid: multipart/form-data score fields=2 replay=present"
    )
    _assert_secret_free(result.diagnostic_summary.message)


def test_verify_golden_response_validates_completed_fixture_required_chart_fields() -> None:
    fixture_body = (FIXTURE_DIR / "completed_response.txt").read_bytes()

    parsed = parse_score_submit_response(fixture_body)
    result = _result_by_reference(
        ScoreSubmitVerifier(fixture_dir=FIXTURE_DIR).verify_golden_response(),
        "completed_response.txt",
    )

    assert parsed.error is None
    assert parsed.response is not None
    assert parsed.response.beatmap_metadata.beatmap_playcount == 1
    assert parsed.response.beatmap_metadata.beatmap_passcount == 1
    assert parsed.response.beatmap_chart.fields["achieved"] == "true"
    assert parsed.response.beatmap_chart.fields["rankAfter"] == "42"
    assert parsed.response.beatmap_chart.fields["rankBefore"] == ""
    assert parsed.response.beatmap_chart.fields["rankedScoreAfter"] == "7654321"
    assert parsed.response.beatmap_chart.fields["rankedScoreBefore"] == "0"
    assert parsed.response.beatmap_chart.fields["maxComboAfter"] == "987"
    assert parsed.response.beatmap_chart.fields["accuracyAfter"] == "95.6789"
    assert parsed.response.beatmap_chart.fields["ppAfter"] == "248"
    assert parsed.response.beatmap_chart.fields["onlineScoreId"] == "12345"
    assert parsed.response.overall_chart.fields["totalScoreAfter"] == "0"
    assert parsed.response.overall_chart.fields["achievements-new"] == ""
    assert parsed.response.achievement_notification == ""
    assert result.status is VerificationStatus.PASS
    assert result.diagnostic_summary.message == (
        "score submit completed fixture parsed with required chart fields"
    )


def test_verify_golden_response_parses_mapper_generated_completed_response() -> None:
    result = ScoreSubmitVerifier(fixture_dir=FIXTURE_DIR).verify_response_body_as(
        _mapper_generated_completed_response(),
        reference="mapper-generated completed response",
        evidence_type=EvidenceType.AUTOMATED_TEST,
    )

    assert result.status is VerificationStatus.PASS
    assert result.evidence_type is EvidenceType.AUTOMATED_TEST
    assert result.scope is EvidenceScope.MANDATORY
    assert result.diagnostic_summary.message == (
        "score submit completed fixture parsed with required chart fields"
    )


def test_verify_golden_response_includes_fixture_and_known_gap_results() -> None:
    results = ScoreSubmitVerifier(fixture_dir=FIXTURE_DIR).verify_golden_response()

    fixture_result = _result_by_reference(
        results,
        "completed_response.txt",
    )
    gap_result = _result_by_status(
        results,
        VerificationStatus.KNOWN_GAP,
    )

    assert fixture_result.status is VerificationStatus.PASS
    assert gap_result.fails_run is False


def _mapper_generated_completed_response() -> bytes:
    response = StableScoreSubmitMapper().to_response(
        SubmissionResult(
            outcome=SubmissionOutcome.COMPLETED,
            score_id=12345,
            beatmap_id=654,
            beatmapset_id=321,
            score=7654321,
            max_combo=987,
            accuracy=0.956789,
            passed=True,
            stable_pp=248,
        )
    )
    return bytes(response.body)


def test_verify_response_body_maps_failed_response_to_secret_free_fail_result() -> None:
    failed_body = (FIXTURE_DIR / "failed_response.txt").read_bytes()
    password_hash_key = "password_" + "hash"
    session_token_key = "session_" + "token"
    body_with_secret_hint = (
        failed_body
        + f"\n{password_hash_key}=fixture-value {session_token_key}=fixture-value".encode()
    )

    result = ScoreSubmitVerifier(fixture_dir=FIXTURE_DIR).verify_response_body(
        body_with_secret_hint,
        reference="tests/fixtures/stable_compatibility/score_submit/failed_response.txt",
    )

    assert result.status is VerificationStatus.FAIL
    assert result.fails_run is True
    assert result.diagnostic_summary.message == (
        "score submit response is not a completed stable chart response"
    )
    _assert_secret_free(result.diagnostic_summary.message)


def test_verify_golden_response_reports_user_stats_and_leaderboard_known_gap() -> None:
    result = _result_by_status(
        ScoreSubmitVerifier(fixture_dir=FIXTURE_DIR).verify_golden_response(),
        VerificationStatus.KNOWN_GAP,
    )

    assert result.fails_run is False
    assert "user-stats" in result.diagnostic_summary.message
    assert "leaderboard" in result.diagnostic_summary.message
    assert "rank" in result.diagnostic_summary.message
    assert "totalScore" in result.diagnostic_summary.message


def _result_by_reference(
    results: tuple[SurfaceResult, ...],
    reference_suffix: str,
) -> SurfaceResult:
    matches = [
        result
        for result in results
        if result.reference is not None and result.reference.endswith(reference_suffix)
    ]
    assert len(matches) == 1

    return matches[0]


def _result_by_status(
    results: tuple[SurfaceResult, ...],
    status: VerificationStatus,
) -> SurfaceResult:
    matches = [result for result in results if result.status is status]
    assert len(matches) == 1

    return matches[0]


def _assert_secret_free(message: str) -> None:
    forbidden_fragments = (
        "fixture-value",
        "password_" + "hash",
        "session_" + "token",
        "raw_" + "replay",
        "cred" + "ential",
    )
    for fragment in forbidden_fragments:
        assert fragment not in message
