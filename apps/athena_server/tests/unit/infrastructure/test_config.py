"""AppConfigの環境読込とvalidationおよびdefault設定契約を検証する."""

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

import osu_server.config as config_module
from osu_server.config import (
    AppConfig,
    environment_file_path,
    load_config,
    load_routing_config,
)

if TYPE_CHECKING:
    from pathlib import Path

_TEST_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/osu"
_TEST_VALKEY_URL = "redis://localhost:6379/0"

_DEFAULT_PORT = 8000
_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_ENVIRONMENT = "development"


def test_environment_file_path_is_independent_of_current_working_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Server project root基準のenvironment file pathがCWDに依存しないことを検証する.

    server rootと無関係なworking directoryを設定してenvironment file pathを解決し,
    target pathがserver root内で一定になることを確認する.

    Args:
        monkeypatch (pytest.MonkeyPatch): project rootとworking directoryを隔離するpytest helper.
        tmp_path (Path): server rootとworking directoryを置くpytest一時directory.

    Returns:
        None: 解決pathを検証して完了し, 呼び出し側へ値を返さない.
    """
    server_root = tmp_path / "server"
    server_root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setattr(config_module, "server_project_root", lambda: server_root)
    monkeypatch.chdir(cwd)

    assert environment_file_path("test") == server_root / ".env.test"


def test_osu_direct_upstream_search_defaults_to_hinamizawa_then_nerinyan() -> None:
    """osu!direct hybrid検索の既定provider順と待機秒数を検証する.

    Returns:
        None: default config値を検証して完了し値を返さない.
    """
    config = AppConfig.model_validate(
        {"database_url": _TEST_DATABASE_URL, "valkey_url": _TEST_VALKEY_URL}
    )

    assert config.osu_direct_upstream_search_enabled is True
    assert config.osu_direct_upstream_search_providers == ["hinamizawa", "nerinyan"]
    assert config.osu_direct_upstream_search_wait_seconds == 5.0
    assert config.osu_direct_upstream_search_first_page_refresh_seconds == 300.0


def test_osu_direct_upstream_search_provider_list_accepts_comma_text() -> None:
    """外部検索provider一覧をcomma-separated textから読む契約を検証する.

    Returns:
        None: provider名の正規化結果を検証して完了し値を返さない.
    """
    config = AppConfig.model_validate(
        {
            "database_url": _TEST_DATABASE_URL,
            "valkey_url": _TEST_VALKEY_URL,
            "osu_direct_upstream_search_providers": "Hinamizawa,nerinyan",
        }
    )

    assert config.osu_direct_upstream_search_providers == ["hinamizawa", "nerinyan"]


def test_osu_direct_upstream_search_enabled_requires_provider() -> None:
    """外部検索が有効な場合はprovider一覧を空にできない契約を検証する.

    Returns:
        None: ValidationErrorを検証して完了し値を返さない.
    """
    with pytest.raises(ValidationError, match="osu_direct_upstream_search_providers"):
        _ = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "osu_direct_upstream_search_providers": [],
            }
        )


class TestAppConfigDatabaseRuntime:
    """Database poolとworker metadata fetch制限のruntime設定契約を検証する."""

    def test_database_pool_defaults(self) -> None:
        """Database poolとmetadata fetch制限が安全な既定値を持つことを検証する.

        Returns:
            None: default値を検証して完了する.
        """
        config = AppConfig.model_validate(
            {"database_url": _TEST_DATABASE_URL, "valkey_url": _TEST_VALKEY_URL}
        )

        assert config.database_pool_size == 5
        assert config.database_max_overflow == 10
        assert config.database_pool_timeout_seconds == 30.0
        assert config.beatmap_metadata_fetch_max_concurrency == 4

    def test_database_pool_overrides_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Database pool設定を環境変数からoverrideできることを検証する.

        Args:
            monkeypatch (pytest.MonkeyPatch): runtime設定環境変数を設定するfixture.

        Returns:
            None: override結果を検証して完了する.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("DATABASE_POOL_SIZE", "8")
        monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "4")
        monkeypatch.setenv("DATABASE_POOL_TIMEOUT_SECONDS", "12.5")
        monkeypatch.setenv("BEATMAP_METADATA_FETCH_MAX_CONCURRENCY", "3")

        config = load_config()

        assert config.database_pool_size == 8
        assert config.database_max_overflow == 4
        assert config.database_pool_timeout_seconds == 12.5
        assert config.beatmap_metadata_fetch_max_concurrency == 3

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("database_pool_size", 0),
            ("database_max_overflow", -1),
            ("database_pool_timeout_seconds", 0),
            ("beatmap_metadata_fetch_max_concurrency", 0),
        ],
    )
    def test_rejects_invalid_database_runtime_values(
        self,
        field: str,
        value: int,
    ) -> None:
        """DB runtime制限の不正値をvalidationが拒否することを検証する.

        Args:
            field (str): 不正値を入れる設定field名.
            value (int): validationで拒否される値.

        Returns:
            None: ValidationErrorを検証して完了する.
        """
        with pytest.raises(ValidationError, match=field):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    field: value,
                }
            )

    def test_metadata_fetch_concurrency_must_fit_database_pool(self) -> None:
        """DB-heavy metadata fetch同時実行数が通常poolを超える設定を拒否する.

        Returns:
            None: database_pool_sizeとの相互制約ValidationErrorを検証して完了する.
        """
        with pytest.raises(ValidationError, match="database_pool_size"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "database_pool_size": 2,
                    "beatmap_metadata_fetch_max_concurrency": 3,
                }
            )


class TestAppConfigEnvVarReading:
    """AppConfigが環境変数とenvironment別env fileを読む契約を検証するtest群."""

    def test_reads_database_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DATABASE_URL環境変数がdatabase_urlへ反映される契約を検証する.

        必須URLを環境へ設定してload_configを実行する.
        configのdatabase_urlが設定したURLと一致することを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): test用環境変数を設定するpytest helper.

        Returns:
            None: database URL読込を検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        config = load_config()
        assert str(config.database_url) == _TEST_DATABASE_URL

    def test_reads_valkey_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """VALKEY_URL環境変数がvalkey_urlへ反映される契約を検証する.

        必須URLを環境へ設定してload_configを実行する.
        configのvalkey_urlが設定したURLと一致することを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): test用環境変数を設定するpytest helper.

        Returns:
            None: Valkey URL読込を検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        config = load_config()
        assert str(config.valkey_url) == _TEST_VALKEY_URL

    def test_load_config_reads_development_env_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Development env fileをload_configが読む契約を検証する.

        必須URLを持つ.env.developmentだけを一時directoryへ作成してload_configを実行する.
        URLとdefault development environmentがfileから読まれることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): project root、working directory、環境変数を隔離する
                pytest helper.
            tmp_path (Path): env fileを置くpytest一時directory.

        Returns:
            None: development env file読込を検証して完了し値を返さない.
        """
        server_root = tmp_path / "server"
        server_root.mkdir()
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.setattr(config_module, "server_project_root", lambda: server_root)
        monkeypatch.chdir(cwd)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VALKEY_URL", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        _ = (server_root / ".env.development").write_text(
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
        """Plain metadata mirror URLをenv fileからlistとして読む契約を検証する.

        metadata mirror base URLを持つ.env.developmentを一時directoryへ作成する.
        load_configを実行してconfigへ読み込む.
        configが1件のmirror base URL listを保持することを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): project root、working directory、環境変数を隔離する
                pytest helper.
            tmp_path (Path): env fileを置くpytest一時directory.

        Returns:
            None: metadata mirror URL読込を検証して完了し値を返さない.
        """
        server_root = tmp_path / "server"
        server_root.mkdir()
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.setattr(config_module, "server_project_root", lambda: server_root)
        monkeypatch.chdir(cwd)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VALKEY_URL", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        env_file_content = (
            f"DATABASE_URL={_TEST_DATABASE_URL}\n"
            f"VALKEY_URL={_TEST_VALKEY_URL}\n"
            "BEATMAP_METADATA_MIRROR_BASE_URLS=https://api.nerinyan.moe\n"
        )
        _ = (server_root / ".env.development").write_text(env_file_content, encoding="utf-8")

        config = load_config()

        assert config.beatmap_metadata_mirror_base_urls == ["https://api.nerinyan.moe"]

    def test_load_config_reads_environment_specific_env_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ENVIRONMENTに対応するenv fileを優先して読む契約を検証する.

        developmentとtestの異なる必須URL fileを用意してENVIRONMENTをtestへ設定する.
        test fileのURLとtest environmentが選ばれることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): project root、working directory、環境変数を隔離する
                pytest helper.
            tmp_path (Path): environment別env fileを置くpytest一時directory.

        Returns:
            None: environment別env file選択を検証して完了し値を返さない.
        """
        test_database_url = "postgresql+asyncpg://test:test@localhost/test_osu"
        test_valkey_url = "redis://localhost:6380/1"
        server_root = tmp_path / "server"
        server_root.mkdir()
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.setattr(config_module, "server_project_root", lambda: server_root)
        monkeypatch.chdir(cwd)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VALKEY_URL", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "test")
        _ = (server_root / ".env.development").write_text(
            f"DATABASE_URL={_TEST_DATABASE_URL}\nVALKEY_URL={_TEST_VALKEY_URL}\n",
            encoding="utf-8",
        )
        _ = (server_root / ".env.test").write_text(
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
        """Routing configが必須service URLなしでDOMAINを読む契約を検証する.

        DOMAINだけを持つ.env.developmentを一時directoryへ作成してload_routing_configを実行する.
        databaseとValkey設定なしでもdomainが読まれることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): project root、working directory、環境変数を隔離する
                pytest helper.
            tmp_path (Path): routing env fileを置くpytest一時directory.

        Returns:
            None: service非依存routing config読込を検証して完了し値を返さない.
        """
        server_root = tmp_path / "server"
        server_root.mkdir()
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.setattr(config_module, "server_project_root", lambda: server_root)
        monkeypatch.chdir(cwd)
        monkeypatch.delenv("DOMAIN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VALKEY_URL", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        _ = (server_root / ".env.development").write_text(
            "DOMAIN=example.test\n",
            encoding="utf-8",
        )

        config = load_routing_config()

        assert config.domain == "example.test"


class TestAppConfigValidation:
    """必須service URLが欠けるAppConfigをvalidationが拒否する契約を検証するtest群."""

    def test_missing_database_url_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DATABASE_URLなしのAppConfigを拒否する契約を検証する.

        VALKEY_URLだけを環境へ設定してAppConfigを生成する.
        ValidationErrorが送出されることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): 必須環境変数を選択的に削除するpytest helper.

        Returns:
            None: missing database URL validationを検証して完了し値を返さない.
        """
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        with pytest.raises(ValidationError):
            _ = AppConfig()  # pyright: ignore[reportCallIssue]

    def test_missing_valkey_url_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VALKEY_URLなしのAppConfigを拒否する契約を検証する.

        DATABASE_URLだけを環境へ設定してAppConfigを生成する.
        ValidationErrorが送出されることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): 必須環境変数を選択的に削除するpytest helper.

        Returns:
            None: missing Valkey URL validationを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.delenv("VALKEY_URL", raising=False)

        with pytest.raises(ValidationError):
            _ = AppConfig()  # pyright: ignore[reportCallIssue]

    def test_missing_all_required_fields_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """両必須service URLなしのAppConfigを拒否する契約を検証する.

        DATABASE_URLとVALKEY_URLを環境から削除してAppConfigを生成する.
        ValidationErrorが送出されることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): 両必須環境変数を削除するpytest helper.

        Returns:
            None: missing required URL validationを検証して完了し値を返さない.
        """
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VALKEY_URL", raising=False)

        with pytest.raises(ValidationError):
            _ = AppConfig()  # pyright: ignore[reportCallIssue]


class TestAppConfigLoggingDefaults:
    """Logging設定のdefault値と環境変数override契約を検証するtest群."""

    def test_default_log_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LOG_LEVEL未設定時にINFOを使う契約を検証する.

        必須service URLだけを設定してLOG_LEVELを削除しload_configを実行する.
        configのlog_levelがINFOとなることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を隔離するpytest helper.

        Returns:
            None: default log levelを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        config = load_config()
        assert config.log_level == "INFO"

    def test_default_log_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LOG_DIR未設定時にlogs directoryを使う契約を検証する.

        必須service URLだけを設定してLOG_DIRを削除しload_configを実行する.
        configのlog_dirがlogsとなることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を隔離するpytest helper.

        Returns:
            None: default log directoryを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("LOG_DIR", raising=False)

        config = load_config()
        assert config.log_dir == "logs"

    def test_default_log_max_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LOG_MAX_FILES未設定時に30を使う契約を検証する.

        必須service URLだけを設定してLOG_MAX_FILESを削除しload_configを実行する.
        configのlog_max_filesが30となることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を隔離するpytest helper.

        Returns:
            None: default log retentionを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("LOG_MAX_FILES", raising=False)

        config = load_config()
        assert config.log_max_files == 30

    def test_override_log_level_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LOG_LEVEL環境変数がdefaultをoverrideする契約を検証する.

        DEBUGをLOG_LEVELへ設定してload_configを実行する.
        configのlog_levelがDEBUGとなることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を設定するpytest helper.

        Returns:
            None: log level overrideを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        config = load_config()
        assert config.log_level == "DEBUG"

    def test_override_log_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LOG_DIR環境変数がdefault directoryをoverrideする契約を検証する.

        custom pathをLOG_DIRへ設定してload_configを実行する.
        configのlog_dirがcustom pathとなることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を設定するpytest helper.

        Returns:
            None: log directory overrideを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_DIR", "/var/log/athena")

        config = load_config()
        assert config.log_dir == "/var/log/athena"

    def test_override_log_max_files_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LOG_MAX_FILES環境変数がdefault retentionをoverrideする契約を検証する.

        50をLOG_MAX_FILESへ設定してload_configを実行する.
        configのlog_max_filesが50となることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を設定するpytest helper.

        Returns:
            None: log retention overrideを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_MAX_FILES", "50")

        config = load_config()
        assert config.log_max_files == 50

    def test_log_max_files_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """負のLOG_MAX_FILESをvalidationが拒否する契約を検証する.

        必須service URLと-1のLOG_MAX_FILESを設定してload_configを実行する.
        log_max_filesを示すValidationErrorが送出されることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を設定するpytest helper.

        Returns:
            None: invalid log retention拒否を検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        # log_max_files must be greater than or equal to 0
        monkeypatch.setenv("LOG_MAX_FILES", "-1")
        with pytest.raises(ValidationError, match="log_max_files"):
            _ = load_config()


