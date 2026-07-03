from __future__ import annotations

from dataclasses import fields

from athena_cli.stable_verification import models
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
    assert StableSurface.REPLAY_DOWNLOAD.value == "replay_download"


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


def test_replay_download_evidence_models_share_verification_vocabulary() -> None:
    fixture = models.ReplayDownloadSanitizedFixture(
        target_client_family="osu_stable",
        target_build_observed=False,
        target_build=None,
        target_build_note="not observed in replay download request",
        osuver_observed=False,
        osuver=None,
        osuver_note="not observed in replay download request",
        user_agent="osu!",
        captured_at="2026-07-03T06:26:38Z",
        workflow_entrance="replay_download",
        method="GET",
        path="/web/osu-getreplay.php",
        query_keys=("c", "h", "m", "u"),
        auth_fields=(
            models.ReplayDownloadAuthField(
                name="h",
                category="redacted_auth_proof",
            ),
            models.ReplayDownloadAuthField(
                name="u",
                category="redacted_user_identity",
            ),
        ),
        response_status=200,
        response_header_keys_observed=("content-type", "content-length"),
        complete_response_header_key_set_observed=False,
        body_kind="lzma_compressed_replay_payload",
        body_byte_size=90584,
        safe_body_sha256=None,
        raw_values_committed=False,
    )
    branch = models.ReplayDownloadResponseBranchEvidence(
        branch=models.ReplayDownloadResponseBranch.SUCCESS,
        status=VerificationStatus.PASS,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=DiagnosticSummary(
            message="replay download success response metadata valid"
        ),
        response_status=200,
        response_header_keys_observed=("content-type", "content-length"),
        complete_response_header_key_set_observed=False,
        body_kind="lzma_compressed_replay_payload",
        body_byte_size=90584,
        safe_body_sha256=None,
        reference="tests/fixtures/stable_compatibility/replay_download/target_client_response_metadata.json",
    )
    body_decision = models.ReplayDownloadBodyDecision(
        blob_integrity=models.ReplayDownloadBlobIntegrity.UNAVAILABLE,
        target_body_compatible=models.ReplayDownloadBodyCompatibility.LOCAL_ONLY_UNVERIFIED,
        download_body_strategy=models.ReplayDownloadBodyStrategy.BLOCKED,
        status=VerificationStatus.KNOWN_GAP,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=DiagnosticSummary(
            message="body assembly decision blocked pending blob diagnostic"
        ),
        evidence_references=(
            "tests/fixtures/stable_compatibility/replay_download/body_assembly_decision.json",
        ),
    )
    blob_diagnostic = models.ReplayBlobDiagnosticResult(
        score_found=True,
        replay_attachment_found=True,
        blob_found=True,
        storage_object_found=True,
        metadata_sha256="metadata-sha256",
        observed_sha256="observed-sha256",
        metadata_byte_size=90584,
        observed_byte_size=90584,
        classification=models.ReplayBlobDiagnosticClassification.INTEGRITY_PASS,
        status=VerificationStatus.PASS,
        diagnostic_summary=DiagnosticSummary(message="replay blob integrity pass"),
    )

    assert fixture.surface is StableSurface.REPLAY_DOWNLOAD
    assert fixture.evidence_type is EvidenceType.GOLDEN_FIXTURE
    assert fixture.scope is EvidenceScope.MANDATORY
    assert fixture.raw_values_committed is False
    assert branch.surface is StableSurface.REPLAY_DOWNLOAD
    assert branch.branch is models.ReplayDownloadResponseBranch.SUCCESS
    assert body_decision.surface is StableSurface.REPLAY_DOWNLOAD
    assert body_decision.download_body_strategy is models.ReplayDownloadBodyStrategy.BLOCKED
    assert blob_diagnostic.surface is StableSurface.REPLAY_DOWNLOAD
    assert (
        blob_diagnostic.classification is models.ReplayBlobDiagnosticClassification.INTEGRITY_PASS
    )


def test_replay_download_reportable_models_exclude_secret_like_fields() -> None:
    forbidden_field_names = {
        "password",
        "password_hash",
        "session_token",
        "raw_credential",
        "raw_query_value",
        "raw_replay",
        "complete_osr_bytes",
    }
    reportable_model_types = (
        models.ReplayDownloadAuthField,
        models.ReplayDownloadSanitizedFixture,
        models.ReplayDownloadResponseBranchEvidence,
        models.ReplayDownloadBodyDecision,
        models.ReplayBlobDiagnosticResult,
    )

    for model_type in reportable_model_types:
        field_names = {field.name for field in fields(model_type)}

        assert field_names.isdisjoint(forbidden_field_names)
