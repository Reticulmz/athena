from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def _empty_credential_fields() -> dict[str, str]:
    return {}


class StableSurface(StrEnum):
    REGISTRATION = "registration"
    BANCHO_LOGIN = "bancho_login"
    POLLING = "polling"
    CHAT = "chat"
    GETSCORES = "getscores"
    SCORE_SUBMIT = "score_submit"
    REPLAY_DOWNLOAD = "replay_download"


class EvidenceType(StrEnum):
    AUTOMATED_TEST = "automated_test"
    GOLDEN_FIXTURE = "golden_fixture"
    HEADLESS_PROBE = "headless_probe"


class EvidenceScope(StrEnum):
    MANDATORY = "mandatory"
    OPTIONAL = "optional"


class SurfaceScope(StrEnum):
    IN_SCOPE = "in_scope"
    OUT_OF_SCOPE = "out_of_scope"


class VerificationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    KNOWN_GAP = "known_gap"
    UNAVAILABLE = "unavailable"


class ReplayDownloadResponseBranch(StrEnum):
    """Replay download response branch を verification evidence で表す."""

    SUCCESS = "success"
    AUTH_FAILURE = "auth_failure"
    MISSING_REPLAY = "missing_replay"
    HIDDEN_SCORE = "hidden_score"
    STORAGE_MISSING = "storage_missing"
    MISSING_SCORE_ID = "missing_score_id"
    MALFORMED_SCORE_ID = "malformed_score_id"
    MISSING_MODE = "missing_mode"
    MALFORMED_MODE = "malformed_mode"
    UNKNOWN_FIELD = "unknown_field"
    ALIAS = "alias"


class ReplayDownloadBlobIntegrity(StrEnum):
    """Replay blob integrity check の report-safe status を表す."""

    PASS = "pass"
    FAIL = "fail"
    UNAVAILABLE = "unavailable"
    NOT_CHECKED = "not_checked"


class ReplayDownloadBodyCompatibility(StrEnum):
    """Replay download response body の target-client compatibility を表す."""

    PASS = "pass"
    FAIL = "fail"
    LOCAL_ONLY_UNVERIFIED = "local_only_unverified"
    NOT_CHECKED = "not_checked"


class ReplayDownloadBodyStrategy(StrEnum):
    """Replay download response body の assembly 方針を表す."""

    DIRECT_BLOB_BYTES = "direct_blob_bytes"
    ASSEMBLE_DOWNLOAD_BODY = "assemble_download_body"
    BLOCKED = "blocked"


class ReplayBlobDiagnosticClassification(StrEnum):
    """Replay blob diagnostic result の分類を report-safe に表す."""

    INTEGRITY_PASS = "integrity_pass"
    STORAGE_INTEGRITY_FAILURE = "storage_integrity_failure"
    MISSING_SCORE = "missing_score"
    MISSING_REPLAY = "missing_replay"
    MISSING_BLOB_METADATA = "missing_blob_metadata"
    MISSING_STORAGE_OBJECT = "missing_storage_object"


@dataclass(frozen=True, slots=True)
class StableTarget:
    base_url: str
    host_identity: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class GetscoresProbeCase:
    name: str
    checksum: str
    filename: str
    beatmapset_id: int | None
    mode: int
    mods: int
    leaderboard_type: str
    request_version: int


@dataclass(frozen=True, slots=True)
class SurfaceInventoryEntry:
    surface: StableSurface
    implemented: bool
    scope: SurfaceScope
    description: str


@dataclass(frozen=True, slots=True)
class EvidenceEntry:
    surface: StableSurface
    evidence_type: EvidenceType
    scope: EvidenceScope
    reference: str
    purpose: str


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    surface: StableSurface
    status: VerificationStatus
    summary: str
    owner: str


@dataclass(frozen=True, slots=True)
class DiagnosticSummary:
    message: str
    method: str | None = None
    path: str | None = None
    status_code: int | None = None
    response_byte_size: int | None = None
    sanitized_error: str | None = None


