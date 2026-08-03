"""Stable replay downloadのfixture, evidence, diagnostic contractを検証する."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from athena_cli.stable_verification import replay_download
from athena_cli.stable_verification.models import (
    ReplayBlobAttachmentRecord,
    ReplayBlobDiagnosticClassification,
    ReplayBlobDiagnosticInput,
    ReplayBlobMetadataRecord,
    ReplayDownloadBlobIntegrity,
    ReplayDownloadBodyCompatibility,
    ReplayDownloadBodyStrategy,
    StableSurface,
    VerificationStatus,
)
from athena_cli.stable_verification.replay_download import (
    build_replay_download_body_decision,
    diagnose_replay_blob,
    load_replay_download_fixtures,
    validate_replay_download_fixtures,
)

PROJECT_ROOT = Path(__file__).resolve().parents[6]
FIXTURE_DIR = (
    PROJECT_ROOT
    / "apps"
    / "athena_server"
    / "tests"
    / "fixtures"
    / "stable_compatibility"
    / "replay_download"
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def test_load_replay_download_fixtures_preserves_sanitized_contract_fields() -> None:
    """metadata-only fixtureがroute, body, reference evidenceを安全に保持することを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: route, response, reference evidence, またはbody decision fieldが
            変化した場合.
    """
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
    assert branch_by_name["success"].readiness == "implementation_ready"
    assert branch_by_name["success"].blocker is None
    assert branch_by_name["success"].selected_body_byte_size == 90584
    assert branch_by_name["success"].selected_safe_body_sha256 is None
    assert branch_by_name["auth_failure"].readiness == "implementation_ready"
    assert branch_by_name["hidden_score"].selected_body_kind == "empty_http_exception"
    assert branch_by_name["storage_missing"].readiness == "implementation_ready"
    assert branch_by_name["malformed_score_id"].readiness == "unresolved"
    assert branch_by_name["malformed_mode"].status_label == "unconfirmed"
    assert branch_by_name["unknown_field"].blocker == "no_target_or_reference_evidence"


def test_replay_download_public_exports_include_diagnostic_helpers() -> None:
    """Replay download moduleがbody decisionとblob diagnostic helperを公開することを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: diagnostic helperがreplay_download.__all__から欠落した場合.
    """
    assert "build_replay_download_body_decision" in replay_download.__all__
    assert "diagnose_replay_blob" in replay_download.__all__


def test_load_replay_download_fixtures_keeps_missing_replay_unresolved() -> None:
    """Conflicting referenceを持つmissing replay branchがunresolvedのまま残ることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: missing replay branchのreadiness, selected response, またはblockerが
            変化した場合.
    """
    bundle = load_replay_download_fixtures(FIXTURE_DIR)
    branch_by_name = {branch.branch: branch for branch in bundle.response_contract_branches}
    missing_replay = branch_by_name["missing_replay"]

    assert missing_replay.readiness == "unresolved"
    assert missing_replay.selected_response_status is None
    assert missing_replay.selected_body_kind is None
    assert missing_replay.blocker == "conflicting_reference_evidence"
    assert "reference_responses:lets_primary_missing_replay" in missing_replay.evidence_sources


def test_load_replay_download_fixtures_preserves_body_decision_contract() -> None:
    """fixtureのbody decisionがdirect blob成功のevidence contractを保つことを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: body integrity, target compatibility, strategy, またはevidence referenceが
            変化した場合.
    """
    bundle = load_replay_download_fixtures(FIXTURE_DIR)
    body_decision = bundle.body_decision

    assert body_decision.blob_integrity is ReplayDownloadBlobIntegrity.PASS
    assert body_decision.target_body_compatible is ReplayDownloadBodyCompatibility.PASS
    assert body_decision.download_body_strategy is ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES
    assert body_decision.status is VerificationStatus.PASS
    assert body_decision.evidence_references == (
        "target_client_response_metadata:official_bancho_stable_replay_download_200",
        "local_capture:athena_replay_download_score_6_404_after_route",
        "local_diagnostic:score_6_replay_blob_lzma_alone_pass",
        "research:Replay Blob Diagnostic Procedure",
    )
    assert body_decision.success_response_allowed is True


def test_replay_download_body_decision_allows_success_only_after_safe_strategy() -> None:
    """Body decisionが互換性evidenceに応じたsuccess許可だけを返すことを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: direct, assembly, blocked decisionのstrategyまたはsuccess許可が
            変化した場合.
    """
    direct_decision = build_replay_download_body_decision(
        blob_integrity=ReplayDownloadBlobIntegrity.PASS,
        target_body_compatible=ReplayDownloadBodyCompatibility.PASS,
        evidence_references=("unit:target_body_parser_pass",),
    )
    assembly_decision = build_replay_download_body_decision(
        blob_integrity=ReplayDownloadBlobIntegrity.PASS,
        target_body_compatible=ReplayDownloadBodyCompatibility.FAIL,
        evidence_references=("unit:target_body_parser_failure",),
    )
    blocked_decision = build_replay_download_body_decision(
        blob_integrity=ReplayDownloadBlobIntegrity.UNAVAILABLE,
        target_body_compatible=ReplayDownloadBodyCompatibility.LOCAL_ONLY_UNVERIFIED,
        evidence_references=("unit:local_artifact_not_committed",),
    )

    assert direct_decision.download_body_strategy is ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES
    assert direct_decision.success_response_allowed is True
    assert (
        assembly_decision.download_body_strategy
        is ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY
    )
    assert assembly_decision.success_response_allowed is True
    assert blocked_decision.download_body_strategy is ReplayDownloadBodyStrategy.BLOCKED
    assert blocked_decision.success_response_allowed is False


def test_replay_download_docs_and_matrix_share_current_evidence_terms() -> None:
    """guideとmatrixが現在のreplay evidence用語を共通して記載することを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: guideまたはmatrixから必須evidence用語が欠落した場合.
    """
    server_docs = PROJECT_ROOT / "apps" / "athena_server" / "docs"
    guide = (server_docs / "stable-compatibility-guide.md").read_text(encoding="utf-8")
    matrix = (server_docs / "stable-compatibility-matrix.md").read_text(encoding="utf-8")
    required_terms = (
        "primary_target_client_route",
        "candidate_only_reference_backed",
        "local_diagnostic:score_6_replay_blob_lzma_alone_pass",
        "download_body_strategy=direct_blob_bytes",
    )

    assert all(term in guide for term in required_terms)
    assert all(term in matrix for term in required_terms)


def test_replay_download_docs_define_issue_36_and_37_handoff_boundary() -> None:
    """guideがIssue #36と#37のreplay download handoff境界を記載することを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: guideからIssue #36/#37のhandoff用語またはroute contractが欠落した場合.
    """
    guide = (
        PROJECT_ROOT / "apps" / "athena_server" / "docs" / "stable-compatibility-guide.md"
    ).read_text(encoding="utf-8")
    required_terms = (
        "Issue #36 handoff",
        "Issue #37 boundary",
        "GET /web/osu-getreplay.php",
        "Query keys `c`, `h`, `m`, `u`",
        "local_diagnostic:score_6_replay_blob_lzma_alone_pass",
        "no_target_or_reference_evidence",
        "apps/athena_server/tests/fixtures/stable_compatibility/replay_download/response_contract.json",
        "apps/athena_server/tests/fixtures/stable_compatibility/replay_download/body_assembly_decision.json",
        "download_body_strategy=direct_blob_bytes",
        "assemble_download_body",
        "view count and latest activity are not #36 readiness criteria",
        "response bytes, status, or headers",
    )

    assert all(term in guide for term in required_terms)


def test_validate_replay_download_fixtures_accepts_metadata_only_fixtures() -> None:
    """Committed metadata-only fixtureが全てpass evidenceとして検証されることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: metadata-only fixtureがpass evidenceとして受理されない場合.
    """
    results = validate_replay_download_fixtures(load_replay_download_fixtures(FIXTURE_DIR))

    assert len(results) == 5
    assert {result.surface for result in results} == {StableSurface.REPLAY_DOWNLOAD}
    assert {result.status for result in results} == {VerificationStatus.PASS}
    assert all(result.fails_run is False for result in results)
    assert all(result.reference is not None for result in results)


def test_validate_replay_download_fixtures_rejects_secret_containing_fixtures(
    tmp_path: Path,
) -> None:
    """secret値を含むfixtureが値を漏らさずvalidation failureになることを検証する.

    Args:
        tmp_path (Path): 隔離したfixture directoryを作るpytest temporary path.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: secret値を含むfixtureがfailureにならないか値をdiagnosticへ漏らす場合.
    """
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
                "status": "known_gap",
                "download_body_strategy": "blocked",
                "blocker": "target_body_validation_requires_local_raw_blob_artifact",
                "observed_success_body_kind": "lzma_compressed_replay_payload",
                "observed_success_body_source": "secret_capture",
                "observed_success_body_is_complete_osr": False,
                "observed_success_body_is_zip_archive": False,
                "stored_blob_integrity": "unavailable",
                "stored_blob_target_body_compatible": "local_only_unverified",
                "body_format_classification": "unverified",
                "local_artifact_policy": "raw_blob_and_parser_result_not_committed",
                "diagnostic_outcome": "procedure_available_no_target_score_dry_run_committed",
                "evidence_references": ["unit:secret_capture"],
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
    """raw値または不正field型のfixtureが安全なvalidation failureになることを検証する.

    Args:
        tmp_path (Path): 隔離したfixture directoryを作るpytest temporary path.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: raw field値がfailureにならないか安全なvalidation codeが欠落する場合.
    """
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
                "status": "known_gap",
                "download_body_strategy": "blocked",
                "blocker": "target_body_validation_requires_local_raw_blob_artifact",
                "observed_success_body_kind": "lzma_compressed_replay_payload",
                "observed_success_body_source": "bad_capture",
                "observed_success_body_is_complete_osr": False,
                "observed_success_body_is_zip_archive": False,
                "stored_blob_integrity": "unavailable",
                "stored_blob_target_body_compatible": "local_only_unverified",
                "body_format_classification": "unverified",
                "local_artifact_policy": "raw_blob_and_parser_result_not_committed",
                "diagnostic_outcome": "procedure_available_no_target_score_dry_run_committed",
                "evidence_references": ["unit:bad_capture"],
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


def test_validate_replay_download_fixtures_rejects_committed_body_digests(
    tmp_path: Path,
) -> None:
    """Committed replay body digestが値を漏らさずvalidation failureになることを検証する.

    Args:
        tmp_path (Path): copyしたfixtureを変更するpytest temporary path.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: committed digestがfailureにならないかdigest値をdiagnosticへ漏らす場合.
    """
    fixture_dir = tmp_path / "replay_download"
    _ = shutil.copytree(FIXTURE_DIR, fixture_dir)

    response_metadata = _read_json_object(fixture_dir / "target_client_response_metadata.json")
    first_capture = _first_json_mapping(response_metadata["captures"])
    first_capture["safe_body_sha256"] = "f" * 64
    _write_json(fixture_dir / "target_client_response_metadata.json", response_metadata)

    response_contract = _read_json_object(fixture_dir / "response_contract.json")
    first_branch = _first_json_mapping(response_contract["branches"])
    first_branch["selected_safe_body_sha256"] = "e" * 64
    _write_json(fixture_dir / "response_contract.json", response_contract)

    results = validate_replay_download_fixtures(load_replay_download_fixtures(fixture_dir))
    failure_messages = "\n".join(
        result.diagnostic_summary.message
        for result in results
        if result.status is VerificationStatus.FAIL
    )

    assert "committed_safe_body_sha256" in failure_messages
    assert "committed_selected_safe_body_sha256" in failure_messages
    assert "f" * 64 not in failure_messages
    assert "e" * 64 not in failure_messages


def test_validate_replay_download_fixtures_rejects_incomplete_route_contract(
    tmp_path: Path,
) -> None:
    """必須fieldを欠くtarget route contractがvalidation failureになることを検証する.

    Args:
        tmp_path (Path): 不完全なfixture directoryを作るpytest temporary path.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: required route contract field不足がfailureとして報告されない場合.
    """
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
                "status": "known_gap",
                "download_body_strategy": "blocked",
                "blocker": "target_body_validation_requires_local_raw_blob_artifact",
                "observed_success_body_kind": "lzma_compressed_replay_payload",
                "observed_success_body_source": "incomplete_route_capture",
                "observed_success_body_is_complete_osr": False,
                "observed_success_body_is_zip_archive": False,
                "stored_blob_integrity": "unavailable",
                "stored_blob_target_body_compatible": "local_only_unverified",
                "body_format_classification": "unverified",
                "local_artifact_policy": "raw_blob_and_parser_result_not_committed",
                "diagnostic_outcome": "procedure_available_no_target_score_dry_run_committed",
                "evidence_references": ["unit:incomplete_route_capture"],
            },
        },
    )

    results = validate_replay_download_fixtures(load_replay_download_fixtures(fixture_dir))
    failure_messages = "\n".join(
        result.diagnostic_summary.message
        for result in results
        if result.status is VerificationStatus.FAIL
    )

    assert (
        "route_contract_missing_required_fields:"
        "alias_policy,primary_route_classification,route_evidence_source"
    ) in failure_messages
    assert "route_contract_evidence_fixture_names_must_be_string_list" in failure_messages


def test_build_replay_download_body_decision_requires_assembly_on_format_mismatch() -> None:
    """Target body format不一致でassembly strategyが選択されることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: format mismatchでassembly strategyまたはpass statusが選択されない場合.
    """
    decision = build_replay_download_body_decision(
        blob_integrity=ReplayDownloadBlobIntegrity.PASS,
        target_body_compatible=ReplayDownloadBodyCompatibility.FAIL,
        evidence_references=("unit:target_body_parser_failure",),
    )

    assert decision.blob_integrity is ReplayDownloadBlobIntegrity.PASS
    assert decision.target_body_compatible is ReplayDownloadBodyCompatibility.FAIL
    assert decision.download_body_strategy is ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY
    assert decision.status is VerificationStatus.PASS
    assert decision.evidence_references == ("unit:target_body_parser_failure",)
    assert "download_body_format_mismatch" in decision.diagnostic_summary.message


def test_build_replay_download_body_decision_blocks_when_local_only_unverified() -> None:
    """local-only evidenceではsuccess body decisionがblockedになることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: local-only evidenceがblocked strategyとknown gapにならない場合.
    """
    decision = build_replay_download_body_decision(
        blob_integrity=ReplayDownloadBlobIntegrity.UNAVAILABLE,
        target_body_compatible=ReplayDownloadBodyCompatibility.LOCAL_ONLY_UNVERIFIED,
        evidence_references=("unit:local_artifact_not_committed",),
    )

    assert decision.download_body_strategy is ReplayDownloadBodyStrategy.BLOCKED
    assert decision.status is VerificationStatus.KNOWN_GAP
    assert "body_decision_blocked" in decision.diagnostic_summary.message


@pytest.mark.asyncio
async def test_diagnose_replay_blob_reports_integrity_pass_without_raw_bytes() -> None:
    """正常blob diagnosticがraw bytesを露出せずintegrity passを返すことを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: integrity passのmetadataまたはraw payload redactionが変化した場合.
    """
    replay_body = b"synthetic replay payload password=secret-value"
    digest = hashlib.sha256(replay_body).hexdigest()

    result = await diagnose_replay_blob(
        ReplayBlobDiagnosticInput(score_id=42),
        score_lookup=_ScoreLookup(score_ids=frozenset((42,))),
        replay_attachment_lookup=_ReplayAttachmentLookup(
            attachments={
                42: ReplayBlobAttachmentRecord(score_id=42, blob_id=7),
            }
        ),
        blob_metadata_lookup=_BlobMetadataLookup(
            blobs={
                7: ReplayBlobMetadataRecord(
                    blob_id=7,
                    sha256=digest,
                    byte_size=len(replay_body),
                    storage_key="sha256/example",
                ),
            }
        ),
        blob_object_reader=_BlobObjectReader(objects={"sha256/example": replay_body}),
    )

    assert result.score_found is True
    assert result.replay_attachment_found is True
    assert result.blob_found is True
    assert result.storage_object_found is True
    assert result.metadata_sha256 == digest
    assert result.observed_sha256 == digest
    assert result.metadata_byte_size == len(replay_body)
    assert result.observed_byte_size == len(replay_body)
    assert result.classification is ReplayBlobDiagnosticClassification.INTEGRITY_PASS
    assert result.status is VerificationStatus.PASS
    assert "synthetic replay payload" not in repr(result)
    assert "secret-value" not in result.diagnostic_summary.message


@pytest.mark.asyncio
async def test_diagnose_replay_blob_distinguishes_missing_score() -> None:
    """score未検出がMISSING_SCORE unavailable診断になることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: score未検出時のfield値, classification, またはstatusが変化した場合.
    """
    result = await diagnose_replay_blob(
        ReplayBlobDiagnosticInput(score_id=404),
        score_lookup=_ScoreLookup(score_ids=frozenset()),
        replay_attachment_lookup=_ReplayAttachmentLookup(),
        blob_metadata_lookup=_BlobMetadataLookup(),
        blob_object_reader=_BlobObjectReader(),
    )

    assert result.score_found is False
    assert result.replay_attachment_found is False
    assert result.blob_found is False
    assert result.storage_object_found is False
    assert result.classification is ReplayBlobDiagnosticClassification.MISSING_SCORE
    assert result.status is VerificationStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_diagnose_replay_blob_distinguishes_missing_replay_attachment() -> None:
    """Replay attachment未検出がMISSING_REPLAY unavailable診断になることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: replay attachment未検出時のclassificationまたはstatusが変化した場合.
    """
    result = await diagnose_replay_blob(
        ReplayBlobDiagnosticInput(score_id=42),
        score_lookup=_ScoreLookup(score_ids=frozenset((42,))),
        replay_attachment_lookup=_ReplayAttachmentLookup(),
        blob_metadata_lookup=_BlobMetadataLookup(),
        blob_object_reader=_BlobObjectReader(),
    )

    assert result.score_found is True
    assert result.replay_attachment_found is False
    assert result.classification is ReplayBlobDiagnosticClassification.MISSING_REPLAY
    assert result.status is VerificationStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_diagnose_replay_blob_distinguishes_missing_blob_metadata() -> None:
    """Blob metadata未検出がMISSING_BLOB_METADATA unavailable診断になることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: blob metadata未検出時のclassificationまたはstatusが変化した場合.
    """
    result = await diagnose_replay_blob(
        ReplayBlobDiagnosticInput(score_id=42),
        score_lookup=_ScoreLookup(score_ids=frozenset((42,))),
        replay_attachment_lookup=_ReplayAttachmentLookup(
            attachments={
                42: ReplayBlobAttachmentRecord(score_id=42, blob_id=7),
            }
        ),
        blob_metadata_lookup=_BlobMetadataLookup(),
        blob_object_reader=_BlobObjectReader(),
    )

    assert result.replay_attachment_found is True
    assert result.blob_found is False
    assert result.classification is ReplayBlobDiagnosticClassification.MISSING_BLOB_METADATA
    assert result.status is VerificationStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_diagnose_replay_blob_distinguishes_missing_storage_object() -> None:
    """Storage object未検出がMISSING_STORAGE_OBJECT unavailable診断になることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: storage object未検出時のmetadata, classification, またはstatusが
            変化した場合.
    """
    result = await diagnose_replay_blob(
        ReplayBlobDiagnosticInput(score_id=42),
        score_lookup=_ScoreLookup(score_ids=frozenset((42,))),
        replay_attachment_lookup=_ReplayAttachmentLookup(
            attachments={
                42: ReplayBlobAttachmentRecord(score_id=42, blob_id=7),
            }
        ),
        blob_metadata_lookup=_BlobMetadataLookup(
            blobs={
                7: ReplayBlobMetadataRecord(
                    blob_id=7,
                    sha256="a" * 64,
                    byte_size=12,
                    storage_key="sha256/missing",
                ),
            }
        ),
        blob_object_reader=_BlobObjectReader(),
    )

    assert result.blob_found is True
    assert result.storage_object_found is False
    assert result.metadata_sha256 == "a" * 64
    assert result.observed_sha256 is None
    assert result.metadata_byte_size == 12
    assert result.observed_byte_size is None
    assert result.classification is ReplayBlobDiagnosticClassification.MISSING_STORAGE_OBJECT
    assert result.status is VerificationStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_diagnose_replay_blob_treats_storage_read_error_as_missing_object() -> None:
    """Storage read errorがstorage keyを漏らさずmissing object扱いになることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: read errorのmissing-object分類またはstorage key redactionが変化した場合.
    """
    result = await diagnose_replay_blob(
        ReplayBlobDiagnosticInput(score_id=42),
        score_lookup=_ScoreLookup(score_ids=frozenset((42,))),
        replay_attachment_lookup=_ReplayAttachmentLookup(
            attachments={
                42: ReplayBlobAttachmentRecord(score_id=42, blob_id=7),
            }
        ),
        blob_metadata_lookup=_BlobMetadataLookup(
            blobs={
                7: ReplayBlobMetadataRecord(
                    blob_id=7,
                    sha256="a" * 64,
                    byte_size=12,
                    storage_key="sha256/read-error",
                ),
            }
        ),
        blob_object_reader=_BlobObjectReader(
            objects={"sha256/read-error": b"stored replay payload"},
            read_failures=frozenset(("sha256/read-error",)),
        ),
    )

    assert result.storage_object_found is False
    assert result.observed_sha256 is None
    assert result.observed_byte_size is None
    assert result.classification is ReplayBlobDiagnosticClassification.MISSING_STORAGE_OBJECT
    assert "sha256/read-error" not in result.diagnostic_summary.message


@pytest.mark.asyncio
async def test_diagnose_replay_blob_distinguishes_hash_or_size_mismatch() -> None:
    """hashまたはbyte size不一致がSTORAGE_INTEGRITY_FAILUREになることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: hash/size mismatchのclassificationまたはstatusが変化した場合.
    """
    stored_body = b"stored replay payload"

    result = await diagnose_replay_blob(
        ReplayBlobDiagnosticInput(score_id=42),
        score_lookup=_ScoreLookup(score_ids=frozenset((42,))),
        replay_attachment_lookup=_ReplayAttachmentLookup(
            attachments={
                42: ReplayBlobAttachmentRecord(score_id=42, blob_id=7),
            }
        ),
        blob_metadata_lookup=_BlobMetadataLookup(
            blobs={
                7: ReplayBlobMetadataRecord(
                    blob_id=7,
                    sha256="b" * 64,
                    byte_size=len(stored_body) + 1,
                    storage_key="sha256/mismatch",
                ),
            }
        ),
        blob_object_reader=_BlobObjectReader(objects={"sha256/mismatch": stored_body}),
    )

    assert result.storage_object_found is True
    assert result.observed_sha256 == hashlib.sha256(stored_body).hexdigest()
    assert result.observed_byte_size == len(stored_body)
    assert result.classification is ReplayBlobDiagnosticClassification.STORAGE_INTEGRITY_FAILURE
    assert result.status is VerificationStatus.FAIL


def _write_valid_reference_responses(fixture_dir: Path) -> None:
    """Fixture validationに必要な最小reference_responses.jsonを書き出す.

    Args:
        fixture_dir (Path): JSON fixtureを配置するdirectory.

    Returns:
        None: reference response documentを書き出して値を返さずに完了する.

    Raises:
        OSError: fixture directoryまたはfileへ書き込めない場合.
    """
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
    """Fixture validationに必要な最小response_contract.jsonを書き出す.

    Args:
        fixture_dir (Path): JSON fixtureを配置するdirectory.

    Returns:
        None: response contract documentを書き出して値を返さずに完了する.

    Raises:
        OSError: fixture directoryまたはfileへ書き込めない場合.
    """
    _write_json(
        fixture_dir / "response_contract.json",
        {
            "schema": "athena.stable_compatibility.replay_download.response_contract.v1",
            "secret_policy": "metadata-only",
            "raw_artifact_committed": False,
            "branches": [
                {
                    "branch": "success",
                    "status_label": "unconfirmed",
                    "readiness": "blocked",
                    "selected_response_status": 200,
                    "selected_header_keys": ["content-type"],
                    "selected_body_kind": "lzma_compressed_replay_payload",
                    "selected_body_byte_size": 90584,
                    "selected_safe_body_sha256": None,
                    "evidence_sources": ["unit_reference_success"],
                    "blocker": "target_body_validation_requires_local_raw_blob_artifact",
                    "notes": ["unit fixture"],
                }
            ],
        },
    )


def _write_json(path: Path, document: object) -> None:
    """test用JSON documentをUTF-8 fileとして書き出す.

    Args:
        path (Path): 書き込み先JSON file path.
        document (object): JSON serializableなtest fixture document.

    Returns:
        None: JSON fileを書き出して値を返さずに完了する.

    Raises:
        OSError: pathへ書き込めない場合.
        TypeError: documentがJSON serializableでない場合.
        ValueError: documentが循環参照を含む場合.
    """
    _ = path.write_text(json.dumps(document), encoding="utf-8")


def _read_json_object(path: Path) -> dict[str, object]:
    """JSON fileをroot object mappingとして読み込む.

    Args:
        path (Path): 読み込むJSON fixture file path.

    Returns:
        dict[str, object]: JSON root objectを表すmapping.

    Raises:
        OSError: pathを読み込めない場合.
        json.JSONDecodeError: file内容が有効なJSONでない場合.
        AssertionError: JSON rootがobjectでない場合.
    """
    value = cast("object", json.loads(path.read_text(encoding="utf-8")))
    assert isinstance(value, dict)

    return cast("dict[str, object]", value)


def _first_json_mapping(value: object) -> dict[str, object]:
    """JSON listの先頭要素をobject mappingとして取得する.

    Args:
        value (object): listであることを期待するJSON value.

    Returns:
        dict[str, object]: list先頭のJSON object mapping.

    Raises:
        AssertionError: valueがlistでないか先頭要素がobjectでない場合.
        IndexError: valueが空listの場合.
    """
    assert isinstance(value, list)
    items = cast("list[object]", value)
    first_item = items[0]
    assert isinstance(first_item, dict)

    return cast("dict[str, object]", first_item)


@dataclass(slots=True)
class _ScoreLookup:
    """score存在判定だけを再現するdiagnostic lookup fakeを表す.

    Attributes:
        score_ids (frozenset[int]): 存在すると判定するscore ID集合.
    """

    score_ids: frozenset[int]

    async def get_by_id(self, score_id: int) -> object | None:
        """Score IDが登録済みならopaque score objectを返す.

        Args:
            score_id (int): 存在確認するscore ID.

        Returns:
            object | None: 登録済みならopaque object, 未登録ならNone.
        """
        if score_id not in self.score_ids:
            return None

        return object()


@dataclass(slots=True)
class _ReplayAttachmentLookup:
    """score IDからreplay attachmentを返すdiagnostic lookup fakeを表す.

    Attributes:
        attachments (dict[int, ReplayBlobAttachmentRecord]): score IDごとのattachment record.
    """

    attachments: dict[int, ReplayBlobAttachmentRecord] = field(default_factory=dict)

    async def get_by_score_id(self, score_id: int) -> ReplayBlobAttachmentRecord | None:
        """Score IDに対応するreplay attachment recordを返す.

        Args:
            score_id (int): attachmentを検索するscore ID.

        Returns:
            ReplayBlobAttachmentRecord | None: 登録済みrecord, または未登録時はNone.
        """
        return self.attachments.get(score_id)


@dataclass(slots=True)
class _BlobMetadataLookup:
    """blob IDからreplay blob metadataを返すdiagnostic lookup fakeを表す.

    Attributes:
        blobs (dict[int, ReplayBlobMetadataRecord]): blob IDごとのmetadata record.
    """

    blobs: dict[int, ReplayBlobMetadataRecord] = field(default_factory=dict)

    async def get_by_id(self, blob_id: int) -> ReplayBlobMetadataRecord | None:
        """Blob IDに対応するmetadata recordを返す.

        Args:
            blob_id (int): metadataを検索するblob ID.

        Returns:
            ReplayBlobMetadataRecord | None: 登録済みrecord, または未登録時はNone.
        """
        return self.blobs.get(blob_id)


@dataclass(slots=True)
class _BlobObjectReader:
    """storage objectの存在確認と分割読込を再現するdiagnostic reader fakeを表す.

    Attributes:
        objects (dict[str, bytes]): storage keyごとのtest payload.
        read_failures (frozenset[str]): open_readでOSErrorを送出するstorage key集合.
    """

    objects: dict[str, bytes] = field(default_factory=dict)
    read_failures: frozenset[str] = frozenset()

    async def exists(self, storage_key: str) -> bool:
        """Storage keyのpayloadがtest storageに存在するかを返す.

        Args:
            storage_key (str): 存在確認するstorage object key.

        Returns:
            bool: objectsにkeyが登録済みならTrue.
        """
        return storage_key in self.objects

    async def open_read(self, storage_key: str) -> AsyncIterator[bytes]:
        """Storage payloadを2つのasync chunkへ分けて返す.

        Args:
            storage_key (str): 読み込むstorage object key.

        Returns:
            AsyncIterator[bytes]: payloadを前半と後半に分割してyieldするiterator.

        Raises:
            OSError: storage_keyがread_failuresに含まれる場合.
            KeyError: storage_keyがobjectsに登録されていない場合.
        """
        if storage_key in self.read_failures:
            raise OSError(f"backend read failed for {storage_key}")

        payload = self.objects[storage_key]
        midpoint = len(payload) // 2

        async def chunks() -> AsyncIterator[bytes]:
            """payloadを順序を保った2つのchunkとしてyieldする.

            Yields:
                bytes: 前半と後半のpayload chunk.
            """
            yield payload[:midpoint]
            yield payload[midpoint:]

        return chunks()
