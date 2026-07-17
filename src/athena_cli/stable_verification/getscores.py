from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

from athena_cli.stable_verification.client import ProbeResponse, StableProbeClient
from athena_cli.stable_verification.getscores_evidence import (
    GetscoresEvidenceValidationError,
    load_getscores_completion_evidence,
    validate_getscores_completion_evidence,
)
from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    GetscoresProbeCase,
    StableSurface,
    StableTarget,
    SurfaceResult,
    VerificationStatus,
)
from athena_cli.stable_verification.parsers import (
    GetscoresHeader,
    GetscoresResponse,
    GetscoresResponseKind,
    parse_getscores_response,
)

GETSCORES_WEB_LEGACY_PATH = "/web/osu-osz2-getscores.php"

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_WEB_LEGACY_FIXTURE_DIR = _PROJECT_ROOT / "tests" / "fixtures" / "web_legacy" / "getscores"
_DEFAULT_COMPLETION_MANIFEST_ROOT = (
    _PROJECT_ROOT / "tests" / "fixtures" / "stable_compatibility" / "getscores"
)
_DEFAULT_COMPLETION_BODY_ROOT = _DEFAULT_WEB_LEGACY_FIXTURE_DIR / "completion"
_DEFAULT_PROBE_CASES_PATH = (
    _PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "stable_compatibility"
    / "getscores"
    / "probe_cases.json"
)
_LEADERBOARD_TYPE_QUERY_VALUES = {
    "local": "1",
    "selected": "2",
    "selected_mods": "2",
    "friends": "3",
    "country": "4",
}
_COMPLETION_EVIDENCE_LABELS = (
    "response shapes",
    "branch cases",
    "status crosswalk",
)


class GetscoresProbeClient(Protocol):
    def get_web_legacy(
        self,
        path: str,
        *,
        query: Mapping[str, str],
        host_prefix: str = "osu",
    ) -> ProbeResponse: ...


class GetscoresOptionalProbe[ProbePrerequisitesT_contra](Protocol):
    def probe_getscores(
        self,
        case: GetscoresProbeCase,
        prerequisites: ProbePrerequisitesT_contra,
    ) -> SurfaceResult: ...


class GetscoresVerifier[ProbePrerequisitesT]:
    def __init__(
        self,
        *,
        target: StableTarget | None = None,
        client: GetscoresProbeClient | None = None,
        optional_probe: GetscoresOptionalProbe[ProbePrerequisitesT] | None = None,
        optional_probe_prerequisites: ProbePrerequisitesT | None = None,
        fixture_dir: Path | None = None,
        probe_cases_path: Path | None = None,
    ) -> None:
        self._target: StableTarget | None = target
        self._client: GetscoresProbeClient | None = client or (
            StableProbeClient(target=target) if target is not None else None
        )
        self._optional_probe: GetscoresOptionalProbe[ProbePrerequisitesT] | None = optional_probe
        self._optional_probe_prerequisites: ProbePrerequisitesT | None = (
            optional_probe_prerequisites
        )
        self._fixture_dir: Path = fixture_dir or _DEFAULT_WEB_LEGACY_FIXTURE_DIR
        self._probe_cases_path: Path = probe_cases_path or _DEFAULT_PROBE_CASES_PATH

    def verify_fixtures(self) -> tuple[SurfaceResult, ...]:
        """Legacy fixtureとcompletion evidenceを必須evidenceとして検証する。

        Args:
            なし.

        Returns:
            tuple[SurfaceResult, ...]: Legacy response fixtureとcompletion manifestの検証結果。

        Raises:
            なし: Manifestの読込失敗は安全な必須失敗結果へ変換する。

        Notes:
            Completion evidenceの診断とreferenceへraw valueやfilesystem pathを含めない。
        """

        legacy_results = tuple(
            self._verify_fixture(fixture_path)
            for fixture_path in sorted(self._fixture_dir.glob("*.txt"))
        )
        return (*legacy_results, *_verify_completion_evidence())

    def load_probe_cases(self) -> tuple[GetscoresProbeCase, ...]:
        raw_cases = cast(
            "object",
            json.loads(self._probe_cases_path.read_text(encoding="utf-8")),
        )
        if not isinstance(raw_cases, list):
            msg = f"getscores probe cases must be a JSON array: {self._probe_cases_path}"
            raise TypeError(msg)

        case_entries = cast("list[object]", raw_cases)
        return tuple(
            _probe_case_from_mapping(entry, index) for index, entry in enumerate(case_entries)
        )

    def probe_target(self, case: GetscoresProbeCase) -> SurfaceResult:
        if self._client is None:
            return _local_probe_result(
                VerificationStatus.SKIP,
                "getscores local probe skipped: target not configured",
            )

        query = build_getscores_query(case)
        response = self._client.get_web_legacy(
            GETSCORES_WEB_LEGACY_PATH,
            query=query,
        )
        if response.status is not VerificationStatus.PASS:
            return SurfaceResult(
                surface=StableSurface.GETSCORES,
                status=response.status,
                evidence_type=EvidenceType.HEADLESS_PROBE,
                scope=EvidenceScope.OPTIONAL,
                diagnostic_summary=response.diagnostic_summary,
                reference="local getscores probe",
            )

        return _target_result_from_body(response)

    def probe_optional_client(self, case: GetscoresProbeCase) -> SurfaceResult:
        if self._target is None:
            return _optional_osu_py_result(
                VerificationStatus.SKIP,
                "osu.py getscores probe skipped: target not configured",
            )
        if self._optional_probe_prerequisites is None:
            return _optional_osu_py_result(
                VerificationStatus.SKIP,
                "osu.py getscores probe skipped: prerequisites not configured",
            )
        if self._optional_probe is None:
            return _optional_osu_py_result(
                VerificationStatus.SKIP,
                "osu.py getscores probe skipped: probe not configured",
            )

        return self._optional_probe.probe_getscores(
            case,
            self._optional_probe_prerequisites,
        )

    def _verify_fixture(self, fixture_path: Path) -> SurfaceResult:
        parsed = parse_getscores_response(fixture_path.read_bytes())
        if parsed.error is not None or parsed.response is None:
            return SurfaceResult(
                surface=StableSurface.GETSCORES,
                status=VerificationStatus.FAIL,
                evidence_type=EvidenceType.GOLDEN_FIXTURE,
                scope=EvidenceScope.MANDATORY,
                diagnostic_summary=DiagnosticSummary(
                    message=f"{fixture_path.name} parse failed: {parsed.error}",
                ),
                reference=_reference(fixture_path),
            )

        return SurfaceResult(
            surface=StableSurface.GETSCORES,
            status=VerificationStatus.PASS,
            evidence_type=EvidenceType.GOLDEN_FIXTURE,
            scope=EvidenceScope.MANDATORY,
            diagnostic_summary=DiagnosticSummary(
                message=f"{fixture_path.name} parsed as {_response_case(parsed.response)}",
            ),
            reference=_reference(fixture_path),
        )


