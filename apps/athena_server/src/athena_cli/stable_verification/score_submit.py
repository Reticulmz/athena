"""Stable score submitのfixtureとcompleted responseを検証する機能を提供する."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    StableSurface,
    SurfaceResult,
    VerificationStatus,
)
from athena_cli.stable_verification.parsers import (
    ScoreSubmitChart,
    ScoreSubmitResponse,
    parse_score_submit_response,
)
from athena_cli.stable_verification.source_checkout import source_checkout_path

_DEFAULT_FIXTURE_DIR = source_checkout_path(
    Path(__file__),
    "apps",
    "athena_server",
    "tests",
    "fixtures",
    "stable_compatibility",
    "score_submit",
)
_REQUEST_METADATA_FIXTURE = "request_metadata.json"
_COMPLETED_RESPONSE_FIXTURE = "completed_response.txt"
_REQUIRED_SCORE_FIELD_COUNT = 2
_REQUIRED_REQUEST_FIELDS = frozenset(("score", "iv", "pass", "x", "ft", "osuver"))
_OPAQUE_METADATA_FIELDS = frozenset(("fs", "bmk", "sbk", "c1", "st", "i", "token"))
_FORBIDDEN_METADATA_FRAGMENTS = (
    "password_hash",
    "password_md5",
    "session_token",
    "raw_replay",
    "replay_data",
    "encrypted_payload",
    "client_hash",
)
_BEATMAP_CHART_REQUIRED_FIELDS = (
    "achieved",
    "rankBefore",
    "rankAfter",
    "rankedScoreBefore",
    "rankedScoreAfter",
    "maxComboBefore",
    "maxComboAfter",
    "accuracyBefore",
    "accuracyAfter",
    "ppBefore",
    "ppAfter",
    "onlineScoreId",
)
_OVERALL_CHART_REQUIRED_FIELDS = (
    "rankBefore",
    "rankAfter",
    "rankedScoreBefore",
    "rankedScoreAfter",
    "totalScoreBefore",
    "totalScoreAfter",
    "maxComboBefore",
    "maxComboAfter",
    "accuracyBefore",
    "accuracyAfter",
    "ppBefore",
    "ppAfter",
    "achievements-new",
    "onlineScoreId",
)


class ScoreSubmitVerifier:
    """Stable score submitのrequest metadataとcompleted responseを検証する.

    Attributes:
        _fixture_dir (Path): 検証対象のmetadataとresponse fixtureを置くdirectory.
    """

    def __init__(self, *, fixture_dir: Path | None = None) -> None:
        """Score submit fixtureの読み込み先を初期化する.

        Args:
            fixture_dir (Path | None): Fixture directory.未指定時はrepository既定pathを使用する.
        """
        self._fixture_dir: Path = fixture_dir or _DEFAULT_FIXTURE_DIR

    def verify_golden_response(self) -> tuple[SurfaceResult, ...]:
        """Score submitのgolden fixtureと既知projection gapを検証する.

        Returns:
            tuple[SurfaceResult, ...]: Request metadata,completed response,既知gapの順の検証結果.
        """
        return (
            self._verify_request_metadata(),
            self._verify_completed_fixture_response(),
            _known_projection_gap_result(),
        )

    def verify_response_body(self, body: bytes, *, reference: str) -> SurfaceResult:
        """Completed response bodyをgolden fixture evidenceとして検証する.

        Args:
            body (bytes): 検証するstable score submit response body.
            reference (str): Evidenceの参照先を示すreport-safeな文字列.

        Returns:
            SurfaceResult: Required chart fieldの有無を表すmandatory検証結果.
        """
        return self.verify_response_body_as(
            body,
            reference=reference,
            evidence_type=EvidenceType.GOLDEN_FIXTURE,
        )

    def verify_response_body_as(
        self,
        body: bytes,
        *,
        reference: str,
        evidence_type: EvidenceType,
    ) -> SurfaceResult:
        """Completed response bodyを指定したevidence種別として検証する.

        Args:
            body (bytes): 検証するstable score submit response body.
            reference (str): Evidenceの参照先を示すreport-safeな文字列.
            evidence_type (EvidenceType): 結果へ記録するevidence取得手段.

        Returns:
            SurfaceResult: Parse成功と必須chart fieldの有無を表すmandatory検証結果.

        Notes:
            Response bodyの内容は診断に含めず,parse失敗時も固定の安全なmessageを返す.
        """
        parsed = parse_score_submit_response(body)
        if parsed.response is None:
            return _mandatory_result(
                VerificationStatus.FAIL,
                "score submit response is not a completed stable chart response",
                reference,
                evidence_type=evidence_type,
                response_byte_size=len(body),
            )

        missing_fields = _missing_required_fields(parsed.response)
        if missing_fields:
            return _mandatory_result(
                VerificationStatus.FAIL,
                "score submit completed response missing required chart fields: "
                + ", ".join(missing_fields),
                reference,
                evidence_type=evidence_type,
                response_byte_size=len(body),
            )

        return _mandatory_result(
            VerificationStatus.PASS,
            "score submit completed fixture parsed with required chart fields",
            reference,
            evidence_type=evidence_type,
            response_byte_size=len(body),
        )

    def _verify_completed_fixture_response(self) -> SurfaceResult:
        """Completed response fixtureを読み込み検証する.

        Returns:
            SurfaceResult: Fixture未配置時はUNAVAILABLE,それ以外はresponse bodyの検証結果.
        """
        reference = self._fixture_reference(_COMPLETED_RESPONSE_FIXTURE)
        try:
            body = self._read_fixture_bytes(_COMPLETED_RESPONSE_FIXTURE)
        except OSError:
            return _mandatory_result(
                VerificationStatus.UNAVAILABLE,
                "score submit completed response fixture unavailable",
                reference,
            )

        return self.verify_response_body(body, reference=reference)

    def _verify_request_metadata(self) -> SurfaceResult:
        """Score submit request metadata fixtureのschemaと秘匿方針を検証する.

        Returns:
            SurfaceResult: Fixture未配置時はUNAVAILABLE.JSONまたはmetadata不正時はFAIL.
                正常時はPASSの結果.
        """
        reference = self._fixture_reference(_REQUEST_METADATA_FIXTURE)
        try:
            metadata = _read_json_object(self._fixture_dir / _REQUEST_METADATA_FIXTURE)
        except OSError:
            return _mandatory_result(
                VerificationStatus.UNAVAILABLE,
                "score submit request metadata fixture unavailable",
                reference,
            )
        except json.JSONDecodeError:
            return _mandatory_result(
                VerificationStatus.FAIL,
                "score submit request metadata fixture is not valid JSON",
                reference,
            )
        except TypeError as exc:
            return _mandatory_result(
                VerificationStatus.FAIL,
                str(exc),
                reference,
            )

        validation_error = _validate_request_metadata(metadata)
        if validation_error is not None:
            return _mandatory_result(
                VerificationStatus.FAIL,
                validation_error,
                reference,
            )

        score_field_count = _int_value(metadata["score_field_count"])
        message = (
            f"score submit request metadata valid: multipart/form-data "
            f"score fields={score_field_count} replay=present"
        )
        return _mandatory_result(
            VerificationStatus.PASS,
            message,
            reference,
        )

    def _read_fixture_bytes(self, name: str) -> bytes:
        """指定名のfixtureをbytesとして読み込む.

        Args:
            name (str): `_fixture_dir`配下で読むfixture file名.

        Returns:
            bytes: Fixture fileの内容.

        Raises:
            OSError: Fixture fileを開けない場合.
        """
        return (self._fixture_dir / name).read_bytes()

    def _fixture_reference(self, name: str) -> str:
        """Fixture fileのreport用path表現を返す.

        Args:
            name (str): `_fixture_dir`配下のfixture file名.

        Returns:
            str: POSIX区切りで表したfixture path.
        """
        return (self._fixture_dir / name).as_posix()


def _read_json_object(path: Path) -> dict[str, object]:
    """JSON object fixtureを文字列keyのdictとして読み込む.

    Args:
        path (Path): 読み込むJSON fixture path.

    Returns:
        dict[str, object]: JSON objectのfieldを保持するdict.

    Raises:
        OSError: Fixture fileを開けない場合.
        json.JSONDecodeError: FixtureがJSONとして不正な場合.
        TypeError: Top-level valueがobjectでないかkeyが文字列でない場合.
    """
    raw = cast("object", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(raw, Mapping):
        msg = "score submit request metadata fixture must be a JSON object"
        raise TypeError(msg)

    metadata: dict[str, object] = {}
    raw_mapping = cast("Mapping[object, object]", raw)
    for key, value in raw_mapping.items():
        if not isinstance(key, str):
            msg = "score submit request metadata fixture keys must be strings"
            raise TypeError(msg)
        metadata[key] = value

    return metadata


def _validate_request_metadata(metadata: dict[str, object]) -> str | None:
    """Score submit request metadataの全検証を順番に実行する.

    Args:
        metadata (dict[str, object]): JSON fixtureから読み込んだrequest metadata.

    Returns:
        str | None: 最初のvalidation error.すべて有効な場合はNone.
    """
    validators = (
        _validate_metadata_required_keys,
        _validate_metadata_report_safety,
        _validate_metadata_content_type,
        _validate_metadata_field_order,
        _validate_metadata_opaque_fields,
    )
    for validator in validators:
        validation_error = validator(metadata)
        if validation_error is not None:
            return validation_error

    return None


def _validate_metadata_required_keys(metadata: dict[str, object]) -> str | None:
    """Request metadataに必須top-level keyがあるか検証する.

    Args:
        metadata (dict[str, object]): 検証するrequest metadata.

    Returns:
        str | None: 欠落keyを示すerror.すべて存在する場合はNone.
    """
    required_keys = (
        "content_type",
        "field_order",
        "score_field_count",
        "replay_present",
        "opaque_metadata_fields",
        "secret_policy",
    )
    missing_keys = [key for key in required_keys if key not in metadata]
    if missing_keys:
        return "score submit request metadata missing keys: " + ", ".join(missing_keys)

    return None


def _validate_metadata_report_safety(metadata: dict[str, object]) -> str | None:
    """Request metadataにreportへ出せない値が含まれないか検証する.

    Args:
        metadata (dict[str, object]): 検証するrequest metadata.

    Returns:
        str | None: 禁止fragmentを検出したerror.検出しない場合はNone.
    """
    if _contains_forbidden_metadata(metadata):
        return "score submit request metadata contains report-unsafe values"

    return None


def _validate_metadata_content_type(metadata: dict[str, object]) -> str | None:
    """Request metadataのcontent typeとsecret policyを検証する.

    Args:
        metadata (dict[str, object]): 検証するrequest metadata.

    Returns:
        str | None: `multipart/form-data`または`metadata-only`に一致しないerror.一致時はNone.
    """
    content_type = _string_value(metadata["content_type"])
    if content_type != "multipart/form-data":
        return "score submit request metadata content_type must be multipart/form-data"

    secret_policy = _string_value(metadata["secret_policy"])
    if secret_policy != "metadata-only":
        return "score submit request metadata must use metadata-only secret policy"

    return None


def _validate_metadata_field_order(metadata: dict[str, object]) -> str | None:
    """Request field orderとreplay score fieldの条件を検証する.

    Args:
        metadata (dict[str, object]): 検証するrequest metadata.

    Returns:
        str | None: 必須field,score field数,replay有無の不整合を示すerror.正常時はNone.
    """
    field_order_result = _string_tuple(metadata["field_order"], "field_order")
    if isinstance(field_order_result, str):
        return field_order_result

    missing_request_fields = sorted(_REQUIRED_REQUEST_FIELDS - set(field_order_result))
    if missing_request_fields:
        return "score submit request metadata missing fields: " + ", ".join(missing_request_fields)

    score_field_count = _int_value(metadata["score_field_count"])
    if score_field_count != field_order_result.count("score"):
        return "score submit request metadata score field count does not match"
    if score_field_count < _REQUIRED_SCORE_FIELD_COUNT:
        return "score submit request metadata must include replay score field"

    replay_present = _bool_value(metadata["replay_present"])
    if not replay_present:
        return "score submit request metadata must mark replay as present"

    return None


def _validate_metadata_opaque_fields(metadata: dict[str, object]) -> str | None:
    """Opaque metadata fieldが許可集合だけで構成されるか検証する.

    Args:
        metadata (dict[str, object]): 検証するrequest metadata.

    Returns:
        str | None: 型不正または未対応opaque fieldを示すerror.正常時はNone.
    """
    opaque_result = _string_tuple(
        metadata["opaque_metadata_fields"],
        "opaque_metadata_fields",
    )
    if isinstance(opaque_result, str):
        return opaque_result

    unsupported_opaque_fields = sorted(set(opaque_result) - _OPAQUE_METADATA_FIELDS)
    if unsupported_opaque_fields:
        return "score submit request metadata has unsupported opaque fields: " + ", ".join(
            unsupported_opaque_fields
        )

    return None


def _contains_forbidden_metadata(value: object) -> bool:
    """入れ子のmetadataに秘密情報を示すfragmentが含まれるか判定する.

    Args:
        value (object): Mappingまたはsequenceを含み得る検証対象.

    Returns:
        bool: 禁止fragmentを持つkeyまたは文字列値を見つけた場合はTrue.
    """
    if isinstance(value, Mapping):
        value_mapping = cast("Mapping[object, object]", value)
        for key, child in value_mapping.items():
            if isinstance(key, str) and _contains_forbidden_fragment(key):
                return True
            if _contains_forbidden_metadata(child):
                return True
        return False

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_contains_forbidden_metadata(child) for child in value)

    return isinstance(value, str) and _contains_forbidden_fragment(value)


def _contains_forbidden_fragment(value: str) -> bool:
    """文字列が禁止metadata fragmentを含むか判定する.

    Args:
        value (str): 検査するmetadata keyまたは文字列値.

    Returns:
        bool: Forbidden metadata fragmentを1つ以上含む場合はTrue.
    """
    return any(fragment in value for fragment in _FORBIDDEN_METADATA_FRAGMENTS)


def _string_value(value: object) -> str:
    """Objectから文字列値だけを取り出す.

    Args:
        value (object): JSON metadataから取得した値.

    Returns:
        str: 値が文字列ならその値.それ以外は空文字列.
    """
    if isinstance(value, str):
        return value

    return ""


def _int_value(value: object) -> int:
    """Objectからboolを除く整数値だけを取り出す.

    Args:
        value (object): JSON metadataから取得した値.

    Returns:
        int: 値が整数ならその値.それ以外はvalidation用sentinelの`-1`.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value

    return -1