class TestAppConfigLogLevelValidation:
    """Log levelのnormalizationと許容値validation契約を検証するtest群."""

    def test_normalizes_lowercase_to_uppercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """小文字LOG_LEVELを大文字へ正規化する契約を検証する.

        debugをLOG_LEVELへ設定してload_configを実行する.
        configのlog_levelがDEBUGとなることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を設定するpytest helper.

        Returns:
            None: log level normalizationを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_LEVEL", "debug")

        config = load_config()
        assert config.log_level == "DEBUG"

    def test_rejects_invalid_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """許容外のWARN log levelを拒否する契約を検証する.

        WARNをLOG_LEVELへ設定してload_configを実行する.
        Invalid log levelを示すValidationErrorが送出されることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を設定するpytest helper.

        Returns:
            None: invalid log level拒否を検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_LEVEL", "WARN")

        with pytest.raises(ValidationError, match="Invalid log level"):
            _ = load_config()

    def test_rejects_typo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """許容外のTRACE typoをlog levelとして拒否する契約を検証する.

        TRACEをLOG_LEVELへ設定してload_configを実行する.
        Invalid log levelを示すValidationErrorが送出されることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を設定するpytest helper.

        Returns:
            None: typo log level拒否を検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("LOG_LEVEL", "TRACE")

        with pytest.raises(ValidationError, match="Invalid log level"):
            _ = load_config()

    def test_accepts_all_valid_levels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """全許容log levelをそのまま受け付ける契約を検証する.

        5種類のvalid levelを順にLOG_LEVELへ設定してload_configを実行する.
        各configが対応する設定値を保持することを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): logging環境変数を反復設定するpytest helper.

        Returns:
            None: valid log level集合を検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            monkeypatch.setenv("LOG_LEVEL", level)
            config = load_config()
            assert config.log_level == level


