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
    route_contract = bundle.target_route_contract
    fixture = bundle.fixtures["official_bancho_stable_replay_download_200"]
    reference_by_name = {reference.name: reference for reference in bundle.reference_responses}
    branch_by_name = {branch.branch: branch for branch in bundle.response_contract_branches}

    assert route_contract.primary_route == "/web/osu-getreplay.php"
    assert route_contract.primary_route_observed_in_target_client_traffic is True
    assert route_contract.primary_route_classification == "primary_target_client_route"
    assert route_contract.alias_route == "/web/replays/<id>"
    assert route_contract.alias_route_observed_in_target_client_traffic is False
    assert route_contract.alias_policy == "candidate_only_reference_backed"
    assert route_contract.route_evidence_fixture_names == (
        "local_athena_stable_replay_download_404",
        "official_bancho_stable_replay_download_200",
    )
    assert fixture.target_client_family == "osu_stable"
    assert fixture.target_build_observed is False
    assert fixture.target_build is None
    assert fixture.osuver_observed is False
    assert fixture.osuver is None
    assert fixture.route_classification == "primary_target_client_route"
    assert fixture.target_route_observed is True
    assert fixture.alias_routes_observed == ()
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
    assert reference_by_name["deck_missing_replay"].source == "deck"
    assert reference_by_name["deck_missing_replay"].branch == "missing_replay"
    assert reference_by_name["deck_missing_replay"].response_status == 404
    assert reference_by_name["deck_hidden_score"].branch == "hidden_score"
    assert reference_by_name["deck_storage_missing"].body_kind == "empty_http_exception"
    assert reference_by_name["lets_replay_alias_success"].route == "/web/replays/<id>"
    assert reference_by_name["lets_replay_alias_success"].body_kind == "complete_osr_file"
    assert reference_by_name["lets_replay_alias_success"].unresolved_reason is None
    assert reference_by_name["bancho_py_success"].unresolved_reason is not None
    assert branch_by_name["success"].readiness == "blocked"
    assert branch_by_name["success"].blocker == "body_assembly_decision_pending"
    assert branch_by_name["success"].selected_body_byte_size == 90584
    assert branch_by_name["success"].selected_safe_body_sha256 is None
    assert branch_by_name["auth_failure"].readiness == "implementation_ready"
    assert branch_by_name["missing_replay"].selected_response_status == 404
    assert branch_by_name["hidden_score"].selected_body_kind == "empty_http_exception"
    assert branch_by_name["storage_missing"].readiness == "implementation_ready"
    assert branch_by_name["malformed_score_id"].readiness == "unresolved"
    assert branch_by_name["malformed_mode"].status_label == "未確認"
    assert branch_by_name["unknown_field"].blocker == "no_target_or_reference_evidence"


def test_validate_replay_download_fixtures_accepts_metadata_only_fixtures() -> None:
    results = validate_replay_download_fixtures(load_replay_download_fixtures(FIXTURE_DIR))

    assert len(results) == 5
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
    _write_valid_reference_responses(fixture_dir)
    _write_valid_response_contract(fixture_dir)
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
    _write_valid_reference_responses(fixture_dir)
    _write_valid_response_contract(fixture_dir)
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


def test_validate_replay_download_fixtures_rejects_incomplete_route_contract(
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
            "target_route_contract": {
                "primary_route": "/web/osu-getreplay.php",
                "primary_route_observed_in_target_client_traffic": True,
                "alias_route": "/web/replays/<id>",
                "alias_route_observed_in_target_client_traffic": False,
            },
            "captures": [
                {
                    "name": "incomplete_route_capture",
                    "source": "unit_test",
                    "raw_artifact": "local-only",
                    "target_client_family": "osu_stable",
                    "target_build_observed": False,
                    "target_build": None,
                    "target_build_note": "not observed in replay download request",
                    "osuver_observed": False,
                    "osuver": None,
                    "osuver_note": "not observed in replay download request",
                    "captured_at": "2026-07-03T06:18:07Z",
                    "workflow_entrance": "replay_download",
                    "route_classification": "primary_target_client_route",
                    "target_route_observed": True,
                    "alias_routes_observed": [],
                    "method": "GET",
                    "path": "/web/osu-getreplay.php",
                    "query_keys": ["c", "h", "m", "u"],
                    "query_values_committed": False,
                    "auth_fields": [
                        {
                            "name": "h",
                            "category": "redacted_auth_proof",
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
                    "name": "incomplete_route_capture",
                    "method": "GET",
                    "path": "/web/osu-getreplay.php",
                    "response_status": 404,
                    "response_header_keys_observed": ["content-length"],
                    "complete_response_header_key_set_observed": False,
                    "body_kind": "plain_text_not_found",
                    "body_byte_size": 9,
                    "safe_body_sha256": None,
                }
            ],
        },
    )
    _write_valid_reference_responses(fixture_dir)
    _write_valid_response_contract(fixture_dir)
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
                "observed_success_body_source": "incomplete_route_capture",
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

    assert "route_contract_missing_required_fields:3" in failure_messages
    assert "route_contract_evidence_fixture_names_must_be_string_list" in failure_messages


def _write_valid_reference_responses(fixture_dir: Path) -> None:
    _write_json(
        fixture_dir / "reference_responses.json",
        {
            "schema": "athena.stable_compatibility.replay_download.reference_responses.v1",
            "secret_policy": "metadata-only",
            "raw_artifact_committed": False,
            "references": [
                {
                    "name": "unit_reference_success",
                    "source": "bancho.py",
                    "source_role": "stable_baseline_comparison",
                    "repository": "osuAkatsuki/bancho.py",
                    "commit": "358d23a0d906ee08de96bafd9ca207071b061b43",
                    "source_paths": ["app/api/domains/osu.py"],
                    "branch": "success",
                    "route": "/web/osu-getreplay.php",
                    "method": "GET",
                    "request_keys": ["c", "h", "m", "u"],
                    "auth_fields": [
                        {
                            "name": "h",
                            "category": "redacted_auth_proof",
                            "value_committed": False,
                        }
                    ],
                    "response_status": 200,
                    "response_header_keys_observed": [],
                    "complete_response_header_key_set_observed": False,
                    "body_kind": "file_response_osr_path",
                    "contract_status": "reference_only_unresolved",
                    "unresolved_reason": "runtime headers were not captured",
                }
            ],
        },
    )


def _write_valid_response_contract(fixture_dir: Path) -> None:
    _write_json(
        fixture_dir / "response_contract.json",
        {
            "schema": "athena.stable_compatibility.replay_download.response_contract.v1",
            "secret_policy": "metadata-only",
            "raw_artifact_committed": False,
            "branches": [
                {
                    "branch": "success",
                    "status_label": "未確認",
                    "readiness": "blocked",
                    "selected_response_status": 200,
                    "selected_header_keys": ["content-type"],
                    "selected_body_kind": "lzma_compressed_replay_payload",
                    "selected_body_byte_size": 90584,
                    "selected_safe_body_sha256": None,
                    "evidence_sources": ["unit_reference_success"],
                    "blocker": "body_assembly_decision_pending",
                    "notes": ["unit fixture"],
                }
            ],
        },
    )


def _write_json(path: Path, document: object) -> None:
    _ = path.write_text(json.dumps(document), encoding="utf-8")