def _bool_value(value: object) -> bool:
    """Objectからbool値だけを取り出す.

    Args:
        value (object): JSON metadataから取得した値.

    Returns:
        bool: 値がboolならその値.それ以外はFalse.
    """
    if isinstance(value, bool):
        return value

    return False


def _string_tuple(value: object, field_name: str) -> tuple[str, ...] | str:
    """JSON listを文字列tupleへ変換し不正時はerrorを返す.

    Args:
        value (object): 変換するJSON metadata fieldの値.
        field_name (str): Error messageへ含めるfield名.

    Returns:
        tuple[str, ...] | str: 文字列だけで構成されるtuple.型不正時はerror message.
    """
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return f"score submit request metadata {field_name} must be a list"

    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return f"score submit request metadata {field_name} must contain strings"
        items.append(item)

    return tuple(items)


def _missing_required_fields(response: ScoreSubmitResponse) -> tuple[str, ...]:
    """Completed responseのbeatmap/overall chartに不足するfieldを集める.

    Args:
        response (ScoreSubmitResponse): 検査する構造化completed response.

    Returns:
        tuple[str, ...]: `beatmap.`または`overall.`接頭辞付きの不足field名.
    """
    return _missing_chart_fields("beatmap", response.beatmap_chart) + _missing_chart_fields(
        "overall", response.overall_chart
    )


