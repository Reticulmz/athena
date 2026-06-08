from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from athena_cli.errors import CliUserError

if TYPE_CHECKING:
    from osu_server.config import AppConfig


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class ProductionSafetyError(CliUserError):
    def __init__(self, unsafe_settings: tuple[str, ...]) -> None:
        self.unsafe_settings: tuple[str, ...] = unsafe_settings
        joined_settings = ", ".join(unsafe_settings)
        super().__init__(f"Unsafe production settings: {joined_settings}")


def assert_production_safe(config: AppConfig) -> None:
    if config.environment != "production":
        return
    unsafe_settings = _find_unsafe_settings(config)
    if unsafe_settings:
        raise ProductionSafetyError(unsafe_settings)


def _find_unsafe_settings(config: AppConfig) -> tuple[str, ...]:
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
    parsed = urlparse(value)
    return parsed.hostname in _LOCAL_HOSTS
