from __future__ import annotations

import json
from pathlib import Path

from athena_cli.stable_verification.models import (
    StableSurface,
    VerificationStatus,
)
from athena_cli.stable_verification.replay_download import (
    load_replay_download_fixtures,
    validate_replay_download_fixtures,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[4]
    / "tests"
    / "fixtures"
    / "stable_compatibility"
    / "replay_download"
)


def test_load_replay_download_fixtures_preserves_sanitized_contract_fields() -> None:
    bundle = load_replay_download_fixtures(FIXTURE_DIR)
    fixture = bundle.fixtures["official_bancho_stable_replay_download_200"]

    assert fixture.target_client_family == "osu_stable"
    assert fixture.target_build_observed is False
    assert fixture.target_build is None
    assert fixture.osuver_observed is False
    assert fixture.osuver is None
    assert fixture.method == "GET"
    assert fixture.path == "/web/osu-getreplay.php"
    assert fixture.query_keys == ("c", "h", "m", "u")
    assert tuple(auth_field.category for auth_field in fixture.auth_fields) == (
        "redacted_auth_proof",
        "redacted_user_identity",
    )
    assert fixture.response_status == 200
    assert fixture.response_header_keys_observed == (
        "connection",
        "content-disposition",
        "content-length",
        "content-type",
        "date",
        "server",
    )
    assert fixture.body_kind == "lzma_compressed_replay_payload"
    assert fixture.safe_body_sha256 is None
    assert fixture.body_byte_size == 90584


def test_validate_replay_download_fixtures_accepts_metadata_only_fixtures() -> None:
    results = validate_replay_download_fixtures(load_replay_download_fixtures(FIXTURE_DIR))

    assert len(results) == 3
    assert {result.surface for result in results} == {StableSurface.REPLAY_DOWNLOAD}
    assert {result.status for result in results} == {VerificationStatus.PASS}
    assert all(result.fails_run is False for result in results)
    assert all(result.reference is not None for result in results)


def test_validate_replay_download_fixtures_rejects_secret_containing_fixtures(
    tmp_path: Path,
) -> None:
    fixture_dir = tmp_path / "replay_download"
    fixture_dir.mkdir()
    _write_json(
        fixture_dir / "target_client_request_metadata.json",
        {
            "schema": (
                "athena.stable_compatibility.replay_download.target_client_request_metadata.v1"
            ),
            "secret_policy": "metadata-only",
            "raw_artifact_committed": True,
            "captures": [
                {
                    "name": "secret_capture",
                    "target_client_family": "osu_stable",
                    "target_build_observed": False,
                    "target_build": None,
                    "target_build_note": "not observed",
                    "osuver_observed": False,
                    "osuver": None,
                    "osuver_note": "not observed",
                    "captured_at": "2026-07-03T06:18:07Z",
                    "workflow_entrance": "replay_download",
                    "method": "GET",
                    "path": "/web/osu-getreplay.php",
                    "query_keys": ["h", "u"],
                    "query_values": {"h": "raw-query-value"},
                    "query_values_committed": True,
                    "auth_fields": [
                        {
                            "name": "h",
                            "category": "redacted_auth_proof",
                            "value": "super-secret-password",
                            "value_committed": True,
                        }
                    ],
                    "request_header_keys_observed": ["host"],
                    "user_agent": "osu!",
                    "session_token": "super-secret-token",
                }
            ],
        },
    )
    _write_json(
        fixture_dir / "target_client_response_metadata.json",
        {
            "schema": (
                "athena.stable_compatibility.replay_download.target_client_response_metadata.v1"
            ),
            "secret_policy": "metadata-only",
            "raw_artifact_committed": False,
            "captures": [
                {
                    "name": "secret_capture",
                    "method": "GET",
                    "path": "/web/osu-getreplay.php",
                    "response_status": 200,
                    "response_header_keys_observed": ["content-length"],
                    "complete_response_header_key_set_observed": False,
                    "body_kind": "lzma_compressed_replay_payload",
                    "body_byte_size": 8,
                    "safe_body_sha256": None,
                    "raw_replay_bytes": "raw-replay-bytes",
                    "complete_osr_bytes": "complete-osr-bytes",
                    "har_archive": {"log": {"entries": list[object]()}},
                }
            ],
        },
    )
    _write_json(
        fixture_dir / "body_assembly_decision.json",
        {
            "schema": ("athena.stable_compatibility.replay_download.body_assembly_decision.v1"),
            "secret_policy": "metadata-only",
            "raw_artifact_committed": False,
            "decision": {
                "status": "blocked_pending_blob_diagnostic",
                "download_body_strategy": "blocked",
                "observed_success_body_kind": "lzma_compressed_replay_payload",
                "observed_success_body_source": "secret_capture",
                "observed_success_body_is_complete_osr": False,
                "observed_success_body_is_zip_archive": False,
                "stored_blob_integrity": "not_checked",
                "stored_blob_target_body_compatible": "not_checked",
                "raw_body_bytes": "raw-replay-bytes",
            },
        },
    )

    results = validate_replay_download_fixtures(load_replay_download_fixtures(fixture_dir))
    failure_messages = "\n".join(
        result.diagnostic_summary.message
        for result in results
        if result.status is VerificationStatus.FAIL
    )

    assert failure_messages
    assert "redaction policy failed" in failure_messages
    assert "raw-query-value" not in failure_messages
    assert "super-secret-password" not in failure_messages
    assert "super-secret-token" not in failure_messages
    assert "raw-replay-bytes" not in failure_messages
    assert "complete-osr-bytes" not in failure_messages


