"""Modern getscores completion evidence の typed manifest boundary。"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import cast, final

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    StableSurface,
    SurfaceResult,
    VerificationStatus,
)
from osu_server.domain.beatmaps.models import BeatmapRankStatus
from osu_server.domain.compatibility.stable.getscores import GetscoresParseWarning
from osu_server.domain.scores.personal_best import LeaderboardCategory

_RESPONSE_SHAPES_FILE = "response_shapes.json"
_BRANCH_CASES_FILE = "branch_cases.json"
_STATUS_CROSSWALK_FILE = "beatmap_status_crosswalk.json"

_RESPONSE_SHAPES_SCHEMA = "athena.stable_compatibility.getscores.response_shapes.v1"
_BRANCH_CASES_SCHEMA = "athena.stable_compatibility.getscores.branch_cases.v1"
_STATUS_CROSSWALK_SCHEMA = "athena.stable_compatibility.getscores.beatmap_status_crosswalk.v1"

_SAFE_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

_SHAPE_FIELDS = frozenset(
    {
        "shape_id",
        "http_status",
        "required_headers",
        "absent_headers",
        "body_file",
        "body_encoding",
        "terminal_lf_count",
        "personal_best_present",
        "leaderboard_row_count",
    }
)
_BRANCH_FIELDS = frozenset(
    {
        "case_id",
        "identity_profile",
        "request_selector",
        "expected_domain_category",
        "seed_profile",
        "mutation_profiles",
        "expected_shape_id",
        "expected_warning_categories",
        "evidence_status",
    }
)
_STATUS_FIELDS = frozenset({"canonical_status", "getscores", "beatmap_info"})
_ENDPOINT_STATUS_FIELDS = frozenset(
    {"representation", "wire_status", "evidence_status", "evidence_sources"}
)

_FORBIDDEN_RAW_QUERY_KEYS = frozenset(
    {
        "captured_query",
        "query",
        "query_string",
        "query_value",
        "query_values",
        "raw_query",
        "raw_query_value",
        "raw_query_values",
        "request_query",
    }
)
_FORBIDDEN_CREDENTIAL_KEYS = frozenset(
    {
        "auth_value",
        "authorization",
        "cookie",
        "credential",
        "credential_value",
        "password",
        "password_hash",
        "raw_credential",
        "session_token",
        "token",
    }
)
_FORBIDDEN_IDENTITY_KEYS = frozenset({"raw_username", "username", "user_name"})
_FORBIDDEN_INTERNAL_KEYS = frozenset(
    {"fetch_source", "internal_provenance", "provenance", "verification_state"}
)
_FORBIDDEN_RAW_BODY_KEYS = frozenset(
    {"body", "body_base64", "body_bytes", "raw_body", "raw_body_bytes"}
)
_EVIDENCE_SOURCE_PREFIXES = frozenset(
    {
        ".kiro",
        "athena_deterministic",
        "automated_test",
        "docs",
        "issue",
        "official_fixture",
        "protocol_documentation",
        "reference_consensus",
        "reference_implementation",
        "reference_responses",
        "research",
        "target_client_traffic",
        "tests",
    }
)
_EVIDENCE_SOURCE_PAYLOAD_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./#-]{0,191}$")
_MAX_EVIDENCE_SOURCE_LENGTH = 256
_MAX_MANIFEST_NESTING = 64
_HEADER_FIELD_COUNT = 7
_SCORE_ROW_FIELD_COUNT = 16
_SCORE_ROW_NUMERIC_FIELD_INDICES = (0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)


class GetscoresEvidenceValidationError(ValueError):
    """Getscores evidence manifest の安全な検証失敗を表す。

    Args:
        errors (Sequence[str]): File名, entry位置, field名, error codeだけで構成した診断。

    Returns:
        None: 例外初期化のため戻り値はない。

    Raises:
        なし。

    Notes:
        JSONのraw value, credential, username, query valueは診断へ含めない。
    """

    errors: tuple[str, ...]

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


class GetscoresWireShapeId(StrEnum):
    """Getscoresのdistinct wire shapeを表す。

    Attributes:
        AUTH_FAILURE (str): Authentication failureのempty body shape。
        UNAVAILABLE (str): Beatmap unavailableのshort body shape。
        UPDATE_AVAILABLE (str): Beatmap update availableのshort body shape。
        HEADER_ONLY (str): Score rowを含まないheader shape。
        HEADER_WITH_ROWS (str): Personal Bestとleaderboard rowを含むshape。

    Notes:
        Manifestはこのclosed value以外を受け付けない。
    """

    AUTH_FAILURE = "auth_failure"
    UNAVAILABLE = "unavailable"
    UPDATE_AVAILABLE = "update_available"
    HEADER_ONLY = "header_only"
    HEADER_WITH_ROWS = "header_with_rows"


class GetscoresBodyEncoding(StrEnum):
    """Exact response body fixtureの保存encodingを表す。

    Attributes:
        BASE64 (str): Repository hookのtext normalizationからdecoded bytesを分離するBase64。

    Notes:
        Manifestはcanonical Base64以外の保存形式を受け付けない。
    """

    BASE64 = "base64"


class GetscoresEvidenceStatus(StrEnum):
    """Getscores evidenceの確度を表す。

    Attributes:
        CONFIRMED (str): Higher-authority evidenceで確認済みの状態。
        ATHENA_DETERMINISTIC (str): Athena current behaviorで固定した状態。
        PROVISIONAL_ATHENA_BEHAVIOR (str): Target未確認の暫定Athena behavior。
        UNCONFIRMED (str): Evidenceが未確認の状態。

    Notes:
        Provisionalとconfirmedを同一の互換保証として扱わない。
    """

    CONFIRMED = "confirmed"
    ATHENA_DETERMINISTIC = "athena_deterministic"
    PROVISIONAL_ATHENA_BEHAVIOR = "provisional_athena_behavior"
    UNCONFIRMED = "unconfirmed"


class GetscoresIdentityProfile(StrEnum):
    """Branch caseが利用するbeatmap identity profileを表す。

    Attributes:
        AUTH_MISSING (str): Credentialが存在しないprofile。
        AUTH_INVALID (str): Credentialが不正なprofile。
        KNOWN_BEATMAP (str): Known beatmap identity profile。
        MISSING_BEATMAP_IDENTITY (str): Beatmap identity不足profile。
        INVALID_CHECKSUM (str): Checksum形式不正profile。
        UNAVAILABLE_BEATMAP (str): Beatmap unavailable profile。
        UPDATE_CANDIDATE (str): Same-set update candidate profile。

    Notes:
        Raw credential, username, checksum valueは保持しない。
    """

    AUTH_MISSING = "auth_missing"
    AUTH_INVALID = "auth_invalid"
    KNOWN_BEATMAP = "known_beatmap"
    MISSING_BEATMAP_IDENTITY = "missing_beatmap_identity"
    INVALID_CHECKSUM = "invalid_checksum"
    UNAVAILABLE_BEATMAP = "unavailable_beatmap"
    UPDATE_CANDIDATE = "update_candidate"


class GetscoresRequestSelector(StrEnum):
    """Stable getscores requestのselector意味を表す。

    Attributes:
        GLOBAL_DOMAIN (str): Athena Global domain scope。
        LOCAL (str): Stable Local selector。
        SELECTED_MODS (str): Stable Selected Mods selector。
        FRIENDS (str): Stable Friends selector。
        COUNTRY (str): Stable Country selector。
        SONG_SELECT (str): Song select header-only selector。
        UNSUPPORTED_LEADERBOARD (str): Unsupported leaderboard selector。
        UNSUPPORTED_PLAYSTYLE (str): Unsupported playstyle selector。

    Notes:
        Stable selector meaningとdomain category meaningを分離する。
    """

    GLOBAL_DOMAIN = "global_domain"
    LOCAL = "local"
    SELECTED_MODS = "selected_mods"
    FRIENDS = "friends"
    COUNTRY = "country"
    SONG_SELECT = "song_select"
    UNSUPPORTED_LEADERBOARD = "unsupported_leaderboard"
    UNSUPPORTED_PLAYSTYLE = "unsupported_playstyle"


class GetscoresSeedProfile(StrEnum):
    """Branch caseが要求するsynthetic seed profileを表す。

    Attributes:
        NONE (str): Seed不要profile。
        RANKED_NO_SCORES (str): Ranked beatmap with no scores。
        RANKED_WITH_ROWS (str): Ranked beatmap with score rows。
        SELECTED_MODS_SUPPORTED (str): Supported exact mod selection。
        SELECTED_MODS_UNSUPPORTED (str): Unsupported mod selection。
        FRIENDS_DIRECTIONAL (str): Outbound friend directionality seed。
        COUNTRY_MATCH (str): Viewer country match seed。
        COUNTRY_MISSING (str): Viewer country missing seed。
        COUNTRY_XX (str): Viewer country XX seed。
        UPDATE_CANDIDATE (str): Same-set update candidate seed。

    Notes:
        Database row自体は保持せず, symbolic seed IDだけを表す。
    """

    NONE = "none"
    RANKED_NO_SCORES = "ranked_no_scores"
    RANKED_WITH_ROWS = "ranked_with_rows"
    SELECTED_MODS_SUPPORTED = "selected_mods_supported"
    SELECTED_MODS_UNSUPPORTED = "selected_mods_unsupported"
    FRIENDS_DIRECTIONAL = "friends_directional"
    COUNTRY_MATCH = "country_match"
    COUNTRY_MISSING = "country_missing"
    COUNTRY_XX = "country_xx"
    UPDATE_CANDIDATE = "update_candidate"


class GetscoresMutationProfile(StrEnum):
    """Branch caseが表すsafeなrequest mutation profileを表す。

    Attributes:
        INVALID_MODE (str): Invalid mode mutation。
        INVALID_MODS (str): Invalid mods mutation。
        INVALID_LEADERBOARD_TYPE (str): Invalid leaderboard type mutation。
        INVALID_LEADERBOARD_VERSION (str): Invalid leaderboard version mutation。
        INVALID_SONG_SELECT_FLAG (str): Invalid song select flag mutation。
        INVALID_ANTI_CHEAT_SIGNAL (str): Invalid anti-cheat signal mutation。
        INVALID_BEATMAPSET_ID_HINT (str): Invalid beatmapset hint mutation。
        VALID_ANTI_CHEAT_SIGNAL (str): Valid anti-cheat signal mutation。
        REQUEST_VERSION_VARIANT (str): Request version variation。

    Notes:
        Raw malformed query valueは保持しない。
    """

    INVALID_MODE = "invalid_mode"
    INVALID_MODS = "invalid_mods"
    INVALID_LEADERBOARD_TYPE = "invalid_leaderboard_type"
    INVALID_LEADERBOARD_VERSION = "invalid_leaderboard_version"
    INVALID_SONG_SELECT_FLAG = "invalid_song_select_flag"
    INVALID_ANTI_CHEAT_SIGNAL = "invalid_anti_cheat_signal"
    INVALID_BEATMAPSET_ID_HINT = "invalid_beatmapset_id_hint"
    VALID_ANTI_CHEAT_SIGNAL = "valid_anti_cheat_signal"
    REQUEST_VERSION_VARIANT = "request_version_variant"


_WARNING_BY_INVALID_MUTATION: Mapping[GetscoresMutationProfile, GetscoresParseWarning] = (
    MappingProxyType(
        {
            GetscoresMutationProfile.INVALID_MODE: GetscoresParseWarning.INVALID_MODE,
            GetscoresMutationProfile.INVALID_MODS: GetscoresParseWarning.INVALID_MODS,
            GetscoresMutationProfile.INVALID_LEADERBOARD_TYPE: (
                GetscoresParseWarning.INVALID_LEADERBOARD_TYPE
            ),
            GetscoresMutationProfile.INVALID_LEADERBOARD_VERSION: (
                GetscoresParseWarning.INVALID_LEADERBOARD_VERSION
            ),
            GetscoresMutationProfile.INVALID_SONG_SELECT_FLAG: (
                GetscoresParseWarning.INVALID_SONG_SELECT_FLAG
            ),
            GetscoresMutationProfile.INVALID_ANTI_CHEAT_SIGNAL: (
                GetscoresParseWarning.INVALID_ANTI_CHEAT_SIGNAL
            ),
            GetscoresMutationProfile.INVALID_BEATMAPSET_ID_HINT: (
                GetscoresParseWarning.INVALID_BEATMAPSET_ID_HINT
            ),
        }
    )
)


class StatusRepresentation(StrEnum):
    """Endpoint statusのwire表現種別を表す。

    Attributes:
        WIRE (str): Numeric wire statusを持つ表現。
        UNAVAILABLE (str): Unavailable responseへ対応する表現。
        UNSUPPORTED (str): Endpointで未対応の表現。
        UNCONFIRMED (str): Wire representation未確認の表現。

    Notes:
        WIRE以外へnumeric wire statusを設定しない。
    """

    WIRE = "wire"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    UNCONFIRMED = "unconfirmed"


class EndpointEvidenceState(StrEnum):
    """Endpoint status evidenceの確定状態を表す。

    Attributes:
        CONFIRMED (str): Confirmed evidenceに基づく状態。
        OFFICIAL_FIXTURE (str): Official fixtureに基づく状態。
        ATHENA_DETERMINISTIC (str): Athena deterministic behaviorに基づく状態。
        UNCONFIRMED (str): Evidence未確認の状態。

    Notes:
        Endpointごとのevidence authorityを明示する。
    """

    CONFIRMED = "confirmed"
    OFFICIAL_FIXTURE = "official_fixture"
    ATHENA_DETERMINISTIC = "athena_deterministic"
    UNCONFIRMED = "unconfirmed"


@final
class GetscoresEvidenceSource(str):
    """Getscores evidenceのsafeなsymbolic source reference。

    Args:
        value (str): 証跡種別prefixとsafe identifierで構成した参照名。

    Returns:
        GetscoresEvidenceSource: Raw query, credential, 制御文字を含まない参照名。

    Raises:
        ValueError: 許可されたsymbolic reference形式でない場合。

    Notes:
        参照名はfixtureやtestの識別子だけを表し, raw request valueやsecretを保持しない。
    """

    __slots__ = ()

    def __new__(cls, value: str) -> GetscoresEvidenceSource:
        if not _is_safe_evidence_source(value):
            raise ValueError("unsafe evidence source")
        return cast("GetscoresEvidenceSource", str.__new__(cls, value))


@dataclass(frozen=True, slots=True)
class GetscoresWireShapeFixture:
    """Getscoresのclient-visible wire shape metadataを保持する。

    Args:
        shape_id (GetscoresWireShapeId): Distinct response shapeの識別子。
        http_status (int): Shapeが返すHTTP status。
        required_headers (Mapping[str, str]): Deterministicに検証するheader subset。
        absent_headers (tuple[str, ...]): 存在してはならないheader名。
        body_file (Path): Base64 encoded body fixture path。
        body_encoding (GetscoresBodyEncoding): Body fixtureの保存encoding。
        terminal_lf_count (int): Body末尾の連続LF数。
        personal_best_present (bool): Personal Best欄を含むか。
        leaderboard_row_count (int): Personal Bestを除いたleaderboard row数。

    Returns:
        None: Dataclass初期化のため戻り値はない。

    Raises:
        なし。

    Notes:
        body_fileはloaderでbody root配下へ制限される。Raw body bytesは保持しない。
    """

    shape_id: GetscoresWireShapeId
    http_status: int
    required_headers: Mapping[str, str]
    absent_headers: tuple[str, ...]
    body_file: Path
    body_encoding: GetscoresBodyEncoding
    terminal_lf_count: int
    personal_best_present: bool
    leaderboard_row_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_headers", MappingProxyType(dict(self.required_headers)))
        object.__setattr__(self, "absent_headers", tuple(self.absent_headers))

    def read_body_bytes(self) -> bytes:
        """Canonical Base64 fixtureからexact client body bytesを復元する。

        Returns:
            bytes: Repository上のencoding metadataを含まないdecoded response body。

        Raises:
            GetscoresEvidenceValidationError: Terminal LF, ASCII, whitespace, Base64 canonicality,
                またはfile readの検証に失敗した場合。

        Notes:
            Errorにはshape idとerror codeだけを含め, encoded payloadを出力しない。
        """

        body, error_code = _decode_body_fixture(self.body_file, self.body_encoding)
        if body is None:
            raise GetscoresEvidenceValidationError(
                (
                    _error(
                        _RESPONSE_SHAPES_FILE,
                        self.shape_id.value,
                        "body_file",
                        error_code,
                    ),
                )
            )
        return body


@dataclass(frozen=True, slots=True)
class GetscoresBranchCase:
    """Getscores request profileと期待wire shapeの対応を保持する。

    Args:
        case_id (str): Branch caseのsafe identifier。
        identity_profile (GetscoresIdentityProfile): Beatmap identityのclosed profile。
        request_selector (GetscoresRequestSelector): Stable request selector。
        expected_domain_category (LeaderboardCategory | None): 期待domain category。
        seed_profile (GetscoresSeedProfile): Synthetic seedのclosed profile。
        mutation_profiles (tuple[GetscoresMutationProfile, ...]): Request mutation群。
        expected_shape_id (GetscoresWireShapeId): 対応するwire shape。
        expected_warning_categories (tuple[GetscoresParseWarning, ...]): Warning集合。
        evidence_status (GetscoresEvidenceStatus): Evidenceの確度。

    Returns:
        None: Dataclass初期化のため戻り値はない。

    Raises:
        なし。

    Notes:
        Raw query value, credential, usernameは保持しない。
    """

    case_id: str
    identity_profile: GetscoresIdentityProfile
    request_selector: GetscoresRequestSelector
    expected_domain_category: LeaderboardCategory | None
    seed_profile: GetscoresSeedProfile
    mutation_profiles: tuple[GetscoresMutationProfile, ...]
    expected_shape_id: GetscoresWireShapeId
    expected_warning_categories: tuple[GetscoresParseWarning, ...]
    evidence_status: GetscoresEvidenceStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "mutation_profiles", tuple(self.mutation_profiles))
        object.__setattr__(
            self, "expected_warning_categories", tuple(self.expected_warning_categories)
        )


@dataclass(frozen=True, slots=True)
class EndpointStatusEvidence:
    """1 endpointにおけるcanonical statusのwire evidenceを保持する。

    Args:
        representation (StatusRepresentation): Wire representation種別。
        wire_status (int | None): Numeric wire status。非wire表現ではNone。
        evidence_status (EndpointEvidenceState): 根拠の確定状態。
        evidence_sources (tuple[GetscoresEvidenceSource, ...]): Safeな参照名。

    Returns:
        None: Dataclass初期化のため戻り値はない。

    Raises:
        ValueError: Evidence sourceがsafe symbolic referenceでない場合。

    Notes:
        未確認表現の数値を推測して保持しない。
    """

    representation: StatusRepresentation
    wire_status: int | None
    evidence_status: EndpointEvidenceState
    evidence_sources: tuple[GetscoresEvidenceSource, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_sources",
            tuple(GetscoresEvidenceSource(str(source)) for source in self.evidence_sources),
        )


@dataclass(frozen=True, slots=True)
class StableBeatmapStatusCrosswalkEntry:
    """canonical BeatmapRankStatusとendpoint別status evidenceを保持する。

    Args:
        canonical_status (BeatmapRankStatus): Athena canonical status。
        getscores (EndpointStatusEvidence): Getscores endpointのstatus evidence。
        beatmap_info (EndpointStatusEvidence): Beatmap info endpointのstatus evidence。

    Returns:
        None: Dataclass初期化のため戻り値はない。

    Raises:
        なし。

    Notes:
        endpoint固有mapperを共有するruntime lookup sourceにはしない。
    """

    canonical_status: BeatmapRankStatus
    getscores: EndpointStatusEvidence
    beatmap_info: EndpointStatusEvidence


@dataclass(frozen=True, slots=True)
class GetscoresCompletionEvidence:
    """Getscores completion evidenceをimmutable bundleとして保持する。

    Args:
        response_shapes (tuple[GetscoresWireShapeFixture, ...]): Wire shape metadata。
        branch_cases (tuple[GetscoresBranchCase, ...]): Selectionとshapeの対応表。
        status_crosswalk (tuple[StableBeatmapStatusCrosswalkEntry, ...]): Status対応表。

    Returns:
        None: Dataclass初期化のため戻り値はない。

    Raises:
        なし。

    Notes:
        Raw JSON, raw query, credential, internal provenanceは保持しない。
    """

    response_shapes: tuple[GetscoresWireShapeFixture, ...]
    branch_cases: tuple[GetscoresBranchCase, ...]
    status_crosswalk: tuple[StableBeatmapStatusCrosswalkEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "response_shapes", tuple(self.response_shapes))
        object.__setattr__(self, "branch_cases", tuple(self.branch_cases))
        object.__setattr__(self, "status_crosswalk", tuple(self.status_crosswalk))


def load_getscores_completion_evidence(
    manifest_root: Path,
    body_root: Path,
) -> GetscoresCompletionEvidence:
    """Getscores completion manifestを安全にtyped bundleへ変換する。

    Args:
        manifest_root (Path): 3つのversioned manifestを含むdirectory。
        body_root (Path): Exact response body fixtureのroot directory。

    Returns:
        GetscoresCompletionEvidence: Immutableなtyped evidence bundle。

    Raises:
        GetscoresEvidenceValidationError: Schema, 型, 参照, secret policy, path safetyの失敗。

    Notes:
        Errorにはfile名, entry位置, field名, error codeだけを含め, raw valueを出さない。
    """

    try:
        root = manifest_root.resolve(strict=True)
        resolved_body_root = body_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise GetscoresEvidenceValidationError(
            ("getscores_completion:root:root:unsafe_root_path",)
        ) from None
    errors: list[str] = []

    response_document = _read_manifest(
        root / _RESPONSE_SHAPES_FILE, _RESPONSE_SHAPES_SCHEMA, "shapes", errors
    )
    branch_document = _read_manifest(
        root / _BRANCH_CASES_FILE, _BRANCH_CASES_SCHEMA, "cases", errors
    )
    crosswalk_document = _read_manifest(
        root / _STATUS_CROSSWALK_FILE,
        _STATUS_CROSSWALK_SCHEMA,
        "entries",
        errors,
    )

    shapes = _parse_shapes(response_document, resolved_body_root, errors)
    shape_ids = {shape.shape_id for shape in shapes}
    branches = _parse_branches(branch_document, errors)
    for index, branch in enumerate(branches):
        if branch.expected_shape_id not in shape_ids:
            errors.append(
                _error(_BRANCH_CASES_FILE, index, "expected_shape_id", "unknown_shape_id")
            )
    crosswalk = _parse_crosswalk(crosswalk_document, errors)
    errors.extend(_crosswalk_semantic_errors(crosswalk))

    if errors:
        raise GetscoresEvidenceValidationError(_sorted_errors(errors))

    return GetscoresCompletionEvidence(
        response_shapes=shapes,
        branch_cases=branches,
        status_crosswalk=crosswalk,
    )


def validate_getscores_completion_evidence(
    evidence: GetscoresCompletionEvidence,
) -> tuple[SurfaceResult, ...]:
    """Loaded evidence bundleの内部不変条件を検証する。

    Args:
        evidence (GetscoresCompletionEvidence): Typed loaderが生成したbundle。

    Returns:
        tuple[SurfaceResult, ...]: Shapes, branch cases, status crosswalkの検証結果。

    Raises:
        なし。

    Notes:
        診断へraw valueを含めない。失敗はSurfaceResultとして返す。
    """

    shape_errors = _validate_bundle_shapes(evidence)
    branch_errors = _validate_bundle_branches(evidence)
    crosswalk_errors = _validate_bundle_crosswalk(evidence)
    return (
        _surface_result("response shapes", shape_errors),
        _surface_result("branch cases", branch_errors),
        _surface_result("status crosswalk", crosswalk_errors),
    )


def _read_manifest(
    path: Path,
    expected_schema: str,
    collection_key: str,
    errors: list[str],
) -> Mapping[str, object]:
    filename = path.name
    raw: object = None
    load_failed = False
    try:
        raw = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        errors.append(_error(filename, "document", "schema", "missing_manifest"))
        load_failed = True
    except UnicodeDecodeError:
        errors.append(_error(filename, "document", "root", "invalid_utf8"))
        load_failed = True
    except RecursionError:
        errors.append(_error(filename, "document", "root", "nested_content_too_deep"))
        load_failed = True
    except json.JSONDecodeError:
        errors.append(_error(filename, "document", "schema", "invalid_json"))
        load_failed = True
    except OSError:
        errors.append(_error(filename, "document", "schema", "unreadable_manifest"))
        load_failed = True

    if load_failed:
        return {}

    if not isinstance(raw, Mapping):
        errors.append(_error(filename, "document", "root", "non_object_root"))
        return {}
    document = cast("Mapping[str, object]", raw)
    errors.extend(_forbidden_errors(document, filename, "document"))

    allowed_fields = {"schema", collection_key}
    errors.extend(
        _error(
            filename,
            "document",
            key if _safe_key(key) else "field",
            "unknown_top_level_field",
        )
        for key in document
        if key not in allowed_fields
    )

    schema = document.get("schema")
    if schema != expected_schema:
        errors.append(_error(filename, "document", "schema", "unknown_schema"))
    collection = document.get(collection_key)
    if not _is_sequence(collection):
        errors.append(_error(filename, "document", collection_key, "collection_must_be_list"))

    return document


def _parse_shapes(
    document: Mapping[str, object],
    body_root: Path,
    errors: list[str],
) -> tuple[GetscoresWireShapeFixture, ...]:
    entries = _entry_mappings(
        document.get("shapes"),
        _RESPONSE_SHAPES_FILE,
        errors,
    )
    shapes: list[GetscoresWireShapeFixture] = []
    seen: set[GetscoresWireShapeId] = set()
    for index, entry in enumerate(entries):
        location = index
        errors.extend(_forbidden_errors(entry, _RESPONSE_SHAPES_FILE, location))
        errors.extend(_unknown_entry_fields(entry, _SHAPE_FIELDS, _RESPONSE_SHAPES_FILE, location))
        shape_id = _enum_member(GetscoresWireShapeId, entry.get("shape_id"))
        if shape_id is None:
            errors.append(_error(_RESPONSE_SHAPES_FILE, location, "shape_id", "invalid_enum"))
            continue
        if shape_id in seen:
            errors.append(_error(_RESPONSE_SHAPES_FILE, location, "shape_id", "duplicate_id"))
            continue
        seen.add(shape_id)
        http_status = _int_value(entry.get("http_status"))
        headers = _string_mapping(entry.get("required_headers"))
        absent_headers = _string_tuple_value(entry.get("absent_headers"))
        body_file, body_path_error = _safe_body_path(entry.get("body_file"), body_root)
        body_encoding = _enum_member(GetscoresBodyEncoding, entry.get("body_encoding"))
        terminal_lf_count = _non_negative_int(entry.get("terminal_lf_count"))
        personal_best_present = _strict_bool(entry.get("personal_best_present"))
        leaderboard_row_count = _non_negative_int(entry.get("leaderboard_row_count"))
        if http_status is None:
            errors.append(
                _error(_RESPONSE_SHAPES_FILE, location, "http_status", "invalid_integer")
            )
        if headers is None:
            errors.append(
                _error(_RESPONSE_SHAPES_FILE, location, "required_headers", "invalid_mapping")
            )
        if absent_headers is None:
            errors.append(
                _error(_RESPONSE_SHAPES_FILE, location, "absent_headers", "invalid_string_list")
            )
        if body_file is None:
            errors.append(_error(_RESPONSE_SHAPES_FILE, location, "body_file", body_path_error))
        if body_encoding is None:
            errors.append(_error(_RESPONSE_SHAPES_FILE, location, "body_encoding", "invalid_enum"))
        if terminal_lf_count is None:
            errors.append(
                _error(_RESPONSE_SHAPES_FILE, location, "terminal_lf_count", "invalid_integer")
            )
        if not isinstance(entry.get("personal_best_present"), bool):
            errors.append(
                _error(_RESPONSE_SHAPES_FILE, location, "personal_best_present", "invalid_boolean")
            )
        if leaderboard_row_count is None:
            errors.append(
                _error(_RESPONSE_SHAPES_FILE, location, "leaderboard_row_count", "invalid_integer")
            )
        if (
            http_status is None
            or headers is None
            or absent_headers is None
            or body_file is None
            or body_encoding is None
            or terminal_lf_count is None
            or personal_best_present is None
            or leaderboard_row_count is None
        ):
            continue
        shapes.append(
            GetscoresWireShapeFixture(
                shape_id=shape_id,
                http_status=http_status,
                required_headers=headers,
                absent_headers=absent_headers,
                body_file=body_file,
                body_encoding=body_encoding,
                terminal_lf_count=terminal_lf_count,
                personal_best_present=personal_best_present,
                leaderboard_row_count=leaderboard_row_count,
            )
        )
    return tuple(shapes)


def _parse_branches(
    document: Mapping[str, object],
    errors: list[str],
) -> tuple[GetscoresBranchCase, ...]:
    entries = _entry_mappings(document.get("cases"), _BRANCH_CASES_FILE, errors)
    branches: list[GetscoresBranchCase] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        location = index
        errors.extend(_forbidden_errors(entry, _BRANCH_CASES_FILE, location))
        errors.extend(_unknown_entry_fields(entry, _BRANCH_FIELDS, _BRANCH_CASES_FILE, location))
        case_id = entry.get("case_id")
        if not isinstance(case_id, str) or not _SAFE_IDENTIFIER.fullmatch(case_id):
            errors.append(_error(_BRANCH_CASES_FILE, location, "case_id", "invalid_identifier"))
            continue
        if case_id in seen:
            errors.append(_error(_BRANCH_CASES_FILE, location, "case_id", "duplicate_id"))
            continue
        seen.add(case_id)
        identity_profile = _enum_member(GetscoresIdentityProfile, entry.get("identity_profile"))
        request_selector = _enum_member(GetscoresRequestSelector, entry.get("request_selector"))
        seed_profile = _enum_member(GetscoresSeedProfile, entry.get("seed_profile"))
        expected_shape_id = _enum_member(GetscoresWireShapeId, entry.get("expected_shape_id"))
        evidence_status = _enum_member(GetscoresEvidenceStatus, entry.get("evidence_status"))
        expected_category = _enum_member(
            LeaderboardCategory, entry.get("expected_domain_category")
        )
        raw_category = entry.get("expected_domain_category")
        if raw_category is not None and expected_category is None:
            errors.append(
                _error(_BRANCH_CASES_FILE, location, "expected_domain_category", "invalid_enum")
            )
        mutation_profiles = _enum_tuple(
            GetscoresMutationProfile,
            entry.get("mutation_profiles"),
            _BRANCH_CASES_FILE,
            location,
            "mutation_profiles",
            errors,
        )
        warning_categories = _enum_tuple(
            GetscoresParseWarning,
            entry.get("expected_warning_categories"),
            _BRANCH_CASES_FILE,
            location,
            "expected_warning_categories",
            errors,
        )
        for field_name, value in (
            ("identity_profile", identity_profile),
            ("request_selector", request_selector),
            ("seed_profile", seed_profile),
            ("evidence_status", evidence_status),
        ):
            if value is None:
                errors.append(_error(_BRANCH_CASES_FILE, location, field_name, "invalid_enum"))
        if expected_shape_id is None:
            errors.append(
                _error(
                    _BRANCH_CASES_FILE,
                    location,
                    "expected_shape_id",
                    "unknown_shape_id",
                )
            )
        if mutation_profiles is None:
            mutation_profiles = ()
        if warning_categories is None:
            warning_categories = ()
        if (
            identity_profile is None
            or request_selector is None
            or seed_profile is None
            or expected_shape_id is None
            or evidence_status is None
        ):
            continue
        branches.append(
            GetscoresBranchCase(
                case_id=case_id,
                identity_profile=identity_profile,
                request_selector=request_selector,
                expected_domain_category=expected_category,
                seed_profile=seed_profile,
                mutation_profiles=mutation_profiles,
                expected_shape_id=expected_shape_id,
                expected_warning_categories=warning_categories,
                evidence_status=evidence_status,
            )
        )
    return tuple(branches)


def _parse_crosswalk(
    document: Mapping[str, object],
    errors: list[str],
) -> tuple[StableBeatmapStatusCrosswalkEntry, ...]:
    entries = _entry_mappings(document.get("entries"), _STATUS_CROSSWALK_FILE, errors)
    crosswalk: list[StableBeatmapStatusCrosswalkEntry] = []
    seen: set[BeatmapRankStatus] = set()
    for index, entry in enumerate(entries):
        location = index
        errors.extend(_forbidden_errors(entry, _STATUS_CROSSWALK_FILE, location))
        errors.extend(
            _unknown_entry_fields(entry, _STATUS_FIELDS, _STATUS_CROSSWALK_FILE, location)
        )
        canonical_status = _enum_member(BeatmapRankStatus, entry.get("canonical_status"))
        if canonical_status is None:
            errors.append(
                _error(_STATUS_CROSSWALK_FILE, location, "canonical_status", "invalid_enum")
            )
            continue
        if canonical_status in seen:
            errors.append(
                _error(_STATUS_CROSSWALK_FILE, location, "canonical_status", "duplicate_id")
            )
            continue
        seen.add(canonical_status)
        getscores = _parse_endpoint_status(
            entry.get("getscores"), _STATUS_CROSSWALK_FILE, location, "getscores", errors
        )
        beatmap_info = _parse_endpoint_status(
            entry.get("beatmap_info"),
            _STATUS_CROSSWALK_FILE,
            location,
            "beatmap_info",
            errors,
        )
        if getscores is None or beatmap_info is None:
            continue
        crosswalk.append(
            StableBeatmapStatusCrosswalkEntry(
                canonical_status=canonical_status,
                getscores=getscores,
                beatmap_info=beatmap_info,
            )
        )
    return tuple(crosswalk)


def _parse_endpoint_status(
    value: object,
    filename: str,
    location: int,
    field_name: str,
    errors: list[str],
) -> EndpointStatusEvidence | None:
    if not isinstance(value, Mapping):
        errors.append(_error(filename, location, field_name, "invalid_mapping"))
        return None
    entry = cast("Mapping[str, object]", value)
    errors.extend(_forbidden_errors(entry, filename, location))
    errors.extend(_unknown_entry_fields(entry, _ENDPOINT_STATUS_FIELDS, filename, location))
    representation = _enum_member(StatusRepresentation, entry.get("representation"))
    evidence_status = _enum_member(EndpointEvidenceState, entry.get("evidence_status"))
    wire_status = entry.get("wire_status")
    if representation is None:
        errors.append(_error(filename, location, f"{field_name}.representation", "invalid_enum"))
    if evidence_status is None:
        errors.append(_error(filename, location, f"{field_name}.evidence_status", "invalid_enum"))
    if wire_status is not None and _int_value(wire_status) is None:
        errors.append(_error(filename, location, f"{field_name}.wire_status", "invalid_integer"))
    evidence_sources = _evidence_source_tuple(entry.get("evidence_sources"))
    if evidence_sources is None:
        errors.append(
            _error(
                filename,
                location,
                f"{field_name}.evidence_sources",
                "invalid_evidence_source",
            )
        )
    if representation is None or evidence_status is None or evidence_sources is None:
        return None
    return EndpointStatusEvidence(
        representation=representation,
        wire_status=_int_value(wire_status) if wire_status is not None else None,
        evidence_status=evidence_status,
        evidence_sources=evidence_sources,
    )


def _validate_bundle_shapes(evidence: GetscoresCompletionEvidence) -> tuple[str, ...]:
    errors: list[str] = []
    seen: set[GetscoresWireShapeId] = set()
    seen_body_files: set[Path] = set()
    for index, shape in enumerate(evidence.response_shapes):
        if shape.shape_id in seen:
            errors.append(_error(_RESPONSE_SHAPES_FILE, index, "shape_id", "duplicate_id"))
        seen.add(shape.shape_id)

        if shape.body_file in seen_body_files:
            errors.append(
                _error(_RESPONSE_SHAPES_FILE, index, "body_file", "duplicate_body_owner")
            )
        seen_body_files.add(shape.body_file)
        if shape.body_file.name != f"{shape.shape_id.value}.body.b64":
            errors.append(
                _error(_RESPONSE_SHAPES_FILE, index, "body_file", "unexpected_body_owner")
            )

        if not shape.body_file.is_file():
            errors.append(_error(_RESPONSE_SHAPES_FILE, index, "body_file", "missing_body_file"))
            continue

        try:
            body = shape.read_body_bytes()
        except GetscoresEvidenceValidationError as error:
            errors.extend(error.errors)
            continue

        errors.extend(_wire_shape_metadata_errors(shape, index, body))
        errors.extend(_wire_shape_body_errors(shape, index, body))

    if seen != set(GetscoresWireShapeId):
        errors.append(
            _error(_RESPONSE_SHAPES_FILE, "root", "shape_id", "required_shape_set_mismatch")
        )
    return tuple(_sorted_errors(errors))


def _decode_body_fixture(
    body_file: Path,
    body_encoding: object,
) -> tuple[bytes | None, str]:
    if body_encoding is not GetscoresBodyEncoding.BASE64:
        return None, "unsupported_body_encoding"
    try:
        encoded = body_file.read_bytes()
    except OSError:
        return None, "unreadable_body_file"
    return _decode_canonical_base64_text(encoded)


def _decode_canonical_base64_text(encoded: bytes) -> tuple[bytes | None, str]:
    if not encoded:
        return b"", ""
    if encoded == b"\n":
        return None, "non_canonical_base64"

    format_error = _canonical_base64_format_error(encoded)
    if format_error is not None:
        return None, format_error
    payload = encoded[:-1]
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None, "invalid_base64_payload"
    if base64.b64encode(decoded) != payload:
        return None, "non_canonical_base64"
    return decoded, ""


def _canonical_base64_format_error(encoded: bytes) -> str | None:
    if not encoded.endswith(b"\n") or encoded.endswith(b"\n\n"):
        return "invalid_base64_terminal_lf"

    payload = encoded[:-1]
    if not payload.isascii():
        return "invalid_base64_non_ascii"
    if any(character in b" \t\r\n\v\f" for character in payload):
        return "invalid_base64_whitespace"
    return None


def _wire_shape_metadata_errors(
    shape: GetscoresWireShapeFixture,
    index: int,
    body: bytes,
) -> tuple[str, ...]:
    errors: list[str] = []
    expected_status = 401 if shape.shape_id is GetscoresWireShapeId.AUTH_FAILURE else 200
    if shape.http_status != expected_status:
        errors.append(
            _error(_RESPONSE_SHAPES_FILE, index, "http_status", "unexpected_http_status")
        )

    expected_headers = {"content-length": str(len(body))}
    if shape.shape_id is not GetscoresWireShapeId.AUTH_FAILURE:
        expected_headers["content-type"] = "text/plain; charset=utf-8"
    if dict(shape.required_headers) != expected_headers:
        errors.append(
            _error(_RESPONSE_SHAPES_FILE, index, "required_headers", "header_contract_mismatch")
        )

    expected_absent_headers = (
        ("content-type", "content-encoding", "transfer-encoding")
        if shape.shape_id is GetscoresWireShapeId.AUTH_FAILURE
        else ("content-encoding", "transfer-encoding")
    )
    if shape.absent_headers != expected_absent_headers:
        errors.append(
            _error(_RESPONSE_SHAPES_FILE, index, "absent_headers", "header_contract_mismatch")
        )

    expected_terminal_lf_count = 0
    if shape.shape_id is GetscoresWireShapeId.HEADER_ONLY:
        expected_terminal_lf_count = 3
    elif shape.shape_id is GetscoresWireShapeId.HEADER_WITH_ROWS:
        expected_terminal_lf_count = 1
    if shape.terminal_lf_count != expected_terminal_lf_count:
        errors.append(
            _error(
                _RESPONSE_SHAPES_FILE,
                index,
                "terminal_lf_count",
                "newline_contract_mismatch",
            )
        )

    expected_personal_best = shape.shape_id is GetscoresWireShapeId.HEADER_WITH_ROWS
    if shape.personal_best_present is not expected_personal_best:
        errors.append(
            _error(
                _RESPONSE_SHAPES_FILE,
                index,
                "personal_best_present",
                "personal_best_contract_mismatch",
            )
        )

    expected_row_count = 2 if shape.shape_id is GetscoresWireShapeId.HEADER_WITH_ROWS else 0
    if shape.leaderboard_row_count != expected_row_count:
        errors.append(
            _error(
                _RESPONSE_SHAPES_FILE,
                index,
                "leaderboard_row_count",
                "leaderboard_count_contract_mismatch",
            )
        )
    return tuple(errors)


def _wire_shape_body_errors(
    shape: GetscoresWireShapeFixture,
    index: int,
    body: bytes,
) -> tuple[str, ...]:
    errors: list[str] = []
    actual_terminal_lf_count = len(body) - len(body.rstrip(b"\n"))
    if actual_terminal_lf_count != shape.terminal_lf_count:
        errors.append(
            _error(
                _RESPONSE_SHAPES_FILE,
                index,
                "body_file",
                "terminal_newline_mismatch",
            )
        )

    expected_short_body: bytes | None = None
    if shape.shape_id is GetscoresWireShapeId.AUTH_FAILURE:
        expected_short_body = b""
    elif shape.shape_id is GetscoresWireShapeId.UNAVAILABLE:
        expected_short_body = b"-1|false"
    elif shape.shape_id is GetscoresWireShapeId.UPDATE_AVAILABLE:
        expected_short_body = b"1|false"
    if expected_short_body is not None:
        if body != expected_short_body:
            errors.append(_error(_RESPONSE_SHAPES_FILE, index, "body_file", "short_body_mismatch"))
        return tuple(errors)

    errors.extend(_header_shape_body_errors(shape, index, body))
    return tuple(errors)


def _header_shape_body_errors(
    shape: GetscoresWireShapeFixture,
    index: int,
    body: bytes,
) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        _ = body.decode("utf-8")
    except UnicodeDecodeError:
        return (_error(_RESPONSE_SHAPES_FILE, index, "body_file", "invalid_body_utf8"),)

    if b"\r" in body:
        errors.append(_error(_RESPONSE_SHAPES_FILE, index, "body_file", "unsanitized_line_break"))
    lowered_body = body.lower()
    if any(
        forbidden in lowered_body
        for forbidden in (
            b"credential",
            b"fetch_source",
            b"internal_provenance",
            b"password",
            b"verification_state",
        )
    ):
        errors.append(
            _error(_RESPONSE_SHAPES_FILE, index, "body_file", "forbidden_internal_content")
        )

    lines = body.split(b"\n")
    expected_line_count = (
        7
        if shape.shape_id is GetscoresWireShapeId.HEADER_ONLY
        else 6 + shape.leaderboard_row_count
    )
    if len(lines) != expected_line_count:
        errors.append(
            _error(_RESPONSE_SHAPES_FILE, index, "body_file", "header_line_count_mismatch")
        )
        return tuple(errors)

    errors.extend(_header_prelude_errors(shape, index, lines))
    errors.extend(_header_score_section_errors(shape, index, lines))
    return tuple(errors)


def _header_prelude_errors(
    shape: GetscoresWireShapeFixture,
    index: int,
    lines: list[bytes],
) -> tuple[str, ...]:
    errors: list[str] = []
    header_fields = lines[0].split(b"|")
    if (
        len(header_fields) != _HEADER_FIELD_COUNT
        or header_fields[1] != b"false"
        or header_fields[5:] != [b"", b""]
        or any(
            not _is_ascii_non_negative_integer(header_fields[field_index])
            for field_index in (0, 2, 3, 4)
        )
    ):
        errors.append(_error(_RESPONSE_SHAPES_FILE, index, "body_file", "invalid_header_row"))
    elif int(header_fields[4]) != shape.leaderboard_row_count:
        errors.append(
            _error(_RESPONSE_SHAPES_FILE, index, "body_file", "header_row_count_mismatch")
        )

    if lines[1] != b"0" or lines[3] != b"0":
        errors.append(_error(_RESPONSE_SHAPES_FILE, index, "body_file", "invalid_header_metadata"))
    display_prefix = b"[bold:0,size:20]"
    if not lines[2].startswith(display_prefix) or lines[2].count(b"|") != 1:
        errors.append(_error(_RESPONSE_SHAPES_FILE, index, "body_file", "invalid_display_title"))
    return tuple(errors)


def _header_score_section_errors(
    shape: GetscoresWireShapeFixture,
    index: int,
    lines: list[bytes],
) -> tuple[str, ...]:
    errors: list[str] = []
    personal_best_row = lines[4]
    if shape.personal_best_present:
        if not _is_valid_score_row(personal_best_row):
            errors.append(
                _error(_RESPONSE_SHAPES_FILE, index, "body_file", "invalid_personal_best_row")
            )
    elif personal_best_row:
        errors.append(
            _error(_RESPONSE_SHAPES_FILE, index, "body_file", "unexpected_personal_best_row")
        )

    leaderboard_rows = lines[5:-1]
    if shape.shape_id is GetscoresWireShapeId.HEADER_ONLY:
        if leaderboard_rows != [b""]:
            errors.append(
                _error(_RESPONSE_SHAPES_FILE, index, "body_file", "unexpected_leaderboard_rows")
            )
    elif len(leaderboard_rows) != shape.leaderboard_row_count or any(
        not _is_valid_score_row(row) for row in leaderboard_rows
    ):
        errors.append(
            _error(_RESPONSE_SHAPES_FILE, index, "body_file", "invalid_leaderboard_rows")
        )
    return tuple(errors)


def _is_valid_score_row(row: bytes) -> bool:
    fields = row.split(b"|")
    if len(fields) != _SCORE_ROW_FIELD_COUNT or not fields[1]:
        return False
    if any(
        not _is_ascii_non_negative_integer(fields[field_index])
        for field_index in _SCORE_ROW_NUMERIC_FIELD_INDICES
    ):
        return False
    return fields[10] in {b"0", b"1"} and fields[15] in {b"0", b"1"}


def _is_ascii_non_negative_integer(value: bytes) -> bool:
    return bool(value) and value.isascii() and value.isdigit()


def _validate_bundle_branches(evidence: GetscoresCompletionEvidence) -> tuple[str, ...]:
    shape_ids = {shape.shape_id for shape in evidence.response_shapes}
    errors: list[str] = []
    seen: set[str] = set()
    for index, case in enumerate(evidence.branch_cases):
        if case.case_id in seen:
            errors.append(_error(_BRANCH_CASES_FILE, index, "case_id", "duplicate_id"))
        seen.add(case.case_id)
        if case.expected_shape_id not in shape_ids:
            errors.append(
                _error(_BRANCH_CASES_FILE, index, "expected_shape_id", "unknown_shape_id")
            )
        if len(set(case.mutation_profiles)) != len(case.mutation_profiles):
            errors.append(
                _error(_BRANCH_CASES_FILE, index, "mutation_profiles", "duplicate_member")
            )
        if len(set(case.expected_warning_categories)) != len(case.expected_warning_categories):
            errors.append(
                _error(
                    _BRANCH_CASES_FILE,
                    index,
                    "expected_warning_categories",
                    "duplicate_member",
                )
            )
        expected_warnings = {
            warning
            for mutation in case.mutation_profiles
            if (warning := _WARNING_BY_INVALID_MUTATION.get(mutation)) is not None
        }
        if set(case.expected_warning_categories) != expected_warnings:
            errors.append(
                _error(
                    _BRANCH_CASES_FILE,
                    index,
                    "expected_warning_categories",
                    "mutation_warning_mismatch",
                )
            )
        malformed_identity = case.identity_profile in {
            GetscoresIdentityProfile.MISSING_BEATMAP_IDENTITY,
            GetscoresIdentityProfile.INVALID_CHECKSUM,
        }
        malformed_optional = any(
            mutation in _WARNING_BY_INVALID_MUTATION for mutation in case.mutation_profiles
        )
        if (
            malformed_identity or malformed_optional
        ) and case.evidence_status is not GetscoresEvidenceStatus.PROVISIONAL_ATHENA_BEHAVIOR:
            errors.append(
                _error(
                    _BRANCH_CASES_FILE,
                    index,
                    "evidence_status",
                    "malformed_case_must_be_provisional",
                )
            )
    return tuple(_sorted_errors(errors))


def _validate_bundle_crosswalk(evidence: GetscoresCompletionEvidence) -> tuple[str, ...]:
    errors: list[str] = []
    seen: set[BeatmapRankStatus] = set()
    for index, entry in enumerate(evidence.status_crosswalk):
        if entry.canonical_status in seen:
            errors.append(
                _error(_STATUS_CROSSWALK_FILE, index, "canonical_status", "duplicate_id")
            )
        seen.add(entry.canonical_status)
    errors.extend(_crosswalk_semantic_errors(evidence.status_crosswalk))
    return tuple(_sorted_errors(errors))


def _crosswalk_semantic_errors(
    entries: Sequence[StableBeatmapStatusCrosswalkEntry],
) -> tuple[str, ...]:
    errors: list[str] = []
    for index, entry in enumerate(entries):
        for endpoint_name, endpoint in (
            ("getscores", entry.getscores),
            ("beatmap_info", entry.beatmap_info),
        ):
            errors.extend(_endpoint_semantic_errors(index, endpoint_name, endpoint))
    return tuple(_sorted_errors(errors))


def _endpoint_semantic_errors(
    index: int,
    endpoint_name: str,
    endpoint: EndpointStatusEvidence,
) -> tuple[str, ...]:
    errors: list[str] = []
    if endpoint.representation is StatusRepresentation.WIRE and endpoint.wire_status is None:
        errors.append(
            _error(
                _STATUS_CROSSWALK_FILE,
                index,
                f"{endpoint_name}.wire_status",
                "wire_status_required",
            )
        )
    if (
        endpoint.representation is not StatusRepresentation.WIRE
        and endpoint.wire_status is not None
    ):
        errors.append(
            _error(
                _STATUS_CROSSWALK_FILE,
                index,
                f"{endpoint_name}.wire_status",
                "wire_status_requires_wire_representation",
            )
        )
    if (
        endpoint.representation is StatusRepresentation.UNCONFIRMED
        and endpoint.wire_status is not None
    ):
        errors.append(
            _error(
                _STATUS_CROSSWALK_FILE,
                index,
                f"{endpoint_name}.wire_status",
                "unconfirmed_wire_status",
            )
        )
    return tuple(errors)


def _surface_result(label: str, errors: Sequence[str]) -> SurfaceResult:
    if errors:
        message = f"getscores {label} validation failed: {len(errors)} error(s)"
        status = VerificationStatus.FAIL
    else:
        message = f"getscores {label} validation passed"
        status = VerificationStatus.PASS
    return SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=status,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference=f"getscores completion {label}",
    )


def _entry_mappings(
    value: object,
    filename: str,
    errors: list[str],
) -> tuple[Mapping[str, object], ...]:
    if not _is_sequence(value):
        return ()
    entries: list[Mapping[str, object]] = []
    for index, item in enumerate(cast("Sequence[object]", value)):
        if not isinstance(item, Mapping):
            errors.append(_error(filename, index, "entry", "entry_must_be_object"))
            continue
        entries.append(cast("Mapping[str, object]", item))
    return tuple(entries)


def _unknown_entry_fields(
    entry: Mapping[str, object],
    allowed: frozenset[str],
    filename: str,
    location: int,
) -> tuple[str, ...]:
    return tuple(
        _error(filename, location, key if _safe_key(key) else "field", "unknown_entry_field")
        for key in entry
        if key not in allowed
    )


def _forbidden_errors(value: object, filename: str, location: str | int) -> tuple[str, ...]:
    errors: list[str] = []
    pending: list[tuple[object, int]] = [(value, 0)]
    while pending:
        nested, depth = pending.pop()
        if depth > _MAX_MANIFEST_NESTING:
            errors.append(_error(filename, location, "document", "nested_content_too_deep"))
            continue
        if isinstance(nested, Mapping):
            mapping = cast("Mapping[object, object]", nested)
            for key, child in mapping.items():
                if isinstance(key, str):
                    normalized = key.lower().replace("-", "_")
                    if normalized in _FORBIDDEN_RAW_QUERY_KEYS:
                        errors.append(
                            _error(filename, location, "raw_query", "forbidden_raw_query_field")
                        )
                    elif normalized in _FORBIDDEN_CREDENTIAL_KEYS:
                        errors.append(
                            _error(filename, location, "credential", "forbidden_credential_field")
                        )
                    elif normalized in _FORBIDDEN_IDENTITY_KEYS:
                        errors.append(
                            _error(filename, location, "identity", "forbidden_username_field")
                        )
                    elif normalized in _FORBIDDEN_INTERNAL_KEYS:
                        errors.append(
                            _error(filename, location, "provenance", "forbidden_internal_field")
                        )
                    elif normalized in _FORBIDDEN_RAW_BODY_KEYS:
                        errors.append(
                            _error(filename, location, "body", "forbidden_raw_body_field")
                        )
                pending.append((child, depth + 1))
        elif _is_sequence(nested):
            pending.extend((child, depth + 1) for child in cast("Sequence[object]", nested))
    return tuple(_sorted_errors(errors))


def _safe_body_path(value: object, body_root: Path) -> tuple[Path | None, str]:
    if not isinstance(value, str) or not value:
        return None, "invalid_body_path"
    try:
        relative = Path(value)
    except (OSError, ValueError):
        relative = None
    if relative is None or relative.is_absolute() or ".." in relative.parts:
        return None, "unsafe_body_path"
    try:
        candidate = (body_root / relative).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        candidate = None
    if candidate is None or not candidate.is_relative_to(body_root):
        return None, "unsafe_body_path"
    if candidate.is_file():
        return candidate, ""
    return None, "missing_body_file"


def _enum_member[EnumT: Enum](enum_type: type[EnumT], value: object) -> EnumT | None:
    if not isinstance(value, str):
        return None
    try:
        return enum_type(value)
    except ValueError:
        return None


def _enum_tuple[EnumT: Enum](
    enum_type: type[EnumT],
    value: object,
    filename: str,
    location: int,
    field_name: str,
    errors: list[str],
) -> tuple[EnumT, ...] | None:
    if not _is_sequence(value):
        errors.append(_error(filename, location, field_name, "invalid_enum_list"))
        return None
    members: list[EnumT] = []
    valid = True
    for member_value in cast("Sequence[object]", value):
        member = _enum_member(enum_type, member_value)
        if member is None:
            valid = False
        else:
            members.append(member)
    if not valid:
        errors.append(_error(filename, location, field_name, "invalid_enum"))
        return None
    return tuple(members)


def _string_mapping(value: object) -> Mapping[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    mapping = cast("Mapping[object, object]", value)
    result: dict[str, str] = {}
    for key, child in mapping.items():
        if not isinstance(key, str) or not isinstance(child, str):
            return None
        result[key] = child
    return result


def _string_tuple_value(value: object) -> tuple[str, ...] | None:
    if not _is_sequence(value):
        return None
    items = cast("Sequence[object]", value)
    if not all(isinstance(item, str) for item in items):
        return None
    return tuple(cast("str", item) for item in items)


def _evidence_source_tuple(
    value: object,
) -> tuple[GetscoresEvidenceSource, ...] | None:
    strings = _string_tuple_value(value)
    if strings is None:
        return None
    try:
        return tuple(GetscoresEvidenceSource(item) for item in strings)
    except ValueError:
        return None


def _is_safe_evidence_source(value: str) -> bool:
    if not value or len(value) > _MAX_EVIDENCE_SOURCE_LENGTH:
        return False
    if any(character in value for character in "\x00\r\n=&?%"):
        return False
    prefix, separator, payload = value.partition(":")
    if not separator:
        prefix, separator, payload = value.partition("/")
    path_segments = payload.split("/")
    return (
        bool(separator)
        and prefix in _EVIDENCE_SOURCE_PREFIXES
        and all(segment not in {"", ".", ".."} for segment in path_segments)
        and _EVIDENCE_SOURCE_PAYLOAD_PATTERN.fullmatch(payload) is not None
    )


def _int_value(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _non_negative_int(value: object) -> int | None:
    number = _int_value(value)
    if number is None or number < 0:
        return None
    return number


def _strict_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _safe_key(value: str) -> bool:
    return bool(_SAFE_IDENTIFIER.fullmatch(value))


def _error(filename: str, location: str | int, field_name: str, code: str) -> str:
    safe_field = field_name if _safe_key(field_name.replace(".", "_")) else "field"
    return f"{filename}:entry[{location}]:{safe_field}:{code}"


def _sorted_errors(errors: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(set(errors)))


__all__ = [
    "EndpointEvidenceState",
    "EndpointStatusEvidence",
    "GetscoresBodyEncoding",
    "GetscoresBranchCase",
    "GetscoresCompletionEvidence",
    "GetscoresEvidenceSource",
    "GetscoresEvidenceStatus",
    "GetscoresEvidenceValidationError",
    "GetscoresIdentityProfile",
    "GetscoresMutationProfile",
    "GetscoresRequestSelector",
    "GetscoresSeedProfile",
    "GetscoresWireShapeFixture",
    "GetscoresWireShapeId",
    "StableBeatmapStatusCrosswalkEntry",
    "StatusRepresentation",
    "load_getscores_completion_evidence",
    "validate_getscores_completion_evidence",
]
