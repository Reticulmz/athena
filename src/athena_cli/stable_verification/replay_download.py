from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    ReplayBlobAttachmentRecord,
    ReplayBlobDiagnosticClassification,
    ReplayBlobDiagnosticInput,
    ReplayBlobDiagnosticResult,
    ReplayBlobMetadataRecord,
    ReplayDownloadAuthField,
    ReplayDownloadBlobIntegrity,
    ReplayDownloadBodyCompatibility,
    ReplayDownloadBodyDecision,
    ReplayDownloadBodyStrategy,
    ReplayDownloadReferenceResponseEvidence,
    ReplayDownloadResponseContractBranch,
    ReplayDownloadSanitizedFixture,
    ReplayDownloadTargetRouteContract,
    StableSurface,
    SurfaceResult,
    VerificationStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

_REQUEST_METADATA_FIXTURE = "target_client_request_metadata.json"
_RESPONSE_METADATA_FIXTURE = "target_client_response_metadata.json"
_REFERENCE_RESPONSES_FIXTURE = "reference_responses.json"
_RESPONSE_CONTRACT_FIXTURE = "response_contract.json"
_BODY_ASSEMBLY_DECISION_FIXTURE = "body_assembly_decision.json"
_REQUIRED_TARGET_ROUTE_CONTRACT_FIELDS = frozenset(
    (
        "primary_route",
        "primary_route_observed_in_target_client_traffic",
        "primary_route_classification",
        "alias_route",
        "alias_route_observed_in_target_client_traffic",
        "alias_policy",
        "route_evidence_source",
    )
)
_REQUIRED_REQUEST_CAPTURE_FIELDS = frozenset(
    (
        "target_client_family",
        "target_build_observed",
        "target_build",
        "target_build_note",
        "osuver_observed",
        "osuver",
        "osuver_note",
        "user_agent",
        "captured_at",
        "workflow_entrance",
        "route_classification",
        "target_route_observed",
        "alias_routes_observed",
        "method",
        "path",
        "query_keys",
        "auth_fields",
    )
)
_REQUIRED_RESPONSE_CAPTURE_FIELDS = frozenset(
    (
        "method",
        "path",
        "response_status",
        "response_header_keys_observed",
        "complete_response_header_key_set_observed",
        "body_kind",
        "body_byte_size",
        "safe_body_sha256",
    )
)
_REQUIRED_REFERENCE_RESPONSE_FIELDS = frozenset(
    (
        "name",
        "source",
        "source_role",
        "repository",
        "commit",
        "source_paths",
        "branch",
        "route",
        "method",
        "request_keys",
        "auth_fields",
        "response_status",
        "response_header_keys_observed",
        "complete_response_header_key_set_observed",
        "body_kind",
        "contract_status",
        "unresolved_reason",
    )
)
_REQUIRED_RESPONSE_CONTRACT_BRANCH_FIELDS = frozenset(
    (
        "branch",
        "status_label",
        "readiness",
        "selected_response_status",
        "selected_header_keys",
        "selected_body_kind",
        "selected_body_byte_size",
        "selected_safe_body_sha256",
        "evidence_sources",
        "blocker",
        "notes",
    )
)
_REQUIRED_BODY_DECISION_FIELDS = frozenset(
    (
        "status",
        "download_body_strategy",
        "blocker",
        "observed_success_body_kind",
        "observed_success_body_source",
        "observed_success_body_is_complete_osr",
        "observed_success_body_is_zip_archive",
        "stored_blob_integrity",
        "stored_blob_target_body_compatible",
        "body_format_classification",
        "local_artifact_policy",
        "diagnostic_outcome",
        "evidence_references",
    )
)
_RAW_QUERY_VALUE_KEYS = frozenset(
    (
        "query",
        "query_string",
        "query_values",
        "raw_query",
        "raw_query_value",
        "raw_query_values",
    )
)
_CREDENTIAL_VALUE_KEYS = frozenset(
    (
        "auth_value",
        "authorization",
        "cookie",
        "credential",
        "credential_value",
        "pass",
        "password",
        "password_hash",
        "password_md5",
        "raw_credential",
        "session_token",
        "token",
    )
)
_RAW_REPLAY_VALUE_KEYS = frozenset(
    (
        "body",
        "body_base64",
        "body_bytes",
        "body_hex",
        "raw_body",
        "raw_body_bytes",
        "raw_replay",
        "raw_replay_bytes",
        "replay_bytes",
    )
)
_COMPLETE_OSR_VALUE_KEYS = frozenset(
    (
        "complete_osr",
        "complete_osr_bytes",
        "osr_bytes",
    )
)
_HAR_ARCHIVE_KEYS = frozenset(("har", "har_archive", "har_log"))
_FORBIDDEN_KEY_ERRORS = (
    dict.fromkeys(_RAW_QUERY_VALUE_KEYS, "raw_query_value_field")
    | dict.fromkeys(_CREDENTIAL_VALUE_KEYS, "credential_like_field")
    | dict.fromkeys(_RAW_REPLAY_VALUE_KEYS, "raw_replay_field")
    | dict.fromkeys(_COMPLETE_OSR_VALUE_KEYS, "complete_osr_field")
    | dict.fromkeys(_HAR_ARCHIVE_KEYS, "har_archive_field")
    | {"value": "raw_auth_value_field"}
)


@dataclass(frozen=True, slots=True)
class ReplayDownloadEvidenceBundle:
    """Replay download sanitized fixture set を保持する.

    Args:
        request_metadata: Target client request metadata fixture の JSON object.
        response_metadata: Target client response metadata fixture の JSON object.
        reference_responses: Reference implementation audit fixture の parsed evidence.
        reference_responses_metadata: Reference implementation audit fixture の JSON object.
        body_assembly_decision: Body assembly decision fixture の JSON object.
        fixtures: Capture name で参照できる sanitized fixture.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        fixtures は sanitized view として raw query values, credential-like values,
        raw replay bytes を保持しない. Raw document の検証失敗診断にも raw 値を出さない.
    """

    request_metadata: Mapping[str, object]
    response_metadata: Mapping[str, object]
    reference_responses: tuple[ReplayDownloadReferenceResponseEvidence, ...]
    reference_responses_metadata: Mapping[str, object]
    response_contract_branches: tuple[ReplayDownloadResponseContractBranch, ...]
    response_contract_metadata: Mapping[str, object]
    body_assembly_decision: Mapping[str, object]
    body_decision: ReplayDownloadBodyDecision
    target_route_contract: ReplayDownloadTargetRouteContract
    fixtures: Mapping[str, ReplayDownloadSanitizedFixture]


