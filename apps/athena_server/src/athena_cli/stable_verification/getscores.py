"""Stable getscores fixture検証と任意target probeを提供する."""

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
from athena_cli.stable_verification.source_checkout import source_checkout_path

GETSCORES_WEB_LEGACY_PATH = "/web/osu-osz2-getscores.php"

_PROJECT_ROOT = source_checkout_path(Path(__file__))
_SERVER_TEST_ROOT = _PROJECT_ROOT / "apps" / "athena_server" / "tests"
_DEFAULT_WEB_LEGACY_FIXTURE_DIR = _SERVER_TEST_ROOT / "fixtures" / "web_legacy" / "getscores"
_DEFAULT_COMPLETION_MANIFEST_ROOT = (
    _SERVER_TEST_ROOT / "fixtures" / "stable_compatibility" / "getscores"
)
_DEFAULT_COMPLETION_BODY_ROOT = _DEFAULT_WEB_LEGACY_FIXTURE_DIR / "completion"
_DEFAULT_PROBE_CASES_PATH = (
    _SERVER_TEST_ROOT / "fixtures" / "stable_compatibility" / "getscores" / "probe_cases.json"
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
    """Stable web legacy GET requestを実行するprobe clientの契約を表す."""

    def get_web_legacy(
        self,
        path: str,
        *,
        query: Mapping[str, str],
        host_prefix: str = "osu",
    ) -> ProbeResponse:
        """Stable web legacy endpointへGET requestを実行する.

        Args:
            path (str): `/web/`配下のrequest path.
            query (Mapping[str, str]): URL query fieldと文字列表現の対応.
            host_prefix (str): Host header先頭へ付けるstable service prefix.

        Returns:
            ProbeResponse: 通信可否,response body,report-safeな診断を含む結果.

        Notes:
            実装は通信失敗をProbeResponseへ変換することを想定する.
        """
        ...


class GetscoresOptionalProbe[ProbePrerequisitesT_contra](Protocol):
    """任意のclient-like getscores probe adapterの契約を表す."""

    def probe_getscores(
        self,
        case: GetscoresProbeCase,
        prerequisites: ProbePrerequisitesT_contra,
    ) -> SurfaceResult:
        """指定caseを任意clientで検証する.

        Args:
            case (GetscoresProbeCase): 実行するstable getscores probe case.
            prerequisites (ProbePrerequisitesT_contra): Adapter固有の実行前提条件.

        Returns:
            SurfaceResult: Optional evidenceとしてreport可能な検証結果.

        Notes:
            Adapterは失敗をSurfaceResultへ変換することを想定する.
        """
        ...


class GetscoresVerifier[ProbePrerequisitesT]:
    """Getscores fixture検証とoptional target probeをまとめて実行する.

    Attributes:
        _target (StableTarget | None): Optional probeの接続先.未設定時はtarget probeをskipする.
        _client (GetscoresProbeClient | None): Stable web legacy requestを送るclient.
        _optional_probe (GetscoresOptionalProbe[ProbePrerequisitesT] | None): 任意client用adapter.
        _optional_probe_prerequisites (ProbePrerequisitesT | None): 任意client probeの前提条件.
        _fixture_dir (Path): Legacy response fixtureを置くdirectory.
        _probe_cases_path (Path): Optional target probe case JSONのpath.
        _completion_manifest_root (Path): Completion evidence manifestのroot directory.
        _completion_body_root (Path): Completion evidence body fixtureのroot directory.
    """

    def __init__(
        self,
        *,
        target: StableTarget | None = None,
        client: GetscoresProbeClient | None = None,
        optional_probe: GetscoresOptionalProbe[ProbePrerequisitesT] | None = None,
        optional_probe_prerequisites: ProbePrerequisitesT | None = None,
        fixture_dir: Path | None = None,
        probe_cases_path: Path | None = None,
        completion_manifest_root: Path | None = None,
        completion_body_root: Path | None = None,
    ) -> None:
        """Getscores fixture検証とoptional target probeの依存先を初期化する.

        Args:
            target (StableTarget | None): Optionalなlocal target.未設定時はtarget probeを
                skipする.
            client (GetscoresProbeClient | None): Target requestに使うclient.未指定時はtargetから
                生成する.
            optional_probe (GetscoresOptionalProbe[ProbePrerequisitesT] | None): Optionalなclient
                probe adapter.
            optional_probe_prerequisites (ProbePrerequisitesT | None): Optional probe実行の
                前提条件.
            fixture_dir (Path | None): Legacy getscores response fixture directory.
            probe_cases_path (Path | None): Optional target probe case JSON path.
            completion_manifest_root (Path | None): Completion evidence manifest directory.
            completion_body_root (Path | None): Completion evidence body fixture directory.

        Notes:
            Fixture pathの安全性はverification実行時に判定する.completion evidenceの診断と
            referenceへraw valueやfilesystem pathを含めない.
        """
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
        self._completion_manifest_root: Path = (
            completion_manifest_root or _DEFAULT_COMPLETION_MANIFEST_ROOT
        )
        self._completion_body_root: Path = completion_body_root or _DEFAULT_COMPLETION_BODY_ROOT

    def verify_fixtures(self) -> tuple[SurfaceResult, ...]:
        """Legacy fixtureとcompletion evidenceを必須evidenceとして検証する.

        Returns:
            tuple[SurfaceResult, ...]: Legacy response fixtureとcompletion manifestの検証結果.

        Notes:
            Manifestの読込失敗は安全な必須失敗結果へ変換する.診断とreferenceへraw valueや
            filesystem pathを含めない.
        """
        legacy_results = tuple(
            self._verify_fixture(fixture_path)
            for fixture_path in sorted(self._fixture_dir.glob("*.txt"))
        )
        return (
            *legacy_results,
            *_verify_completion_evidence(
                self._completion_manifest_root,
                self._completion_body_root,
            ),
        )

    def load_probe_cases(self) -> tuple[GetscoresProbeCase, ...]:
        """Optional target probe用のcase JSONをtyped caseへ変換する.

        Returns:
            tuple[GetscoresProbeCase, ...]: JSONに定義された順序を保つprobe case.

        Raises:
            OSError: Probe case JSONを読み出せない場合.
            json.JSONDecodeError: JSON構文が不正な場合.
            TypeError: JSON rootまたはcase entryがobjectでない場合.
            ValueError: 必須文字列,整数,またはfield値が不正な場合.

        Notes:
            JSONのraw valueを診断へ出力する責務は持たず,callerが例外種別をreport-safeに扱う.
        """
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
        """1件のprobe caseをtargetのstable getscores endpointへ送信する.

        Args:
            case (GetscoresProbeCase): Queryへ変換するstable probe case.

        Returns:
            SurfaceResult: Response grammarに基づくoptional headless probe結果.

        Raises:
            TypeError: Case内の整数fieldがboolである場合.
            ValueError: 必須文字列またはleaderboard typeが不正な場合.

        Notes:
            Target未設定時は通信せずSKIP結果を返す.clientが返す通信失敗はそのstatusを維持する.
        """
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
        """構成済みの任意client adapterで1件のprobe caseを検証する.

        Args:
            case (GetscoresProbeCase): 任意clientへ渡すstable probe case.

        Returns:
            SurfaceResult: 前提不足時のSKIP,またはadapterが返したoptional probe結果.

        Notes:
            target,prerequisites,adapterのいずれかが未設定ならadapterを呼び出さない.
        """
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
        """1つのlegacy response fixtureをparse可能性で検証する.

        Args:
            fixture_path (Path): 読み出すlegacy getscores response fixtureのpath.

        Returns:
            SurfaceResult: Parse成功時のPASS,またはparse失敗時のmandatory FAIL結果.

        Raises:
            OSError: Fixture bodyを読み出せない場合.

        Notes:
            Fixture名だけを診断へ含め,親directoryを含むpathはreferenceへ公開しない.
        """
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
    """Probe caseをstable `/web/osu-osz2-getscores.php` queryへ変換する.

    Args:
        case (GetscoresProbeCase): Stable request fieldを保持するprobe case.

    Returns:
        dict[str, str]: `c`, `f`, `m`, `mods`, `v`, `vv`と必要時の`i`を含むquery.

    Raises:
        TypeError: `mode`,`mods`,`beatmapset_id`がboolである場合.
        ValueError: `checksum`,`filename`が空,または`leaderboard_type`が未対応の場合.

    Notes:
        `selected`と`selected_mods`はstable protocol上で同じ`v=2`へ変換する.
    """
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
    """JSON entryを検証済みGetscoresProbeCaseへ変換する.

    Args:
        entry (object): JSON array内のcandidate entry.
        index (int): Error messageに使う元のarray index.

    Returns:
        GetscoresProbeCase: 必須fieldを満たすtyped probe case.

    Raises:
        TypeError: Entryがobjectでない,または整数fieldがboolか整数以外の場合.
        ValueError: 必須文字列が空,または必須整数fieldがnullの場合.
    """
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
    """Target probeのresponse bodyをstable getscores結果へ分類する.

    Args:
        response (ProbeResponse): Clientが取得したtarget responseと通信診断.

    Returns:
        SurfaceResult: Parse不能時のFAIL,not submitted時のUNAVAILABLE,その他のPASS結果.

    Notes:
        通信診断のmethod,path,HTTP status,body sizeは維持し,raw bodyは結果へ含めない.
    """
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
    """Parsed getscores responseをtarget probe用statusへ対応付ける.

    Args:
        response (GetscoresResponse): Grammar検証済みのgetscores response.

    Returns:
        VerificationStatus: NOT_SUBMITTEDならUNAVAILABLE,それ以外ならPASS.
    """
    if response.kind is GetscoresResponseKind.NOT_SUBMITTED:
        return VerificationStatus.UNAVAILABLE

    return VerificationStatus.PASS


def _has_only_personal_best_fallback_score_row(header: GetscoresHeader) -> bool:
    """Personal Best rowだけがleaderboard fallbackとして重複したheaderか判定する.

    Args:
        header (GetscoresHeader): Headerとpersonal best,score rowを含むparsed response.

    Returns:
        bool: Personal Bestがあり,score rowが同じ1行だけの場合はTrue.
    """
    return (
        header.personal_best_row is not None
        and len(header.score_rows) == 1
        and header.score_rows[0] == header.personal_best_row
    )


def _response_case(response: GetscoresResponse) -> str:
    """Parsed responseをreport用の固定case名へ分類する.

    Args:
        response (GetscoresResponse): Targetまたはfixtureからparse済みのresponse.

    Returns:
        str: `unavailable`,`update available`,またはheader内容を表す固定ラベル.

    Notes:
        ラベルはCLI report契約であり,response bodyのraw fieldを含めない.
    """
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
    """Local getscores probe用のoptional結果を組み立てる.

    Args:
        status (VerificationStatus): Probeの完了状態.
        message (str): Reportへ出す固定またはredaction済みの診断文言.

    Returns:
        SurfaceResult: `local getscores probe`をreferenceに持つoptional headless probe結果.
    """
    return SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=status,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference="local getscores probe",
    )


