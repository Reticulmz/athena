"""安定版 legacy score submit の request/response mapper。"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP
from typing import TYPE_CHECKING, Protocol

from starlette.responses import Response

from osu_server.domain.compatibility.stable.mods import stable_mod_bitmask_to_mod_combination
from osu_server.domain.identity.passwords import normalize_legacy_md5_hex
from osu_server.domain.scores.payload_parser import ParsedScore, ParseError
from osu_server.infrastructure.parsers.multipart_parser import (
    MultipartLimits,
    parse,
)
from osu_server.infrastructure.parsers.multipart_parser import (
    ParseError as MultipartParseError,
)
from osu_server.services.commands.scores import (
    BeatmapRankDelta,
    ParsedSubmissionInput,
    SubmissionOutcome,
    SubmissionResult,
)
from osu_server.shared.errors import DecryptionError

if TYPE_CHECKING:
    from osu_server.domain.scores.decryption import DecryptedPayload
    from osu_server.domain.scores.mods import ModCombination
    from osu_server.domain.scores.personal_best import PersonalBestDelta
    from osu_server.domain.scores.user_stats import UserCurrentStats

_LEGACY_FIELD_COUNT = 16
_STABLE_MIN_FIELD_COUNT = 16
_STABLE_MAX_FIELD_COUNT = 19
_NO_PAYLOAD_USER_ID = 0
_STABLE_SUBMITTED_AT_INDEX = 16
_STABLE_CLIENT_VERSION_INDEX = 17
_STABLE_CLIENT_CHECKSUM_INDEX = 18
_OPAQUE_METADATA_FIELDS = frozenset({"fs", "bmk", "sbk", "c1", "st", "i", "token"})


class _FingerprintHasher(Protocol):
    def update(self, data: bytes, /) -> None: ...


def _update_fingerprint_bytes(hasher: _FingerprintHasher, label: bytes, value: bytes) -> None:
    hasher.update(label)
    hasher.update(b"\0")
    hasher.update(str(len(value)).encode())
    hasher.update(b"\0")
    hasher.update(value)
    hasher.update(b"\0")


def _update_fingerprint_text(hasher: _FingerprintHasher, label: str, value: str) -> None:
    _update_fingerprint_bytes(hasher, label.encode(), value.encode())


def _hash_submission_metadata(metadata: dict[str, str]) -> dict[str, str]:
    return {
        f"{key}_sha256": hashlib.sha256(value.encode()).hexdigest()
        for key, value in sorted(metadata.items())
        if key in _OPAQUE_METADATA_FIELDS
    }


class StableScorePayloadDecryptor(Protocol):
    """安定版 score payload を復号する transport 境界。

    振る舞い:
        Stable multipart から取り出した encrypted payload と IV を復号し、
        plaintext と checksum 検証結果を返す。

    Constraints:
        実装は credential や encrypted payload を logging しない。復号失敗の詳細は
        呼び出し側で stable response 用の固定理由へ正規化される。
    """

    def decrypt_score_payload(
        self,
        encrypted: bytes,
        iv: bytes,
        osu_version: str | None,
    ) -> DecryptedPayload:
        """暗号化 payload と IV を復号し checksum 検証結果を返す。

        Args:
            encrypted: multipart field から取り出した encrypted score payload。
            iv: stable client が送る IV。
            osu_version: stable client version。未送信の場合は None。

        Returns:
            plaintext と checksum_valid を含む DecryptedPayload。

        Raises:
            DecryptionError: payload を復号できない、または暗号入力が不正な場合。

        Constraints:
            plaintext は transport 境界内で parse し、command use-case へ encrypted
            payload や IV を渡さない。
        """
        ...


class StableScorePayloadParser:
    """安定版 score payload text を canonical score domain 値へ変換する parser。

    Legacy 16-field payload と stable 16-19-field payload を受け付け、
    command 境界で扱う ParsedScore へ変換する。
    """

    def parse(self, payload: str) -> ParsedScore:
        """レガシーまたは stable score payload を ParsedScore に変換する.

        Args:
            payload: stable client が送る colon-delimited payload.

        Returns:
            ParsedScore.

        Raises:
            ParseError: payload が空, field count が不正, または field 値を変換できない場合.
        """
        if not payload:
            raise ParseError("Payload cannot be empty")

        fields = payload.split(":")

        if len(fields) == _LEGACY_FIELD_COUNT and _is_int(fields[0]):
            return _parse_legacy_payload(fields)

        if _STABLE_MIN_FIELD_COUNT <= len(fields) <= _STABLE_MAX_FIELD_COUNT:
            return _parse_stable_payload(fields)

        raise ParseError(
            f"Expected 16 legacy fields or 16-19 stable fields, got {len(fields)}",
        )


@dataclass(frozen=True, slots=True)
class StableScoreSubmitRequestMapping:
    """安定版 multipart request から取り出した復号前 material。

    振る舞い:
        Handler が受け取った HTTP request body から、score payload、IV、replay、
        credential、client metadata、診断用 metadata を保持する。

    Args:
        encrypted_payload: 復号前の score payload。
        iv: payload 復号に使う IV。
        replay_data: 添付 replay binary。未送信の場合は None。
        password_md5: stable client が送る password-md5 credential。
        client_hash: stable client の checksum/hash field。
        submitted_at: server が request を受け取った時刻。
        score_field_count: multipart 内の score field 数。
        replay_present: replay field が存在したかどうか。
        replay_byte_size: replay_data の byte 数。未送信の場合は None。
        fail_time_ms: fail time field。未送信の場合は None。
        submit_exit_classification: client 終了種別の診断値。
        osu_version: stable client version。未送信の場合は None。
        beatmap_id: form field 由来の beatmap id。未送信の場合は None。
        submission_metadata: token など opaque field の生値。command へは hash 済みで渡す。

    Constraints:
        この型は transport 内だけで扱い、command use-case へは渡さない。
    """

    encrypted_payload: bytes
    iv: bytes
    replay_data: bytes | None
    password_md5: str
    client_hash: str
    submitted_at: datetime
    score_field_count: int
    replay_present: bool
    replay_byte_size: int | None
    fail_time_ms: int | None
    submit_exit_classification: str | None
    osu_version: str | None
    beatmap_id: int | None
    submission_metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class StableScoreSubmitCommandMapping:
    """命令 input と stable transport 診断情報をまとめた decode 結果。

    Args:
        input_data: score submission command に渡す正規化済み入力。
        score_field_count: multipart 内の score field 数。
        replay_present: replay field が存在したかどうか。
        replay_byte_size: replay_data の byte 数。未送信の場合は None。
        fail_time_ms: fail time field。未送信の場合は None。
        submit_exit_classification: client 終了種別の診断値。
        osu_version: stable client version。未送信の場合は None。

    Constraints:
        logging 用の診断値と command input を同じ decode 結果として返すが、
        transport wire 型は command input へ混入させない。
    """

    input_data: ParsedSubmissionInput
    score_field_count: int
    replay_present: bool
    replay_byte_size: int | None
    fail_time_ms: int | None
    submit_exit_classification: str | None
    osu_version: str | None


class StableScoreSubmitDecodeError(Exception):
    """安定版 score submit payload を command input に変換できない場合の例外。

    振る舞い:
        復号失敗、checksum 不一致、payload parse 失敗を stable response 用の
        SubmissionResult と sanitized diagnostics に変換して保持する。
    """

    def __init__(
        self,
        *,
        result: SubmissionResult,
        reason: str,
        request_hash: str,
        opaque_field_hashes: dict[str, str],
        error: str | None = None,
    ) -> None:
        """復号 decode 失敗の response 結果と診断情報を保持する。

        Args:
            result: client へ返す stable response の基になる SubmissionResult。
            reason: logging と分類に使う固定理由。
            request_hash: stable request を識別する hash。
            opaque_field_hashes: opaque metadata の SHA-256 hash。
            error: raw exception text を含まない sanitized error label。

        Returns:
            None。

        Raises:
            生成時に独自例外は送出しない。

        Constraints:
            error と result.error_reason に復号鍵、payload、credential、raw exception
            message を含めない。
        """
        super().__init__(result.error_reason)
        self.result: SubmissionResult = result
        self.reason: str = reason
        self.request_hash: str = request_hash
        self.opaque_field_hashes: dict[str, str] = opaque_field_hashes
        self.error: str | None = error


@dataclass(frozen=True, slots=True)
class StableScoreSubmitOverallStats:
    """安定版 score submit overall chart に載せる current stats 値。

    Args:
        rank: current global rank。未取得の場合は None。
        ranked_score: current ranked score。未取得の場合は None。
        total_score: current total score。未取得の場合は None。
        accuracy: current accuracy。未取得の場合は None。
        stable_pp: stable client response 用の rounded pp。未取得の場合は None。

    Constraints:
        response formatting 専用の値であり、command result の canonical state には戻さない。
    """

    rank: int | None = None
    ranked_score: int = 0
    total_score: int = 0
    max_combo: int = 0
    accuracy: float = 0.0
    stable_pp: int = 0


@dataclass(frozen=True, slots=True)
class _BeatmapMetadataFields:
    beatmap_id: int
    beatmapset_id: int
    playcount: int
    passcount: int
    approved_at: datetime | None


@dataclass(frozen=True, slots=True)
class _BeatmapChartFields:
    chart_url: str
    achieved: str
    rank_before: int | str
    rank_after: int
    max_combo_before: int
    max_combo_after: int
    accuracy_before: str
    accuracy_after: str
    score_before: int
    score_after: int
    pp_before: int
    pp_after: int
    score_id: int


@dataclass(frozen=True, slots=True)
class _OverallChartFields:
    chart_url: str
    rank_before: int
    rank_after: int
    ranked_score_before: int
    ranked_score_after: int
    total_score_before: int
    total_score_after: int
    max_combo_before: int
    max_combo_after: int
    accuracy_before: str
    accuracy_after: str
    pp_before: int
    pp_after: int
    score_id: int


class StableScoreSubmitMapper:
    """安定版 legacy score submit の wire request/response を変換する mapper。

    Stable multipart request を復号前 mapping に変換し、command の SubmissionResult を
    stable client 互換の text response へ整形する。
    """

    def __init__(
        self,
        limits: MultipartLimits | None = None,
        stable_web_base_url: str = "",
    ) -> None:
        """変換 mapper の multipart 制限と stable URL base を設定する。

        Args:
            limits: multipart parser の制限値。None の場合は既定値を使う。
            stable_web_base_url: response 内 chart URL の base URL。

        Returns:
            None。

        Raises:
            生成時に独自例外は送出しない。

        Constraints:
            stable_web_base_url 末尾の slash は response 組み立て前に除去する。
        """
        self._limits: MultipartLimits = limits or MultipartLimits()
        self._stable_web_base_url: str = stable_web_base_url.rstrip("/")

    def to_request_mapping(
        self,
        *,
        body: bytes,
        content_type: str,
        submitted_at: datetime,
    ) -> StableScoreSubmitRequestMapping:
        """マルチパート body を復号前の request mapping に変換する.

        Args:
            body: stable client が送信した multipart body.
            content_type: multipart boundary を含む Content-Type header.
            submitted_at: transport が request を受け取った時刻.

        Returns:
            復号前 payload, replay, metadata を含む request mapping.

        Raises:
            MultipartParseError: multipart body が stable score submit として不正な場合.
        """
        parsed = parse(body, content_type, self._limits)
        return StableScoreSubmitRequestMapping(
            encrypted_payload=parsed.encrypted_payload,
            iv=parsed.iv,
            replay_data=parsed.replay_data,
            password_md5=parsed.password_md5,
            client_hash=parsed.client_hash,
            submitted_at=submitted_at,
            score_field_count=parsed.score_field_count,
            replay_present=parsed.replay_data is not None,
            replay_byte_size=len(parsed.replay_data) if parsed.replay_data is not None else None,
            fail_time_ms=parsed.fail_time_ms,
            submit_exit_classification=parsed.submit_exit_classification,
            osu_version=parsed.osu_version,
            beatmap_id=None,
            submission_metadata=parsed.submission_metadata,
        )

    def to_response(
        self,
        result: SubmissionResult,
        *,
        overall_stats: StableScoreSubmitOverallStats | None = None,
    ) -> Response:
        """送信 result を stable legacy response body へ変換する。

        Args:
            result: command use-case が返した submission 結果。
            overall_stats: handler が補完した現在 user stats。None の場合は result から作る。

        Returns:
            stable client 互換の Starlette Response。

        Raises:
            response 整形時に独自例外は送出しない。

        Constraints:
            COMPLETED は chart 行を返し、RETRYABLE と ACCEPTED_PENDING は
            ``error: yes``、terminal reject は ``error: no`` を返す。
        """
        if result.outcome == SubmissionOutcome.COMPLETED:
            return _format_completed_response(
                result,
                overall_stats_after=overall_stats
                or _score_submit_overall_stats(result.overall_stats_after),
                stable_web_base_url=self._stable_web_base_url,
            )
        if result.outcome in {SubmissionOutcome.RETRYABLE, SubmissionOutcome.ACCEPTED_PENDING}:
            return Response(b"error: yes", status_code=200)
        return Response(b"error: no", status_code=200)


class StableScoreSubmitDecoder:
    """安定版 score submit wire payload を command input に変換する decoder。

    復号、checksum 検証、stable payload parse、request hash 生成、opaque metadata の
    hash 化を transport 層で完結させる。
    """

    def __init__(
        self,
        payload_decryptor: StableScorePayloadDecryptor,
        payload_parser: StableScorePayloadParser,
    ) -> None:
        """復号 decoder の復号器と parser を受け取る。

        Args:
            payload_decryptor: encrypted payload を復号する port。
            payload_parser: plaintext stable payload を ParsedScore へ変換する parser。

        Returns:
            None。

        Raises:
            生成時に独自例外は送出しない。

        Constraints:
            decoder は transport 境界でのみ使い、command use-case へ復号器や parser を
            注入しない。
        """
        self._payload_decryptor: StableScorePayloadDecryptor = payload_decryptor
        self._payload_parser: StableScorePayloadParser = payload_parser

    def to_command_input(
        self,
        request_mapping: StableScoreSubmitRequestMapping,
    ) -> ParsedSubmissionInput:
        """要求 mapping を復号して command input だけを返す.

        Args:
            request_mapping: Stable multipart から取り出した復号前 request material.

        Returns:
            score submission command に渡す parsed input.

        Raises:
            StableScoreSubmitDecodeError: 復号, checksum 検証, または payload parse に失敗した場合.
        """
        return self.to_command_mapping(request_mapping).input_data

    def to_command_mapping(
        self,
        request_mapping: StableScoreSubmitRequestMapping,
    ) -> StableScoreSubmitCommandMapping:
        """要求 mapping を復号/parse し command mapping に変換する.

        Args:
            request_mapping: Stable multipart から取り出した復号前 request material.

        Returns:
            command input と stable transport 診断情報.

        Raises:
            StableScoreSubmitDecodeError: 復号, checksum 検証, または payload parse に失敗した場合.
        """
        request_hash = _generate_stable_score_submit_request_hash(request_mapping)
        opaque_field_hashes = _hash_submission_metadata(request_mapping.submission_metadata)
        decrypt_start = time.perf_counter()
        try:
            decrypted = self._payload_decryptor.decrypt_score_payload(
                request_mapping.encrypted_payload,
                request_mapping.iv,
                request_mapping.osu_version,
            )
            decrypt_latency_ms = (time.perf_counter() - decrypt_start) * 1000
        except DecryptionError as exc:
            raise StableScoreSubmitDecodeError(
                result=SubmissionResult(
                    outcome=SubmissionOutcome.TERMINAL_REJECTED,
                    error_reason="decryption_failed",
                ),
                reason="decryption_failed",
                request_hash=request_hash,
                opaque_field_hashes=opaque_field_hashes,
                error="decryption_failed",
            ) from exc

        if not decrypted.checksum_valid:
            raise StableScoreSubmitDecodeError(
                result=SubmissionResult(
                    outcome=SubmissionOutcome.TERMINAL_REJECTED,
                    error_reason="crypto_checksum_invalid",
                ),
                reason="crypto_checksum_invalid",
                request_hash=request_hash,
                opaque_field_hashes=opaque_field_hashes,
            )

        try:
            parsed_score = self._payload_parser.parse(decrypted.plaintext)
        except ParseError as exc:
            raise StableScoreSubmitDecodeError(
                result=SubmissionResult(
                    outcome=SubmissionOutcome.TERMINAL_REJECTED,
                    error_reason="parse_failed",
                ),
                reason="parse_failed",
                request_hash=request_hash,
                opaque_field_hashes=opaque_field_hashes,
                error="parse_failed",
            ) from exc

        input_data = ParsedSubmissionInput(
            parsed_score=parsed_score,
            request_hash=request_hash,
            opaque_field_hashes=opaque_field_hashes,
            decrypt_latency_ms=decrypt_latency_ms,
            replay_data=request_mapping.replay_data,
            password_md5=request_mapping.password_md5,
            fail_time_ms=request_mapping.fail_time_ms,
            osu_version=request_mapping.osu_version,
            submitted_at=request_mapping.submitted_at,
            beatmap_id=request_mapping.beatmap_id,
            submit_exit_classification=request_mapping.submit_exit_classification,
        )
        return StableScoreSubmitCommandMapping(
            input_data=input_data,
            score_field_count=request_mapping.score_field_count,
            replay_present=request_mapping.replay_present,
            replay_byte_size=request_mapping.replay_byte_size,
            fail_time_ms=request_mapping.fail_time_ms,
            submit_exit_classification=request_mapping.submit_exit_classification,
            osu_version=request_mapping.osu_version,
        )


def _generate_stable_score_submit_request_hash(
    request_mapping: StableScoreSubmitRequestMapping,
) -> str:
    hasher = hashlib.sha256()
    _update_fingerprint_bytes(hasher, b"encrypted_payload", request_mapping.encrypted_payload)
    _update_fingerprint_bytes(hasher, b"iv", request_mapping.iv)
    _update_fingerprint_text(
        hasher,
        "password_md5_hash",
        hashlib.sha256(
            normalize_legacy_md5_hex(request_mapping.password_md5).encode()
        ).hexdigest(),
    )
    replay_marker = b"" if request_mapping.replay_data is None else request_mapping.replay_data
    _update_fingerprint_bytes(hasher, b"replay", replay_marker)
    _update_fingerprint_text(
        hasher,
        "replay_present",
        str(request_mapping.replay_data is not None),
    )
    _update_fingerprint_text(hasher, "client_hash", request_mapping.client_hash)
    _update_fingerprint_text(hasher, "fail_time_ms", str(request_mapping.fail_time_ms))
    _update_fingerprint_text(
        hasher,
        "submit_exit_classification",
        str(request_mapping.submit_exit_classification),
    )
    _update_fingerprint_text(hasher, "osu_version", str(request_mapping.osu_version))
    _update_fingerprint_text(hasher, "beatmap_id", str(request_mapping.beatmap_id or ""))
    for key, digest in _hash_submission_metadata(request_mapping.submission_metadata).items():
        _update_fingerprint_text(hasher, f"metadata:{key}", digest)
    return hasher.hexdigest()


def _is_int(value: str) -> bool:
    try:
        _ = int(value)
    except ValueError:
        return False
    return True


def _parse_bool(value: str) -> bool:
    match value:
        case "1" | "True" | "true":
            return True
        case "0" | "False" | "false":
            return False
        case _:
            raise ValueError(f"invalid boolean value: {value}")


def _parse_stable_mods(value: str) -> ModCombination:
    """stable Mods fieldをcanonical Mod combinationへ変換する.

    Args:
        value (str): stable payload内の10進bitmask文字列.

    Returns:
        ModCombination: stable対応済みbitだけを含むcanonical Mods.

    Raises:
        ParseError: integer変換に失敗した場合, または無効/未対応bitを含む場合.

    Notes:
        wire integerのsyntax errorとMod bitmaskのsemantic errorを別messageで報告する.
    """
    try:
        bitmask = int(value)
    except ValueError as exc:
        raise ParseError(f"Failed to parse mods integer field: {exc}") from exc

    try:
        return stable_mod_bitmask_to_mod_combination(bitmask)
    except ValueError as exc:
        raise ParseError(f"Invalid stable mod bitmask: {exc}") from exc


def _parse_legacy_payload(fields: list[str]) -> ParsedScore:
    try:
        return ParsedScore(
            user_id=int(fields[0]),
            username=fields[1],
            beatmap_checksum=fields[2],
            online_checksum=fields[3],
            ruleset=int(fields[4]),
            mods=_parse_stable_mods(fields[5]),
            n300=int(fields[6]),
            n100=int(fields[7]),
            n50=int(fields[8]),
            geki=int(fields[9]),
            katu=int(fields[10]),
            miss=int(fields[11]),
            score=int(fields[12]),
            max_combo=int(fields[13]),
            perfect=_parse_bool(fields[14]),
            passed=_parse_bool(fields[15]),
        )
    except ValueError as e:
        raise ParseError(f"Failed to parse integer field: {e}") from e


def _parse_stable_payload(fields: list[str]) -> ParsedScore:
    try:
        return ParsedScore(
            user_id=_NO_PAYLOAD_USER_ID,
            username=fields[1],
            beatmap_checksum=fields[0],
            online_checksum=fields[2],
            n300=int(fields[3]),
            n100=int(fields[4]),
            n50=int(fields[5]),
            geki=int(fields[6]),
            katu=int(fields[7]),
            miss=int(fields[8]),
            score=int(fields[9]),
            max_combo=int(fields[10]),
            perfect=_parse_bool(fields[11]),
            client_grade=fields[12],
            mods=_parse_stable_mods(fields[13]),
            passed=_parse_bool(fields[14]),
            ruleset=int(fields[15]),
            client_submitted_at=fields[_STABLE_SUBMITTED_AT_INDEX]
            if len(fields) > _STABLE_SUBMITTED_AT_INDEX
            else None,
            client_version=fields[_STABLE_CLIENT_VERSION_INDEX]
            if len(fields) > _STABLE_CLIENT_VERSION_INDEX
            else None,
            client_checksum=fields[_STABLE_CLIENT_CHECKSUM_INDEX]
            if len(fields) > _STABLE_CLIENT_CHECKSUM_INDEX
            else None,
        )
    except ValueError as e:
        raise ParseError(f"Failed to parse integer field: {e}") from e


def _format_completed_response(
    result: SubmissionResult,
    *,
    overall_stats_after: StableScoreSubmitOverallStats | None,
    stable_web_base_url: str,
) -> Response:
    overall_stats_before = _score_submit_overall_stats(result.overall_stats_before)
    body = "\n".join(
        (
            _format_beatmap_metadata_line(_beatmap_metadata_fields(result)),
            _format_beatmap_chart_line(
                _beatmap_chart_fields(
                    result,
                    stable_web_base_url=stable_web_base_url,
                )
            ),
            _format_overall_chart_line(
                _overall_chart_fields(
                    result,
                    overall_stats_before=overall_stats_before,
                    overall_stats_after=overall_stats_after,
                    stable_web_base_url=stable_web_base_url,
                )
            ),
        )
    )

    return Response(body.encode(), status_code=200)


def _beatmap_metadata_fields(result: SubmissionResult) -> _BeatmapMetadataFields:
    return _BeatmapMetadataFields(
        beatmap_id=result.beatmap_id or 0,
        beatmapset_id=result.beatmapset_id or 0,
        playcount=result.beatmap_playcount if result.beatmap_playcount is not None else 1,
        passcount=_displayed_passcount(result),
        approved_at=result.beatmap_approved_at,
    )


def _displayed_passcount(result: SubmissionResult) -> int:
    if result.beatmap_passcount is not None:
        return result.beatmap_passcount
    return 0 if result.passed is False else 1


def _beatmap_chart_fields(
    result: SubmissionResult,
    *,
    stable_web_base_url: str,
) -> _BeatmapChartFields:
    score_before, max_combo_before, accuracy_before = _score_submit_before_fields(
        result.personal_best_delta,
    )
    score_after, max_combo_after, accuracy_after = _score_submit_after_fields(result)
    rank_before, rank_after = _beatmap_rank_fields(result.beatmap_rank_delta)
    pp_after = (
        result.stable_pp_after if result.stable_pp_after is not None else result.stable_pp or 0
    )

    return _BeatmapChartFields(
        chart_url=_stable_beatmap_url(stable_web_base_url, result.beatmap_id or 0),
        achieved="false" if result.passed is False else "true",
        rank_before=rank_before,
        rank_after=rank_after,
        max_combo_before=max_combo_before,
        max_combo_after=max_combo_after,
        accuracy_before=accuracy_before,
        accuracy_after=accuracy_after,
        score_before=score_before,
        score_after=score_after,
        pp_before=result.stable_pp_before or 0,
        pp_after=pp_after,
        score_id=result.score_id or 0,
    )


def _score_submit_before_fields(
    personal_best_delta: PersonalBestDelta | None,
) -> tuple[int, int, str]:
    if personal_best_delta is None:
        return 0, 0, "0"
    return (
        personal_best_delta.before_score or 0,
        personal_best_delta.before_max_combo or 0,
        _format_accuracy_percent(personal_best_delta.before_accuracy),
    )


def _score_submit_after_fields(result: SubmissionResult) -> tuple[int, int, str]:
    personal_best_delta = result.personal_best_delta
    if personal_best_delta is None:
        return result.score or 0, result.max_combo or 0, _format_accuracy_percent(result.accuracy)
    return (
        personal_best_delta.after_score or 0,
        personal_best_delta.after_max_combo or 0,
        _format_accuracy_percent(personal_best_delta.after_accuracy),
    )


def _beatmap_rank_fields(beatmap_rank_delta: BeatmapRankDelta | None) -> tuple[int | str, int]:
    if beatmap_rank_delta is None:
        return "", 0

    rank_before: int | str = (
        beatmap_rank_delta.before if beatmap_rank_delta.before is not None else ""
    )
    rank_after = beatmap_rank_delta.after if beatmap_rank_delta.after is not None else 0
    return rank_before, rank_after


def _overall_chart_fields(
    result: SubmissionResult,
    *,
    overall_stats_before: StableScoreSubmitOverallStats | None,
    overall_stats_after: StableScoreSubmitOverallStats | None,
    stable_web_base_url: str,
) -> _OverallChartFields:
    before = overall_stats_before or StableScoreSubmitOverallStats()
    after = overall_stats_after or StableScoreSubmitOverallStats()

    return _OverallChartFields(
        chart_url=_stable_user_url(stable_web_base_url, result.user_id or 0),
        rank_before=before.rank or 0,
        rank_after=after.rank or 0,
        ranked_score_before=before.ranked_score,
        ranked_score_after=after.ranked_score,
        total_score_before=before.total_score,
        total_score_after=after.total_score,
        max_combo_before=before.max_combo,
        max_combo_after=after.max_combo,
        accuracy_before=_format_accuracy_percent(before.accuracy),
        accuracy_after=_format_accuracy_percent(after.accuracy),
        pp_before=before.stable_pp,
        pp_after=after.stable_pp,
        score_id=result.score_id or 0,
    )


def _format_beatmap_metadata_line(fields: _BeatmapMetadataFields) -> str:
    return _format_chart_line(
        (
            ("beatmapId", fields.beatmap_id),
            ("beatmapSetId", fields.beatmapset_id),
            ("beatmapPlaycount", fields.playcount),
            ("beatmapPasscount", fields.passcount),
            ("approvedDate", _format_stable_datetime(fields.approved_at)),
        )
    )


def _format_beatmap_chart_line(fields: _BeatmapChartFields) -> str:
    return _format_chart_line(
        (
            ("chartId", "beatmap"),
            ("chartUrl", fields.chart_url),
            ("chartName", "Beatmap Ranking"),
            ("achieved", fields.achieved),
            ("rankBefore", fields.rank_before),
            ("rankAfter", fields.rank_after),
            ("maxComboBefore", fields.max_combo_before),
            ("maxComboAfter", fields.max_combo_after),
            ("accuracyBefore", fields.accuracy_before),
            ("accuracyAfter", fields.accuracy_after),
            ("rankedScoreBefore", fields.score_before),
            ("rankedScoreAfter", fields.score_after),
            ("ppBefore", fields.pp_before),
            ("ppAfter", fields.pp_after),
            ("onlineScoreId", fields.score_id),
        )
    )


def _format_overall_chart_line(fields: _OverallChartFields) -> str:
    return _format_chart_line(
        (
            ("chartId", "overall"),
            ("chartUrl", fields.chart_url),
            ("chartName", "Overall Ranking"),
            ("rankBefore", fields.rank_before),
            ("rankAfter", fields.rank_after),
            ("rankedScoreBefore", fields.ranked_score_before),
            ("rankedScoreAfter", fields.ranked_score_after),
            ("totalScoreBefore", fields.total_score_before),
            ("totalScoreAfter", fields.total_score_after),
            ("maxComboBefore", fields.max_combo_before),
            ("maxComboAfter", fields.max_combo_after),
            ("accuracyBefore", fields.accuracy_before),
            ("accuracyAfter", fields.accuracy_after),
            ("ppBefore", fields.pp_before),
            ("ppAfter", fields.pp_after),
            ("achievements-new", ""),
            ("onlineScoreId", fields.score_id),
        )
    )


def _stable_beatmap_url(stable_web_base_url: str, beatmap_id: int) -> str:
    if not stable_web_base_url or beatmap_id <= 0:
        return ""
    return f"{stable_web_base_url}/b/{beatmap_id}"


def _stable_user_url(stable_web_base_url: str, user_id: int) -> str:
    if not stable_web_base_url or user_id <= 0:
        return ""
    return f"{stable_web_base_url}/u/{user_id}"


def _score_submit_overall_stats(
    current_stats: UserCurrentStats | None,
) -> StableScoreSubmitOverallStats | None:
    if current_stats is None:
        return None
    return StableScoreSubmitOverallStats(
        rank=current_stats.global_rank,
        ranked_score=current_stats.ranked_score,
        total_score=current_stats.total_score,
        max_combo=current_stats.max_combo,
        accuracy=current_stats.accuracy,
        stable_pp=int(current_stats.pp.to_integral_value(rounding=ROUND_HALF_UP)),
    )


def _format_accuracy_percent(accuracy: float | None) -> str:
    if accuracy is None:
        return "0"
    percent = accuracy * 100
    return f"{percent:.6f}".rstrip("0").rstrip(".")


def _format_stable_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    stable_value = value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)
    return stable_value.strftime("%Y-%m-%d %H:%M:%S")


def _format_chart_line(entries: tuple[tuple[str, object], ...]) -> str:
    return "|".join(f"{key}:{value}" for key, value in entries)


__all__ = [
    "MultipartParseError",
    "StableScorePayloadParser",
    "StableScoreSubmitCommandMapping",
    "StableScoreSubmitDecodeError",
    "StableScoreSubmitDecoder",
    "StableScoreSubmitMapper",
    "StableScoreSubmitOverallStats",
    "StableScoreSubmitRequestMapping",
]