class _ScoreLookup(Protocol):
    async def get_by_id(self, score_id: int) -> object | None: ...


class _ReplayAttachmentLookup(Protocol):
    async def get_by_score_id(
        self,
        score_id: int,
    ) -> ReplayBlobAttachmentRecord | None: ...


class _BlobMetadataLookup(Protocol):
    async def get_by_id(self, blob_id: int) -> ReplayBlobMetadataRecord | None: ...


class _BlobObjectReader(Protocol):
    async def exists(self, storage_key: str) -> bool: ...

    async def open_read(self, storage_key: str) -> AsyncIterator[bytes]: ...


@dataclass(frozen=True, slots=True)
class _StorageObservation:
    sha256: str
    byte_size: int


async def diagnose_replay_blob(
    diagnostic_input: ReplayBlobDiagnosticInput,
    *,
    score_lookup: _ScoreLookup,
    replay_attachment_lookup: _ReplayAttachmentLookup,
    blob_metadata_lookup: _BlobMetadataLookup,
    blob_object_reader: _BlobObjectReader,
) -> ReplayBlobDiagnosticResult:
    """Score id から replay blob integrity を report-safe に診断する.

    Args:
        diagnostic_input: 診断対象の score id.
        score_lookup: Score existence を確認する read-only lookup.
        replay_attachment_lookup: Score id から replay attachment を取得する lookup.
        blob_metadata_lookup: Blob metadata id から metadata を取得する lookup.
        blob_object_reader: Storage object existence と byte stream を読む backend.

    Returns:
        Replay attachment, blob metadata, storage object, size, SHA-256 の照合結果.

    Raises:
        なし.

    Constraints:
        Raw replay bytes, credential-like value, complete .osr bytes は出力しない.
        Diagnostic summary には storage key や digest を含めない.
    """

    score = await score_lookup.get_by_id(diagnostic_input.score_id)
    if score is None:
        return _replay_blob_diagnostic_result(
            classification=ReplayBlobDiagnosticClassification.MISSING_SCORE,
            score_found=False,
            replay_attachment_found=False,
            blob_found=False,
            storage_object_found=False,
        )

    attachment = await replay_attachment_lookup.get_by_score_id(diagnostic_input.score_id)
    if attachment is None:
        return _replay_blob_diagnostic_result(
            classification=ReplayBlobDiagnosticClassification.MISSING_REPLAY,
            score_found=True,
            replay_attachment_found=False,
            blob_found=False,
            storage_object_found=False,
        )

    blob = await blob_metadata_lookup.get_by_id(attachment.blob_id)
    if blob is None:
        return _replay_blob_diagnostic_result(
            classification=ReplayBlobDiagnosticClassification.MISSING_BLOB_METADATA,
            score_found=True,
            replay_attachment_found=True,
            blob_found=False,
            storage_object_found=False,
        )

    if not await blob_object_reader.exists(blob.storage_key):
        return _replay_blob_diagnostic_result(
            classification=ReplayBlobDiagnosticClassification.MISSING_STORAGE_OBJECT,
            score_found=True,
            replay_attachment_found=True,
            blob_found=True,
            storage_object_found=False,
            metadata_sha256=blob.sha256,
            metadata_byte_size=blob.byte_size,
        )

    observed = await _observe_storage_object(blob_object_reader, blob.storage_key)
    if observed is None:
        return _replay_blob_diagnostic_result(
            classification=ReplayBlobDiagnosticClassification.MISSING_STORAGE_OBJECT,
            score_found=True,
            replay_attachment_found=True,
            blob_found=True,
            storage_object_found=False,
            metadata_sha256=blob.sha256,
            metadata_byte_size=blob.byte_size,
        )

    classification = (
        ReplayBlobDiagnosticClassification.INTEGRITY_PASS
        if blob.sha256 == observed.sha256 and blob.byte_size == observed.byte_size
        else ReplayBlobDiagnosticClassification.STORAGE_INTEGRITY_FAILURE
    )
    return _replay_blob_diagnostic_result(
        classification=classification,
        score_found=True,
        replay_attachment_found=True,
        blob_found=True,
        storage_object_found=True,
        metadata_sha256=blob.sha256,
        observed_sha256=observed.sha256,
        metadata_byte_size=blob.byte_size,
        observed_byte_size=observed.byte_size,
    )


async def _observe_storage_object(
    blob_object_reader: _BlobObjectReader,
    storage_key: str,
) -> _StorageObservation | None:
    digest_builder = hashlib.sha256()
    byte_size = 0
    try:
        chunks = await blob_object_reader.open_read(storage_key)
        async for chunk in chunks:
            digest_builder.update(chunk)
            byte_size += len(chunk)
    except FileNotFoundError:
        return None

    return _StorageObservation(
        sha256=digest_builder.hexdigest(),
        byte_size=byte_size,
    )


def _replay_blob_diagnostic_result(
    *,
    classification: ReplayBlobDiagnosticClassification,
    score_found: bool,
    replay_attachment_found: bool,
    blob_found: bool,
    storage_object_found: bool,
    metadata_sha256: str | None = None,
    observed_sha256: str | None = None,
    metadata_byte_size: int | None = None,
    observed_byte_size: int | None = None,
) -> ReplayBlobDiagnosticResult:
    return ReplayBlobDiagnosticResult(
        score_found=score_found,
        replay_attachment_found=replay_attachment_found,
        blob_found=blob_found,
        storage_object_found=storage_object_found,
        metadata_sha256=metadata_sha256,
        observed_sha256=observed_sha256,
        metadata_byte_size=metadata_byte_size,
        observed_byte_size=observed_byte_size,
        classification=classification,
        status=_replay_blob_diagnostic_status(classification),
        diagnostic_summary=DiagnosticSummary(
            message=(
                f"replay blob diagnostic {classification.value} "
                f"score_found={str(score_found).lower()} "
                f"replay_attachment_found={str(replay_attachment_found).lower()} "
                f"blob_found={str(blob_found).lower()} "
                f"storage_object_found={str(storage_object_found).lower()} "
                f"metadata_byte_size={metadata_byte_size} "
                f"observed_byte_size={observed_byte_size}"
            )
        ),
    )