def _optional_osu_py_result(status: VerificationStatus, message: str) -> SurfaceResult:
    """Optional osu.py getscores probe用の結果を組み立てる.

    Args:
        status (VerificationStatus): Probeの完了状態.
        message (str): Reportへ出す固定またはredaction済みの診断文言.

    Returns:
        SurfaceResult: `optional:osu.py getscores probe`をreferenceに持つoptional結果.
    """
    return SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=status,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference="optional:osu.py getscores probe",
    )


def _verify_completion_evidence(
    manifest_root: Path,
    body_root: Path,
) -> tuple[SurfaceResult, ...]:
    """Completion evidenceを読み込み,検証結果へ変換する.

    Args:
        manifest_root (Path): Completion evidence manifest directory.
        body_root (Path): Completion evidence body fixture directory.

    Returns:
        tuple[SurfaceResult, ...]: 3種類のcompletion evidenceの必須検証結果.

    Notes:
        Loaderの検証失敗は固定された失敗結果へ変換する.Loader由来の診断内容を出力せず,raw
        value,path,internal provenanceを隠す.
    """
    try:
        evidence = load_getscores_completion_evidence(
            manifest_root,
            body_root,
        )
    except GetscoresEvidenceValidationError:
        return _completion_evidence_failure_results()

    return validate_getscores_completion_evidence(evidence)


