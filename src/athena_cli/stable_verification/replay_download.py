from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    ReplayDownloadAuthField,
    ReplayDownloadSanitizedFixture,
    StableSurface,
    SurfaceResult,
    VerificationStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

_REQUEST_METADATA_FIXTURE = "target_client_request_metadata.json"
_RESPONSE_METADATA_FIXTURE = "target_client_response_metadata.json"
_BODY_ASSEMBLY_DECISION_FIXTURE = "body_assembly_decision.json"
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
_REQUIRED_BODY_DECISION_FIELDS = frozenset(
    (
        "status",
        "download_body_strategy",
        "observed_success_body_kind",
        "observed_success_body_source",
        "observed_success_body_is_complete_osr",
        "observed_success_body_is_zip_archive",
        "stored_blob_integrity",
        "stored_blob_target_body_compatible",
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
    body_assembly_decision: Mapping[str, object]
    fixtures: Mapping[str, ReplayDownloadSanitizedFixture]


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
    body_assembly_decision = _read_json_object(root / _BODY_ASSEMBLY_DECISION_FIXTURE)

    return ReplayDownloadEvidenceBundle(
        request_metadata=request_metadata,
        response_metadata=response_metadata,
        body_assembly_decision=body_assembly_decision,
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
            "replay download body assembly decision metadata",
            _BODY_ASSEMBLY_DECISION_FIXTURE,
            decision_errors,
        ),
    )


def _validate_request_metadata(document: Mapping[str, object]) -> tuple[str, ...]:
    errors = list(_validate_metadata_document(document))
    captures = _capture_mappings(document)
    if not captures:
        errors.append("missing_capture_list")

    for capture in captures:
        errors.extend(_missing_required_fields(capture, _REQUIRED_REQUEST_CAPTURE_FIELDS))
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


def _validate_string_list_field(
    entry: Mapping[str, object],
    key: str,
    *,
    required: bool = True,
) -> tuple[str, ...]:
    value = entry.get(key)
    if value is None and not required:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return (f"{key}_must_be_string_list",)
    if not all(isinstance(item, str) and _is_safe_metadata_token(item) for item in value):
        return (f"{key}_must_contain_safe_strings",)

    return ()


def _validate_int_field(entry: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = entry.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return ()

    return (f"{key}_must_be_int",)


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