def _replay_blob_diagnostic_status(
    classification: ReplayBlobDiagnosticClassification,
) -> VerificationStatus:
    if classification is ReplayBlobDiagnosticClassification.INTEGRITY_PASS:
        return VerificationStatus.PASS
    if classification is ReplayBlobDiagnosticClassification.STORAGE_INTEGRITY_FAILURE:
        return VerificationStatus.FAIL

    return VerificationStatus.UNAVAILABLE


def build_replay_download_body_decision(
    *,
    blob_integrity: ReplayDownloadBlobIntegrity,
    target_body_compatible: ReplayDownloadBodyCompatibility,
    evidence_references: tuple[str, ...] = (),
) -> ReplayDownloadBodyDecision:
    """Blob integrity と target body compatibility から download body 方針を決める.

    Args:
        blob_integrity: Replay blob storage integrity の診断結果.
        target_body_compatible: Stored blob bytes の target-client-compatible body 判定.
        evidence_references: 判定に使った sanitized evidence の参照.

    Returns:
        #36 が direct blob bytes, body assembly, blocked のどれを採るべきかの
        report-safe decision.

    Raises:
        なし.

    Constraints:
        Raw replay bytes, complete .osr bytes, credential-like value は保持しない.
        Format mismatch は storage corruption ではなく assembly required として扱う.
    """

    if blob_integrity is ReplayDownloadBlobIntegrity.PASS:
        if target_body_compatible is ReplayDownloadBodyCompatibility.PASS:
            return _body_decision_result(
                blob_integrity=blob_integrity,
                target_body_compatible=target_body_compatible,
                download_body_strategy=ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES,
                status=VerificationStatus.PASS,
                message="direct_blob_bytes_allowed",
                evidence_references=evidence_references,
            )
        if target_body_compatible is ReplayDownloadBodyCompatibility.FAIL:
            return _body_decision_result(
                blob_integrity=blob_integrity,
                target_body_compatible=target_body_compatible,
                download_body_strategy=ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY,
                status=VerificationStatus.PASS,
                message="download_body_format_mismatch assemble_download_body_required",
                evidence_references=evidence_references,
            )

    if blob_integrity is ReplayDownloadBlobIntegrity.FAIL:
        return _body_decision_result(
            blob_integrity=blob_integrity,
            target_body_compatible=target_body_compatible,
            download_body_strategy=ReplayDownloadBodyStrategy.BLOCKED,
            status=VerificationStatus.FAIL,
            message="storage_integrity_failure body_decision_blocked",
            evidence_references=evidence_references,
        )

    return _body_decision_result(
        blob_integrity=blob_integrity,
        target_body_compatible=target_body_compatible,
        download_body_strategy=ReplayDownloadBodyStrategy.BLOCKED,
        status=VerificationStatus.KNOWN_GAP,
        message="body_decision_blocked target_body_compatibility_unverified",
        evidence_references=evidence_references,
    )


def _body_decision_result(
    *,
    blob_integrity: ReplayDownloadBlobIntegrity,
    target_body_compatible: ReplayDownloadBodyCompatibility,
    download_body_strategy: ReplayDownloadBodyStrategy,
    status: VerificationStatus,
    message: str,
    evidence_references: tuple[str, ...],
) -> ReplayDownloadBodyDecision:
    return ReplayDownloadBodyDecision(
        blob_integrity=blob_integrity,
        target_body_compatible=target_body_compatible,
        download_body_strategy=download_body_strategy,
        status=status,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=DiagnosticSummary(message=message),
        evidence_references=evidence_references,
    )


def load_replay_download_fixtures(root: Path) -> ReplayDownloadEvidenceBundle:
    """Replay download sanitized fixtures を読み込む.

    Args:
        root: replay_download fixture directory.

    Returns:
        Request/response/body decision JSON と capture name で結合した fixture bundle.

    Raises:
        FileNotFoundError: 必須 fixture file が存在しない場合.
        json.JSONDecodeError: fixture file が JSON として読めない場合.
        TypeError: fixture root の内容が JSON object ではない場合.

    Constraints:
        Local-only raw capture artifact は読まず、repository-managed JSON だけを扱う.
    """

    request_metadata = _read_json_object(root / _REQUEST_METADATA_FIXTURE)
    response_metadata = _read_json_object(root / _RESPONSE_METADATA_FIXTURE)
    reference_responses_metadata = _read_json_object(root / _REFERENCE_RESPONSES_FIXTURE)
    response_contract_metadata = _read_json_object(root / _RESPONSE_CONTRACT_FIXTURE)
    body_assembly_decision = _read_json_object(root / _BODY_ASSEMBLY_DECISION_FIXTURE)

    return ReplayDownloadEvidenceBundle(
        request_metadata=request_metadata,
        response_metadata=response_metadata,
        reference_responses=_reference_responses_from_document(reference_responses_metadata),
        reference_responses_metadata=reference_responses_metadata,
        response_contract_branches=_response_contract_branches_from_document(
            response_contract_metadata
        ),
        response_contract_metadata=response_contract_metadata,
        body_assembly_decision=body_assembly_decision,
        body_decision=_body_decision_from_document(body_assembly_decision),
        target_route_contract=_target_route_contract_from_document(request_metadata),
        fixtures=_load_sanitized_fixtures(request_metadata, response_metadata),
    )


