"""Application configuration management via pydantic-settings.

Reads configuration from environment variables with type-safe validation.
Required fields: DATABASE_URL, VALKEY_URL.
Optional fields with defaults: ENVIRONMENT, SERVER_HOST, SERVER_PORT.
"""

import os
import re
from string import Formatter
from typing import Annotated, ClassVar, Self
from urllib.parse import urlparse

from pydantic import Field, PostgresDsn, RedisDsn, TypeAdapter, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Valkey は redis:// スキーマを使用するため、RedisDsn のバリデーションをそのまま活用
ValkeyDsn = RedisDsn

_BANCHO_BOT_USERNAME_MIN = 2
_BANCHO_BOT_USERNAME_MAX = 15
_BANCHO_BOT_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_ -]+$")
_BEATMAP_URL_TEMPLATE_TOKEN = "{beatmap_id}"
_SOURCE_CREDENTIAL_ENVIRONMENTS = frozenset({"development", "production"})
_TEST_ENVIRONMENT = "test"
_BEATMAP_URL_TEMPLATE_FIELD = "beatmap_id"
_DEFAULT_ENVIRONMENT = "development"
_ENVIRONMENT_VARIABLE = "ENVIRONMENT"


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
    score_submit_max_replay_size: int = 1_048_576
    score_submit_max_text_field_size: int = 65_536

    message_max_length: int = 450
    rate_limit_messages: int = 10
    rate_limit_window: int = 10

    bancho_bot_username: str = "BanchoBot"

    log_level: str = "INFO"
    log_dir: str = "logs"
    log_max_files: int = 30

    blob_storage_backend: str = "local"
    blob_storage_local_root: str = ".data/blobs"
    blob_storage_s3_bucket: str | None = None
    blob_storage_s3_region: str | None = None
    blob_storage_s3_endpoint: str | None = None
    blob_storage_s3_access_key: str | None = None
    blob_storage_s3_secret_key: str | None = None

    beatmap_official_sources_enabled: bool = False
    beatmap_official_api_client_id: str | None = None
    beatmap_official_api_client_secret: str | None = None
    beatmap_mirror_trust_policy: str = "untrusted"
    beatmap_osu_current_url_template: str = "https://osu.ppy.sh/osu/{beatmap_id}"
    beatmap_osu_legacy_url_template: str = "https://old.ppy.sh/osu/{beatmap_id}"
    beatmap_community_mirror_url_templates: Annotated[list[str], NoDecode] = Field(
        default_factory=list
    )
    beatmap_metadata_mirror_base_urls: Annotated[list[str], NoDecode] = Field(default_factory=list)
    beatmap_ranked_refresh_interval_seconds: int = 2_592_000
    beatmap_pending_refresh_interval_seconds: int = 86_400
    beatmap_graveyard_refresh_interval_seconds: int = 604_800
    beatmap_mirror_refresh_interval_seconds: int = 86_400
    beatmap_default_bounded_wait_seconds: float = 0.5
    beatmap_max_bounded_wait_seconds: float = 3.0

    @field_validator("blob_storage_backend")
    @classmethod
    def _validate_blob_storage_backend(cls, v: str) -> str:
        valid = frozenset({"local", "s3"})
        lower = v.lower()
        if lower not in valid:
            msg = f"Invalid blob_storage_backend: {v!r}. Valid: local, s3"
            raise ValueError(msg)
        return lower

    @field_validator("beatmap_mirror_trust_policy")
    @classmethod
    def _validate_beatmap_mirror_trust_policy(cls, v: str) -> str:
        valid = frozenset({"trusted", "untrusted"})
        lower = v.lower()
        if lower not in valid:
            msg = f"Invalid beatmap_mirror_trust_policy: {v!r}. Valid: trusted, untrusted"
            raise ValueError(msg)
        return lower

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

    @field_validator(
        "beatmap_community_mirror_url_templates",
        "beatmap_metadata_mirror_base_urls",
        mode="before",
    )
    @classmethod
    def _parse_url_list(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        stripped = v.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            return TypeAdapter(list[str]).validate_json(stripped)
        return [item.strip() for item in stripped.split(",") if item.strip()]

    @model_validator(mode="after")
    def _validate_beatmap_mirror_config(self) -> Self:
        environment = self.environment.lower()
        if (
            self.beatmap_official_sources_enabled
            and environment in _SOURCE_CREDENTIAL_ENVIRONMENTS
            and (
                not self.beatmap_official_api_client_id
                or not self.beatmap_official_api_client_secret
            )
        ):
            msg = (
                "beatmap official source credentials are required when official "
                "sources are enabled in development or production"
            )
            raise ValueError(msg)

        self._validate_beatmap_url_template(
            self.beatmap_osu_current_url_template,
            field_name="beatmap_osu_current_url_template",
            environment=environment,
        )
        self._validate_beatmap_url_template(
            self.beatmap_osu_legacy_url_template,
            field_name="beatmap_osu_legacy_url_template",
            environment=environment,
        )
        for template in self.beatmap_community_mirror_url_templates:
            self._validate_beatmap_url_template(
                template,
                field_name="beatmap_community_mirror_url_templates",
                environment=environment,
            )
        for base_url in self.beatmap_metadata_mirror_base_urls:
            self._validate_beatmap_base_url(
                base_url,
                field_name="beatmap_metadata_mirror_base_urls",
                environment=environment,
            )

        refresh_intervals = (
            self.beatmap_ranked_refresh_interval_seconds,
            self.beatmap_pending_refresh_interval_seconds,
            self.beatmap_graveyard_refresh_interval_seconds,
            self.beatmap_mirror_refresh_interval_seconds,
        )
        if any(interval <= 0 for interval in refresh_intervals):
            msg = "beatmap refresh intervals must be greater than 0 seconds"
            raise ValueError(msg)

        if self.beatmap_default_bounded_wait_seconds <= 0:
            msg = "beatmap bounded wait defaults must be greater than 0 seconds"
            raise ValueError(msg)
        if self.beatmap_max_bounded_wait_seconds <= 0:
            msg = "beatmap bounded wait maximum must be greater than 0 seconds"
            raise ValueError(msg)
        if self.beatmap_default_bounded_wait_seconds > self.beatmap_max_bounded_wait_seconds:
            msg = "beatmap default bounded wait cannot exceed the maximum bounded wait"
            raise ValueError(msg)

        return self

    @staticmethod
    def _validate_beatmap_url_template(
        template: str,
        *,
        field_name: str,
        environment: str,
    ) -> None:
        try:
            parsed_template = tuple(Formatter().parse(template))
        except ValueError as exc:
            msg = f"{field_name} must be a valid URL template"
            raise ValueError(msg) from exc

        parsed_fields = tuple(
            (placeholder, conversion, format_spec)
            for _, placeholder, format_spec, conversion in parsed_template
            if placeholder is not None
        )
        beatmap_id_fields = tuple(
            field for field in parsed_fields if field[0] == _BEATMAP_URL_TEMPLATE_FIELD
        )
        if len(beatmap_id_fields) != 1:
            msg = f"{field_name} must include exactly one {_BEATMAP_URL_TEMPLATE_TOKEN}"
            raise ValueError(msg)
        _, conversion, format_spec = beatmap_id_fields[0]
        if conversion or format_spec:
            msg = f"{field_name} must use exactly {_BEATMAP_URL_TEMPLATE_TOKEN}"
            raise ValueError(msg)

        unsupported_placeholders = tuple(
            placeholder
            for placeholder, _, _ in parsed_fields
            if placeholder != _BEATMAP_URL_TEMPLATE_FIELD
        )
        if unsupported_placeholders:
            msg = (
                f"{field_name} contains unsupported placeholder "
                f"{unsupported_placeholders[0]!r}; only "
                f"{_BEATMAP_URL_TEMPLATE_TOKEN} is supported"
            )
            raise ValueError(msg)

        try:
            candidate = template.format(beatmap_id=1)
        except ValueError as exc:
            msg = f"{field_name} must be a valid URL template"
            raise ValueError(msg) from exc
        parsed = urlparse(candidate)
        if not parsed.scheme or not parsed.netloc:
            msg = f"{field_name} must be an absolute URL template"
            raise ValueError(msg)
        if parsed.scheme not in {"http", "https"}:
            msg = f"{field_name} must use HTTP or HTTPS"
            raise ValueError(msg)
        if environment != _TEST_ENVIRONMENT and parsed.scheme != "https":
            msg = f"{field_name} must use HTTPS outside test configuration"
            raise ValueError(msg)

    @staticmethod
    def _validate_beatmap_base_url(
        base_url: str,
        *,
        field_name: str,
        environment: str,
    ) -> None:
        parsed = urlparse(base_url)
        if not parsed.scheme or not parsed.netloc:
            msg = f"{field_name} must be an absolute URL"
            raise ValueError(msg)
        if parsed.scheme not in {"http", "https"}:
            msg = f"{field_name} must use HTTP or HTTPS"
            raise ValueError(msg)
        if environment != _TEST_ENVIRONMENT and parsed.scheme != "https":
            msg = f"{field_name} must use HTTPS outside test configuration"
            raise ValueError(msg)

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="")


def load_config() -> AppConfig:
    """Factory function to create AppConfig from environment variables."""
    environment = os.environ.get(_ENVIRONMENT_VARIABLE, _DEFAULT_ENVIRONMENT).lower()
    return AppConfig(_env_file=f".env.{environment}")  # pyright: ignore[reportCallIssue]
