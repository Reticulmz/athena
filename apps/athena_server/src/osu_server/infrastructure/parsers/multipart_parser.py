"""stable score submissionのmultipart formを解析するmodule.

wire formatのfieldを検証し, score commandが使う型付き入力へ変換する.
"""

import base64
import binascii
from dataclasses import dataclass
from email import message_from_bytes
from typing import TYPE_CHECKING

from osu_server.domain.identity.passwords import normalize_legacy_md5_hex

if TYPE_CHECKING:
    from email.message import Message

_REPLAY_FIELD_INDEX = 1
_RIJNDAEL_IV_SIZE = 32
_DEFAULT_TOTAL_BODY_SIZE = 1_048_576
_DEFAULT_REPLAY_SIZE = 1_048_576
_DEFAULT_TEXT_FIELD_SIZE = 65_536
_DEFAULT_SCORE_PAYLOAD_FIELD_SIZE = 262_144
_DEFAULT_OPAQUE_FIELD_SIZE = 262_144
_OPAQUE_METADATA_FIELDS = ("fs", "bmk", "sbk", "c1", "st", "i", "token")


class ParseError(Exception):
    """multipart formの構造またはfield値が不正な場合に送出する例外.

    Notes:
        parser helperはrequest body, 必須field, encoding, またはsize limitの違反を
        この例外へ正規化する.
    """


@dataclass(frozen=True, slots=True)
class MultipartLimits:
    """multipart formの各要素に適用するbyte数上限.

    Attributes:
        total_body_size (int): request body全体に許可する最大byte数.
        replay_size (int): replay binary fieldに許可する最大byte数.
        text_field_size (int): 通常のtext fieldに許可する最大byte数.
        score_payload_field_size (int): 暗号化score payloadに許可する最大byte数.
        opaque_field_size (int): 互換metadata fieldに許可する最大byte数.
    """

    total_body_size: int = _DEFAULT_TOTAL_BODY_SIZE
    replay_size: int = _DEFAULT_REPLAY_SIZE
    text_field_size: int = _DEFAULT_TEXT_FIELD_SIZE
    score_payload_field_size: int = _DEFAULT_SCORE_PAYLOAD_FIELD_SIZE
    opaque_field_size: int = _DEFAULT_OPAQUE_FIELD_SIZE


@dataclass(frozen=True, slots=True)
class ParsedSubmission:
    """検証済みmultipart score submissionの値object.

    Attributes:
        encrypted_payload (bytes): base64復号後の暗号化score payload.
        iv (bytes): Rijndael復号に必要な32 byteのinitialization vector.
        replay_data (bytes | None): 添付済みreplay binary. 未添付時はNone.
        score_field_count (int): 同名``score`` fieldを受信した個数.
        password_md5 (str): 正規化済みlegacy MD5 password hash.
        client_hash (str): client integrity hash fieldの値.
        fail_time_ms (int | None): clientが報告した失敗時刻. 未指定または不正時はNone.
        submit_exit_classification (str | None): score submission終了分類. 現在はNone.
        osu_version (str): submission元stable clientのversion.
        submission_metadata (dict[str, str]): 互換用opaque metadata fieldの値.
    """

    encrypted_payload: bytes
    iv: bytes
    replay_data: bytes | None
    score_field_count: int
    password_md5: str
    client_hash: str
    fail_time_ms: int | None
    submit_exit_classification: str | None
    osu_version: str
    submission_metadata: dict[str, str]


def _decode_base64_field(field_name: str, value: bytes) -> bytes:
    """base64 fieldを検証してbytesへ復号する.

    Args:
        field_name (str): error messageに使うmultipart field名.
        value (bytes): whitespaceを含む可能性があるbase64 encoded値.

    Returns:
        bytes: 妥当なbase64として復号したbinary値.

    Raises:
        ParseError: fieldが空, またはbase64 encodingが不正な場合.
    """
    encoded = value.strip()
    if not encoded:
        raise ParseError(f"Empty base64 field: {field_name}")

    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ParseError(f"Invalid base64 field: {field_name}") from e