def validate_replay_download_fixtures(
    bundle: ReplayDownloadEvidenceBundle,
) -> tuple[SurfaceResult, ...]:
    """Replay download fixtures の schema と redaction policy を検証する.

    Args:
        bundle: load_replay_download_fixtures が返す fixture bundle.

    Returns:
        Fixture file ごとの SurfaceResult tuple.

    Raises:
        なし.

    Constraints:
        DiagnosticSummary には raw query values, credential values, raw replay bytes を含めない.
    """

    request_errors = _validate_request_metadata(bundle.request_metadata)
    response_errors = _validate_response_metadata(bundle.response_metadata)
    reference_errors = _validate_reference_responses_metadata(bundle.reference_responses_metadata)
    response_contract_errors = _validate_response_contract_metadata(
        bundle.response_contract_metadata
    )
    decision_errors = _validate_body_assembly_decision(bundle.body_assembly_decision)

    return (
        _validation_result_from_errors(
            "replay download target client request metadata",
            _REQUEST_METADATA_FIXTURE,
            request_errors,
        ),
        _validation_result_from_errors(
            "replay download target client response metadata",
            _RESPONSE_METADATA_FIXTURE,
            response_errors,
        ),
        _validation_result_from_errors(
            "replay download reference response metadata",
            _REFERENCE_RESPONSES_FIXTURE,
            reference_errors,
        ),
        _validation_result_from_errors(
            "replay download response contract metadata",
            _RESPONSE_CONTRACT_FIXTURE,
            response_contract_errors,
        ),
        _validation_result_from_errors(
            "replay download body assembly decision metadata",
            _BODY_ASSEMBLY_DECISION_FIXTURE,
            decision_errors,
        ),
    )


def _validate_request_metadata(document: Mapping[str, object]) -> tuple[str, ...]:
    errors = list(_validate_metadata_document(document))
    errors.extend(_validate_target_route_contract(document))
    captures = _capture_mappings(document)
    if not captures:
        errors.append("missing_capture_list")

    for capture in captures:
        errors.extend(_missing_required_fields(capture, _REQUIRED_REQUEST_CAPTURE_FIELDS))
        errors.extend(_validate_string_field(capture, "target_client_family"))
        errors.extend(
            _validate_observed_metadata(
                capture,
                observed_key="target_build_observed",
                value_key="target_build",
                note_key="target_build_note",
            )
        )
        errors.extend(
            _validate_observed_metadata(
                capture,
                observed_key="osuver_observed",
                value_key="osuver",
                note_key="osuver_note",
            )
        )
        errors.extend(_validate_string_field(capture, "captured_at", safe_token=False))
        errors.extend(_validate_string_field(capture, "workflow_entrance"))
        errors.extend(_validate_string_field(capture, "route_classification"))
        errors.extend(_validate_bool_field(capture, "target_route_observed"))
        errors.extend(_validate_string_list_field(capture, "alias_routes_observed"))
        errors.extend(_validate_string_field(capture, "method"))
        errors.extend(_validate_string_field(capture, "path"))
        errors.extend(_validate_string_field(capture, "user_agent"))
        errors.extend(_validate_string_list_field(capture, "query_keys"))
        errors.extend(
            _validate_string_list_field(
                capture,
                "request_header_keys_observed",
                required=False,
            )
        )
        if _bool_value(capture.get("query_values_committed")):
            errors.append("committed_query_values")
        if _bool_value(capture.get("raw_values_committed")):
            errors.append("committed_raw_values")

        auth_fields = _auth_field_mappings(capture.get("auth_fields"))
        if not auth_fields:
            errors.append("missing_auth_field_list")
        for auth_field in auth_fields:
            auth_name = auth_field.get("name")
            if not isinstance(auth_name, str):
                errors.append("auth_field_missing_name")
            elif not _is_safe_metadata_token(auth_name):
                errors.append("auth_field_name_must_be_safe_token")
            auth_category = auth_field.get("category")
            if not isinstance(auth_category, str):
                errors.append("auth_field_missing_category")
            elif not _is_safe_metadata_token(auth_category):
                errors.append("auth_field_category_must_be_safe_token")
            if "value" in auth_field:
                errors.append("raw_auth_value_field")
            if _bool_value(auth_field.get("value_committed")):
                errors.append("committed_auth_value")

    return _sorted_unique(errors)


def _validate_target_route_contract(document: Mapping[str, object]) -> tuple[str, ...]:
    errors: list[str] = []
    route_contract = document.get("target_route_contract")
    if not isinstance(route_contract, Mapping):
        return ("missing_target_route_contract",)

    typed_route_contract = cast("Mapping[str, object]", route_contract)
    errors.extend(
        _missing_required_fields_with_prefix(
            typed_route_contract,
            _REQUIRED_TARGET_ROUTE_CONTRACT_FIELDS,
            "route_contract",
        )
    )
    errors.extend(_validate_string_field(typed_route_contract, "primary_route"))
    errors.extend(
        _validate_bool_field(
            typed_route_contract,
            "primary_route_observed_in_target_client_traffic",
        )
    )
    errors.extend(_validate_string_field(typed_route_contract, "primary_route_classification"))
    errors.extend(_validate_string_field(typed_route_contract, "alias_route"))
    errors.extend(
        _validate_bool_field(
            typed_route_contract,
            "alias_route_observed_in_target_client_traffic",
        )
    )
    errors.extend(_validate_string_field(typed_route_contract, "alias_policy"))
    errors.extend(_validate_string_field(typed_route_contract, "route_evidence_source"))
    if not _is_safe_string_list(typed_route_contract.get("route_evidence_fixture_names")):
        errors.append("route_contract_evidence_fixture_names_must_be_string_list")

    return _sorted_unique(errors)


def _validate_response_metadata(document: Mapping[str, object]) -> tuple[str, ...]:
    errors = list(_validate_metadata_document(document))
    captures = _capture_mappings(document)
    if not captures:
        errors.append("missing_capture_list")

    for capture in captures:
        errors.extend(_missing_required_fields(capture, _REQUIRED_RESPONSE_CAPTURE_FIELDS))
        errors.extend(_validate_string_list_field(capture, "response_header_keys_observed"))
        errors.extend(_validate_int_field(capture, "response_status"))
        errors.extend(_validate_bool_field(capture, "complete_response_header_key_set_observed"))
        errors.extend(_validate_int_field(capture, "body_byte_size"))

    return _sorted_unique(errors)


