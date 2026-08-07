"""databaseとValkeyのDSNを構築するvalue objectとhelperを提供する."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from athena_cli.presentation import mask_secret


@dataclass(frozen=True, slots=True)
class DsnValue:
    """接続用DSNとsecretをmaskした表示用DSNを表す.

    Attributes:
        value (str): 接続に使用するURL encode済みDSN.
        masked_value (str): passwordをsecret maskへ置換した表示用DSN.
    """

    value: str
    masked_value: str


@dataclass(frozen=True, slots=True)
class DatabaseConnectionParts:
    """PostgreSQL database DSNを構成する接続情報を表す.

    Attributes:
        host (str): database serverのhost名.
        port (int): database serverのTCP port.
        database (str): 接続対象database名.
        username (str): database認証に使用するusername.
        password (str): database認証に使用するpassword.
    """

    host: str
    port: int
    database: str
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class ValkeyConnectionParts:
    """Valkey DSNを構成する接続情報を表す.

    Attributes:
        host (str): Valkey serverのhost名.
        port (int): Valkey serverのTCP port.
        database (int): 接続するValkey logical database番号.
        username (str | None): optionalなValkey ACL username.
        password (str | None): optionalなValkey ACL password.
    """

    host: str
    port: int
    database: int
    username: str | None
    password: str | None


def build_database_dsn(parts: DatabaseConnectionParts) -> DsnValue:
    """PostgreSQL用database DSNとmask済みDSNを構築する.

    Args:
        parts (DatabaseConnectionParts): URL encode前のdatabase接続情報.

    Returns:
        DsnValue: 接続用DSNとpasswordをmaskした表示用DSN.
    """
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
    """Valkey用DSNとmask済みDSNを構築する.

    Args:
        parts (ValkeyConnectionParts): URL encode前のValkey接続情報.

    Returns:
        DsnValue: 接続用DSNとpasswordをmaskした表示用DSN.
    """
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
    """schemeと接続情報からURL形式のDSNを組み立てる.

    Args:
        scheme (str): DSNのURL scheme.
        host (str): 接続先host名.
        port (int): 接続先TCP port.
        path (str): URL encode済みのdatabase path.
        username (str | None): optionalな認証username.
        password (str | None): optionalな認証password.
        password_is_masked (bool): passwordがすでに表示用maskでURL encodeしない場合はTrue.

    Returns:
        str: credentialsを含むURL形式のDSN.
    """
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
    """DSNのauthority部へ付加する認証情報を整形する.

    Args:
        username (str | None): optionalな認証username.
        password (str | None): optionalな認証password.
        password_is_masked (bool): passwordがすでにmask済みでURL encodeしない場合はTrue.

    Returns:
        str: 空文字または末尾@を含むcredentials文字列.
    """
    if username is None and password is None:
        return ""
    encoded_username = quote(username or "", safe="")
    if password is None:
        return f"{encoded_username}@"
    encoded_password = password if password_is_masked else quote(password, safe="")
    return f"{encoded_username}:{encoded_password}@"
