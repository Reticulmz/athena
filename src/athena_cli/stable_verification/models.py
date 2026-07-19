"""Stable verificationで共有するreport-safeな値オブジェクトを定義する."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def _empty_credential_fields() -> dict[str, str]:
    """SecretProbeInput用の空credential mappingを生成する.

    Returns:
        dict[str, str]: 呼出しごとに独立した空のcredential field mapping。
    """
    return {}


class StableSurface(StrEnum):
    """Stable verificationが扱う互換surfaceを表す.

    Attributes:
        REGISTRATION (str): Legacy web endpointによるaccount registration。
        BANCHO_LOGIN (str): Stable bancho login requestとpacket-stream response。
        POLLING (str): Token認証済みbancho polling。
        CHAT (str): Channelとprivate chatのpacket flow。
        GETSCORES (str): Legacy getscores endpointとtext response。
        SCORE_SUBMIT (str): Modular score submissionとchart response。
        REPLAY_DOWNLOAD (str): Replay download endpoint contract。
    """

    REGISTRATION = "registration"
    BANCHO_LOGIN = "bancho_login"
    POLLING = "polling"
    CHAT = "chat"
    GETSCORES = "getscores"
    SCORE_SUBMIT = "score_submit"
    REPLAY_DOWNLOAD = "replay_download"


class EvidenceType(StrEnum):
    """Stable verification evidenceの取得手段を表す.

    Attributes:
        AUTOMATED_TEST (str): 自動testで検証したevidence。
        GOLDEN_FIXTURE (str): 固定fixtureで検証したevidence。
        HEADLESS_PROBE (str): Client-like headless probeで取得したevidence。
    """

    AUTOMATED_TEST = "automated_test"
    GOLDEN_FIXTURE = "golden_fixture"
    HEADLESS_PROBE = "headless_probe"


class EvidenceScope(StrEnum):
    """Evidenceがverification runの成否へ与える強さを表す.

    Attributes:
        MANDATORY (str): FAILまたはUNAVAILABLEをrun failureとして扱うevidence。
        OPTIONAL (str): 不可用またはskipでもrun failureにしない補助evidence。
    """

    MANDATORY = "mandatory"
    OPTIONAL = "optional"


class SurfaceScope(StrEnum):
    """Stable surfaceが現在のverification対象かを表す.

    Attributes:
        IN_SCOPE (str): 現在のverification catalogで扱うsurface。
        OUT_OF_SCOPE (str): 現在のverification対象外のsurface。
    """

    IN_SCOPE = "in_scope"
    OUT_OF_SCOPE = "out_of_scope"


class VerificationStatus(StrEnum):
    """Stable verification結果の状態を表す.

    Attributes:
        PASS (str): Contractを満たした状態。
        FAIL (str): Mandatory contractに違反した状態。
        SKIP (str): 前提不足などにより実行しなかった状態。
        KNOWN_GAP (str): 既知の未実装または未確認contractがある状態。
        UNAVAILABLE (str): 必要なdataまたは外部条件を利用できない状態。
    """

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    KNOWN_GAP = "known_gap"
    UNAVAILABLE = "unavailable"


class ReplayDownloadResponseBranch(StrEnum):
    """Replay download response branchをverification evidenceで表す.

    Attributes:
        SUCCESS (str): Replay bodyを返す成功branch。
        AUTH_FAILURE (str): 認証に失敗したbranch。
        MISSING_REPLAY (str): Replay attachmentがないbranch。
        HIDDEN_SCORE (str): 表示を許可しないscoreのbranch。
        STORAGE_MISSING (str): Storage objectがないbranch。
        MISSING_SCORE_ID (str): Score IDが欠落したbranch。
        MALFORMED_SCORE_ID (str): Score IDが不正なbranch。
        MISSING_MODE (str): Mode fieldが欠落したbranch。
        MALFORMED_MODE (str): Mode fieldが不正なbranch。
        UNKNOWN_FIELD (str): 未知fieldを含むrequest branch。
        ALIAS (str): Reference-only alias routeのbranch。
    """

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
    """Replay blob integrity checkのreport-safe statusを表す.

    Attributes:
        PASS (str): Metadataとstorage objectのintegrityが一致した状態。
        FAIL (str): Hashまたはbyte sizeのintegrityが不一致の状態。
        UNAVAILABLE (str): 必要なmetadataまたはstorage objectを取得できない状態。
        NOT_CHECKED (str): Integrity checkを実行していない状態。
    """

    PASS = "pass"
    FAIL = "fail"
    UNAVAILABLE = "unavailable"
    NOT_CHECKED = "not_checked"


class ReplayDownloadBodyCompatibility(StrEnum):
    """Replay download response bodyのtarget-client compatibilityを表す.

    Attributes:
        PASS (str): Target clientで互換性を確認したbody。
        FAIL (str): Target clientで非互換と確認したbody。
        LOCAL_ONLY_UNVERIFIED (str): Local validationだけでtarget client未確認のbody。
        NOT_CHECKED (str): Body compatibilityを確認していない状態。
    """

    PASS = "pass"
    FAIL = "fail"
    LOCAL_ONLY_UNVERIFIED = "local_only_unverified"
    NOT_CHECKED = "not_checked"


class ReplayDownloadBodyStrategy(StrEnum):
    """Replay download response bodyのassembly方針を表す.

    Attributes:
        DIRECT_BLOB_BYTES (str): Storage blob bytesを直接返す方針。
        ASSEMBLE_DOWNLOAD_BODY (str): Download response bodyを組み立てる方針。
        BLOCKED (str): Evidence不足によりsuccess responseを許可しない方針。
    """

    DIRECT_BLOB_BYTES = "direct_blob_bytes"
    ASSEMBLE_DOWNLOAD_BODY = "assemble_download_body"
    BLOCKED = "blocked"


class ReplayBlobDiagnosticClassification(StrEnum):
    """Replay blob diagnostic resultの分類をreport-safeに表す.

    Attributes:
        INTEGRITY_PASS (str): Replay metadataとstorage objectが整合した分類。
        STORAGE_INTEGRITY_FAILURE (str): Storage integrityが不一致の分類。
        MISSING_SCORE (str): Scoreが存在しない分類。
        MISSING_REPLAY (str): Replay attachmentが存在しない分類。
        MISSING_BLOB_METADATA (str): Blob metadataが存在しない分類。
        MISSING_STORAGE_OBJECT (str): Storage objectが存在しない分類。
    """

    INTEGRITY_PASS = "integrity_pass"
    STORAGE_INTEGRITY_FAILURE = "storage_integrity_failure"
    MISSING_SCORE = "missing_score"
    MISSING_REPLAY = "missing_replay"
    MISSING_BLOB_METADATA = "missing_blob_metadata"
    MISSING_STORAGE_OBJECT = "missing_storage_object"


@dataclass(frozen=True, slots=True)
class ReplayBlobDiagnosticInput:
    """Replay blob diagnostic procedureの入力を表す.

    Attributes:
        score_id (int): 診断対象のscore ID。

    Notes:
        Raw replay bytes、credential-like value、complete `.osr` bytesは保持しない。
    """

    score_id: int


@dataclass(frozen=True, slots=True)
class ReplayBlobAttachmentRecord:
    """Scoreに紐づくreplay attachmentのreport-safe viewを表す.

    Attributes:
        score_id (int): Replay attachmentが属するscore ID。
        blob_id (int): Replay bytesを参照するblob metadata ID。

    Notes:
        Attachment lookup結果のうちdiagnosticに必要なIDだけを保持する。
    """

    score_id: int
    blob_id: int


@dataclass(frozen=True, slots=True)
class ReplayBlobMetadataRecord:
    """Replay blob metadataのdiagnostic用report-safe viewを表す.

    Attributes:
        blob_id (int): Blob metadata ID。
        sha256 (str): Blob metadataが保持するSHA-256 digest。reprには含めない。
        byte_size (int): Blob metadataが保持するbyte size。
        storage_key (str): Backend objectを読むstorage key。reprとreporter outputには含めない。

    Notes:
        Raw replay bytes、credential-like value、complete `.osr` bytesは保持しない。
    """

    blob_id: int
    sha256: str = field(repr=False)
    byte_size: int
    storage_key: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class StableTarget:
    """Stable verification probeの接続先を表す.

    Attributes:
        base_url (str): Probe requestを送るHTTP base URL。
        host_identity (str): Host headerに使うstable host identity。
        timeout_seconds (float): HTTP requestに適用するtimeout秒数。
    """

    base_url: str
    host_identity: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class GetscoresProbeCase:
    """Stable getscores target probeへ送るquery field群を表す.

    Attributes:
        name (str): Reportで識別するprobe case名。
        checksum (str): Requestの`c` fieldへ送るbeatmap checksum。
        filename (str): Requestの`f` fieldへ送るbeatmap filename。
        beatmapset_id (int | None): 任意の`i` field。Noneならqueryへ含めない。
        mode (int): Requestの`m` fieldへ送るmode値。
        mods (int): Requestの`mods` fieldへ送るmod bitmask。
        leaderboard_type (str): Requestの`v` fieldへ変換するselector。
        request_version (int): Requestの`vv` fieldへ送るversion値。
    """

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
    """Stable verification catalog内のsurfaceの実装状態を表す.

    Attributes:
        surface (StableSurface): Catalog対象のstable surface。
        implemented (bool): Athena側の実装が完了しているか。
        scope (SurfaceScope): 現在のverification対象scope。
        description (str): Surface責務を示す英語のcatalog説明。
    """

    surface: StableSurface
    implemented: bool
    scope: SurfaceScope
    description: str


@dataclass(frozen=True, slots=True)
class EvidenceEntry:
    """Stable surfaceを支える1件のverification evidenceを表す.

    Attributes:
        surface (StableSurface): Evidenceが対象にするstable surface。
        evidence_type (EvidenceType): Evidenceの取得手段。
        scope (EvidenceScope): Run failureへの影響範囲。
        reference (str): Fixture、test、またはprobeを指すcatalog reference。
        purpose (str): Evidenceが検証するcontractを示す説明。
    """

    surface: StableSurface
    evidence_type: EvidenceType
    scope: EvidenceScope
    reference: str
    purpose: str


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    """Stable compatibilityで既知の未確認または未完了事項を表す.

    Attributes:
        surface (StableSurface): Gapが属するstable surface。
        status (VerificationStatus): 通常はKNOWN_GAPである状態。
        summary (str): Gapの内容を示すreport-safeな説明。
        owner (str): Gapを引き継ぐissueまたはcomponent。
    """

    surface: StableSurface
    status: VerificationStatus
    summary: str
    owner: str


@dataclass(frozen=True, slots=True)
class DiagnosticSummary:
    """Verification resultへ公開してよい通信診断の要約を表す.

    Attributes:
        message (str): Reportに出すredaction済みの診断文言。
        method (str | None): 実行したHTTP method。未取得時はNone。
        path (str | None): 対象path。未取得時はNone。
        status_code (int | None): HTTP status code。未取得時はNone。
        response_byte_size (int | None): Response bodyのbyte size。未取得時はNone。
        sanitized_error (str | None): Targetやhostを伏せた通信error。未発生時はNone。
    """

    message: str
    method: str | None = None
    path: str | None = None
    status_code: int | None = None
    response_byte_size: int | None = None
    sanitized_error: str | None = None


@dataclass(frozen=True, slots=True)
class SecretProbeInput:
    """Probe実行時だけ利用するsecret-bearing inputを表す.

    Attributes:
        password (str | None): Probe用password。reprには含めない。
        password_hash (str | None): Probe用password hash。reprには含めない。
        session_token (str | None): Probe用session token。reprには含めない。
        raw_replay (bytes | None): Probe用raw replay bytes。reprには含めない。
        credential_fields (Mapping[str, str]): 追加credential field。reprには含めない。

    Notes:
        この型をreportable diagnosticまたはcatalog evidenceへ渡してはならない。
    """

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
    """Replay download auth fieldの名前とredacted categoryを表す.

    Attributes:
        name (str): Request内のauth field名。
        category (str): Raw valueを含まないfieldの分類。
        value_committed (bool): Fixtureへraw valueが記録されているかを示すmetadata。

    Notes:
        Raw credential valueは保持しない。validatorは`value_committed`でfixtureへのraw value
        混入を検出する。
    """

    name: str
    category: str
    value_committed: bool = False


@dataclass(frozen=True, slots=True)
class ReplayDownloadTargetRouteContract:
    """Target stable clientから観測したreplay download route contractを表す.

    Attributes:
        primary_route (str): Target clientが使うprimary route。
        primary_route_observed_in_target_client_traffic (bool): Primary routeをtrafficで
            観測したか。
        primary_route_classification (str): Primary routeのevidence分類。
        alias_route (str): 比較対象のreference-only alias route。
        alias_route_observed_in_target_client_traffic (bool): Alias routeをtrafficで観測したか。
        alias_policy (str): Aliasをcurrent required routeと混同しないための方針。
        route_evidence_source (str): Route contractを支えるevidence source。
        route_evidence_fixture_names (tuple[str, ...]): Route evidenceを記録するfixture名。

    Notes:
        Primary routeとalias routeのtarget traffic観測状態を分離する。raw query valueとcredential
        valueは保持しない。
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
    """Replay download sanitized fixture metadataをverification語彙で表す.

    Attributes:
        target_client_family (str): 観測対象のclient family。
        target_build_observed (bool): Target buildを観測できたか。
        target_build (str | None): 観測済みtarget build。未観測時はNone。
        target_build_note (str): Target build未観測時を含む説明。
        osuver_observed (bool): `osuver`を観測できたか。
        osuver (str | None): 観測済み`osuver`。未観測時はNone。
        osuver_note (str): `osuver`未観測時を含む説明。
        user_agent (str): Requestで観測したUser-Agent分類。
        captured_at (str): Fixture metadataを取得した時刻。
        workflow_entrance (str): Requestが入ったworkflow入口。
        route_classification (str): 観測routeの分類。
        target_route_observed (bool): Target client trafficでrouteを観測したか。
        alias_routes_observed (tuple[str, ...]): 観測したalias routeの一覧。
        method (str): 観測したHTTP method。
        path (str): Raw queryを除いたrequest path。
        query_keys (tuple[str, ...]): 値を除いたquery field名。
        auth_fields (tuple[ReplayDownloadAuthField, ...]): Redacted auth field metadata。
        response_status (int | None): 観測したHTTP status。未観測時はNone。
        response_header_keys_observed (tuple[str, ...]): 観測したresponse header名。
        complete_response_header_key_set_observed (bool): Header key集合を完全に観測したか。
        body_kind (str | None): Response bodyの分類。未観測時はNone。
        body_byte_size (int | None): Response bodyのbyte size。未観測時はNone。
        safe_body_sha256 (str | None): Report-safeなbody digest。reprには含めない。
        raw_values_committed (bool): Fixtureへraw valueが混入したかを示すmetadata。
        evidence_type (EvidenceType): Fixture evidenceの取得手段。
        scope (EvidenceScope): Fixture evidenceのrun scope。
        surface (StableSurface): 固定のREPLAY_DOWNLOAD surface。

    Notes:
        Query value、credential value、raw replay bytes、complete `.osr` bytesはfieldとして
        持たない。
        Raw artifactはrepository外のlocal-only証跡として扱う。
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
    """Replay download response branch evidenceをSurfaceResultと同じ語彙で表す.

    Attributes:
        branch (ReplayDownloadResponseBranch): 検証したresponse branch。
        status (VerificationStatus): Branchのverification状態。
        evidence_type (EvidenceType): Evidenceの取得手段。
        scope (EvidenceScope): Evidenceのrun scope。
        diagnostic_summary (DiagnosticSummary): Report-safeなbranch診断。
        response_status (int | None): Observed HTTP status。未観測時はNone。
        response_header_keys_observed (tuple[str, ...]): Observed response header名。
        complete_response_header_key_set_observed (bool): Header key集合を完全観測したか。
        body_kind (str | None): Bodyの分類。未観測時はNone。
        body_byte_size (int | None): Bodyのbyte size。未観測時はNone。
        safe_body_sha256 (str | None): Report-safeなbody digest。reprには含めない。
        reference (str | None): Evidenceを指すreference。未設定時はNone。
        surface (StableSurface): 固定のREPLAY_DOWNLOAD surface。

    Notes:
        Bodyはkind、byte size、safe hash metadataだけを保持する。raw body bytesとcomplete `.osr`
        bytesは保持しない。
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
    """Replay download reference implementation auditの1 branchを表す.

    Attributes:
        name (str): Audit対象branchの識別名。
        source (str): Reference sourceの短い識別子。
        source_role (str): Referenceが果たす比較上の役割。
        repository (str): Reference implementationのrepository名。
        commit (str): 監査したrevision identifier。
        source_paths (tuple[str, ...]): 調査したsource path。
        branch (str): 対応するresponse branch名。
        route (str): Reference implementationのroute。
        method (str): Reference requestのHTTP method。
        request_keys (tuple[str, ...]): 値を除いたrequest key名。
        auth_fields (tuple[ReplayDownloadAuthField, ...]): Redacted auth field metadata。
        response_status (int | None): Reference response status。未確認時はNone。
        response_header_keys_observed (tuple[str, ...]): Observed response header名。
        complete_response_header_key_set_observed (bool): Header key集合を完全観測したか。
        body_kind (str): Reference bodyの分類。
        contract_status (str): Reference evidenceの契約確度。
        unresolved_reason (str | None): 未解決理由。なければNone。

    Notes:
        Raw response body、raw credential value、raw replay bytesは保持しない。
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
class ReplayDownloadResponseContractBranch:
    """Replay download response contractのbranch readinessを表す.

    Attributes:
        branch (str): Response branchの識別名。
        status_label (str): Evidence状態を示すlabel。
        readiness (str): 実装可能性を示すreadiness。
        selected_response_status (int | None): 選定したHTTP status。未選定時はNone。
        selected_header_keys (tuple[str, ...]): 選定したresponse header名。
        selected_body_kind (str | None): 選定したbody分類。未選定時はNone。
        selected_body_byte_size (int | None): 選定したbody byte size。未選定時はNone。
        selected_safe_body_sha256 (str | None): 選定したsafe body digest。reprには含めない。
        evidence_sources (tuple[str, ...]): 選定根拠のreference。
        blocker (str | None): 未解決のblocker。なければNone。
        notes (tuple[str, ...]): Branch判断の補足。

    Notes:
        Raw body bytes、raw credential value、raw replay bytesは保持しない。
    """

    branch: str
    status_label: str
    readiness: str
    selected_response_status: int | None
    selected_header_keys: tuple[str, ...]
    selected_body_kind: str | None
    selected_body_byte_size: int | None
    selected_safe_body_sha256: str | None = field(repr=False)
    evidence_sources: tuple[str, ...]
    blocker: str | None
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayDownloadBodyDecision:
    """Replay download body assembly decisionをverification語彙で表す.

    Attributes:
        blob_integrity (ReplayDownloadBlobIntegrity): Blob integrity checkの結果。
        target_body_compatible (ReplayDownloadBodyCompatibility): Target client body互換性。
        download_body_strategy (ReplayDownloadBodyStrategy): 選定したbody assembly方針。
        status (VerificationStatus): Decisionのverification状態。
        evidence_type (EvidenceType): Decisionを支えるevidenceの取得手段。
        scope (EvidenceScope): Decision evidenceのrun scope。
        diagnostic_summary (DiagnosticSummary): Report-safeなdecision診断。
        evidence_references (tuple[str, ...]): Decisionを支えるreference。
        surface (StableSurface): 固定のREPLAY_DOWNLOAD surface。

    Notes:
        Decisionはdirect blob bytes、assembled body、blockedのいずれかを示す。raw replay bytesと
        complete `.osr` bytesは保持しない。
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

    @property
    def success_response_allowed(self) -> bool:
        """Success HTTP 200 responseを返してよいdecisionかを判定する.

        Returns:
            bool: Local validation済みの`direct_blob_bytes`または`assemble_download_body` decision
                の場合だけTrue。

        Notes:
            blocked、known_gap、unavailable、storage integrity failureではsuccess responseを
            許可しない。
            Raw replay bytes、complete `.osr` bytes、credential-like valueは参照しない。
        """
        if self.status is not VerificationStatus.PASS:
            return False

        if self.download_body_strategy is ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES:
            return (
                self.blob_integrity is ReplayDownloadBlobIntegrity.PASS
                and self.target_body_compatible is ReplayDownloadBodyCompatibility.PASS
            )

        if self.download_body_strategy is ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY:
            return (
                self.blob_integrity is ReplayDownloadBlobIntegrity.PASS
                and self.target_body_compatible is ReplayDownloadBodyCompatibility.FAIL
            )

        return False