@dataclass(frozen=True, slots=True)
class SecretProbeInput:
    password: str | None = field(default=None, repr=False)
    password_hash: str | None = field(default=None, repr=False)
    session_token: str | None = field(default=None, repr=False)
    raw_replay: bytes | None = field(default=None, repr=False)
    credential_fields: Mapping[str, str] = field(
        default_factory=_empty_credential_fields,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class ReplayDownloadAuthField:
    """Replay download auth field の名前と redacted category を表す.

    Raw credential value は保持しない. value_committed は fixture に raw value が
    入っていないことを validator が確認するための metadata である.
    """

    name: str
    category: str
    value_committed: bool = False


@dataclass(frozen=True, slots=True)
class ReplayDownloadTargetRouteContract:
    """Target stable client から観測した replay download route contract を表す.

    Primary route と alias route の target traffic 観測状態を分けて保持する.
    Reference-only alias を current target-client required route と混同しないための
    report-safe metadata であり、raw query values や credential values は保持しない.
    """

    primary_route: str
    primary_route_observed_in_target_client_traffic: bool
    primary_route_classification: str
    alias_route: str
    alias_route_observed_in_target_client_traffic: bool
    alias_policy: str
    route_evidence_source: str
    route_evidence_fixture_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayDownloadSanitizedFixture:
    """Replay download sanitized fixture metadata を verification 語彙で表す.

    Query values, credential values, raw replay bytes, complete .osr bytes は
    field として持たない. Raw artifact は repository 外の local-only 証跡として扱う.
    """

    target_client_family: str
    target_build_observed: bool
    target_build: str | None
    target_build_note: str
    osuver_observed: bool
    osuver: str | None
    osuver_note: str
    user_agent: str
    captured_at: str
    workflow_entrance: str
    route_classification: str
    target_route_observed: bool
    alias_routes_observed: tuple[str, ...]
    method: str
    path: str
    query_keys: tuple[str, ...]
    auth_fields: tuple[ReplayDownloadAuthField, ...]
    response_status: int | None = None
    response_header_keys_observed: tuple[str, ...] = ()
    complete_response_header_key_set_observed: bool = False
    body_kind: str | None = None
    body_byte_size: int | None = None
    safe_body_sha256: str | None = field(default=None, repr=False)
    raw_values_committed: bool = False
    evidence_type: EvidenceType = EvidenceType.GOLDEN_FIXTURE
    scope: EvidenceScope = EvidenceScope.MANDATORY
    surface: StableSurface = field(
        default=StableSurface.REPLAY_DOWNLOAD,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class ReplayDownloadResponseBranchEvidence:
    """Replay download response branch evidence を SurfaceResult と同じ語彙で表す.

    Body は kind, byte size, safe hash metadata だけを保持する. Raw body bytes と
    complete .osr bytes は保持しない.
    """

    branch: ReplayDownloadResponseBranch
    status: VerificationStatus
    evidence_type: EvidenceType
    scope: EvidenceScope
    diagnostic_summary: DiagnosticSummary
    response_status: int | None = None
    response_header_keys_observed: tuple[str, ...] = ()
    complete_response_header_key_set_observed: bool = False
    body_kind: str | None = None
    body_byte_size: int | None = None
    safe_body_sha256: str | None = field(default=None, repr=False)
    reference: str | None = None
    surface: StableSurface = field(
        default=StableSurface.REPLAY_DOWNLOAD,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class ReplayDownloadReferenceResponseEvidence:
    """Replay download reference implementation audit の 1 branch を表す.

    Reference source, branch, route, status, header key metadata, body kind,
    unresolved reason を保持する. Raw response body, raw credential value,
    raw replay bytes は保持しない.
    """

    name: str
    source: str
    source_role: str
    repository: str
    commit: str
    source_paths: tuple[str, ...]
    branch: str
    route: str
    method: str
    request_keys: tuple[str, ...]
    auth_fields: tuple[ReplayDownloadAuthField, ...]
    response_status: int | None
    response_header_keys_observed: tuple[str, ...]
    complete_response_header_key_set_observed: bool
    body_kind: str
    contract_status: str
    unresolved_reason: str | None


@dataclass(frozen=True, slots=True)
class ReplayDownloadBodyDecision:
    """Replay download body assembly decision を verification 語彙で表す.

    Decision は direct blob bytes, assembled body, blocked のいずれかを示す.
    Raw replay bytes と complete .osr bytes は保持しない.
    """

    blob_integrity: ReplayDownloadBlobIntegrity
    target_body_compatible: ReplayDownloadBodyCompatibility
    download_body_strategy: ReplayDownloadBodyStrategy
    status: VerificationStatus
    evidence_type: EvidenceType
    scope: EvidenceScope
    diagnostic_summary: DiagnosticSummary
    evidence_references: tuple[str, ...] = ()
    surface: StableSurface = field(
        default=StableSurface.REPLAY_DOWNLOAD,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class ReplayBlobDiagnosticResult:
    """Replay blob diagnostic の report-safe result を表す.

    Storage existence, size, SHA-256 comparison result と classification だけを
    返す. Raw replay bytes, credential-like value, complete .osr bytes は保持しない.
    """

    score_found: bool
    replay_attachment_found: bool
    blob_found: bool
    storage_object_found: bool
    metadata_sha256: str | None = field(repr=False)
    observed_sha256: str | None = field(repr=False)
    metadata_byte_size: int | None
    observed_byte_size: int | None
    classification: ReplayBlobDiagnosticClassification
    status: VerificationStatus
    diagnostic_summary: DiagnosticSummary
    evidence_type: EvidenceType = EvidenceType.AUTOMATED_TEST
    scope: EvidenceScope = EvidenceScope.OPTIONAL
    surface: StableSurface = field(
        default=StableSurface.REPLAY_DOWNLOAD,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class SurfaceResult:
    surface: StableSurface
    status: VerificationStatus
    evidence_type: EvidenceType
    scope: EvidenceScope
    diagnostic_summary: DiagnosticSummary
    reference: str | None = None

    @property
    def fails_run(self) -> bool:
        if self.status is VerificationStatus.FAIL:
            return True

        return (
            self.scope is EvidenceScope.MANDATORY and self.status is VerificationStatus.UNAVAILABLE
        )


@dataclass(frozen=True, slots=True)
class VerificationRunResult:
    target: StableTarget | None
    results: tuple[SurfaceResult, ...]

    @property
    def failed(self) -> bool:
        return any(result.fails_run for result in self.results)


__all__ = [
    "DiagnosticSummary",
    "EvidenceEntry",
    "EvidenceGap",
    "EvidenceScope",
    "EvidenceType",
    "GetscoresProbeCase",
    "ReplayBlobDiagnosticClassification",
    "ReplayBlobDiagnosticResult",
    "ReplayDownloadAuthField",
    "ReplayDownloadBlobIntegrity",
    "ReplayDownloadBodyCompatibility",
    "ReplayDownloadBodyDecision",
    "ReplayDownloadBodyStrategy",
    "ReplayDownloadReferenceResponseEvidence",
    "ReplayDownloadResponseBranch",
    "ReplayDownloadResponseBranchEvidence",
    "ReplayDownloadSanitizedFixture",
    "ReplayDownloadTargetRouteContract",
    "SecretProbeInput",
    "StableSurface",
    "StableTarget",
    "SurfaceInventoryEntry",
    "SurfaceResult",
    "SurfaceScope",
    "VerificationRunResult",
    "VerificationStatus",
]
