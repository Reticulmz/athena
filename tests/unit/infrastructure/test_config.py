"""Tests for AppConfig — pydantic-settings based configuration management.

Covers requirements 2.1, 2.2, 2.3:
- 2.1: Read DATABASE_URL and VALKEY_URL from environment variables
- 2.2: ValidationError when required fields are missing or invalid
- 2.3: Type-safe configuration object (not raw strings)
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from osu_server.config import AppConfig, load_config, load_routing_config

_TEST_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/osu"
_TEST_VALKEY_URL = "redis://localhost:6379/0"

_DEFAULT_PORT = 8000
_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_ENVIRONMENT = "development"


class TestAppConfigEnvVarReading:
    """Requirement 2.1: Read DATABASE_URL and VALKEY_URL from env vars."""

    def test_reads_database_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        config = load_config()
        assert str(config.database_url) == _TEST_DATABASE_URL

    def test_reads_valkey_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        config = load_config()
        assert str(config.valkey_url) == _TEST_VALKEY_URL

    def test_load_config_reads_development_env_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VALKEY_URL", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        _ = (tmp_path / ".env.development").write_text(
            f"DATABASE_URL={_TEST_DATABASE_URL}\nVALKEY_URL={_TEST_VALKEY_URL}\n",
            encoding="utf-8",
        )

        config = load_config()

        assert str(config.database_url) == _TEST_DATABASE_URL
        assert str(config.valkey_url) == _TEST_VALKEY_URL
        assert config.environment == "development"

    def test_load_config_accepts_plain_metadata_mirror_url_in_env_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VALKEY_URL", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        env_file_content = (
            f"DATABASE_URL={_TEST_DATABASE_URL}\n"
            f"VALKEY_URL={_TEST_VALKEY_URL}\n"
            "BEATMAP_METADATA_MIRROR_BASE_URLS=https://api.nerinyan.moe\n"
        )
        _ = (tmp_path / ".env.development").write_text(env_file_content, encoding="utf-8")

        config = load_config()

        assert config.beatmap_metadata_mirror_base_urls == ["https://api.nerinyan.moe"]

    def test_load_config_reads_environment_specific_env_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        test_database_url = "postgresql+asyncpg://test:test@localhost/test_osu"
        test_valkey_url = "redis://localhost:6380/1"
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VALKEY_URL", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "test")
        _ = (tmp_path / ".env.development").write_text(
            f"DATABASE_URL={_TEST_DATABASE_URL}\nVALKEY_URL={_TEST_VALKEY_URL}\n",
            encoding="utf-8",
        )
        _ = (tmp_path / ".env.test").write_text(
            f"DATABASE_URL={test_database_url}\nVALKEY_URL={test_valkey_url}\n",
            encoding="utf-8",
        )

        config = load_config()

        assert str(config.database_url) == test_database_url
        assert str(config.valkey_url) == test_valkey_url
        assert config.environment == "test"

    def test_load_routing_config_reads_development_domain_without_required_services(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DOMAIN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VALKEY_URL", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        _ = (tmp_path / ".env.development").write_text(
            "DOMAIN=example.test\n",
            encoding="utf-8",
        )

        config = load_routing_config()

        assert config.domain == "example.test"


class TestAppConfigValidation:
    """Requirement 2.2: ValidationError when required fields are missing."""

    def test_missing_database_url_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        with pytest.raises(ValidationError):
            _ = AppConfig()  # pyright: ignore[reportCallIssue]

    def test_missing_valkey_url_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.delenv("VALKEY_URL", raising=False)

        with pytest.raises(ValidationError):
            _ = AppConfig()  # pyright: ignore[reportCallIssue]

    def test_missing_all_required_fields_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VALKEY_URL", raising=False)

        with pytest.raises(ValidationError):
            _ = AppConfig()  # pyright: ignore[reportCallIssue]


class TestAppConfigLoggingDefaults:
    """Requirement 1.1, 1.2, 1.3, 1.4: Logging config fields with defaults."""

    def test_default_log_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        config = load_config()
        assert config.log_level == "INFO"

    def test_default_log_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("LOG_DIR", raising=False)

        config = load_config()
        assert config.log_dir == "logs"

    def test_default_log_max_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("LOG_MAX_FILES", raising=False)

        config = load_config()
        assert config.log_max_files == 30

    def test_override_log_level_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        config = load_config()
        assert config.log_level == "DEBUG"

    def test_override_log_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_DIR", "/var/log/athena")

        config = load_config()
        assert config.log_dir == "/var/log/athena"

    def test_override_log_max_files_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_MAX_FILES", "50")

        config = load_config()
        assert config.log_max_files == 50

    def test_log_max_files_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        # log_max_files must be greater than or equal to 0
        monkeypatch.setenv("LOG_MAX_FILES", "-1")
        with pytest.raises(ValidationError, match="log_max_files"):
            _ = load_config()


class TestAppConfigLogLevelValidation:
    """log_level field normalizes to uppercase and rejects invalid values."""

    def test_normalizes_lowercase_to_uppercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_LEVEL", "debug")

        config = load_config()
        assert config.log_level == "DEBUG"

    def test_rejects_invalid_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_LEVEL", "WARN")

        with pytest.raises(ValidationError, match="Invalid log level"):
            _ = load_config()

    def test_rejects_typo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_LEVEL", "TRACE")

        with pytest.raises(ValidationError, match="Invalid log level"):
            _ = load_config()

    def test_accepts_all_valid_levels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            monkeypatch.setenv("LOG_LEVEL", level)
            config = load_config()
            assert config.log_level == level


class TestAppConfigDefaults:
    """Requirement 2.3: Type-safe defaults for optional fields."""

    def test_default_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("ENVIRONMENT", raising=False)

        config = load_config()
        assert config.environment == _DEFAULT_ENVIRONMENT

    def test_default_server_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("SERVER_HOST", raising=False)

        config = load_config()
        assert config.server_host == _DEFAULT_HOST

    def test_default_server_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("SERVER_PORT", raising=False)

        config = load_config()
        assert config.server_port == _DEFAULT_PORT

    def test_override_environment_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("ENVIRONMENT", "production")

        config = load_config()
        assert config.environment == "production"

    def test_override_server_port_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        expected_port = 9000
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("SERVER_PORT", str(expected_port))

        config = load_config()
        assert config.server_port == expected_port


class TestAppConfigTypeSafety:
    """Requirement 2.3: Values are proper types, not raw strings."""

    def test_server_port_is_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        config = load_config()
        assert isinstance(config.server_port, int)

    def test_server_port_coerced_from_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        expected_port = 3000
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("SERVER_PORT", str(expected_port))

        config = load_config()
        assert config.server_port == expected_port
        assert isinstance(config.server_port, int)

    def test_load_config_returns_app_config_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        config = load_config()
        assert isinstance(config, AppConfig)


class TestBeatmapMirrorConfig:
    """Beatmap mirror source configuration and startup validation."""

    def test_beatmap_mirror_defaults_disable_mirror_trust(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        config = load_config()

        assert config.beatmap_official_sources_enabled is False
        assert config.beatmap_mirror_trust_policy == "untrusted"
        assert config.beatmap_osu_current_url_template == "https://osu.ppy.sh/osu/{beatmap_id}"
        assert config.beatmap_osu_legacy_url_template == "https://old.ppy.sh/osu/{beatmap_id}"
        assert config.beatmap_community_mirror_url_templates == []
        assert config.beatmap_metadata_mirror_base_urls == []
        assert config.beatmap_default_bounded_wait_seconds == 3.0
        assert (
            config.beatmap_default_bounded_wait_seconds == config.beatmap_max_bounded_wait_seconds
        )

    def test_development_requires_official_credentials_when_sources_enabled(self) -> None:
        with pytest.raises(ValidationError, match="beatmap official source credentials"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "development",
                    "beatmap_official_sources_enabled": True,
                }
            )

    def test_production_requires_official_credentials_when_sources_enabled(self) -> None:
        with pytest.raises(ValidationError, match="beatmap official source credentials"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_official_sources_enabled": True,
                    "beatmap_official_api_client_id": "123",
                }
            )

    def test_test_environment_allows_fake_source_settings_without_real_credentials(self) -> None:
        config = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "environment": "test",
                "beatmap_official_sources_enabled": True,
                "beatmap_community_mirror_url_templates": [
                    "http://fake-beatmap-source.local/osu/{beatmap_id}"
                ],
            }
        )

        assert config.beatmap_official_sources_enabled is True
        assert config.beatmap_official_api_client_id is None

    def test_accepts_configured_community_mirror_url_templates(self) -> None:
        config = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "environment": "production",
                "beatmap_community_mirror_url_templates": [
                    "https://catboy.best/osu/{beatmap_id}",
                    "https://mirror.example.com/beatmaps/{beatmap_id}/download",
                ],
            }
        )

        assert config.beatmap_community_mirror_url_templates == [
            "https://catboy.best/osu/{beatmap_id}",
            "https://mirror.example.com/beatmaps/{beatmap_id}/download",
        ]

    def test_rejects_invalid_community_mirror_url_template(self) -> None:
        with pytest.raises(ValidationError, match="beatmap_id"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_community_mirror_url_templates": ["https://catboy.best/osu/{id}"],
                }
            )

    def test_rejects_direct_url_template_with_unsupported_placeholder(self) -> None:
        with pytest.raises(ValidationError, match="unsupported placeholder"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_osu_current_url_template": (
                        "https://osu.ppy.sh/osu/{beatmap_id}/{extra}"
                    ),
                }
            )

    def test_rejects_direct_url_template_with_escaped_beatmap_id_placeholder(
        self,
    ) -> None:
        with pytest.raises(ValidationError, match="beatmap_id"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_osu_current_url_template": ("https://osu.ppy.sh/osu/{{beatmap_id}}"),
                }
            )

    def test_rejects_direct_url_template_with_beatmap_id_conversion(self) -> None:
        with pytest.raises(ValidationError, match="exactly"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_osu_current_url_template": ("https://osu.ppy.sh/osu/{beatmap_id!s}"),
                }
            )

    def test_rejects_community_mirror_url_template_with_unsupported_placeholder(
        self,
    ) -> None:
        with pytest.raises(ValidationError, match="unsupported placeholder"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_community_mirror_url_templates": [
                        "https://mirror.example.com/osu/{beatmap_id}/{extra}"
                    ],
                }
            )

    def test_rejects_community_mirror_url_template_with_escaped_beatmap_id_placeholder(
        self,
    ) -> None:
        with pytest.raises(ValidationError, match="beatmap_id"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_community_mirror_url_templates": [
                        "https://mirror.example.com/osu/{{beatmap_id}}"
                    ],
                }
            )

    def test_rejects_community_mirror_url_template_with_beatmap_id_format_spec(
        self,
    ) -> None:
        with pytest.raises(ValidationError, match="exactly"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_community_mirror_url_templates": [
                        "https://mirror.example.com/osu/{beatmap_id:04d}"
                    ],
                }
            )

    def test_rejects_non_https_mirror_url_outside_test(self) -> None:
        with pytest.raises(ValidationError, match="HTTPS"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_community_mirror_url_templates": [
                        "http://catboy.best/osu/{beatmap_id}"
                    ],
                }
            )

    def test_accepts_metadata_mirror_base_urls(self) -> None:
        config = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "environment": "production",
                "beatmap_metadata_mirror_base_urls": [
                    "https://api.nerinyan.moe",
                    "https://mirror.example.com/api/v2",
                ],
            }
        )

        assert config.beatmap_metadata_mirror_base_urls == [
            "https://api.nerinyan.moe",
            "https://mirror.example.com/api/v2",
        ]

    def test_metadata_mirror_base_url_does_not_require_beatmap_id_placeholder(self) -> None:
        config = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "environment": "production",
                "beatmap_metadata_mirror_base_urls": ["https://api.nerinyan.moe"],
            }
        )

        assert config.beatmap_metadata_mirror_base_urls == ["https://api.nerinyan.moe"]

    def test_rejects_relative_metadata_mirror_base_url(self) -> None:
        with pytest.raises(ValidationError, match="absolute URL"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_metadata_mirror_base_urls": ["/api/v2"],
                }
            )

    def test_rejects_non_https_metadata_mirror_base_url_outside_test(self) -> None:
        with pytest.raises(ValidationError, match="HTTPS"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "beatmap_metadata_mirror_base_urls": ["http://api.nerinyan.moe"],
                }
            )

    def test_test_environment_allows_http_metadata_mirror_base_url(self) -> None:
        config = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "environment": "test",
                "beatmap_metadata_mirror_base_urls": ["http://mirror.test/api/v2"],
            }
        )

        assert config.beatmap_metadata_mirror_base_urls == ["http://mirror.test/api/v2"]

    def test_rejects_invalid_mirror_trust_policy(self) -> None:
        with pytest.raises(ValidationError, match="beatmap_mirror_trust_policy"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "beatmap_mirror_trust_policy": "always",
                }
            )

    def test_rejects_invalid_refresh_timing(self) -> None:
        with pytest.raises(ValidationError, match="beatmap refresh intervals"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "beatmap_ranked_refresh_interval_seconds": 0,
                }
            )

    def test_rejects_default_bounded_wait_above_maximum(self) -> None:
        with pytest.raises(ValidationError, match="bounded wait"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "beatmap_default_bounded_wait_seconds": 5.0,
                    "beatmap_max_bounded_wait_seconds": 1.0,
                }
            )