def _collect_fields(msg: Message) -> dict[str, list[bytes]]:
    """Email parserのmultipart messageから同名fieldを保持して収集する.

    Args:
        msg (Message): Content-Type headerを含めて解析済みのemail message.

    Returns:
        dict[str, list[bytes]]: field名ごとに出現順のpayloadを格納したmapping.

    Notes:
        nested multipart containerとnameまたはbinary payloadを持たないpartは無視する.
    """
    fields: dict[str, list[bytes]] = {}
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue

        name = part.get_param("name", header="content-disposition")
        if not name or not isinstance(name, str):
            continue

        payload = part.get_payload(decode=True)
        if payload is None or not isinstance(payload, bytes):
            continue

        if name not in fields:
            fields[name] = []
        fields[name].append(payload)

    return fields


def _enforce_size_limit(label: str, actual: int, limit: int) -> None:
    """計測値が指定上限以下であることを確認する.

    Args:
        label (str): error messageに使う検査対象の名前.
        actual (int): 受信したbyte数.
        limit (int): 許可する最大byte数.

    Returns:
        None: 上限内の場合は何も返さない.

    Raises:
        ParseError: ``actual``が``limit``を超える場合.
    """
    if actual > limit:
        raise ParseError(f"{label} size exceeds limit: {actual} > {limit}")


def _validate_field_sizes(fields: dict[str, list[bytes]], limits: MultipartLimits) -> None:
    """Multipart fieldごとに適切なsize limitを適用する.

    Args:
        fields (dict[str, list[bytes]]): field名と受信値を出現順に保持したmapping.
        limits (MultipartLimits): field種別ごとの最大byte数.

    Returns:
        None: 全fieldが上限内の場合は何も返さない.

    Raises:
        ParseError: いずれかのfieldが対応するsize limitを超える場合.
    """
    for field_name, field_values in fields.items():
        for index, value in enumerate(field_values):
            if field_name == "score":
                if index == _REPLAY_FIELD_INDEX:
                    _enforce_size_limit("replay", len(value), limits.replay_size)
                elif index == 0:
                    _enforce_size_limit(
                        "field 'score'",
                        len(value),
                        limits.score_payload_field_size,
                    )
                else:
                    _enforce_size_limit("field 'score'", len(value), limits.text_field_size)
                continue

            if field_name in _OPAQUE_METADATA_FIELDS:
                _enforce_size_limit(
                    f"field {field_name!r}",
                    len(value),
                    limits.opaque_field_size,
                )
                continue

            _enforce_size_limit(f"field {field_name!r}", len(value), limits.text_field_size)


def _extract_optional_metadata(fields: dict[str, list[bytes]]) -> dict[str, str]:
    """Opaque metadata fieldをUTF-8 textまたはhex textとして取り出す.

    Args:
        fields (dict[str, list[bytes]]): field名と受信値を出現順に保持したmapping.

    Returns:
        dict[str, str]: 定義済みopaque metadata fieldだけを含むmapping.

    Notes:
        UTF-8として復号できない値は情報を失わないhex textへ変換する.
    """
    submission_metadata: dict[str, str] = {}
    for field_name in _OPAQUE_METADATA_FIELDS:
        field_values = fields.get(field_name)
        if field_values:
            try:
                submission_metadata[field_name] = field_values[0].decode("utf-8")
            except UnicodeDecodeError:
                submission_metadata[field_name] = field_values[0].hex()

    return submission_metadata


