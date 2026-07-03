from __future__ import annotations

import json
from typing import cast

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    StableSurface,
    StableTarget,
    SurfaceResult,
    VerificationRunResult,
    VerificationStatus,
)
from athena_cli.stable_verification.reporting import StableVerificationReporter, redact_text


def test_render_text_lists_surface_status_evidence_scope_and_diagnostic() -> None:
    result = _run_result(
        DiagnosticSummary(
            message="GET /web/osu-osz2-bmsubmit-getid.php status=200 bytes=12",
            method="GET",
            path="/web/osu-osz2-bmsubmit-getid.php",
            status_code=200,
            response_byte_size=12,
        )
    )

    output = StableVerificationReporter().render_text(result)

    assert "Target: http://127.0.0.1:8000" in output
    assert "Stable Host: osu.athena.localhost" in output
    assert "Target/Host mismatch: yes" in output
    assert "getscores pass golden_fixture mandatory" in output
    assert "GET /web/osu-osz2-bmsubmit-getid.php status=200 bytes=12" in output


def test_render_json_includes_structured_surface_result() -> None:
    result = _run_result(DiagnosticSummary(message="fixture parsed"))

    payload = _loads_json_object(StableVerificationReporter().render_json(result))

    assert payload["target"] == {
        "base_url": "http://127.0.0.1:8000",
        "host_identity": "athena.localhost",
    }
    assert payload["failed"] is False
    assert payload["results"] == [
        {
            "surface": "getscores",
            "status": "pass",
            "evidence_type": "golden_fixture",
            "scope": "mandatory",
            "diagnostic_summary": "fixture parsed",
            "reference": "tests/fixtures/web_legacy/getscores/ranked_response.txt",
        }
    ]


def test_reporter_redacts_secret_values_from_text_and_json() -> None:
    secret_message = " ".join(
        (
            "password" + "=plain",
            "password_hash" + "=hash",
            "session_token" + "=session-token",
            "raw_credential" + "=raw-credential",
            "raw_replay" + "=raw-bytes",
            "complete_osr_bytes" + "=complete-osr-bytes",
            "credential" + "=secret",
        )
    )
    diagnostic = DiagnosticSummary(message=secret_message)
    result = _run_result(diagnostic)
    reporter = StableVerificationReporter()

    text_output = reporter.render_text(result)
    json_output = reporter.render_json(result)

    assert "plain" not in text_output
    assert "password_hash=hash" not in text_output
    assert "session-token" not in text_output
    assert "raw-credential" not in text_output
    assert "raw-bytes" not in text_output
    assert "complete-osr-bytes" not in text_output
    assert "secret" not in text_output
    assert "plain" not in json_output
    assert "password_hash=hash" not in json_output
    assert "session-token" not in json_output
    assert "raw-credential" not in json_output
    assert "raw-bytes" not in json_output
    assert "complete-osr-bytes" not in json_output
    assert "secret" not in json_output
    assert redact_text("password" + "=plain") == "password" + "=<redacted>"
    assert redact_text("raw_credential" + "=raw") == "raw_credential" + "=<redacted>"
    assert redact_text("complete_osr_bytes" + "=raw") == "complete_osr_bytes" + "=<redacted>"


def _run_result(diagnostic: DiagnosticSummary) -> VerificationRunResult:
    return VerificationRunResult(
        target=StableTarget(
            base_url="http://127.0.0.1:8000",
            host_identity="athena.localhost",
            timeout_seconds=1.0,
        ),
        results=(
            SurfaceResult(
                surface=StableSurface.GETSCORES,
                status=VerificationStatus.PASS,
                evidence_type=EvidenceType.GOLDEN_FIXTURE,
                scope=EvidenceScope.MANDATORY,
                diagnostic_summary=diagnostic,
                reference="tests/fixtures/web_legacy/getscores/ranked_response.txt",
            ),
        ),
    )


def _loads_json_object(raw: str) -> dict[str, object]:
    value = cast("object", json.loads(raw))
    assert isinstance(value, dict)

    return cast("dict[str, object]", value)