def test_validate_replay_download_fixtures_rejects_raw_values_in_expected_fields(
    tmp_path: Path,
) -> None:
    fixture_dir = tmp_path / "replay_download"
    fixture_dir.mkdir()
    _write_json(
        fixture_dir / "target_client_request_metadata.json",
        {
            "schema": (
                "athena.stable_compatibility.replay_download.target_client_request_metadata.v1"
            ),
            "secret_policy": "metadata-only",
            "raw_artifact_committed": False,
            "captures": [
                {
                    "name": "bad_capture",
                    "target_client_family": "osu_stable",
                    "target_build_observed": False,
                    "target_build": None,
                    "target_build_note": "not observed",
                    "osuver_observed": False,
                    "osuver": None,
                    "osuver_note": "not observed",
                    "captured_at": "2026-07-03T06:18:07Z",
                    "workflow_entrance": "replay_download",
                    "method": "GET",
                    "path": "/web/osu-getreplay.php",
                    "query_keys": "c=1&h=raw-query-value",
                    "auth_fields": [
                        {
                            "name": "h=raw-auth-value",
                            "category": "redacted_auth_proof:raw",
                            "value_committed": False,
                        }
                    ],
                    "request_header_keys_observed": ["host"],
                    "user_agent": "osu!",
                }
            ],
        },
    )
    _write_json(
        fixture_dir / "target_client_response_metadata.json",
        {
            "schema": (
                "athena.stable_compatibility.replay_download.target_client_response_metadata.v1"
            ),
            "secret_policy": "metadata-only",
            "raw_artifact_committed": False,
            "captures": [
                {
                    "name": "bad_capture",
                    "method": "GET",
                    "path": "/web/osu-getreplay.php",
                    "response_status": 200,
                    "response_header_keys_observed": "content-type: zip",
                    "complete_response_header_key_set_observed": False,
                    "body_kind": "lzma_compressed_replay_payload",
                    "body_byte_size": 8,
                    "safe_body_sha256": None,
                }
            ],
        },
    )
    _write_json(
        fixture_dir / "body_assembly_decision.json",
        {
            "schema": ("athena.stable_compatibility.replay_download.body_assembly_decision.v1"),
            "secret_policy": "metadata-only",
            "raw_artifact_committed": False,
            "decision": {
                "status": "blocked_pending_blob_diagnostic",
                "download_body_strategy": "blocked",
                "observed_success_body_kind": "lzma_compressed_replay_payload",
                "observed_success_body_source": "bad_capture",
                "observed_success_body_is_complete_osr": False,
                "observed_success_body_is_zip_archive": False,
                "stored_blob_integrity": "not_checked",
                "stored_blob_target_body_compatible": "not_checked",
            },
        },
    )

    results = validate_replay_download_fixtures(load_replay_download_fixtures(fixture_dir))
    failure_messages = "\n".join(
        result.diagnostic_summary.message
        for result in results
        if result.status is VerificationStatus.FAIL
    )

    assert failure_messages
    assert "query_keys_must_be_string_list" in failure_messages
    assert "auth_field_name_must_be_safe_token" in failure_messages
    assert "auth_field_category_must_be_safe_token" in failure_messages
    assert "response_header_keys_observed_must_be_string_list" in failure_messages
    assert "raw-query-value" not in failure_messages
    assert "raw-auth-value" not in failure_messages
    assert "redacted_auth_proof:raw" not in failure_messages
    assert "content-type: zip" not in failure_messages


def _write_json(path: Path, document: object) -> None:
    _ = path.write_text(json.dumps(document), encoding="utf-8")
