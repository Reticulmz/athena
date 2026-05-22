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
    banned_passwords: list[str] = []

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="", env_file=".env")


def load_config() -> AppConfig:
    """Factory function to create AppConfig from environment variables."""
    return AppConfig()  # pyright: ignore[reportCallIssue]