def build_getscores_query(case: GetscoresProbeCase) -> dict[str, str]:
    query = {
        "c": _required_string(case.checksum, "checksum"),
        "f": _required_string(case.filename, "filename"),
        "m": str(_required_int(case.mode, "mode")),
        "mods": str(_required_int(case.mods, "mods")),
        "v": _leaderboard_type_query_value(case.leaderboard_type),
        "vv": str(_required_int(case.request_version, "request_version")),
    }
    if case.beatmapset_id is not None:
        query["i"] = str(_required_int(case.beatmapset_id, "beatmapset_id"))

    return query


def _probe_case_from_mapping(entry: object, index: int) -> GetscoresProbeCase:
    if not isinstance(entry, Mapping):
        msg = f"getscores probe case #{index} must be an object"
        raise TypeError(msg)

    case_data = cast("Mapping[object, object]", entry)
    return GetscoresProbeCase(
        name=_json_string(case_data, "name", index),
        checksum=_json_string(case_data, "checksum", index),
        filename=_json_string(case_data, "filename", index),
        beatmapset_id=_json_optional_int(case_data, "beatmapset_id", index),
        mode=_json_int(case_data, "mode", index),
        mods=_json_int(case_data, "mods", index),
        leaderboard_type=_json_string(case_data, "leaderboard_type", index),
        request_version=_json_int(case_data, "request_version", index),
    )


def _target_result_from_body(response: ProbeResponse) -> SurfaceResult:
    parsed = parse_getscores_response(response.body)
    if parsed.error is not None or parsed.response is None:
        return SurfaceResult(
            surface=StableSurface.GETSCORES,
            status=VerificationStatus.FAIL,
            evidence_type=EvidenceType.HEADLESS_PROBE,
            scope=EvidenceScope.OPTIONAL,
            diagnostic_summary=DiagnosticSummary(
                message=f"getscores response parse failed: {parsed.error}",
                method=response.diagnostic_summary.method,
                path=response.diagnostic_summary.path,
                status_code=response.diagnostic_summary.status_code,
                response_byte_size=response.diagnostic_summary.response_byte_size,
            ),
            reference="local getscores probe",
        )

    response_case = _response_case(parsed.response)
    status = _target_status(parsed.response)
    return SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=status,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        diagnostic_summary=DiagnosticSummary(
            message=f"getscores response parsed as {response_case}",
            method=response.diagnostic_summary.method,
            path=response.diagnostic_summary.path,
            status_code=response.diagnostic_summary.status_code,
            response_byte_size=response.diagnostic_summary.response_byte_size,
        ),
        reference="local getscores probe",
    )