def _extract_required_fields(
    fields: dict[str, list[bytes]],
) -> tuple[bytes, bytes | None, int, bytes, str, str, int | None, str | None, str]:
    """必須score submission fieldを復号して構造化する.

    Args:
        fields (dict[str, list[bytes]]): field名と受信値を出現順に保持したmapping.

    Returns:
        tuple[bytes, bytes | None, int, bytes, str, str, int | None, str | None, str]:
            暗号化payload, replay, score field数, IV, password hash, client hash,
            fail time, 終了分類, osu versionの順の値.

    Raises:
        KeyError: 必須fieldが存在しない場合.
        IndexError: 必須fieldに値がない場合.
        ParseError: scoreまたはIVのbase64値, IV長が不正な場合.
        UnicodeDecodeError: text fieldがUTF-8として不正な場合.
        ValueError: password hashの正規化に失敗した場合.
    """
    score_fields = fields.get("score", [])
    if len(score_fields) < 1:
        raise ParseError("Missing required field: score")

    encrypted_payload = _decode_base64_field("score", score_fields[0])
    replay_data = None
    if len(score_fields) > _REPLAY_FIELD_INDEX and score_fields[_REPLAY_FIELD_INDEX]:
        replay_data = score_fields[_REPLAY_FIELD_INDEX]
    score_field_count = len(score_fields)

    iv = _decode_base64_field("iv", fields["iv"][0])
    if len(iv) != _RIJNDAEL_IV_SIZE:
        msg = f"Invalid iv length: expected {_RIJNDAEL_IV_SIZE} bytes, got {len(iv)}"
        raise ParseError(msg)

    password_md5 = normalize_legacy_md5_hex(fields["pass"][0].decode("utf-8"))
    client_hash = fields["x"][0].decode("utf-8")
    submit_exit_classification = None
    osu_version = fields["osuver"][0].decode("utf-8")
    fail_time_ms = _parse_fail_time_ms(fields.get("ft"))

    return (
        encrypted_payload,
        replay_data,
        score_field_count,
        iv,
        password_md5,
        client_hash,
        fail_time_ms,
        submit_exit_classification,
        osu_version,
    )


def _parse_fail_time_ms(ft_values: list[bytes] | None) -> int | None:
    """任意の``ft`` fieldを非負のmillisecond値として解析する.

    Args:
        ft_values (list[bytes] | None): ``ft`` fieldの出現順の値. 未指定時はNone.

    Returns:
        int | None: 非負のmillisecond値. 欠損, 不正, または負数の場合はNone.
    """
    if not ft_values:
        return None

    try:
        ft_str = ft_values[0].decode("utf-8")
        if not ft_str:
            return None
        fail_time_ms = int(ft_str)
    except ValueError, UnicodeDecodeError:
        return None
    return fail_time_ms if fail_time_ms >= 0 else None


def parse(
    body: bytes,
    content_type: str,
    limits: MultipartLimits | None = None,
) -> ParsedSubmission:
    """Stable score submissionのmultipart formを検証して解析する.

    Args:
        body (bytes): raw HTTP request body.
        content_type (str): multipart boundaryを含むContent-Type header値.
        limits (MultipartLimits | None): size limit. Noneの場合は標準上限を使う.

    Returns:
        ParsedSubmission: 必須fieldと対応する任意metadataを含む検証済みsubmission.

    Raises:
        ParseError: multipart構造, 必須field, encoding, IV, またはsize limitが不正な場合.

    Notes:
        重複する``score`` fieldは先頭を暗号化score payload, 2番目をreplay binaryとして扱う.
    """
    effective_limits = limits or MultipartLimits()

    if not body:
        raise ParseError("Request body cannot be empty")
    _enforce_size_limit("request body", len(body), effective_limits.total_body_size)

    if not content_type or "multipart/form-data" not in content_type:
        raise ParseError("Content-Type must be multipart/form-data")

    # Parse multipart using email module
    headers = f"Content-Type: {content_type}\r\n\r\n".encode()
    msg = message_from_bytes(headers + body)

    if not msg.is_multipart():
        raise ParseError("Request is not multipart")

    fields = _collect_fields(msg)
    _validate_field_sizes(fields, effective_limits)

    # Extract required fields
    try:
        (
            encrypted_payload,
            replay_data,
            score_field_count,
            iv,
            password_md5,
            client_hash,
            fail_time_ms,
            submit_exit_classification,
            osu_version,
        ) = _extract_required_fields(fields)

    except (KeyError, IndexError) as e:
        raise ParseError(f"Missing required field: {e}") from e
    except (ValueError, UnicodeDecodeError) as e:
        raise ParseError(f"Invalid field format: {e}") from e

    return ParsedSubmission(
        encrypted_payload=encrypted_payload,
        iv=iv,
        replay_data=replay_data,
        score_field_count=score_field_count,
        password_md5=password_md5,
        client_hash=client_hash,
        fail_time_ms=fail_time_ms,
        submit_exit_classification=submit_exit_classification,
        osu_version=osu_version,
        submission_metadata=_extract_optional_metadata(fields),
    )
