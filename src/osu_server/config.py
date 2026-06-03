"""Application configuration management via pydantic-settings.

Reads configuration from environment variables with type-safe validation.
Required fields: DATABASE_URL, VALKEY_URL.
Optional fields with defaults: ENVIRONMENT, SERVER_HOST, SERVER_PORT.
"""

import re
from typing import ClassVar

from pydantic import PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valkey は redis:// スキーマを使用するため、RedisDsn のバリデーションをそのまま活用
ValkeyDsn = RedisDsn

_BANCHO_BOT_USERNAME_MIN = 2
_BANCHO_BOT_USERNAME_MAX = 15
_BANCHO_BOT_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_ -]+$")


class AppConfig(BaseSettings):
    """Type-safe application configuration loaded from environment variables."""

    database_url: PostgresDsn
    valkey_url: ValkeyDsn
    environment: str = "development"
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    domain: str = "athena.localhost"
    banned_passwords: list[str] = []

    session_ttl: int = 300
    packet_queue_max_size: int = 4096
    max_request_body_size: int = 1_048_576

    message_max_length: int = 450
    rate_limit_messages: int = 10
    rate_limit_window: int = 10

    bancho_bot_username: str = "BanchoBot"

    log_level: str = "INFO"
    log_dir: str = "logs"
    log_max_files: int = 30

    @field_validator("log_max_files")
    @classmethod
    def _validate_log_max_files(cls, v: int) -> int:
        if v < 0:
            msg = f"log_max_files must be greater than or equal to 0, got {v}"
            raise ValueError(msg)
        return v

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        valid = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
        upper = v.upper()
        if upper not in valid:
            msg = f"Invalid log level: {v!r}. Valid: DEBUG, INFO, WARNING, ERROR, CRITICAL"
            raise ValueError(msg)
        return upper

    @field_validator("bancho_bot_username")
    @classmethod
    def _validate_bancho_bot_username(cls, v: str) -> str:
        length = len(v)
        if length < _BANCHO_BOT_USERNAME_MIN or length > _BANCHO_BOT_USERNAME_MAX:
            msg = (
                f"bancho_bot_username must be between {_BANCHO_BOT_USERNAME_MIN} "
                f"and {_BANCHO_BOT_USERNAME_MAX} characters, got {length!r}"
            )
            raise ValueError(msg)
        if not _BANCHO_BOT_USERNAME_PATTERN.match(v):
            msg = (
                "bancho_bot_username may only contain alphanumeric characters, "
                "spaces, underscores, and hyphens."
            )
            raise ValueError(msg)
        return v

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="", env_file=".env")


def load_config() -> AppConfig:
    """Factory function to create AppConfig from environment variables."""
    return AppConfig()  # pyright: ignore[reportCallIssue]