def _target_status(response: GetscoresResponse) -> VerificationStatus:
    if response.kind is GetscoresResponseKind.NOT_SUBMITTED:
        return VerificationStatus.UNAVAILABLE

    return VerificationStatus.PASS


def _has_only_personal_best_fallback_score_row(header: GetscoresHeader) -> bool:
    return (
        header.personal_best_row is not None
        and len(header.score_rows) == 1
        and header.score_rows[0] == header.personal_best_row
    )


def _response_case(response: GetscoresResponse) -> str:
    if response.kind is GetscoresResponseKind.NOT_SUBMITTED:
        return "unavailable"
    if response.kind is GetscoresResponseKind.UPDATE_AVAILABLE:
        return "update available"

    header = response.header
    if header is None:
        response_case = "header gap"
    elif _has_only_personal_best_fallback_score_row(header):
        response_case = "header personal best fallback row"
    elif header.score_rows:
        response_case = "header score rows"
    elif header.personal_best_row is not None:
        response_case = "header personal best"
    elif header.empty_leaderboard:
        response_case = "header empty leaderboard"
    else:
        response_case = "header"

    return response_case


def _local_probe_result(status: VerificationStatus, message: str) -> SurfaceResult:
    return SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=status,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference="local getscores probe",
    )


def _optional_osu_py_result(status: VerificationStatus, message: str) -> SurfaceResult:
    return SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=status,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference="optional:osu.py getscores probe",
    )


def _verify_completion_evidence() -> tuple[SurfaceResult, ...]:
    """Completion evidenceを読み込み, 検証結果へ変換する。

    Args:
        なし.

    Returns:
        tuple[SurfaceResult, ...]: 3種類のcompletion evidenceの必須検証結果。

    Raises:
        なし: Loaderの安全な検証失敗は固定された失敗結果へ変換する。

    Notes:
        Loader由来の診断内容を出力せず, raw value, path, internal provenanceを隠す。
    """

    try:
        evidence = load_getscores_completion_evidence(
            _DEFAULT_COMPLETION_MANIFEST_ROOT,
            _DEFAULT_COMPLETION_BODY_ROOT,
        )
    except GetscoresEvidenceValidationError:
        return _completion_evidence_failure_results()

    return validate_getscores_completion_evidence(evidence)


def _completion_evidence_failure_results() -> tuple[SurfaceResult, ...]:
    """Completion evidenceのloader失敗を安全な必須結果として投影する。

    Args:
        なし.

    Returns:
        tuple[SurfaceResult, ...]: 各completion evidence種類へ対応する固定の失敗結果。

    Raises:
        なし.

    Notes:
        入力値, path, loader内部のprovenanceやerror detailを診断へ露出しない。
    """

    return tuple(
        SurfaceResult(
            surface=StableSurface.GETSCORES,
            status=VerificationStatus.FAIL,
            evidence_type=EvidenceType.GOLDEN_FIXTURE,
            scope=EvidenceScope.MANDATORY,
            diagnostic_summary=DiagnosticSummary(
                message="getscores completion evidence validation failed"
            ),
            reference=f"getscores completion {label}",
        )
        for label in _COMPLETION_EVIDENCE_LABELS
    )


def _json_string(entry: Mapping[object, object], key: str, index: int) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        msg = f"getscores probe case #{index} has invalid {key}"
        raise ValueError(msg)

    return value


def _json_optional_int(
    entry: Mapping[object, object],
    key: str,
    index: int,
) -> int | None:
    value = entry.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"getscores probe case #{index} has invalid {key}"
        raise TypeError(msg)

    return value


def _json_int(entry: Mapping[object, object], key: str, index: int) -> int:
    value = _json_optional_int(entry, key, index)
    if value is None:
        msg = f"getscores probe case #{index} has invalid {key}"
        raise ValueError(msg)

    return value


def _required_string(value: str, field_name: str) -> str:
    if not value:
        msg = f"getscores probe case requires {field_name}"
        raise ValueError(msg)

    return value


def _required_int(value: int, field_name: str) -> int:
    if isinstance(value, bool):
        msg = f"getscores probe case requires integer {field_name}"
        raise TypeError(msg)

    return value


def _leaderboard_type_query_value(leaderboard_type: str) -> str:
    normalized = leaderboard_type.strip().lower()
    mapped = _LEADERBOARD_TYPE_QUERY_VALUES.get(normalized)
    if mapped is not None:
        return mapped
    if normalized.isdecimal():
        return normalized

    msg = f"unsupported getscores leaderboard_type: {leaderboard_type}"
    raise ValueError(msg)


def _reference(path: Path) -> str:
    try:
        return str(path.relative_to(_PROJECT_ROOT))
    except ValueError:
        return str(path)


__all__ = [
    "GETSCORES_WEB_LEGACY_PATH",
    "GetscoresOptionalProbe",
    "GetscoresProbeClient",
    "GetscoresVerifier",
    "build_getscores_query",
]
