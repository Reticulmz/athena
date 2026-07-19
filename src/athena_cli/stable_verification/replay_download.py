"""Stable replay downloadのevidence fixtureとblob診断を検証する機能を提供する."""

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
    """Replay downloadのsanitized fixtureと解析済みevidenceをまとめる.

    Attributes:
        request_metadata (Mapping[str, object]): Target client request metadataのJSON object.
        response_metadata (Mapping[str, object]): Target client response metadataのJSON object.
        reference_responses (tuple[ReplayDownloadReferenceResponseEvidence, ...]):
            Reference implementation auditの解析済みevidence.
        reference_responses_metadata (Mapping[str, object]): Reference response fixtureのJSON
            object.
        response_contract_branches (tuple[ReplayDownloadResponseContractBranch, ...]):
            Response contract branchの解析済み一覧.
        response_contract_metadata (Mapping[str, object]): Response contract fixtureのJSON object.
        body_assembly_decision (Mapping[str, object]): Body assembly decision fixtureのJSON object.
        body_decision (ReplayDownloadBodyDecision): 現在のdownload body方針を表す解析済みdecision.
        target_route_contract (ReplayDownloadTargetRouteContract): Target client route evidenceの
            解析済みcontract.
        fixtures (Mapping[str, ReplayDownloadSanitizedFixture]): Capture名で参照するsanitized
            fixture.

    Notes:
        Raw query value、credential-like value、raw replay bytes、complete `.osr` bytesを
        保持しない.
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
    """Score IDでscoreの存在を調べるread-only portを表す."""

    async def get_by_id(self, score_id: int) -> object | None:
        """Score IDに対応するscoreを取得する.

        Args:
            score_id (int): 取得するscore ID.

        Returns:
            object | None: Scoreが存在する場合はopaqueなscore object。存在しない場合はNone.
        """
        ...


class _ReplayAttachmentLookup(Protocol):
    """Score IDでreplay attachmentを調べるread-only portを表す."""

    async def get_by_score_id(
        self,
        score_id: int,
    ) -> ReplayBlobAttachmentRecord | None:
        """Scoreに紐づくreplay attachmentを取得する.

        Args:
            score_id (int): Replay attachmentを調べるscore ID.

        Returns:
            ReplayBlobAttachmentRecord | None: Attachment record。存在しない場合はNone.
        """
        ...


class _BlobMetadataLookup(Protocol):
    """Blob IDでreplay blob metadataを調べるread-only portを表す."""

    async def get_by_id(self, blob_id: int) -> ReplayBlobMetadataRecord | None:
        """Blob IDに対応するmetadataを取得する.

        Args:
            blob_id (int): 取得するblob metadata ID.

        Returns:
            ReplayBlobMetadataRecord | None: Blob metadata。存在しない場合はNone.
        """
        ...


class _BlobObjectReader(Protocol):
    """Storage backend上のblob objectを読むportを表す."""

    async def exists(self, storage_key: str) -> bool:
        """Storage objectが存在するか判定する.

        Args:
            storage_key (str): 判定するbackend object key.

        Returns:
            bool: Backendがobjectの存在を報告する場合はTrue.
        """
        ...

    async def open_read(self, storage_key: str) -> AsyncIterator[bytes]:
        """Storage objectのbyte streamを開く.

        Args:
            storage_key (str): 読み込むbackend object key.

        Returns:
            AsyncIterator[bytes]: Object内容を順に返す非同期byte stream.

        Raises:
            OSError: Backend objectを読み込めない場合.
        """
        ...


@dataclass(frozen=True, slots=True)
class _StorageObservation:
    """Storage objectから計測したintegrity情報を表す.

    Attributes:
        sha256 (str): ReadしたbytesのSHA-256 digest.
        byte_size (int): Readしたbytesの総byte数.
    """

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
    """Score IDからreplay blob integrityをreport-safeに診断する.

    Args:
        diagnostic_input (ReplayBlobDiagnosticInput): 診断対象のscore IDを持つ入力値.
        score_lookup (_ScoreLookup): Score存在を確認するread-only lookup.
        replay_attachment_lookup (_ReplayAttachmentLookup): Score IDからreplay attachmentを
            取得するlookup.
        blob_metadata_lookup (_BlobMetadataLookup): Blob metadata IDからmetadataを取得するlookup.
        blob_object_reader (_BlobObjectReader): Storage objectの存在確認とbyte stream読込を行う
            backend.

    Returns:
        ReplayBlobDiagnosticResult: Score、attachment、metadata、storage object、SHA-256、
            byte sizeの照合結果.

    Notes:
        Raw replay bytes、credential-like value、complete `.osr` bytes、storage key、digestを
        診断summaryへ含めない.
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
    """Storage objectを読みSHA-256とbyte sizeを計測する.

    Args:
        blob_object_reader (_BlobObjectReader): Storage objectを読むbackend.
        storage_key (str): 読み込むbackend object key.

    Returns:
        _StorageObservation | None: 読み込み成功時のdigestとbyte size。`OSError`時はNone.
    """
    digest_builder = hashlib.sha256()
    byte_size = 0
    try:
        chunks = await blob_object_reader.open_read(storage_key)
        async for chunk in chunks:
            digest_builder.update(chunk)
            byte_size += len(chunk)
    except OSError:
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
    """Diagnostic classificationと観測値からresultを組み立てる.

    Args:
        classification (ReplayBlobDiagnosticClassification): 診断結果の分類.
        score_found (bool): Scoreが存在したか.
        replay_attachment_found (bool): Replay attachmentが存在したか.
        blob_found (bool): Blob metadataが存在したか.
        storage_object_found (bool): Storage objectを確認できたか.
        metadata_sha256 (str | None): Blob metadataが保持するSHA-256 digest.
        observed_sha256 (str | None): Storage objectから計測したSHA-256 digest.
        metadata_byte_size (int | None): Blob metadataが保持するbyte size.
        observed_byte_size (int | None): Storage objectから計測したbyte size.

    Returns:
        ReplayBlobDiagnosticResult: Classificationとreport-safeな存在確認情報を持つ結果.
    """
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
    """Replay blob classificationをverification statusへ写像する.

    Args:
        classification (ReplayBlobDiagnosticClassification): Replay blobの診断分類.

    Returns:
        VerificationStatus: Integrity passはPASS、integrity failureはFAIL、それ以外はUNAVAILABLE.
    """
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
    """Blob integrityとtarget body compatibilityからdownload body方針を決める.

    Args:
        blob_integrity (ReplayDownloadBlobIntegrity): Replay blob storage integrityの診断結果.
        target_body_compatible (ReplayDownloadBodyCompatibility): Stored blob bytesのtarget
            client互換性判定.
        evidence_references (tuple[str, ...]): 判定に使ったsanitized evidenceの参照.

    Returns:
        ReplayDownloadBodyDecision: Direct blob bytes、body assembly、blockedのいずれかを表す
            report-safeなdecision.

    Notes:
        Format mismatchはstorage corruptionではなくbody assemblyが必要な状態として扱う.
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
    """Download body方針の共通resultを組み立てる.

    Args:
        blob_integrity (ReplayDownloadBlobIntegrity): Blob storage integrityの状態.
        target_body_compatible (ReplayDownloadBodyCompatibility): Target client body互換性の状態.
        download_body_strategy (ReplayDownloadBodyStrategy): Download response bodyの方針.
        status (VerificationStatus): Decisionのverification status.
        message (str): Report-safeな診断message.
        evidence_references (tuple[str, ...]): Decisionを裏付けるsanitized evidenceの参照.

    Returns:
        ReplayDownloadBodyDecision: Mandatory golden fixture evidenceとして扱うbody decision.
    """
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
    """Replay downloadのsanitized fixtureを読み込み解析する.

    Args:
        root (Path): Replay download fixture directory.

    Returns:
        ReplayDownloadEvidenceBundle: Request/response/body decision JSONとcapture名で結合した
            fixture bundle.

    Raises:
        OSError: 必須fixture fileを開けない場合.
        json.JSONDecodeError: Fixture fileがJSONとして不正な場合.
        TypeError: Fixture fileのtop-level valueがJSON objectでない場合.

    Notes:
        Local-only raw capture artifactは読まずrepository管理下のJSONだけを扱う.
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
    """Replay download fixtureのschemaとredaction policyを検証する.

    Args:
        bundle (ReplayDownloadEvidenceBundle): 読み込み済みfixture bundle.

    Returns:
        tuple[SurfaceResult, ...]: Fixture fileごとのmandatory検証結果.

    Notes:
        DiagnosticSummaryにはraw query value、credential value、raw replay bytesを含めない.
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
    """Target client request metadataのschemaとredaction policyを検証する.

    Args:
        document (Mapping[str, object]): Request metadata fixtureのJSON object.

    Returns:
        tuple[str, ...]: 重複を除いたreport-safeなvalidation error code。正常時は空tuple.

    Notes:
        Raw query valueやcredential valueをerror messageへ含めない.
    """
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
    """Target client route contractの必須fieldと安全な値を検証する.

    Args:
        document (Mapping[str, object]): Request metadata fixtureのJSON object.

    Returns:
        tuple[str, ...]: Route contractのreport-safeなvalidation error code。正常時は空tuple.
    """
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
    """Target client response metadataのschemaとredaction policyを検証する.

    Args:
        document (Mapping[str, object]): Response metadata fixtureのJSON object.

    Returns:
        tuple[str, ...]: Response captureのreport-safeなvalidation error code。正常時は空tuple.
    """
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
        if capture.get("safe_body_sha256") is not None:
            errors.append("committed_safe_body_sha256")

    return _sorted_unique(errors)


def _validate_reference_responses_metadata(document: Mapping[str, object]) -> tuple[str, ...]:
    """Reference implementation response metadataのschemaを検証する.

    Args:
        document (Mapping[str, object]): Reference response fixtureのJSON object.

    Returns:
        tuple[str, ...]: Reference entryのreport-safeなvalidation error code。正常時は空tuple.
    """
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
    """Reference response entryのauth field metadataを検証する.

    Args:
        entry (Mapping[str, object]): Reference response entryのJSON object.

    Returns:
        tuple[str, ...]: Auth fieldのreport-safeなvalidation error code。正常時は空tuple.
    """
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
    """Response contract branch metadataのschemaと安全な値を検証する.

    Args:
        document (Mapping[str, object]): Response contract fixtureのJSON object.

    Returns:
        tuple[str, ...]: Branch metadataのreport-safeなvalidation error code。正常時は空tuple.
    """
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
        if branch.get("selected_safe_body_sha256") is not None:
            errors.append("committed_selected_safe_body_sha256")
        errors.extend(_validate_string_list_field(branch, "evidence_sources", safe_token=False))
        errors.extend(_validate_optional_string_field(branch, "blocker"))
        errors.extend(_validate_string_list_field(branch, "notes"))

    return _sorted_unique(errors)


def _validate_body_assembly_decision(document: Mapping[str, object]) -> tuple[str, ...]:
    """Body assembly decision metadataのschemaと安全な値を検証する.

    Args:
        document (Mapping[str, object]): Body assembly decision fixtureのJSON object.

    Returns:
        tuple[str, ...]: Decision metadataのreport-safeなvalidation error code。正常時は空tuple.
    """
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
    """Replay download metadata document共通のschemaと秘匿方針を検証する.

    Args:
        document (Mapping[str, object]): 検証するfixtureのtop-level JSON object.

    Returns:
        tuple[str, ...]: 共通fieldと禁止contentのreport-safeなvalidation error code。正常時は
            空tuple.
    """
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
    """入れ子のmetadataから禁止contentのerror codeを収集する.

    Args:
        value (object): Mappingまたはsequenceを含み得る検証対象.

    Returns:
        tuple[str, ...]: 重複を除いた禁止contentのerror code。禁止contentがなければ空tuple.
    """
    errors: list[str] = []
    _collect_forbidden_content_errors(value, errors)
    return _sorted_unique(errors)


def _collect_forbidden_content_errors(value: object, errors: list[str]) -> None:
    """入れ子のmetadataを巡回して禁止contentのerror codeを追加する.

    Args:
        value (object): 巡回するMapping、sequence、またはleaf値.
        errors (list[str]): 見つけたerror codeを追加する可変list.

    Returns:
        None: `errors`へerror codeを追加して値を返さず完了する.
    """
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
    """Metadata keyに対応する禁止content error codeを返す.

    Args:
        key (str): 検査するmetadata key.

    Returns:
        str | None: Keyが禁止集合に属する場合のerror code。それ以外はNone.
    """
    normalized_key = key.lower().replace("-", "_")
    return _FORBIDDEN_KEY_ERRORS.get(normalized_key)


def _is_har_archive_mapping(value: Mapping[object, object]) -> bool:
    """MappingがHAR archiveらしい`log.entries`構造を持つか判定する.

    Args:
        value (Mapping[object, object]): 検査する任意key/value mapping.

    Returns:
        bool: `log` mappingの中に`entries` keyがある場合はTrue.
    """
    log_value = value.get("log")
    if not isinstance(log_value, Mapping):
        return False

    return "entries" in log_value


def _load_sanitized_fixtures(
    request_metadata: Mapping[str, object],
    response_metadata: Mapping[str, object],
) -> Mapping[str, ReplayDownloadSanitizedFixture]:
    """Request/response captureをcapture名ごとのsanitized fixtureへ結合する.

    Args:
        request_metadata (Mapping[str, object]): Target client request metadataのJSON object.
        response_metadata (Mapping[str, object]): Target client response metadataのJSON object.

    Returns:
        Mapping[str, ReplayDownloadSanitizedFixture]: Request capture名をkeyにしたsanitized
            fixture.
    """
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
    """Reference response documentを解析済みevidence tupleへ変換する.

    Args:
        document (Mapping[str, object]): Reference response fixtureのJSON object.

    Returns:
        tuple[ReplayDownloadReferenceResponseEvidence, ...]: Mappingとして読めるreference
            entryの解析結果.
    """
    return tuple(
        _reference_response_from_entry(reference)
        for reference in _reference_response_mappings(document)
    )


def _reference_response_from_entry(
    reference: Mapping[str, object],
) -> ReplayDownloadReferenceResponseEvidence:
    """Reference response entryをreport-safeなevidence objectへ変換する.

    Args:
        reference (Mapping[str, object]): Reference response entryのJSON object.

    Returns:
        ReplayDownloadReferenceResponseEvidence: 欠損または型不正fieldを安全な既定値へ変換した
            evidence.
    """
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
    """Response contract documentを解析済みbranch tupleへ変換する.

    Args:
        document (Mapping[str, object]): Response contract fixtureのJSON object.

    Returns:
        tuple[ReplayDownloadResponseContractBranch, ...]: Mappingとして読めるbranch entryの
            解析結果.
    """
    return tuple(
        _response_contract_branch_from_entry(branch)
        for branch in _response_contract_branch_mappings(document)
    )


def _response_contract_branch_from_entry(
    branch: Mapping[str, object],
) -> ReplayDownloadResponseContractBranch:
    """Response contract branch entryをreport-safeなobjectへ変換する.

    Args:
        branch (Mapping[str, object]): Response contract branchのJSON object.

    Returns:
        ReplayDownloadResponseContractBranch: 欠損または型不正fieldを安全な既定値へ変換したbranch.
    """
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
    """Body assembly decision documentをtyped decisionへ変換する.

    Args:
        document (Mapping[str, object]): Body assembly decision fixtureのJSON object.

    Returns:
        ReplayDownloadBodyDecision: Decision mappingがない場合はblockedかつunverifiedの既定
            decision.
    """
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
    """Body decisionの安全な診断messageをfield名と値から組み立てる.

    Args:
        decision (Mapping[str, object]): Body assembly decision mapping.

    Returns:
        str: Status、strategy、任意blocker、任意format classificationを結合したmessage.
    """
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
    """Request metadataからtarget route contractを取り出しtyped objectへ変換する.

    Args:
        request_metadata (Mapping[str, object]): Target client request metadataのJSON object.

    Returns:
        ReplayDownloadTargetRouteContract: Route contractがない場合は空の安全なfieldを持つobject.
    """
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
    """Request/response captureをreport-safeなfixture viewへ変換する.

    Args:
        request_capture (Mapping[str, object]): Target client request captureのJSON object.
        response_capture (Mapping[str, object]): 対応するresponse captureのJSON object.

    Returns:
        ReplayDownloadSanitizedFixture: Raw valueを保持せずmetadataだけを持つfixture view.
    """
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
    """JSON object fixtureを読み込みmappingとして返す.

    Args:
        path (Path): 読み込むJSON fixture path.

    Returns:
        Mapping[str, object]: Top-level JSON objectのfield mapping.

    Raises:
        OSError: Fixture fileを開けない場合.
        json.JSONDecodeError: FixtureがJSONとして不正な場合.
        TypeError: Top-level valueがJSON objectでない場合.
    """
    parsed = cast("object", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(parsed, Mapping):
        raise TypeError(f"{path.name} must contain a JSON object")

    return cast("Mapping[str, object]", parsed)


def _captures_by_name(document: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    """Capture listをnameで引けるmappingへ変換する.

    Args:
        document (Mapping[str, object]): `captures` fieldを持ち得るfixture document.

    Returns:
        Mapping[str, Mapping[str, object]]: 文字列nameを持つcaptureだけを格納したmapping.
    """
    captures: dict[str, Mapping[str, object]] = {}
    for capture in _capture_mappings(document):
        name = capture.get("name")
        if not isinstance(name, str):
            continue

        captures[name] = capture

    return captures


def _capture_mappings(document: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    """Documentの`captures` sequenceからmapping entryだけを取り出す.

    Args:
        document (Mapping[str, object]): `captures` fieldを持ち得るfixture document.

    Returns:
        tuple[Mapping[str, object], ...]: Mappingとして読めるcapture entry。field不正時は空tuple.
    """
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
    """Documentの`references` sequenceからmapping entryだけを取り出す.

    Args:
        document (Mapping[str, object]): `references` fieldを持ち得るfixture document.

    Returns:
        tuple[Mapping[str, object], ...]: Mappingとして読めるreference entry。field不正時は空tuple.
    """
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
    """Documentの`branches` sequenceからmapping entryだけを取り出す.

    Args:
        document (Mapping[str, object]): `branches` fieldを持ち得るfixture document.

    Returns:
        tuple[Mapping[str, object], ...]: Mappingとして読めるbranch entry。field不正時は空tuple.
    """
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
    """Auth field sequenceをreport-safeなtyped field tupleへ変換する.

    Args:
        value (object): JSON fixtureから取得したauth field候補.

    Returns:
        tuple[ReplayDownloadAuthField, ...]: Mappingとして読めるauth fieldの解析結果。型不正時は
            空tuple.
    """
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
    """Auth field sequenceからmapping entryだけを取り出す.

    Args:
        value (object): JSON fixtureから取得したauth field候補.

    Returns:
        tuple[Mapping[str, object], ...]: Mappingとして読めるauth field entry。型不正時は空tuple.
    """
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
    """Entryにない必須field名をerror codeとして返す.

    Args:
        entry (Mapping[str, object]): 検査するJSON object.
        required_fields (frozenset[str]): 存在を要求するfield名の集合.

    Returns:
        tuple[str, ...]: `missing_required_fields:`接頭辞付きerror。欠落がなければ空tuple.
    """
    missing_fields = sorted(
        field_name for field_name in required_fields if field_name not in entry
    )
    if not missing_fields:
        return ()

    return (f"missing_required_fields:{','.join(missing_fields)}",)


def _missing_required_fields_with_prefix(
    entry: Mapping[str, object],
    required_fields: frozenset[str],
    prefix: str,
) -> tuple[str, ...]:
    """Entryにない必須field名を指定接頭辞のerror codeとして返す.

    Args:
        entry (Mapping[str, object]): 検査するJSON object.
        required_fields (frozenset[str]): 存在を要求するfield名の集合.
        prefix (str): Error codeへ付ける対象領域の接頭辞.

    Returns:
        tuple[str, ...]: 接頭辞付きmissing-field error。欠落がなければ空tuple.
    """
    missing_fields = sorted(
        field_name for field_name in required_fields if field_name not in entry
    )
    if not missing_fields:
        return ()

    return (f"{prefix}_missing_required_fields:{','.join(missing_fields)}",)


def _validate_string_list_field(
    entry: Mapping[str, object],
    key: str,
    *,
    required: bool = True,
    safe_token: bool = True,
) -> tuple[str, ...]:
    """Entryのfieldが安全な文字列listかを検証する.

    Args:
        entry (Mapping[str, object]): 検査するJSON object.
        key (str): 検査するfield名.
        required (bool): Noneを許容しない場合はTrue.
        safe_token (bool): 各文字列へ安全token制約を適用する場合はTrue.

    Returns:
        tuple[str, ...]: 型または安全性が不正な場合のerror code。正常時は空tuple.
    """
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
    """Entryのfieldが空でない文字列かを検証する.

    Args:
        entry (Mapping[str, object]): 検査するJSON object.
        key (str): 検査するfield名.
        safe_token (bool): 文字列へ安全token制約を適用する場合はTrue.

    Returns:
        tuple[str, ...]: 型または安全性が不正な場合のerror code。正常時は空tuple.
    """
    value = entry.get(key)
    if isinstance(value, str) and value and (not safe_token or _is_safe_metadata_token(value)):
        return ()

    return (f"{key}_must_be_safe_string",)


def _validate_optional_string_field(
    entry: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    """Entryの任意fieldがNoneまたは空でない文字列かを検証する.

    Args:
        entry (Mapping[str, object]): 検査するJSON object.
        key (str): 検査する任意field名.

    Returns:
        tuple[str, ...]: 値がNoneでも文字列でもない場合のerror code。正常時は空tuple.
    """
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
    """Observed flagと対応するvalue/note fieldの整合を検証する.

    Args:
        entry (Mapping[str, object]): 検査するJSON object.
        observed_key (str): 観測有無を示すbool field名.
        value_key (str): 観測値またはNoneを保持するfield名.
        note_key (str): 観測状況を補足する安全なnote field名.

    Returns:
        tuple[str, ...]: Flag、value、noteの不整合を示すerror code。正常時は空tuple.
    """
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
    """値が安全tokenだけから成る文字列sequenceか判定する.

    Args:
        value (object): 判定するJSON value.

    Returns:
        bool: 空を含むsequenceの全要素が安全な文字列ならTrue.
    """
    return _is_string_list(value, safe_token=True)


def _is_string_list(value: object, *, safe_token: bool) -> bool:
    """値が文字列sequenceかを任意の安全token制約付きで判定する.

    Args:
        value (object): 判定するJSON value.
        safe_token (bool): 各文字列へ安全token制約を適用する場合はTrue.

    Returns:
        bool: Valueが文字列やbytesでないsequenceかつ全要素が条件を満たす場合はTrue.
    """
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return False

    return all(
        isinstance(item, str) and (not safe_token or _is_safe_metadata_token(item))
        for item in value
    )


def _validate_int_field(entry: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Entryのfieldがboolではない整数かを検証する.

    Args:
        entry (Mapping[str, object]): 検査するJSON object.
        key (str): 検査するfield名.

    Returns:
        tuple[str, ...]: 整数でない場合のerror code。正常時は空tuple.
    """
    value = entry.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return ()

    return (f"{key}_must_be_int",)


