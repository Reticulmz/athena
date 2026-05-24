"""Tests for AppConfig — pydantic-settings based configuration management.

Covers requirements 2.1, 2.2, 2.3:
- 2.1: Read DATABASE_URL and REDIS_URL from environment variables
- 2.2: ValidationError when required fields are missing or invalid
- 2.3: Type-safe configuration object (not raw strings)
"""

import pytest
from pydantic import ValidationError

from osu_server.config import AppConfig, load_config

_TEST_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/osu"
_TEST_REDIS_URL = "redis://localhost:6379/0"

_DEFAULT_PORT = 8000
_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_ENVIRONMENT = "development"


class TestAppConfigEnvVarReading:
    """Requirement 2.1: Read DATABASE_URL and REDIS_URL from env vars."""

    def test_reads_database_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert str(config.database_url) == _TEST_DATABASE_URL

    def test_reads_redis_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert str(config.redis_url) == _TEST_REDIS_URL


class TestAppConfigValidation:
    """Requirement 2.2: ValidationError when required fields are missing."""

    def test_missing_database_url_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        with pytest.raises(ValidationError):
            AppConfig()  # pyright: ignore[reportCallIssue]

    def test_missing_redis_url_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.delenv("REDIS_URL", raising=False)

        with pytest.raises(ValidationError):
            AppConfig()  # pyright: ignore[reportCallIssue]

    def test_missing_all_required_fields_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)

        with pytest.raises(ValidationError):
            AppConfig()  # pyright: ignore[reportCallIssue]


class TestAppConfigLoggingDefaults:
    """Requirement 1.1, 1.2, 1.3, 1.4: Logging config fields with defaults."""

    def test_default_log_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert config.log_level == "INFO"

    def test_default_log_json_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert config.log_json_enabled is False

    def test_default_log_json_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert config.log_json_path == "logs/athena.jsonl"

    def test_override_log_level_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        config = load_config()
        assert config.log_level == "DEBUG"

    def test_override_log_json_enabled_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
        monkeypatch.setenv("LOG_JSON_ENABLED", "true")

        config = load_config()
        assert config.log_json_enabled is True

    def test_override_log_json_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
        monkeypatch.setenv("LOG_JSON_PATH", "/var/log/athena.jsonl")

        config = load_config()
        assert config.log_json_path == "/var/log/athena.jsonl"

    def test_log_json_enabled_is_bool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert isinstance(config.log_json_enabled, bool)


class TestAppConfigLogLevelValidation:
    """log_level field normalizes to uppercase and rejects invalid values."""

    def test_normalizes_lowercase_to_uppercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
        monkeypatch.setenv("LOG_LEVEL", "debug")

        config = load_config()
        assert config.log_level == "DEBUG"

    def test_rejects_invalid_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
        monkeypatch.setenv("LOG_LEVEL", "WARN")

        with pytest.raises(ValidationError, match="Invalid log level"):
            load_config()

    def test_rejects_typo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
        monkeypatch.setenv("LOG_LEVEL", "TRACE")

        with pytest.raises(ValidationError, match="Invalid log level"):
            load_config()

    def test_accepts_all_valid_levels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            monkeypatch.setenv("LOG_LEVEL", level)
            config = load_config()
            assert config.log_level == level


class TestAppConfigDefaults:
    """Requirement 2.3: Type-safe defaults for optional fields."""

    def test_default_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert config.environment == _DEFAULT_ENVIRONMENT

    def test_default_server_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert config.server_host == _DEFAULT_HOST

    def test_default_server_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert config.server_port == _DEFAULT_PORT

    def test_override_environment_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
        monkeypatch.setenv("ENVIRONMENT", "production")

        config = load_config()
        assert config.environment == "production"

    def test_override_server_port_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        expected_port = 9000
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
        monkeypatch.setenv("SERVER_PORT", str(expected_port))

        config = load_config()
        assert config.server_port == expected_port


class TestAppConfigTypeSafety:
    """Requirement 2.3: Values are proper types, not raw strings."""

    def test_server_port_is_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert isinstance(config.server_port, int)

    def test_server_port_coerced_from_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        expected_port = 3000
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)
        monkeypatch.setenv("SERVER_PORT", str(expected_port))

        config = load_config()
        assert config.server_port == expected_port
        assert isinstance(config.server_port, int)

    def test_load_config_returns_app_config_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", _TEST_REDIS_URL)

        config = load_config()
        assert isinstance(config, AppConfig)