def _completion_evidence_failure_results() -> tuple[SurfaceResult, ...]:
    """Completion evidenceのloader失敗を安全な必須結果として投影する.

    Returns:
        tuple[SurfaceResult, ...]: 各completion evidence種類へ対応する固定の失敗結果.

    Notes:
        入力値,path,loader内部のprovenanceやerror detailを診断へ露出しない.
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
    """JSON mappingから空でない文字列fieldを取得する.

    Args:
        entry (Mapping[object, object]): 検証対象のJSON object.
        key (str): 取得するfield名.
        index (int): Error messageに使うarray index.

    Returns:
        str: 空でない文字列field値.

    Raises:
        ValueError: Fieldが文字列でないか空文字列の場合.
    """
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
    """JSON mappingから任意の整数fieldを取得する.

    Args:
        entry (Mapping[object, object]): 検証対象のJSON object.
        key (str): 取得するfield名.
        index (int): Error messageに使うarray index.

    Returns:
        int | None: FieldがnullならNone,整数ならその値.

    Raises:
        TypeError: Fieldがboolまたは整数以外の場合.
    """
    value = entry.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"getscores probe case #{index} has invalid {key}"
        raise TypeError(msg)

    return value


def _json_int(entry: Mapping[object, object], key: str, index: int) -> int:
    """JSON mappingから必須の整数fieldを取得する.

    Args:
        entry (Mapping[object, object]): 検証対象のJSON object.
        key (str): 取得するfield名.
        index (int): Error messageに使うarray index.

    Returns:
        int: boolではない整数field値.

    Raises:
        TypeError: Fieldがboolまたは整数以外の場合.
        ValueError: Fieldがnullの場合.
    """
    value = _json_optional_int(entry, key, index)
    if value is None:
        msg = f"getscores probe case #{index} has invalid {key}"
        raise ValueError(msg)

    return value


def _required_string(value: str, field_name: str) -> str:
    """空でない必須文字列を検証して返す.

    Args:
        value (str): 検証する文字列値.
        field_name (str): Error messageに使うfield名.

    Returns:
        str: 空でない入力文字列.

    Raises:
        ValueError: 値が空文字列の場合.
    """
    if not value:
        msg = f"getscores probe case requires {field_name}"
        raise ValueError(msg)

    return value


def _required_int(value: int, field_name: str) -> int:
    """boolを除く必須整数を検証して返す.

    Args:
        value (int): 検証する整数値.
        field_name (str): Error messageに使うfield名.

    Returns:
        int: boolではない入力整数.

    Raises:
        TypeError: 値がboolの場合.
    """
    if isinstance(value, bool):
        msg = f"getscores probe case requires integer {field_name}"
        raise TypeError(msg)

    return value


def _leaderboard_type_query_value(leaderboard_type: str) -> str:
    """Namedまたは数値のleaderboard typeをstable query valueへ変換する.

    Args:
        leaderboard_type (str): `local`などの名前,または10進数文字列.

    Returns:
        str: Stable getscores requestの`v` fieldに設定する値.

    Raises:
        ValueError: 空白除去後の値が既知名でも10進数でもない場合.
    """
    normalized = leaderboard_type.strip().lower()
    mapped = _LEADERBOARD_TYPE_QUERY_VALUES.get(normalized)
    if mapped is not None:
        return mapped
    if normalized.isdecimal():
        return normalized

    msg = f"unsupported getscores leaderboard_type: {leaderboard_type}"
    raise ValueError(msg)


def _reference(path: Path) -> str:
    """Project root配下なら相対pathへ正規化してreferenceを作る.

    Args:
        path (Path): Referenceへ変換するfixture path.

    Returns:
        str: Project rootからの相対path.root外なら元の文字列表現.
    """
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