def _validate_reference_responses_metadata(document: Mapping[str, object]) -> tuple[str, ...]:
    errors = list(_validate_metadata_document(document))
    references = _reference_response_mappings(document)
    if not references:
        errors.append("missing_reference_response_list")

    for reference in references:
        errors.extend(_missing_required_fields(reference, _REQUIRED_REFERENCE_RESPONSE_FIELDS))
        errors.extend(_validate_string_field(reference, "name"))
        errors.extend(_validate_string_field(reference, "source"))
        errors.extend(_validate_string_field(reference, "source_role"))
        errors.extend(_validate_string_field(reference, "repository"))
        errors.extend(_validate_string_field(reference, "commit"))
        errors.extend(_validate_string_list_field(reference, "source_paths"))
        errors.extend(_validate_string_field(reference, "branch"))
        errors.extend(_validate_string_field(reference, "route", safe_token=False))
        errors.extend(_validate_string_field(reference, "method"))
        errors.extend(_validate_string_list_field(reference, "request_keys"))
        errors.extend(_validate_reference_auth_fields(reference))
        errors.extend(_validate_optional_int_field(reference, "response_status"))
        errors.extend(_validate_string_list_field(reference, "response_header_keys_observed"))
        errors.extend(_validate_bool_field(reference, "complete_response_header_key_set_observed"))
        errors.extend(_validate_string_field(reference, "body_kind"))
        errors.extend(_validate_string_field(reference, "contract_status"))
        errors.extend(_validate_optional_string_field(reference, "unresolved_reason"))

    return _sorted_unique(errors)


def _validate_reference_auth_fields(entry: Mapping[str, object]) -> tuple[str, ...]:
    errors: list[str] = []
    auth_fields = _auth_field_mappings(entry.get("auth_fields"))
    if not auth_fields:
        errors.append("missing_reference_auth_field_list")
        return tuple(errors)

    for auth_field in auth_fields:
        auth_name = auth_field.get("name")
        if not isinstance(auth_name, str):
            errors.append("reference_auth_field_missing_name")
        elif not _is_safe_metadata_token(auth_name):
            errors.append("reference_auth_field_name_must_be_safe_token")
        auth_category = auth_field.get("category")
        if not isinstance(auth_category, str):
            errors.append("reference_auth_field_missing_category")
        elif not _is_safe_metadata_token(auth_category):
            errors.append("reference_auth_field_category_must_be_safe_token")
        if "value" in auth_field:
            errors.append("raw_auth_value_field")

    return tuple(errors)


def _validate_response_contract_metadata(document: Mapping[str, object]) -> tuple[str, ...]:
    errors = list(_validate_metadata_document(document))
    branches = _response_contract_branch_mappings(document)
    if not branches:
        errors.append("missing_response_contract_branch_list")

    for branch in branches:
        errors.extend(_missing_required_fields(branch, _REQUIRED_RESPONSE_CONTRACT_BRANCH_FIELDS))
        errors.extend(_validate_string_field(branch, "branch"))
        errors.extend(_validate_string_field(branch, "status_label", safe_token=False))
        errors.extend(_validate_string_field(branch, "readiness"))
        errors.extend(_validate_optional_int_field(branch, "selected_response_status"))
        errors.extend(_validate_string_list_field(branch, "selected_header_keys"))
        errors.extend(_validate_optional_string_field(branch, "selected_body_kind"))
        errors.extend(_validate_optional_int_field(branch, "selected_body_byte_size"))
        errors.extend(_validate_optional_string_field(branch, "selected_safe_body_sha256"))
        errors.extend(_validate_string_list_field(branch, "evidence_sources", safe_token=False))
        errors.extend(_validate_optional_string_field(branch, "blocker"))
        errors.extend(_validate_string_list_field(branch, "notes"))

    return _sorted_unique(errors)


def _validate_body_assembly_decision(document: Mapping[str, object]) -> tuple[str, ...]:
    errors = list(_validate_metadata_document(document))
    decision = document.get("decision")
    if not isinstance(decision, Mapping):
        errors.append("missing_decision")
        return _sorted_unique(errors)

    errors.extend(
        _missing_required_fields(
            cast("Mapping[str, object]", decision),
            _REQUIRED_BODY_DECISION_FIELDS,
        )
    )
    errors.extend(
        _validate_bool_field(
            cast("Mapping[str, object]", decision),
            "observed_success_body_is_complete_osr",
        )
    )
    errors.extend(
        _validate_bool_field(
            cast("Mapping[str, object]", decision),
            "observed_success_body_is_zip_archive",
        )
    )
    typed_decision = cast("Mapping[str, object]", decision)
    errors.extend(_validate_string_field(typed_decision, "status"))
    errors.extend(_validate_string_field(typed_decision, "download_body_strategy"))
    errors.extend(_validate_string_field(typed_decision, "blocker"))
    errors.extend(_validate_string_field(typed_decision, "observed_success_body_kind"))
    errors.extend(
        _validate_string_field(
            typed_decision,
            "observed_success_body_source",
            safe_token=False,
        )
    )
    errors.extend(_validate_string_field(typed_decision, "stored_blob_integrity"))
    errors.extend(_validate_string_field(typed_decision, "stored_blob_target_body_compatible"))
    errors.extend(_validate_string_field(typed_decision, "body_format_classification"))
    errors.extend(_validate_string_field(typed_decision, "local_artifact_policy"))
    errors.extend(_validate_string_field(typed_decision, "diagnostic_outcome"))
    errors.extend(
        _validate_string_list_field(
            typed_decision,
            "evidence_references",
            safe_token=False,
        )
    )
    return _sorted_unique(errors)


