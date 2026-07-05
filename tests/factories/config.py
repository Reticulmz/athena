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
    log_dir: str = "logs",
    log_max_files: int = 30,
    query_diagnostics_enabled: bool | None = None,
    query_diagnostics_max_queries: int = 20,
    query_diagnostics_duplicate_threshold: int = 2,
    blob_storage_backend: str = "local",
    blob_storage_local_root: str = ".data/blobs",
    blob_storage_s3_bucket: str | None = None,
    blob_storage_s3_region: str | None = None,
    blob_storage_s3_endpoint: str | None = None,
    blob_storage_s3_access_key: str | None = None,
    blob_storage_s3_secret_key: str | None = None,
    beatmap_official_sources_enabled: bool = True,
    beatmap_official_api_client_id: str | None = "test-client-id",
    beatmap_official_api_client_secret: str | None = "test-client-secret",
    beatmap_mirror_trust_policy: str = "untrusted",
    beatmap_osu_current_url_template: str = "https://osu.ppy.sh/osu/{beatmap_id}",
    beatmap_osu_legacy_url_template: str = "https://old.ppy.sh/osu/{beatmap_id}",
    beatmap_community_mirror_url_templates: list[str] | None = None,
    beatmap_ranked_refresh_interval_seconds: int = 2_592_000,
    beatmap_pending_refresh_interval_seconds: int = 86_400,
    beatmap_graveyard_refresh_interval_seconds: int = 604_800,
    beatmap_mirror_refresh_interval_seconds: int = 86_400,
    beatmap_default_bounded_wait_seconds: float = 3.0,
    beatmap_max_bounded_wait_seconds: float = 3.0,
) -> AppConfig:
    """Type-safe factory for AppConfig.

    Avoids using **kwargs to prevent type degradation.
    """
    if banned_passwords is None:
        banned_passwords = []
    if beatmap_community_mirror_url_templates is None:
        beatmap_community_mirror_url_templates = []

    return AppConfig(
        database_url=PostgresDsn(str(database_url))
        if isinstance(database_url, str)
        else database_url,
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
        log_dir=log_dir,
        log_max_files=log_max_files,
        query_diagnostics_enabled=query_diagnostics_enabled,
        query_diagnostics_max_queries=query_diagnostics_max_queries,
        query_diagnostics_duplicate_threshold=query_diagnostics_duplicate_threshold,
        blob_storage_backend=blob_storage_backend,
        blob_storage_local_root=blob_storage_local_root,
        blob_storage_s3_bucket=blob_storage_s3_bucket,
        blob_storage_s3_region=blob_storage_s3_region,
        blob_storage_s3_endpoint=blob_storage_s3_endpoint,
        blob_storage_s3_access_key=blob_storage_s3_access_key,
        blob_storage_s3_secret_key=blob_storage_s3_secret_key,
        beatmap_official_sources_enabled=beatmap_official_sources_enabled,
        beatmap_official_api_client_id=beatmap_official_api_client_id,
        beatmap_official_api_client_secret=beatmap_official_api_client_secret,
        beatmap_mirror_trust_policy=beatmap_mirror_trust_policy,
        beatmap_osu_current_url_template=beatmap_osu_current_url_template,
        beatmap_osu_legacy_url_template=beatmap_osu_legacy_url_template,
        beatmap_community_mirror_url_templates=beatmap_community_mirror_url_templates,
        beatmap_ranked_refresh_interval_seconds=beatmap_ranked_refresh_interval_seconds,
        beatmap_pending_refresh_interval_seconds=beatmap_pending_refresh_interval_seconds,
        beatmap_graveyard_refresh_interval_seconds=beatmap_graveyard_refresh_interval_seconds,
        beatmap_mirror_refresh_interval_seconds=beatmap_mirror_refresh_interval_seconds,
        beatmap_default_bounded_wait_seconds=beatmap_default_bounded_wait_seconds,
        beatmap_max_bounded_wait_seconds=beatmap_max_bounded_wait_seconds,
    )