class TestAppConfigDefaults:
    """Optional AppConfig fieldのtype-safe defaultとoverride契約を検証するtest群."""

    def test_default_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ENVIRONMENT未設定時にdevelopmentを使う契約を検証する.

        必須service URLだけを設定してENVIRONMENTを削除しload_configを実行する.
        configのenvironmentがdevelopmentとなることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): environment変数を隔離するpytest helper.

        Returns:
            None: default environmentを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("ENVIRONMENT", raising=False)

        config = load_config()
        assert config.environment == _DEFAULT_ENVIRONMENT

    def test_default_server_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SERVER_HOST未設定時に公開host defaultを使う契約を検証する.

        必須service URLだけを設定してSERVER_HOSTを削除しload_configを実行する.
        configのserver_hostが0.0.0.0となることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): server host環境変数を隔離するpytest helper.

        Returns:
            None: default server hostを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("SERVER_HOST", raising=False)

        config = load_config()
        assert config.server_host == _DEFAULT_HOST

    def test_default_server_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SERVER_PORT未設定時に8000を使う契約を検証する.

        必須service URLだけを設定してSERVER_PORTを削除しload_configを実行する.
        configのserver_portが8000となることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): server port環境変数を隔離するpytest helper.

        Returns:
            None: default server portを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.delenv("SERVER_PORT", raising=False)

        config = load_config()
        assert config.server_port == _DEFAULT_PORT

    def test_override_environment_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ENVIRONMENT環境変数がdefault environmentをoverrideする契約を検証する.

        productionをENVIRONMENTへ設定してload_configを実行する.
        configのenvironmentがproductionとなることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): environment変数を設定するpytest helper.

        Returns:
            None: environment overrideを検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("ENVIRONMENT", "production")

        config = load_config()
        assert config.environment == "production"

    def test_override_server_port_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SERVER_PORT環境変数がdefault portをoverrideする契約を検証する.

        9000をSERVER_PORTへ設定してload_configを実行する.
        configのserver_portが9000となることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): server port環境変数を設定するpytest helper.

        Returns:
            None: server port overrideを検証して完了し値を返さない.
        """
        expected_port = 9000
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("SERVER_PORT", str(expected_port))

        config = load_config()
        assert config.server_port == expected_port


class TestAppConfigTypeSafety:
    """AppConfig値がraw environment stringではなくdomain型となる契約を検証するtest群."""

    def test_server_port_is_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default server portがint型として公開される契約を検証する.

        必須service URLを設定してload_configを実行する.
        configのserver_portがint instanceであることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): 必須service URLを設定するpytest helper.

        Returns:
            None: default server port型を検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        config = load_config()
        assert isinstance(config.server_port, int)

    def test_server_port_coerced_from_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """文字列SERVER_PORTをintへcoerceする契約を検証する.

        3000の文字列表現をSERVER_PORTへ設定してload_configを実行する.
        configがint型の3000を保持することを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): server port環境変数を設定するpytest helper.

        Returns:
            None: server port coercionを検証して完了し値を返さない.
        """
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
        """load_configがAppConfig instanceを返す契約を検証する.

        必須service URLを環境へ設定してload_configを実行する.
        resultがAppConfig instanceであることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): 必須service URLを設定するpytest helper.

        Returns:
            None: config factory戻り型を検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)

        config = load_config()
        assert isinstance(config, AppConfig)