def _validate_metadata_document(document: Mapping[str, object]) -> tuple[str, ...]:
    errors: list[str] = []
    if not isinstance(document.get("schema"), str):
        errors.append("missing_schema")
    if document.get("secret_policy") != "metadata-only":
        errors.append("secret_policy_not_metadata_only")
    if _bool_value(document.get("raw_artifact_committed")):
        errors.append("committed_raw_artifact")

    errors.extend(_forbidden_content_errors(document))
    return _sorted_unique(errors)


def _forbidden_content_errors(value: object) -> tuple[str, ...]:
    errors: list[str] = []
    _collect_forbidden_content_errors(value, errors)
    return _sorted_unique(errors)


def _collect_forbidden_content_errors(value: object, errors: list[str]) -> None:
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        if _is_har_archive_mapping(mapping):
            errors.append("har_archive_field")

        for key, nested_value in mapping.items():
            if isinstance(key, str):
                forbidden_key_error = _forbidden_key_error(key)
                if forbidden_key_error is not None:
                    errors.append(forbidden_key_error)
            _collect_forbidden_content_errors(nested_value, errors)
        return

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for item in value:
            _collect_forbidden_content_errors(item, errors)


def _forbidden_key_error(key: str) -> str | None:
    normalized_key = key.lower().replace("-", "_")
    return _FORBIDDEN_KEY_ERRORS.get(normalized_key)


def _is_har_archive_mapping(value: Mapping[object, object]) -> bool:
    log_value = value.get("log")
    if not isinstance(log_value, Mapping):
        return False

    return "entries" in log_value


def _load_sanitized_fixtures(
    request_metadata: Mapping[str, object],
    response_metadata: Mapping[str, object],
) -> Mapping[str, ReplayDownloadSanitizedFixture]:
    response_captures = _captures_by_name(response_metadata)
    fixtures: dict[str, ReplayDownloadSanitizedFixture] = {}
    for name, request_capture in _captures_by_name(request_metadata).items():
        response_capture = response_captures.get(name, {})
        fixtures[name] = _sanitized_fixture_from_capture(
            request_capture,
            response_capture,
        )

    return fixtures


def _reference_responses_from_document(
    document: Mapping[str, object],
) -> tuple[ReplayDownloadReferenceResponseEvidence, ...]:
    return tuple(
        _reference_response_from_entry(reference)
        for reference in _reference_response_mappings(document)
    )


def _reference_response_from_entry(
    reference: Mapping[str, object],
) -> ReplayDownloadReferenceResponseEvidence:
    return ReplayDownloadReferenceResponseEvidence(
        name=_string_value(reference, "name"),
        source=_string_value(reference, "source"),
        source_role=_string_value(reference, "source_role"),
        repository=_string_value(reference, "repository"),
        commit=_string_value(reference, "commit"),
        source_paths=_string_tuple(reference.get("source_paths")),
        branch=_string_value(reference, "branch"),
        route=_string_value(reference, "route"),
        method=_string_value(reference, "method"),
        request_keys=_string_tuple(reference.get("request_keys")),
        auth_fields=_auth_fields(reference.get("auth_fields")),
        response_status=_optional_int_value(reference, "response_status"),
        response_header_keys_observed=_string_tuple(
            reference.get("response_header_keys_observed")
        ),
        complete_response_header_key_set_observed=_bool_value(
            reference.get("complete_response_header_key_set_observed")
        ),
        body_kind=_string_value(reference, "body_kind"),
        contract_status=_string_value(reference, "contract_status"),
        unresolved_reason=_optional_string_value(reference, "unresolved_reason"),
    )


def _response_contract_branches_from_document(
    document: Mapping[str, object],
) -> tuple[ReplayDownloadResponseContractBranch, ...]:
    return tuple(
        _response_contract_branch_from_entry(branch)
        for branch in _response_contract_branch_mappings(document)
    )


def _response_contract_branch_from_entry(
    branch: Mapping[str, object],
) -> ReplayDownloadResponseContractBranch:
    return ReplayDownloadResponseContractBranch(
        branch=_string_value(branch, "branch"),
        status_label=_string_value(branch, "status_label"),
        readiness=_string_value(branch, "readiness"),
        selected_response_status=_optional_int_value(branch, "selected_response_status"),
        selected_header_keys=_string_tuple(branch.get("selected_header_keys")),
        selected_body_kind=_optional_string_value(branch, "selected_body_kind"),
        selected_body_byte_size=_optional_int_value(branch, "selected_body_byte_size"),
        selected_safe_body_sha256=_optional_string_value(branch, "selected_safe_body_sha256"),
        evidence_sources=_string_tuple(branch.get("evidence_sources")),
        blocker=_optional_string_value(branch, "blocker"),
        notes=_string_tuple(branch.get("notes")),
    )


def _body_decision_from_document(
    document: Mapping[str, object],
) -> ReplayDownloadBodyDecision:
    decision = document.get("decision")
    if not isinstance(decision, Mapping):
        return build_replay_download_body_decision(
            blob_integrity=ReplayDownloadBlobIntegrity.UNAVAILABLE,
            target_body_compatible=ReplayDownloadBodyCompatibility.LOCAL_ONLY_UNVERIFIED,
        )

    typed_decision = cast("Mapping[str, object]", decision)
    return ReplayDownloadBodyDecision(
        blob_integrity=_blob_integrity_value(typed_decision, "stored_blob_integrity"),
        target_body_compatible=_body_compatibility_value(
            typed_decision,
            "stored_blob_target_body_compatible",
        ),
        download_body_strategy=_body_strategy_value(typed_decision, "download_body_strategy"),
        status=_verification_status_value(typed_decision, "status"),
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=DiagnosticSummary(
            message=_body_decision_message(typed_decision),
        ),
        evidence_references=_string_tuple(typed_decision.get("evidence_references")),
    )


def _body_decision_message(decision: Mapping[str, object]) -> str:
    status = _string_value(decision, "status")
    strategy = _string_value(decision, "download_body_strategy")
    blocker = _optional_string_value(decision, "blocker")
    classification = _optional_string_value(decision, "body_format_classification")
    parts = [
        f"body_decision_status={status}",
        f"download_body_strategy={strategy}",
    ]
    if blocker is not None:
        parts.append(f"blocker={blocker}")
    if classification is not None:
        parts.append(f"body_format_classification={classification}")

    return " ".join(parts)


