from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from athena_cli.presentation import mask_secret


@dataclass(frozen=True, slots=True)
class DsnValue:
    value: str
    masked_value: str


@dataclass(frozen=True, slots=True)
class DatabaseConnectionParts:
    host: str
    port: int
    database: str
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class ValkeyConnectionParts:
    host: str
    port: int
    database: int
    username: str | None
    password: str | None


def build_database_dsn(parts: DatabaseConnectionParts) -> DsnValue:
    path = quote(parts.database, safe="")
    value = _build_url(
        scheme="postgresql+asyncpg",
        host=parts.host,
        port=parts.port,
        path=path,
        username=parts.username,
        password=parts.password,
    )
    masked_value = _build_url(
        scheme="postgresql+asyncpg",
        host=parts.host,
        port=parts.port,
        path=path,
        username=parts.username,
        password=mask_secret(parts.password),
        password_is_masked=True,
    )
    return DsnValue(value=value, masked_value=masked_value)


def build_valkey_dsn(parts: ValkeyConnectionParts) -> DsnValue:
    path = str(parts.database)
    value = _build_url(
        scheme="redis",
        host=parts.host,
        port=parts.port,
        path=path,
        username=parts.username,
        password=parts.password,
    )
    masked_value = _build_url(
        scheme="redis",
        host=parts.host,
        port=parts.port,
        path=path,
        username=parts.username,
        password=mask_secret(parts.password or "") or None,
        password_is_masked=True,
    )
    return DsnValue(value=value, masked_value=masked_value)


def _build_url(
    *,
    scheme: str,
    host: str,
    port: int,
    path: str,
    username: str | None,
    password: str | None,
    password_is_masked: bool = False,
) -> str:
    credentials = _format_credentials(
        username=username,
        password=password,
        password_is_masked=password_is_masked,
    )
    return f"{scheme}://{credentials}{host}:{port}/{path}"


def _format_credentials(
    *,
    username: str | None,
    password: str | None,
    password_is_masked: bool,
) -> str:
    if username is None and password is None:
        return ""
    encoded_username = quote(username or "", safe="")
    if password is None:
        return f"{encoded_username}@"
    encoded_password = password if password_is_masked else quote(password, safe="")
    return f"{encoded_username}:{encoded_password}@"
