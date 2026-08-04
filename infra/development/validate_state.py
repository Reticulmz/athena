"""Worktree-local development stateがtracked sourceと一致するか検証するmodule."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Callable

type ValidationMode = Literal[
    "nginx-certificates",
    "nginx-config",
    "tunnel-credentials",
    "tunnel-id",
]

CERTIFICATE_SAN_ENTRY_SIZE = 2
MINIMUM_TUNNEL_SECRET_BYTES = 32


class DevelopmentStateError(ValueError):
    """Worktree-local development stateが実行contractを満たさないことを表す."""


@dataclass(slots=True, frozen=True)
class TunnelCredentials:
    """Cloudflared named tunnelの検証済みexecution credentialを表す.

    Attributes:
        account_tag (str): Cloudflare accountを識別するnon-empty tag.
        tunnel_secret (bytes): Base64 sourceから復号した32 byte以上のtunnel secret.
        tunnel_id (UUID): Named tunnelを一意に識別するnon-nil UUID.
    """

    account_tag: str
    tunnel_secret: bytes
    tunnel_id: UUID


def _decode_certificate_metadata(certificate_path: Path) -> dict[str, object]:
    """PEM certificateのoffline metadataをPython valueとして返す.

    Args:
        certificate_path (Path): DecodeするPEM certificate file.

    Returns:
        dict[str, object]: Validity periodとsubjectAltNameを含むX.509 metadata.

    Raises:
        OSError: Certificate fileを読み込めないかX.509としてdecodeできない場合.

    Notes:
        Public `ssl` interfaceは未接続のPEMからcertificate metadataを取得できないため、CPythonが
        test用に公開する`_test_decode_cert`をこのfunctionだけで限定利用する.
    """
    ssl_extension = cast("object", vars(ssl)["_ssl"])
    ssl_extension_namespace = cast("dict[str, object]", vars(ssl_extension))
    decode_certificate = cast(
        "Callable[[str], dict[str, object]]",
        ssl_extension_namespace["_test_decode_cert"],
    )
    return decode_certificate(str(certificate_path))


def _certificate_dns_names(metadata: dict[str, object]) -> set[str]:
    """Decoded certificate metadataからDNS subjectAltNameだけを返す.

    Args:
        metadata (dict[str, object]): `_decode_certificate_metadata`が返したX.509 metadata.

    Returns:
        set[str]: `subjectAltName`でDNS種別として宣言されたhostnameの集合.
    """
    subject_alternative_names = metadata.get("subjectAltName")
    if not isinstance(subject_alternative_names, tuple):
        return set()
    dns_names: set[str] = set()
    for raw_entry in cast("tuple[object, ...]", subject_alternative_names):
        if not isinstance(raw_entry, tuple):
            continue
        entry = cast("tuple[object, ...]", raw_entry)
        if (
            len(entry) == CERTIFICATE_SAN_ENTRY_SIZE
            and entry[0] == "DNS"
            and isinstance(entry[1], str)
        ):
            dns_names.add(entry[1])
    return dns_names


def _certificate_validity_error(
    metadata: dict[str, object],
    *,
    current_time: float | None = None,
) -> str | None:
    """Decoded certificate validityが指定時刻を含むか検証する.

    Args:
        metadata (dict[str, object]): `_decode_certificate_metadata`が返したX.509 metadata.
        current_time (float | None): Unix timestampで指定する検証時刻. Noneの場合は現在時刻を使う.

    Returns:
        str | None: Validity metadataまたはtime windowが不正な理由. 有効な場合はNone.
    """
    not_before_source = metadata.get("notBefore")
    not_after_source = metadata.get("notAfter")
    if not isinstance(not_before_source, str) or not isinstance(not_after_source, str):
        return "generated Nginx certificate validity metadata is missing"
    try:
        not_before = ssl.cert_time_to_seconds(not_before_source)
        not_after = ssl.cert_time_to_seconds(not_after_source)
    except ValueError as error:
        return f"generated Nginx certificate validity metadata is invalid: {error}"
    if not_before > not_after:
        return "generated Nginx certificate validity period is reversed"
    validation_time = time.time() if current_time is None else current_time
    if validation_time < not_before:
        return f"generated Nginx certificate is not valid before {not_before_source}"
    if validation_time > not_after:
        return f"generated Nginx certificate expired at {not_after_source}"
    return None


def _validate_nginx_config(repository_root: Path) -> str | None:
    """Generated Nginx configがtracked templateと一致するか検証する.

    Args:
        repository_root (Path): Tracked templateと`.state`を所有するworktree root.

    Returns:
        str | None: 不一致理由. Configが一致する場合はNone.
    """
    template_path = repository_root / "infra/development/nginx/nginx.conf.template"
    generated_path = repository_root / ".state/nginx/nginx.conf"
    if not template_path.is_file():
        return f"tracked Nginx template is missing: {template_path}"
    if not generated_path.is_file():
        return f"generated Nginx config is missing: {generated_path}"
    if generated_path.read_bytes() != template_path.read_bytes():
        return "generated Nginx config differs from the tracked template"
    return None


def _validate_nginx_certificates(repository_root: Path) -> str | None:
    """Generated Nginx certificate pair、validity、required DNS SANを検証する.

    Args:
        repository_root (Path): `.state/certs`を所有するworktree root.

    Returns:
        str | None: Certificate pair、validity、DNS SANが不正な理由. 有効な場合はNone.
    """
    certificate_path = repository_root / ".state/certs/_wildcard.athena.localhost.pem"
    certificate_key_path = repository_root / ".state/certs/_wildcard.athena.localhost-key.pem"
    if not certificate_path.is_file() or not certificate_key_path.is_file():
        return "generated Nginx certificate or private key is missing"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(certificate_path, certificate_key_path)
    except OSError as error:
        return f"generated Nginx certificate and private key are invalid: {error}"
    try:
        certificate_metadata = _decode_certificate_metadata(certificate_path)
    except OSError as error:
        return f"generated Nginx certificate metadata is invalid: {error}"
    validity_error = _certificate_validity_error(certificate_metadata)
    if validity_error is not None:
        return validity_error
    if "*.athena.localhost" not in _certificate_dns_names(certificate_metadata):
        return "generated Nginx certificate must contain DNS SAN *.athena.localhost"
    return None


def _read_tunnel_credential_mapping(credentials_path: Path) -> dict[str, object]:
    """Cloudflared execution credential fileをJSON objectとして読み込む.

    Args:
        credentials_path (Path): Cloudflared createが出力したcredential file path.

    Returns:
        dict[str, object]: JSON objectとしてdecodeしたcredential field mapping.

    Raises:
        DevelopmentStateError: Fileが存在しないかUTF-8 JSON objectとして読めない場合.
    """
    if not credentials_path.is_file():
        raise DevelopmentStateError(f"tunnel execution credential is missing: {credentials_path}")
    try:
        loaded_credentials = cast(
            "object",
            json.loads(credentials_path.read_text(encoding="utf-8")),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DevelopmentStateError(
            f"tunnel execution credential must be a JSON object: {credentials_path}: {error}",
        ) from error
    if not isinstance(loaded_credentials, dict):
        raise DevelopmentStateError(
            f"tunnel execution credential must be a JSON object: {credentials_path}",
        )
    return cast("dict[str, object]", loaded_credentials)


def _require_tunnel_credential_field(
    credentials: dict[str, object],
    field_name: str,
    credentials_path: Path,
) -> object:
    """Credential mappingからrequired fieldを返す.

    Args:
        credentials (dict[str, object]): Cloudflared credential field mapping.
        field_name (str): 必須として取得するCloudflared field名.
        credentials_path (Path): Error diagnosticへ含めるcredential file path.

    Returns:
        object: 指定fieldに格納された未検証value.

    Raises:
        DevelopmentStateError: 指定fieldがmappingに存在しない場合.
    """
    if field_name not in credentials:
        reason = f"tunnel execution credential is missing required field {field_name}"
        raise DevelopmentStateError(f"{reason}: {credentials_path}")
    return credentials[field_name]


def _parse_tunnel_account_tag(
    credentials: dict[str, object],
    credentials_path: Path,
) -> str:
    """Credential mappingからnon-empty AccountTagを返す.

    Args:
        credentials (dict[str, object]): Cloudflared credential field mapping.
        credentials_path (Path): Error diagnosticへ含めるcredential file path.

    Returns:
        str: Cloudflare accountを識別するnon-empty AccountTag.

    Raises:
        DevelopmentStateError: AccountTagがstringではないか空の場合.
    """
    account_tag = _require_tunnel_credential_field(
        credentials,
        "AccountTag",
        credentials_path,
    )

    if not isinstance(account_tag, str) or not account_tag.strip():
        reason = "tunnel execution credential field AccountTag must be a non-empty string"
        raise DevelopmentStateError(f"{reason}: {credentials_path}")
    return account_tag


def _decode_tunnel_secret(
    credentials: dict[str, object],
    credentials_path: Path,
) -> bytes:
    """Credential mappingのTunnelSecretをstrict Base64 bytesへdecodeする.

    Args:
        credentials (dict[str, object]): Cloudflared credential field mapping.
        credentials_path (Path): Error diagnosticへ含めるcredential file path.

    Returns:
        bytes: Canonical Base64からdecodeした32 byte以上のtunnel secret.

    Raises:
        DevelopmentStateError: TunnelSecretのtype、encoding、decoded lengthが不正な場合.
    """
    tunnel_secret_source = _require_tunnel_credential_field(
        credentials,
        "TunnelSecret",
        credentials_path,
    )

    if not isinstance(tunnel_secret_source, str):
        reason = "tunnel execution credential field TunnelSecret must be a Base64 string"
        raise DevelopmentStateError(f"{reason}: {credentials_path}")
    try:
        tunnel_secret = base64.b64decode(tunnel_secret_source, validate=True)
    except (ValueError, binascii.Error) as error:
        reason = "tunnel execution credential field TunnelSecret must use valid Base64 encoding"
        raise DevelopmentStateError(f"{reason}: {credentials_path}") from error
    if base64.b64encode(tunnel_secret).decode("ascii") != tunnel_secret_source:
        reason = (
            "tunnel execution credential field TunnelSecret must use canonical Base64 encoding"
        )
        raise DevelopmentStateError(f"{reason}: {credentials_path}")
    if len(tunnel_secret) < MINIMUM_TUNNEL_SECRET_BYTES:
        reason = "decoded tunnel credential field TunnelSecret must contain at least 32 bytes"
        raise DevelopmentStateError(f"{reason}: {credentials_path}")
    return tunnel_secret


def _parse_tunnel_id(
    credentials: dict[str, object],
    credentials_path: Path,
) -> UUID:
    """Credential mappingからvalid non-nil TunnelID UUIDを返す.

    Args:
        credentials (dict[str, object]): Cloudflared credential field mapping.
        credentials_path (Path): Error diagnosticへ含めるcredential file path.

    Returns:
        UUID: Named tunnelを識別するnon-nil UUID.

    Raises:
        DevelopmentStateError: TunnelIDがUUID stringではないかnil UUIDの場合.
    """
    tunnel_id_source = _require_tunnel_credential_field(
        credentials,
        "TunnelID",
        credentials_path,
    )

    if not isinstance(tunnel_id_source, str):
        reason = "tunnel execution credential field TunnelID must be a UUID string"
        raise DevelopmentStateError(f"{reason}: {credentials_path}")
    try:
        tunnel_id = UUID(tunnel_id_source)
    except ValueError as error:
        raise DevelopmentStateError(
            f"tunnel execution credential field TunnelID must be a valid UUID: {credentials_path}",
        ) from error
    if tunnel_id.int == 0:
        reason = "tunnel execution credential field TunnelID must not be the nil UUID"
        raise DevelopmentStateError(f"{reason}: {credentials_path}")
    return tunnel_id


def _load_tunnel_credentials(repository_root: Path) -> TunnelCredentials:
    """Fixed pathのCloudflared execution credentialを検証して読み込む.

    Args:
        repository_root (Path): `.state/cloudflared`を所有するworktree root.

    Returns:
        TunnelCredentials: Required field、type、encodingを検証したcredential.

    Raises:
        DevelopmentStateError: Credential fileまたはCloudflared create schemaが不正な場合.
    """
    credentials_path = repository_root / ".state/cloudflared/credentials.json"
    credentials = _read_tunnel_credential_mapping(credentials_path)

    return TunnelCredentials(
        account_tag=_parse_tunnel_account_tag(credentials, credentials_path),
        tunnel_secret=_decode_tunnel_secret(credentials, credentials_path),
        tunnel_id=_parse_tunnel_id(credentials, credentials_path),
    )


def _validate_tunnel_credentials(repository_root: Path) -> str | None:
    """Cloudflared execution credentialがcreate schemaを満たすか検証する.

    Args:
        repository_root (Path): `.state/cloudflared`を所有するworktree root.

    Returns:
        str | None: Credentialが不足または不正な理由. Schemaを満たす場合はNone.
    """
    try:
        _ = _load_tunnel_credentials(repository_root)
    except DevelopmentStateError as error:
        return str(error)
    return None


def _parse_arguments() -> tuple[ValidationMode, Path]:
    """Development state validatorのcommand line argumentを解釈する.

    Returns:
        tuple[ValidationMode, Path]: Validation modeとworktree rootの組.
    """
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "mode",
        choices=("nginx-certificates", "nginx-config", "tunnel-credentials", "tunnel-id"),
    )
    _ = parser.add_argument("repository_root", type=Path)
    arguments = parser.parse_args()
    return cast("ValidationMode", arguments.mode), cast("Path", arguments.repository_root)


def main() -> int:
    """選択されたworktree-local development stateを検証する.

    Returns:
        int: Stateが有効な場合は0、不足または不正な場合は1.
    """
    mode, repository_root = _parse_arguments()
    if mode == "tunnel-id":
        try:
            credentials = _load_tunnel_credentials(repository_root)
        except DevelopmentStateError as error:
            print(error, file=sys.stderr)
            return 1
        print(credentials.tunnel_id)
        return 0
    validators = {
        "nginx-certificates": _validate_nginx_certificates,
        "nginx-config": _validate_nginx_config,
        "tunnel-credentials": _validate_tunnel_credentials,
    }
    error = validators[mode](repository_root)
    if error is None:
        return 0
    print(error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
