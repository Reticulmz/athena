from __future__ import annotations

from pydantic import PostgresDsn, RedisDsn
from osu_server.config import AppConfig

_DEFAULT_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/osu"
_DEFAULT_VALKEY_URL = "redis://localhost:6379/0"


def make_app_config(
    *,
    database_url: str | PostgresDsn = _DEFAULT_DATABASE_URL,
    valkey_url: str | RedisDsn = _DEFAULT_VALKEY_URL,
    environment: str = "development",
    server_host: str = "0.0.0.0",
    server_port: int = 8000,
    domain: str = "athena.localhost",
    banned_passwords: list[str] | None = None,
    session_ttl: int = 300,
    packet_queue_max_size: int = 4096,
    max_request_body_size: int = 1_048_576,
    message_max_length: int = 450,
    rate_limit_messages: int = 10,
    rate_limit_window: int = 10,
    log_level: str = "INFO",
    log_json_enabled: bool = False,
    log_json_path: str = "logs/athena.jsonl",
) -> AppConfig:
    """Type-safe factory for AppConfig.

    Avoids using **kwargs to prevent type degradation.
    """
    if banned_passwords is None:
        banned_passwords = []

    return AppConfig(
        database_url=PostgresDsn(str(database_url)) if isinstance(database_url, str) else database_url,
        valkey_url=RedisDsn(str(valkey_url)) if isinstance(valkey_url, str) else valkey_url,
        environment=environment,
        server_host=server_host,
        server_port=server_port,
        domain=domain,
        banned_passwords=banned_passwords,
        session_ttl=session_ttl,
        packet_queue_max_size=packet_queue_max_size,
        max_request_body_size=max_request_body_size,
        message_max_length=message_max_length,
        rate_limit_messages=rate_limit_messages,
        rate_limit_window=rate_limit_window,
        log_level=log_level,
        log_json_enabled=log_json_enabled,
        log_json_path=log_json_path,
    )