@dataclass(frozen=True, slots=True)
class ReplayBlobDiagnosticResult:
    """Replay blob diagnosticのreport-safe resultを表す.

    Attributes:
        score_found (bool): Score recordを見つけたか。
        replay_attachment_found (bool): Replay attachmentを見つけたか。
        blob_found (bool): Blob metadataを見つけたか。
        storage_object_found (bool): Storage objectを見つけたか。
        metadata_sha256 (str | None): Metadata側SHA-256。reprには含めない。
        observed_sha256 (str | None): Storage object側SHA-256。reprには含めない。
        metadata_byte_size (int | None): Metadata側byte size。
        observed_byte_size (int | None): Storage object側byte size。
        classification (ReplayBlobDiagnosticClassification): Report-safeな診断分類。
        status (VerificationStatus): Diagnosticのverification状態。
        diagnostic_summary (DiagnosticSummary): Report-safeな診断文言。
        evidence_type (EvidenceType): Diagnostic evidenceの取得手段。
        scope (EvidenceScope): Diagnostic evidenceのrun scope。
        surface (StableSurface): 固定のREPLAY_DOWNLOAD surface。

    Notes:
        Storage existence、size、SHA-256 comparison resultとclassificationだけを返す。raw replay
        bytes、credential-like value、complete `.osr` bytesは保持しない。
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
    """1件のstable verification evidenceの判定結果を表す.

    Attributes:
        surface (StableSurface): 判定対象のstable surface。
        status (VerificationStatus): Evidenceの検証状態。
        evidence_type (EvidenceType): Evidenceの取得手段。
        scope (EvidenceScope): Run failureへの影響範囲。
        diagnostic_summary (DiagnosticSummary): Report-safeな診断。
        reference (str | None): Evidenceを指すreference。未設定時はNone。
    """

    surface: StableSurface
    status: VerificationStatus
    evidence_type: EvidenceType
    scope: EvidenceScope
    diagnostic_summary: DiagnosticSummary
    reference: str | None = None

    @property
    def fails_run(self) -> bool:
        """このevidenceがverification runを失敗させるか判定する.

        Returns:
            bool: FAIL、またはmandatory scopeでUNAVAILABLEの場合はTrue。

        Notes:
            Optional evidenceのUNAVAILABLEとSKIPはrun failureにしない。
        """
        if self.status is VerificationStatus.FAIL:
            return True

        return (
            self.scope is EvidenceScope.MANDATORY and self.status is VerificationStatus.UNAVAILABLE
        )


@dataclass(frozen=True, slots=True)
class VerificationRunResult:
    """Stable verification run全体の結果を表す.

    Attributes:
        target (StableTarget | None): Probe target。fixture-only runではNone。
        results (tuple[SurfaceResult, ...]): Surfaceごとのevidence結果。
    """

    target: StableTarget | None
    results: tuple[SurfaceResult, ...]

    @property
    def failed(self) -> bool:
        """Mandatory evidenceにrun failureが含まれるか判定する.

        Returns:
            bool: 1件以上のSurfaceResultが`fails_run`ならTrue。
        """
        return any(result.fails_run for result in self.results)


__all__ = [
    "DiagnosticSummary",
    "EvidenceEntry",
    "EvidenceGap",
    "EvidenceScope",
    "EvidenceType",
    "GetscoresProbeCase",
    "ReplayBlobAttachmentRecord",
    "ReplayBlobDiagnosticClassification",
    "ReplayBlobDiagnosticInput",
    "ReplayBlobDiagnosticResult",
    "ReplayBlobMetadataRecord",
    "ReplayDownloadAuthField",
    "ReplayDownloadBlobIntegrity",
    "ReplayDownloadBodyCompatibility",
    "ReplayDownloadBodyDecision",
    "ReplayDownloadBodyStrategy",
    "ReplayDownloadReferenceResponseEvidence",
    "ReplayDownloadResponseBranch",
    "ReplayDownloadResponseBranchEvidence",
    "ReplayDownloadResponseContractBranch",
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
