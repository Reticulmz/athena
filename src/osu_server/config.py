"""Application configuration management via pydantic-settings.

Reads configuration from environment variables with type-safe validation.
Required fields: DATABASE_URL, REDIS_URL.
Optional fields with defaults: ENVIRONMENT, SERVER_HOST, SERVER_PORT.
"""

from typing import ClassVar

from pydantic import PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Type-safe application configuration loaded from environment variables."""

    database_url: PostgresDsn
    redis_url: RedisDsn
    environment: str = "development"
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    domain: str = "athena.localhost"
    banned_passwords: list[str] = []

    session_ttl: int = 300
    packet_queue_max_size: int = 4096
    max_request_body_size: int = 1_048_576

    log_level: str = "INFO"
    log_json_enabled: bool = False
    log_json_path: str = "logs/athena.jsonl"

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="", env_file=".env")


def load_config() -> AppConfig:
    """Factory function to create AppConfig from environment variables."""
    return AppConfig()  # pyright: ignore[reportCallIssue]