def _target_route_contract_from_document(
    request_metadata: Mapping[str, object],
) -> ReplayDownloadTargetRouteContract:
    route_contract = request_metadata.get("target_route_contract")
    if not isinstance(route_contract, Mapping):
        route_contract = {}

    typed_route_contract = cast("Mapping[str, object]", route_contract)
    return ReplayDownloadTargetRouteContract(
        primary_route=_string_value(typed_route_contract, "primary_route"),
        primary_route_observed_in_target_client_traffic=_bool_value(
            typed_route_contract.get("primary_route_observed_in_target_client_traffic")
        ),
        primary_route_classification=_string_value(
            typed_route_contract,
            "primary_route_classification",
        ),
        alias_route=_string_value(typed_route_contract, "alias_route"),
        alias_route_observed_in_target_client_traffic=_bool_value(
            typed_route_contract.get("alias_route_observed_in_target_client_traffic")
        ),
        alias_policy=_string_value(typed_route_contract, "alias_policy"),
        route_evidence_source=_string_value(typed_route_contract, "route_evidence_source"),
        route_evidence_fixture_names=_string_tuple(
            typed_route_contract.get("route_evidence_fixture_names")
        ),
    )


def _sanitized_fixture_from_capture(
    request_capture: Mapping[str, object],
    response_capture: Mapping[str, object],
) -> ReplayDownloadSanitizedFixture:
    return ReplayDownloadSanitizedFixture(
        target_client_family=_string_value(request_capture, "target_client_family"),
        target_build_observed=_bool_value(request_capture.get("target_build_observed")),
        target_build=_optional_string_value(request_capture, "target_build"),
        target_build_note=_string_value(request_capture, "target_build_note"),
        osuver_observed=_bool_value(request_capture.get("osuver_observed")),
        osuver=_optional_string_value(request_capture, "osuver"),
        osuver_note=_string_value(request_capture, "osuver_note"),
        user_agent=_string_value(request_capture, "user_agent"),
        captured_at=_string_value(request_capture, "captured_at"),
        workflow_entrance=_string_value(request_capture, "workflow_entrance"),
        route_classification=_string_value(request_capture, "route_classification"),
        target_route_observed=_bool_value(request_capture.get("target_route_observed")),
        alias_routes_observed=_string_tuple(request_capture.get("alias_routes_observed")),
        method=_string_value(request_capture, "method"),
        path=_string_value(request_capture, "path"),
        query_keys=_string_tuple(request_capture.get("query_keys")),
        auth_fields=_auth_fields(request_capture.get("auth_fields")),
        response_status=_optional_int_value(response_capture, "response_status"),
        response_header_keys_observed=_string_tuple(
            response_capture.get("response_header_keys_observed")
        ),
        complete_response_header_key_set_observed=_bool_value(
            response_capture.get("complete_response_header_key_set_observed")
        ),
        body_kind=_optional_string_value(response_capture, "body_kind"),
        body_byte_size=_optional_int_value(response_capture, "body_byte_size"),
        safe_body_sha256=_optional_string_value(response_capture, "safe_body_sha256"),
        raw_values_committed=_raw_values_committed(request_capture),
    )