def _validate_optional_int_field(
    entry: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    """Entryの任意fieldがNoneまたはboolではない整数かを検証する.

    Args:
        entry (Mapping[str, object]): 検査するJSON object.
        key (str): 検査する任意field名.

    Returns:
        tuple[str, ...]: Noneでも整数でもない場合のerror code。正常時は空tuple.
    """
    value = entry.get(key)
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return ()

    return (f"{key}_must_be_int_or_null",)


def _validate_bool_field(entry: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Entryのfieldがboolかを検証する.

    Args:
        entry (Mapping[str, object]): 検査するJSON object.
        key (str): 検査するfield名.

    Returns:
        tuple[str, ...]: Boolでない場合のerror code。正常時は空tuple.
    """
    if isinstance(entry.get(key), bool):
        return ()

    return (f"{key}_must_be_bool",)


def _is_safe_metadata_token(value: str) -> bool:
    """Metadata tokenにquery delimiterやkey-value delimiterが含まれないか判定する.

    Args:
        value (str): 判定するmetadata token.

    Returns:
        bool: `=`、`&`、`:`を含まない場合はTrue.
    """
    return "=" not in value and "&" not in value and ":" not in value


def _string_value(entry: Mapping[str, object], key: str) -> str:
    """Entryから文字列fieldを安全に取り出す.

    Args:
        entry (Mapping[str, object]): 値を取り出すJSON object.
        key (str): 取得するfield名.

    Returns:
        str: 値が文字列ならその値。それ以外は空文字列.
    """
    value = entry.get(key)
    if isinstance(value, str):
        return value

    return ""


def _optional_string_value(entry: Mapping[str, object], key: str) -> str | None:
    """Entryから任意の文字列fieldを安全に取り出す.

    Args:
        entry (Mapping[str, object]): 値を取り出すJSON object.
        key (str): 取得する任意field名.

    Returns:
        str | None: 値が文字列ならその値。Noneまたは型不正ならNone.
    """
    value = entry.get(key)
    if value is None:
        return None

    if isinstance(value, str):
        return value

    return None


def _bool_value(value: object) -> bool:
    """Objectからbool値だけを取り出す.

    Args:
        value (object): JSON objectから取得した値.

    Returns:
        bool: 値がboolならその値。それ以外はFalse.
    """
    if isinstance(value, bool):
        return value

    return False


def _optional_int_value(entry: Mapping[str, object], key: str) -> int | None:
    """Entryから任意のboolではない整数fieldを取り出す.

    Args:
        entry (Mapping[str, object]): 値を取り出すJSON object.
        key (str): 取得する任意field名.

    Returns:
        int | None: 値がboolではない整数ならその値。Noneまたは型不正ならNone.
    """
    value = entry.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value

    return None


def _verification_status_value(
    entry: Mapping[str, object],
    key: str,
) -> VerificationStatus:
    """Entryの文字列fieldをVerificationStatusへ変換する.

    Args:
        entry (Mapping[str, object]): 値を取り出すJSON object.
        key (str): VerificationStatus値を持つfield名.

    Returns:
        VerificationStatus: 有効なenum値。欠損または不正値はKNOWN_GAP.
    """
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
    """Entryの文字列fieldをReplayDownloadBlobIntegrityへ変換する.

    Args:
        entry (Mapping[str, object]): 値を取り出すJSON object.
        key (str): Blob integrity値を持つfield名.

    Returns:
        ReplayDownloadBlobIntegrity: 有効なenum値。欠損または不正値はUNAVAILABLE.
    """
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
    """Entryの文字列fieldをReplayDownloadBodyCompatibilityへ変換する.

    Args:
        entry (Mapping[str, object]): 値を取り出すJSON object.
        key (str): Body compatibility値を持つfield名.

    Returns:
        ReplayDownloadBodyCompatibility: 有効なenum値。欠損または不正値はLOCAL_ONLY_UNVERIFIED.
    """
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
    """Entryの文字列fieldをReplayDownloadBodyStrategyへ変換する.

    Args:
        entry (Mapping[str, object]): 値を取り出すJSON object.
        key (str): Download body strategy値を持つfield名.

    Returns:
        ReplayDownloadBodyStrategy: 有効なenum値。欠損または不正値はBLOCKED.
    """
    value = entry.get(key)
    if isinstance(value, str):
        try:
            return ReplayDownloadBodyStrategy(value)
        except ValueError:
            return ReplayDownloadBodyStrategy.BLOCKED

    return ReplayDownloadBodyStrategy.BLOCKED


def _string_tuple(value: object) -> tuple[str, ...]:
    """Sequenceから文字列要素だけを保持するtupleを作る.

    Args:
        value (object): JSON fixtureから取得したsequence候補.

    Returns:
        tuple[str, ...]: 文字列要素だけを元の順序で保持するtuple。型不正時は空tuple.
    """
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return ()

    return tuple(item for item in value if isinstance(item, str))


def _raw_values_committed(request_capture: Mapping[str, object]) -> bool:
    """Request captureがraw valueをcommitしたと示すか判定する.

    Args:
        request_capture (Mapping[str, object]): Target client request captureのJSON object.

    Returns:
        bool: `raw_values_committed`または後方互換の`query_values_committed`がTrueならTrue.
    """
    raw_values_committed = request_capture.get("raw_values_committed")
    if isinstance(raw_values_committed, bool):
        return raw_values_committed

    return _bool_value(request_capture.get("query_values_committed"))


def _validation_result_from_errors(
    prefix: str,
    reference: str,
    errors: tuple[str, ...],
) -> SurfaceResult:
    """Validation error code列をPASSまたはFAILのsurface resultへ変換する.

    Args:
        prefix (str): 診断messageへ付けるfixture種別の名前.
        reference (str): 検証したfixtureの参照名.
        errors (tuple[str, ...]): Report-safeなvalidation error code.

    Returns:
        SurfaceResult: Errorが空ならPASS、それ以外はredaction policy failureを表す結果.
    """
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
    """Replay download surfaceのmandatory golden fixture結果を組み立てる.

    Args:
        status (VerificationStatus): 検証の成否または可用性を表す状態.
        message (str): Report-safeな診断message.
        reference (str): Evidence fixtureの参照名.

    Returns:
        SurfaceResult: `StableSurface.REPLAY_DOWNLOAD`とmandatory scopeを持つ結果.
    """
    return SurfaceResult(
        surface=StableSurface.REPLAY_DOWNLOAD,
        status=status,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference=reference,
    )


def _sorted_unique(values: Sequence[str]) -> tuple[str, ...]:
    """文字列列から重複を除き辞書順に並べたtupleを返す.

    Args:
        values (Sequence[str]): 重複し得る文字列列.

    Returns:
        tuple[str, ...]: 重複を除いた昇順の文字列tuple.
    """
    return tuple(sorted(set(values)))


__all__ = [
    "ReplayDownloadEvidenceBundle",
    "build_replay_download_body_decision",
    "diagnose_replay_blob",
    "load_replay_download_fixtures",
    "validate_replay_download_fixtures",
]
