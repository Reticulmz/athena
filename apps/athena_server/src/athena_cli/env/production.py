"""production環境で危険なdefault設定を拒否するpolicyを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from athena_cli.errors import CliUserError

if TYPE_CHECKING:
    from osu_server.config import AppConfig


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class ProductionSafetyError(CliUserError):
    """production設定に安全でないlocal defaultが残ることを表す.

    Attributes:
        unsafe_settings (tuple[str, ...]): 安全でない設定に対応する環境変数名.
    """

    def __init__(self, unsafe_settings: tuple[str, ...]) -> None:
        """安全でない設定名を保持して例外を初期化する.

        Args:
            unsafe_settings (tuple[str, ...]): productionで拒否する環境変数名.
        """
        self.unsafe_settings: tuple[str, ...] = unsafe_settings
        joined_settings = ", ".join(unsafe_settings)
        super().__init__(f"Unsafe production settings: {joined_settings}")


def assert_production_safe(config: AppConfig) -> None:
    """production設定にlocal defaultが含まれないことを確認する.

    Args:
        config (AppConfig): validation済みのapplication設定.

    Returns:
        None: production以外または安全な設定を受け入れ値を返さずに完了する.

    Raises:
        ProductionSafetyError: production設定にlocal databaseまたはcacheなどが残る場合.
    """
    if config.environment != "production":
        return
    unsafe_settings = _find_unsafe_settings(config)
    if unsafe_settings:
        raise ProductionSafetyError(unsafe_settings)


def _find_unsafe_settings(config: AppConfig) -> tuple[str, ...]:
    """productionで拒否するlocal default設定の環境変数名を収集する.

    Args:
        config (AppConfig): 検査するapplication設定.

    Returns:
        tuple[str, ...]: 安全でない設定に対応する環境変数名を定義順で並べたtuple.
    """
    unsafe_settings: list[str] = []
    if _is_local_url(str(config.database_url)):
        unsafe_settings.append("DATABASE_URL")
    if _is_local_url(str(config.valkey_url)):
        unsafe_settings.append("VALKEY_URL")
    if config.domain.endswith(".localhost") or config.domain == "localhost":
        unsafe_settings.append("DOMAIN")
    if config.blob_storage_backend == "local":
        unsafe_settings.append("BLOB_STORAGE_BACKEND")
    return tuple(unsafe_settings)


def _is_local_url(value: str) -> bool:
    """URLのhostがlocal development用hostか判定する.

    Args:
        value (str): hostを検査するURL文字列.

    Returns:
        bool: URL hostがlocalhostまたはloopback addressの場合はTrue.
    """
    parsed = urlparse(value)
    return parsed.hostname in _LOCAL_HOSTS