def _read_json_object(path: Path) -> Mapping[str, object]:
    parsed = cast("object", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(parsed, Mapping):
        raise TypeError(f"{path.name} must contain a JSON object")

    return cast("Mapping[str, object]", parsed)


def _captures_by_name(document: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    captures: dict[str, Mapping[str, object]] = {}
    for capture in _capture_mappings(document):
        name = capture.get("name")
        if not isinstance(name, str):
            continue

        captures[name] = capture

    return captures


def _capture_mappings(document: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    captures_value = document.get("captures")
    if not isinstance(captures_value, Sequence) or isinstance(
        captures_value,
        str | bytes | bytearray,
    ):
        return ()

    captures: list[Mapping[str, object]] = []
    for capture in captures_value:
        if not isinstance(capture, Mapping):
            continue

        captures.append(cast("Mapping[str, object]", capture))

    return tuple(captures)


def _reference_response_mappings(
    document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    references_value = document.get("references")
    if not isinstance(references_value, Sequence) or isinstance(
        references_value,
        str | bytes | bytearray,
    ):
        return ()

    references: list[Mapping[str, object]] = []
    for reference in references_value:
        if not isinstance(reference, Mapping):
            continue

        references.append(cast("Mapping[str, object]", reference))

    return tuple(references)


def _response_contract_branch_mappings(
    document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    branches_value = document.get("branches")
    if not isinstance(branches_value, Sequence) or isinstance(
        branches_value,
        str | bytes | bytearray,
    ):
        return ()

    branches: list[Mapping[str, object]] = []
    for branch in branches_value:
        if not isinstance(branch, Mapping):
            continue

        branches.append(cast("Mapping[str, object]", branch))

    return tuple(branches)


def _auth_fields(value: object) -> tuple[ReplayDownloadAuthField, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return ()

    fields: list[ReplayDownloadAuthField] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue

        auth_field = cast("Mapping[str, object]", entry)
        fields.append(
            ReplayDownloadAuthField(
                name=_string_value(auth_field, "name"),
                category=_string_value(auth_field, "category"),
                value_committed=_bool_value(auth_field.get("value_committed")),
            )
        )

    return tuple(fields)


def _auth_field_mappings(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return ()

    fields: list[Mapping[str, object]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue

        fields.append(cast("Mapping[str, object]", entry))

    return tuple(fields)


def _missing_required_fields(
    entry: Mapping[str, object],
    required_fields: frozenset[str],
) -> tuple[str, ...]:
    missing_count = sum(1 for field_name in required_fields if field_name not in entry)
    if missing_count == 0:
        return ()

    return (f"missing_required_fields:{missing_count}",)


def _missing_required_fields_with_prefix(
    entry: Mapping[str, object],
    required_fields: frozenset[str],
    prefix: str,
) -> tuple[str, ...]:
    missing_count = sum(1 for field_name in required_fields if field_name not in entry)
    if missing_count == 0:
        return ()

    return (f"{prefix}_missing_required_fields:{missing_count}",)


def _validate_string_list_field(
    entry: Mapping[str, object],
    key: str,
    *,
    required: bool = True,
    safe_token: bool = True,
) -> tuple[str, ...]:
    value = entry.get(key)
    if value is None and not required:
        return ()
    if not _is_string_list(value, safe_token=safe_token):
        return (f"{key}_must_be_string_list",)

    return ()


def _validate_string_field(
    entry: Mapping[str, object],
    key: str,
    *,
    safe_token: bool = True,
) -> tuple[str, ...]:
    value = entry.get(key)
    if isinstance(value, str) and value and (not safe_token or _is_safe_metadata_token(value)):
        return ()

    return (f"{key}_must_be_safe_string",)


def _validate_optional_string_field(
    entry: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    value = entry.get(key)
    if value is None:
        return ()
    if isinstance(value, str) and value:
        return ()

    return (f"{key}_must_be_string_or_null",)


def _validate_observed_metadata(
    entry: Mapping[str, object],
    *,
    observed_key: str,
    value_key: str,
    note_key: str,
) -> tuple[str, ...]:
    errors: list[str] = []
    observed_value = entry.get(observed_key)
    if not isinstance(observed_value, bool):
        errors.append(f"{observed_key}_must_be_bool")
        return tuple(errors)

    metadata_value = entry.get(value_key)
    if observed_value:
        if (
            not isinstance(metadata_value, str)
            or not metadata_value
            or not _is_safe_metadata_token(metadata_value)
        ):
            errors.append(f"{value_key}_must_be_safe_string_when_observed")
    elif metadata_value is not None:
        errors.append(f"{value_key}_must_be_null_when_not_observed")

    note_value = entry.get(note_key)
    if (
        not isinstance(note_value, str)
        or not note_value
        or not _is_safe_metadata_token(note_value)
    ):
        errors.append(f"{note_key}_must_be_safe_string")

    return tuple(errors)


def _is_safe_string_list(value: object) -> bool:
    return _is_string_list(value, safe_token=True)


def _is_string_list(value: object, *, safe_token: bool) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return False

    return all(
        isinstance(item, str) and (not safe_token or _is_safe_metadata_token(item))
        for item in value
    )


def _validate_int_field(entry: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = entry.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return ()

    return (f"{key}_must_be_int",)


def _validate_optional_int_field(
    entry: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    value = entry.get(key)
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return ()

    return (f"{key}_must_be_int_or_null",)


def _validate_bool_field(entry: Mapping[str, object], key: str) -> tuple[str, ...]:
    if isinstance(entry.get(key), bool):
        return ()

    return (f"{key}_must_be_bool",)


def _is_safe_metadata_token(value: str) -> bool:
    return "=" not in value and "&" not in value and ":" not in value


def _string_value(entry: Mapping[str, object], key: str) -> str:
    value = entry.get(key)
    if isinstance(value, str):
        return value

    return ""


def _optional_string_value(entry: Mapping[str, object], key: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None

    if isinstance(value, str):
        return value

    return None


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value

    return False


def _optional_int_value(entry: Mapping[str, object], key: str) -> int | None:
    value = entry.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value

    return None


def _verification_status_value(
    entry: Mapping[str, object],
    key: str,
) -> VerificationStatus:
    value = entry.get(key)
    if isinstance(value, str):
        try:
            return VerificationStatus(value)
        except ValueError:
            return VerificationStatus.KNOWN_GAP

    return VerificationStatus.KNOWN_GAP


def _blob_integrity_value(
    entry: Mapping[str, object],
    key: str,
) -> ReplayDownloadBlobIntegrity:
    value = entry.get(key)
    if isinstance(value, str):
        try:
            return ReplayDownloadBlobIntegrity(value)
        except ValueError:
            return ReplayDownloadBlobIntegrity.UNAVAILABLE

    return ReplayDownloadBlobIntegrity.UNAVAILABLE


def _body_compatibility_value(
    entry: Mapping[str, object],
    key: str,
) -> ReplayDownloadBodyCompatibility:
    value = entry.get(key)
    if isinstance(value, str):
        try:
            return ReplayDownloadBodyCompatibility(value)
        except ValueError:
            return ReplayDownloadBodyCompatibility.LOCAL_ONLY_UNVERIFIED

    return ReplayDownloadBodyCompatibility.LOCAL_ONLY_UNVERIFIED


def _body_strategy_value(
    entry: Mapping[str, object],
    key: str,
) -> ReplayDownloadBodyStrategy:
    value = entry.get(key)
    if isinstance(value, str):
        try:
            return ReplayDownloadBodyStrategy(value)
        except ValueError:
            return ReplayDownloadBodyStrategy.BLOCKED

    return ReplayDownloadBodyStrategy.BLOCKED


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return ()

    return tuple(item for item in value if isinstance(item, str))


def _raw_values_committed(request_capture: Mapping[str, object]) -> bool:
    raw_values_committed = request_capture.get("raw_values_committed")
    if isinstance(raw_values_committed, bool):
        return raw_values_committed

    return _bool_value(request_capture.get("query_values_committed"))


def _validation_result_from_errors(
    prefix: str,
    reference: str,
    errors: tuple[str, ...],
) -> SurfaceResult:
    if not errors:
        return _validation_result(
            VerificationStatus.PASS,
            f"{prefix} valid",
            reference,
        )

    return _validation_result(
        VerificationStatus.FAIL,
        f"{prefix} redaction policy failed: {', '.join(errors)}",
        reference,
    )


def _validation_result(
    status: VerificationStatus,
    message: str,
    reference: str,
) -> SurfaceResult:
    return SurfaceResult(
        surface=StableSurface.REPLAY_DOWNLOAD,
        status=status,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference=reference,
    )


def _sorted_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


__all__ = [
    "ReplayDownloadEvidenceBundle",
    "load_replay_download_fixtures",
    "validate_replay_download_fixtures",
]