class TestBeatmapMirrorConfig:
    """Beatmap sourceとmirror URLおよびrefresh policyのconfiguration契約を検証するtest群."""

    def test_beatmap_mirror_defaults_disable_mirror_trust(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Default設定がmirrorをuntrustedかつ無効にする契約を検証する.

        一時working directoryで必須service URLだけを設定してload_configを実行する.
        source有効化とmirror listがdefault安全値となりbounded waitが最大値に一致することを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): working directoryと必須URLを設定するpytest helper.
            tmp_path (Path): default env fileを持たないpytest一時directory.

        Returns:
            None: safe beatmap mirror defaultsを検証して完了し値を返さない.
        """
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
        """Developmentでofficial source有効化にcredentialを要求する契約を検証する.

        credentialなしでofficial sourceを有効化するdevelopment AppConfigを生成する.
        credential要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: development credential validationを検証して完了し値を返さない.
        """
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
        """Productionで不完全official credentialを拒否する契約を検証する.

        client IDだけでofficial sourceを有効化するproduction AppConfigを生成する.
        credential要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: production credential validationを検証して完了し値を返さない.
        """
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
        """Test environmentがreal official credentialなしのfake sourceを許可する契約を検証する.

        HTTP fake community mirrorを持つtest AppConfigを生成する.
        official source有効化を保持しofficial client IDがNoneであることを確認する.

        Returns:
            None: test-only fake source許可を検証して完了し値を返さない.
        """
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
        """HTTPS community mirror URL templateを複数受け付ける契約を検証する.

        beatmap_id placeholderを持つ2個のHTTPS templateでproduction AppConfigを生成する.
        configが同じtemplate順序を保持することを確認する.

        Returns:
            None: configured community mirror template受理を検証して完了し値を返さない.
        """
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
        """beatmap_id以外のplaceholderをcommunity mirror templateとして拒否する契約を検証する.

        id placeholderを持つproduction AppConfigを生成する.
        beatmap_id要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: invalid community mirror placeholder拒否を検証して完了し値を返さない.
        """
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
        """Direct source URLの追加placeholderを拒否する契約を検証する.

        beatmap_idとextraを持つosu current templateでproduction AppConfigを生成する.
        unsupported placeholderを示すValidationErrorが送出されることを確認する.

        Returns:
            None: invalid direct source placeholder拒否を検証して完了し値を返さない.
        """
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
        """Escaped beatmap_id placeholderをdirect source URLとして拒否する契約を検証する.

        二重braceでescapedしたbeatmap_idを持つosu current templateでAppConfigを生成する.
        beatmap_id要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: escaped direct placeholder拒否を検証して完了し値を返さない.
        """
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
        """Format conversion付きbeatmap_idをdirect source URLとして拒否する契約を検証する.

        !s conversionを持つosu current templateでproduction AppConfigを生成する.
        exact placeholder要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: converted direct placeholder拒否を検証して完了し値を返さない.
        """
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
        """Community mirror URLの追加placeholderを拒否する契約を検証する.

        beatmap_idとextraを持つcommunity templateでproduction AppConfigを生成する.
        unsupported placeholderを示すValidationErrorが送出されることを確認する.

        Returns:
            None: invalid community placeholder拒否を検証して完了し値を返さない.
        """
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
        """Escaped beatmap_id placeholderをcommunity mirror URLとして拒否する契約を検証する.

        二重braceでescapedしたbeatmap_idを持つcommunity templateでAppConfigを生成する.
        beatmap_id要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: escaped community placeholder拒否を検証して完了し値を返さない.
        """
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
        """Format spec付きbeatmap_idをcommunity mirror URLとして拒否する契約を検証する.

        :04d format specを持つcommunity templateでproduction AppConfigを生成する.
        exact placeholder要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: formatted community placeholder拒否を検証して完了し値を返さない.
        """
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
        """Test以外でHTTP community mirror URLを拒否する契約を検証する.

        HTTP templateを持つproduction AppConfigを生成する.
        HTTPS要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: insecure community mirror URL拒否を検証して完了し値を返さない.
        """
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
        """HTTPS metadata mirror base URLを複数受け付ける契約を検証する.

        2個のabsolute HTTPS metadata base URLでproduction AppConfigを生成する.
        configが同じURL順序を保持することを確認する.

        Returns:
            None: configured metadata mirror base URL受理を検証して完了し値を返さない.
        """
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
        """Metadata mirror base URLがbeatmap_id placeholderを要求しない契約を検証する.

        Placeholderなしのabsolute HTTPS metadata base URLでproduction AppConfigを生成する.
        configが同じbase URLを保持することを確認する.

        Returns:
            None: placeholder不要metadata base URLを検証して完了し値を返さない.
        """
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
        """Relative metadata mirror base URLを拒否する契約を検証する.

        pathだけのmetadata base URLでproduction AppConfigを生成する.
        absolute URL要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: relative metadata URL拒否を検証して完了し値を返さない.
        """
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
        """Test以外でHTTP metadata mirror base URLを拒否する契約を検証する.

        HTTP metadata base URLでproduction AppConfigを生成する.
        HTTPS要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: insecure metadata URL拒否を検証して完了し値を返さない.
        """
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
        """Test environmentがHTTP metadata mirror base URLを許可する契約を検証する.

        HTTP metadata base URLを持つtest AppConfigを生成する.
        configが同じHTTP URLを保持することを確認する.

        Returns:
            None: test-only HTTP metadata URL許可を検証して完了し値を返さない.
        """
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
        """未定義のmirror trust policyを拒否する契約を検証する.

        always policyを持つAppConfigを生成する.
        beatmap_mirror_trust_policyを示すValidationErrorが送出されることを確認する.

        Returns:
            None: invalid mirror trust policy拒否を検証して完了し値を返さない.
        """
        with pytest.raises(ValidationError, match="beatmap_mirror_trust_policy"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "beatmap_mirror_trust_policy": "always",
                }
            )

    def test_rejects_invalid_refresh_timing(self) -> None:
        """0以下のbeatmap ranked refresh intervalを拒否する契約を検証する.

        ranked refresh intervalを0にしたAppConfigを生成する.
        beatmap refresh intervalを示すValidationErrorが送出されることを確認する.

        Returns:
            None: invalid refresh timing拒否を検証して完了し値を返さない.
        """
        with pytest.raises(ValidationError, match="beatmap refresh intervals"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "beatmap_ranked_refresh_interval_seconds": 0,
                }
            )

    def test_rejects_default_bounded_wait_above_maximum(self) -> None:
        """Maximumを超えるdefault bounded waitを拒否する契約を検証する.

        default waitを5秒かつmaximumを1秒にしたAppConfigを生成する.
        bounded waitを示すValidationErrorが送出されることを確認する.

        Returns:
            None: inconsistent bounded wait拒否を検証して完了し値を返さない.
        """
        with pytest.raises(ValidationError, match="bounded wait"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "beatmap_default_bounded_wait_seconds": 5.0,
                    "beatmap_max_bounded_wait_seconds": 1.0,
                }
            )


class TestOsuDirectConfig:
    """osu!direct runtime policyとbackend configuration契約を検証するtest群."""

    def test_defaults_enable_authenticated_access_and_auto_search_backend(self) -> None:
        """Defaultのosu!direct設定がcredential不要のauto検索構成になることを検証する.

        必須service URLだけでAppConfigを生成する.
        access policy、search backend、bounded wait、sync interval、budgetが安全なdefaultを
        持ち、optional external index credentialを要求しないことを確認する.

        Returns:
            None: default osu!direct設定を検証して完了し値を返さない.
        """
        config = AppConfig.model_validate(
            {"database_url": _TEST_DATABASE_URL, "valkey_url": _TEST_VALKEY_URL}
        )

        assert config.osu_direct_access_policy == "authenticated"
        assert config.osu_direct_search_backend == "auto"
        assert config.osu_direct_validate_search_backend_on_startup is True
        assert config.osu_direct_external_index_backend == "disabled"
        assert config.osu_direct_meilisearch_url is None
        assert config.osu_direct_meilisearch_access_key is None
        assert config.osu_direct_point_lookup_bounded_wait_seconds == 5.0
        assert config.osu_direct_upstream_search_first_page_refresh_seconds == 300.0
        assert config.osu_direct_catalog_priority_policy == "point_lookup_first"
        assert config.osu_direct_shared_upstream_budget_per_minute == 60

        sync_intervals = {
            config.osu_direct_ranked_sync_interval_seconds,
            config.osu_direct_approved_sync_interval_seconds,
            config.osu_direct_loved_sync_interval_seconds,
            config.osu_direct_qualified_sync_interval_seconds,
            config.osu_direct_pending_sync_interval_seconds,
            config.osu_direct_wip_sync_interval_seconds,
            config.osu_direct_graveyard_sync_interval_seconds,
            config.osu_direct_not_submitted_sync_interval_seconds,
        }
        assert sync_intervals == {86_400}

    @pytest.mark.parametrize("access_policy", ["disabled", "supporter-entitlement"])
    def test_accepts_policy_modes_reserved_by_osu_direct_design(self, access_policy: str) -> None:
        """Disabledとsupporter entitlementのaccess policyを受け付けることを検証する.

        Configured policy値をAppConfigへ渡す.
        hyphen表記を含む入力がruntime用の小文字underscore表記へ正規化されることを確認する.

        Args:
            access_policy (str): 検証対象のosu!direct access policy入力値.

        Returns:
            None: access policy modeの受理と正規化を検証して完了し値を返さない.
        """
        config = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "osu_direct_access_policy": access_policy,
            }
        )

        assert config.osu_direct_access_policy == access_policy.replace("-", "_")

    def test_rejects_invalid_osu_direct_access_policy(self) -> None:
        """未定義のosu!direct access policyを拒否する契約を検証する.

        public policyをAppConfigへ渡す.
        access policy fieldを示すValidationErrorが送出されることを確認する.

        Returns:
            None: invalid access policy拒否を検証して完了し値を返さない.
        """
        with pytest.raises(ValidationError, match="osu_direct_access_policy"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "osu_direct_access_policy": "public",
                }
            )

    def test_rejects_disabled_search_backend(self) -> None:
        """未定義の検索backendを拒否する契約を検証する.

        disabledをsearch backendとしてAppConfigへ渡す.
        search backend fieldを示すValidationErrorが送出されることを確認する.

        Returns:
            None: search backendの無効化拒否を検証して完了し値を返さない.
        """
        with pytest.raises(ValidationError, match="osu_direct_search_backend"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "osu_direct_search_backend": "disabled",
                }
            )

    @pytest.mark.parametrize(
        "search_backend",
        ["auto", "paradedb", "meilisearch", "tsvector", "pg-search"],
    )
    def test_accepts_search_backend_selection(self, search_backend: str) -> None:
        """Search backend選択値を受け付けて正規化する契約を検証する.

        Configured backend値をAppConfigへ渡す.
        hyphen表記を含む入力がruntime用の小文字underscore表記へ正規化されることを確認する.

        Args:
            search_backend (str): 検証対象のsearch backend入力値.

        Returns:
            None: backend選択値の受理と正規化を検証して完了する.
        """
        payload = {
            "database_url": _TEST_DATABASE_URL,
            "valkey_url": _TEST_VALKEY_URL,
            "osu_direct_search_backend": search_backend,
        }
        if search_backend == "meilisearch":
            payload.update(
                {
                    "environment": "test",
                    "osu_direct_external_index_backend": "meilisearch",
                    "osu_direct_meilisearch_url": "http://meilisearch.test:7700",
                }
            )
        config = AppConfig.model_validate(payload)

        expected = "paradedb" if search_backend == "pg-search" else search_backend
        assert config.osu_direct_search_backend == expected

    def test_accepts_legacy_sql_search_backend_alias(self) -> None:
        """旧SQL backend設定名をsearch backend互換aliasとして読むことを検証する.

        旧field名でAppConfigへ値を渡す.
        新しいsearch backend fieldへ値が正規化されて入ることを確認する.

        Returns:
            None: legacy aliasの互換読込を検証して完了する.
        """
        config = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "osu_direct_sql_search_backend": "pg-search",
                "osu_direct_validate_sql_search_backend_on_startup": False,
            }
        )

        assert config.osu_direct_search_backend == "paradedb"
        assert config.osu_direct_validate_search_backend_on_startup is False

    def test_accepts_meilisearch_external_index_settings_without_access_key(self) -> None:
        """Optional Meilisearch設定がaccess keyなしでも構成できることを検証する.

        test environmentでMeilisearch backendとHTTP URLをAppConfigへ渡す.
        backend、URL、index名が保持され、external credentialを要求しないことを確認する.

        Returns:
            None: optional external index設定を検証して完了し値を返さない.
        """
        config = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "environment": "test",
                "osu_direct_external_index_backend": "meilisearch",
                "osu_direct_meilisearch_url": "http://meilisearch.test:7700",
                "osu_direct_meilisearch_index_name": "direct-test",
            }
        )

        assert config.osu_direct_external_index_backend == "meilisearch"
        assert config.osu_direct_meilisearch_url == "http://meilisearch.test:7700"
        assert config.osu_direct_meilisearch_access_key is None
        assert config.osu_direct_meilisearch_index_name == "direct-test"

    def test_rejects_meilisearch_backend_without_url(self) -> None:
        """Meilisearch backend有効時に接続URLを必須にする契約を検証する.

        URLなしでMeilisearch backendをAppConfigへ渡す.
        meilisearch URL要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: missing Meilisearch URL拒否を検証して完了し値を返さない.
        """
        with pytest.raises(ValidationError, match="osu_direct_meilisearch_url"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "osu_direct_external_index_backend": "meilisearch",
                }
            )

    def test_rejects_insecure_meilisearch_url_outside_test(self) -> None:
        """Test以外でHTTP Meilisearch URLを拒否する契約を検証する.

        productionでHTTP Meilisearch URLをAppConfigへ渡す.
        HTTPS要件を示すValidationErrorが送出されることを確認する.

        Returns:
            None: insecure Meilisearch URL拒否を検証して完了し値を返さない.
        """
        with pytest.raises(ValidationError, match="HTTPS"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "environment": "production",
                    "osu_direct_external_index_backend": "meilisearch",
                    "osu_direct_meilisearch_url": "http://meilisearch.local:7700",
                }
            )

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("osu_direct_point_lookup_bounded_wait_seconds", 0),
            ("osu_direct_upstream_search_first_page_refresh_seconds", 0),
            ("osu_direct_ranked_sync_interval_seconds", 0),
            ("osu_direct_shared_upstream_budget_per_minute", 0),
        ],
    )
    def test_rejects_non_positive_osu_direct_runtime_values(
        self, field_name: str, value: int
    ) -> None:
        """正数が必要なosu!direct runtime設定の0以下を拒否する契約を検証する.

        対象fieldへ0を渡してAppConfigを生成する.
        osu!direct runtime valueのValidationErrorが送出されることを確認する.

        Args:
            field_name (str): 0を設定するAppConfig field名.
            value (int): validationで拒否される非正数値.

        Returns:
            None: non-positive runtime設定拒否を検証して完了し値を返さない.
        """
        with pytest.raises(ValidationError, match="osu_direct runtime values"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    field_name: value,
                }
            )

    def test_load_config_reads_osu_direct_environment_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """osu!direct環境変数がload_configでAppConfigへ反映される契約を検証する.

        必須service URLとosu!direct関連環境変数を設定してload_configを実行する.
        文字列環境変数が正しい型と正規化済み値として保持されることを確認する.

        Args:
            monkeypatch (pytest.MonkeyPatch): test用環境変数を設定するpytest helper.

        Returns:
            None: osu!direct environment読込を検証して完了し値を返さない.
        """
        monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
        monkeypatch.setenv("VALKEY_URL", _TEST_VALKEY_URL)
        monkeypatch.setenv("OSU_DIRECT_ACCESS_POLICY", "DISABLED")
        monkeypatch.setenv("OSU_DIRECT_EXTERNAL_INDEX_BACKEND", "MEILISEARCH")
        monkeypatch.setenv("OSU_DIRECT_MEILISEARCH_URL", "https://meilisearch.example.com")
        monkeypatch.setenv("OSU_DIRECT_POINT_LOOKUP_BOUNDED_WAIT_SECONDS", "2.5")
        monkeypatch.setenv("OSU_DIRECT_UPSTREAM_SEARCH_FIRST_PAGE_REFRESH_SECONDS", "120")
        monkeypatch.setenv("OSU_DIRECT_SHARED_UPSTREAM_BUDGET_PER_MINUTE", "30")

        config = load_config()

        assert config.osu_direct_access_policy == "disabled"
        assert config.osu_direct_external_index_backend == "meilisearch"
        assert config.osu_direct_meilisearch_url == "https://meilisearch.example.com"
        assert config.osu_direct_point_lookup_bounded_wait_seconds == 2.5
        assert config.osu_direct_upstream_search_first_page_refresh_seconds == 120.0
        assert config.osu_direct_shared_upstream_budget_per_minute == 30


class TestAppConfigQueryDiagnostics:
    """SQL query diagnosticsのeffective defaultとthreshold validation契約を検証するtest群."""

    def test_query_diagnostics_enabled_by_default_in_development(self) -> None:
        """Developmentでquery diagnosticsがdefault有効となる契約を検証する.

        Overrideなしのdevelopment AppConfigを生成する.
        effective enabled flagがTrueとなることを確認する.

        Returns:
            None: development diagnostics defaultを検証して完了し値を返さない.
        """
        config = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "environment": "development",
            }
        )

        assert config.query_diagnostics_effective_enabled is True

    def test_query_diagnostics_disabled_by_default_outside_development(self) -> None:
        """Productionとtestでquery diagnosticsがdefault無効となる契約を検証する.

        Overrideなしのproductionとtest AppConfigを生成する.
        両effective enabled flagがFalseとなることを確認する.

        Returns:
            None: non-development diagnostics defaultを検証して完了し値を返さない.
        """
        production = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "environment": "production",
            }
        )
        test = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "environment": "test",
            }
        )

        assert production.query_diagnostics_effective_enabled is False
        assert test.query_diagnostics_effective_enabled is False

    def test_query_diagnostics_enabled_override_is_respected(self) -> None:
        """Explicit query diagnostics overrideがenvironment defaultより優先する契約を検証する.

        enabled overrideを持つproduction AppConfigを生成する.
        effective enabled flagがTrueとなることを確認する.

        Returns:
            None: diagnostics explicit overrideを検証して完了し値を返さない.
        """
        config = AppConfig.model_validate(
            {
                "database_url": _TEST_DATABASE_URL,
                "valkey_url": _TEST_VALKEY_URL,
                "environment": "production",
                "query_diagnostics_enabled": True,
            }
        )

        assert config.query_diagnostics_effective_enabled is True

    def test_query_diagnostics_thresholds_must_be_positive(self) -> None:
        """Query diagnostics thresholdが正数だけを受け付ける契約を検証する.

        query countとduplicate thresholdをそれぞれ0にしたAppConfigを生成する.
        両方でthreshold validation errorが送出されることを確認する.

        Returns:
            None: diagnostics threshold validationを検証して完了し値を返さない.
        """
        with pytest.raises(ValidationError, match="query diagnostics thresholds"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "query_diagnostics_max_queries": 0,
                }
            )

        with pytest.raises(ValidationError, match="query diagnostics thresholds"):
            _ = AppConfig.model_validate(
                {
                    "database_url": _TEST_DATABASE_URL,
                    "valkey_url": _TEST_VALKEY_URL,
                    "query_diagnostics_duplicate_threshold": 0,
                }
            )