def _missing_chart_fields(prefix: str, chart: ScoreSubmitChart) -> tuple[str, ...]:
    """指定chartに不足する必須fieldを接頭辞付きで返す.

    Args:
        prefix (str): `beatmap`または`overall`のchart種別.
        chart (ScoreSubmitChart): 検査する構造化chart.

    Returns:
        tuple[str, ...]: 接頭辞付きの不足field名.すべて存在する場合は空tuple.
    """
    required_fields = (
        _BEATMAP_CHART_REQUIRED_FIELDS if prefix == "beatmap" else _OVERALL_CHART_REQUIRED_FIELDS
    )
    return tuple(f"{prefix}.{field}" for field in required_fields if field not in chart.fields)


def _mandatory_result(
    status: VerificationStatus,
    message: str,
    reference: str,
    *,
    evidence_type: EvidenceType = EvidenceType.GOLDEN_FIXTURE,
    response_byte_size: int | None = None,
) -> SurfaceResult:
    """Score submit surfaceのmandatory検証結果を組み立てる.

    Args:
        status (VerificationStatus): 検証の成否または可用性を表す状態.
        message (str): Report-safeな診断message.
        reference (str): Evidenceの参照先.
        evidence_type (EvidenceType): Evidenceの取得手段.既定値はgolden fixture.
        response_byte_size (int | None): Response bodyのbyte size.未測定時はNone.

    Returns:
        SurfaceResult: `StableSurface.SCORE_SUBMIT`とmandatory scopeを持つ結果.
    """
    return SurfaceResult(
        surface=StableSurface.SCORE_SUBMIT,
        status=status,
        evidence_type=evidence_type,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=DiagnosticSummary(
            message=message,
            response_byte_size=response_byte_size,
        ),
        reference=reference,
    )


def _known_projection_gap_result() -> SurfaceResult:
    """User statsとleaderboard projectionの既知gapを結果へ変換する.

    Returns:
        SurfaceResult: Run failureにしないmandatory known-gap結果.
    """
    return SurfaceResult(
        surface=StableSurface.SCORE_SUBMIT,
        status=VerificationStatus.KNOWN_GAP,
        evidence_type=EvidenceType.GOLDEN_FIXTURE,
        scope=EvidenceScope.MANDATORY,
        diagnostic_summary=DiagnosticSummary(
            message=(
                "score submit user-stats and leaderboard projection fields are known "
                "gaps: rank, rankedScore, totalScore"
            ),
        ),
        reference="user-stats, beatmap-leaderboards",
    )


__all__ = ["ScoreSubmitVerifier"]
