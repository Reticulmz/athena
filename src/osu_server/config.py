"""pydantic-settingsを使用してAthenaの環境設定を検証する.

環境変数と環境別`.env` fileから設定を読み込み、起動前に型と運用上の制約を検証する.
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
_DEVELOPMENT_ENVIRONMENT = "development"
_BEATMAP_URL_TEMPLATE_FIELD = "beatmap_id"
_DEFAULT_ENVIRONMENT = "development"
_ENVIRONMENT_VARIABLE = "ENVIRONMENT"
type _BeatmapUrlTemplateField = tuple[str, str | None, str | None]


class AppConfig(BaseSettings):
    """環境変数から読み込むAthena applicationの型安全な設定を表す.

    Attributes:
        database_url (PostgresDsn): PostgreSQLへの接続DSN.
        valkey_url (ValkeyDsn): Valkeyへの接続DSN.
        environment (str): 実行環境名. 未指定時はdevelopment.
        server_host (str): ASGI serverがlistenするhost.
        server_port (int): ASGI serverがlistenするport.
        domain (str): host-based routingに使用する基本domain.
        banned_passwords (list[str]): password変更時に拒否するpassword一覧.
        session_ttl (int): sessionをValkeyに保持する秒数.
        packet_queue_max_size (int): user別packet queueの最大要素数.
        max_request_body_size (int): HTTP request bodyの最大byte数.
        score_submit_max_replay_size (int): score submission replayの最大byte数.
        score_submit_max_text_field_size (int): score submission text fieldの最大byte数.
        message_max_length (int): chat messageの最大文字数.
        rate_limit_messages (int): rate limit window内で許可するmessage数.
        rate_limit_window (int): chat rate limitを集計する秒数.
        bancho_bot_username (str): system BanchoBotに割り当てるusername.
        log_level (str): loggingに使用する正規化済みlevel.
        log_dir (str): log fileを出力するdirectory.
        log_max_files (int): rotation後に保持するlog file数.
        query_diagnostics_enabled (bool | None): SQL query diagnosticsの明示設定.
        query_diagnostics_max_queries (int): diagnostic logに含める最大query数.
        query_diagnostics_duplicate_threshold (int): duplicate query warningの閾値.
        blob_storage_backend (str): blob storage backend名. localまたはs3.
        blob_storage_local_root (str): local blob storageのroot path.
        blob_storage_s3_bucket (str | None): S3 backendのbucket名.
        blob_storage_s3_region (str | None): S3 backendのregion名.
        blob_storage_s3_endpoint (str | None): S3互換endpoint URL.
        blob_storage_s3_access_key (str | None): S3 backendのaccess key.
        blob_storage_s3_secret_key (str | None): S3 backendのsecret key.
        beatmap_official_sources_enabled (bool): official beatmap sourceを使用するか.
        beatmap_official_api_client_id (str | None): official API client ID.
        beatmap_official_api_client_secret (str | None): official API client secret.
        beatmap_mirror_trust_policy (str): mirrorをtrustedとして扱うかを表すpolicy.
        beatmap_osu_current_url_template (str): current osu! beatmap file URL template.
        beatmap_osu_legacy_url_template (str): legacy osu! beatmap file URL template.
        beatmap_community_mirror_url_templates (list[str]): community mirror URL template一覧.
        beatmap_metadata_mirror_base_urls (list[str]): beatmap metadata mirror base URL一覧.
        beatmap_ranked_refresh_interval_seconds (int): ranked beatmap更新間隔の秒数.
        beatmap_pending_refresh_interval_seconds (int): pending beatmap更新間隔の秒数.
        beatmap_graveyard_refresh_interval_seconds (int): graveyard beatmap更新間隔の秒数.
        beatmap_mirror_refresh_interval_seconds (int): mirror情報更新間隔の秒数.
        beatmap_default_bounded_wait_seconds (float): beatmap取得時の標準待機時間の秒数.
        beatmap_max_bounded_wait_seconds (float): beatmap取得時に許可する最大待機時間の秒数.
        model_config (ClassVar[SettingsConfigDict]): environment variableを直接読むSettings設定.

    Notes:
        `database_url`と`valkey_url`は必須であり、各validatorがbackend、URL、intervalの
        実行前制約を検証する.
    """

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
    query_diagnostics_enabled: bool | None = None
    query_diagnostics_max_queries: int = 20
    query_diagnostics_duplicate_threshold: int = 2

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
    beatmap_default_bounded_wait_seconds: float = 3.0
    beatmap_max_bounded_wait_seconds: float = 3.0

    @property
    def query_diagnostics_effective_enabled(self) -> bool:
        """実行時SQL query diagnosticsの有効状態を返す.

        Returns:
            bool: 明示設定がある場合はその値. 未設定の場合はdevelopment環境だけtrue.
        """
        if self.query_diagnostics_enabled is not None:
            return self.query_diagnostics_enabled
        return self.environment.lower() == _DEVELOPMENT_ENVIRONMENT

    @field_validator("blob_storage_backend")
    @classmethod
    def _validate_blob_storage_backend(cls, v: str) -> str:
        """保存backend名を正規化して許可値を検証する.

        Args:
            v (str): environmentから読み込んだbackend名.

        Returns:
            str: 小文字化済みの`local`または`s3`.

        Raises:
            ValueError: backend名が`local`または`s3`以外の場合.
        """
        valid = frozenset({"local", "s3"})
        lower = v.lower()
        if lower not in valid:
            msg = f"Invalid blob_storage_backend: {v!r}. Valid: local, s3"
            raise ValueError(msg)
        return lower

    @field_validator("beatmap_mirror_trust_policy")
    @classmethod
    def _validate_beatmap_mirror_trust_policy(cls, v: str) -> str:
        """譜面mirror trust policyを正規化して許可値を検証する.

        Args:
            v (str): environmentから読み込んだtrust policy名.

        Returns:
            str: 小文字化済みの`trusted`または`untrusted`.

        Raises:
            ValueError: trust policy名が許可値以外の場合.
        """
        valid = frozenset({"trusted", "untrusted"})
        lower = v.lower()
        if lower not in valid:
            msg = f"Invalid beatmap_mirror_trust_policy: {v!r}. Valid: trusted, untrusted"
            raise ValueError(msg)
        return lower

    @field_validator("log_max_files")
    @classmethod
    def _validate_log_max_files(cls, v: int) -> int:
        """保持するlog file数が非負であることを検証する.

        Args:
            v (int): environmentから読み込んだ保持数.

        Returns:
            int: 検証済みの保持数.

        Raises:
            ValueError: 保持数が0未満の場合.
        """
        if v < 0:
            msg = f"log_max_files must be greater than or equal to 0, got {v}"
            raise ValueError(msg)
        return v

    @field_validator("query_diagnostics_max_queries", "query_diagnostics_duplicate_threshold")
    @classmethod
    def _validate_query_diagnostics_thresholds(cls, v: int) -> int:
        """SQL query diagnosticsの閾値が正であることを検証する.

        Args:
            v (int): 最大query数またはduplicate検出閾値.

        Returns:
            int: 検証済みの正の閾値.

        Raises:
            ValueError: 閾値が1未満の場合.
        """
        if v < 1:
            msg = "query diagnostics thresholds must be greater than 0"
            raise ValueError(msg)
        return v

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        """記録levelを大文字化して許可値を検証する.

        Args:
            v (str): environmentから読み込んだlogging level.

        Returns:
            str: 大文字化済みの許可されたlogging level.

        Raises:
            ValueError: levelがDEBUG、INFO、WARNING、ERROR、CRITICAL以外の場合.
        """
        valid = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
        upper = v.upper()
        if upper not in valid:
            msg = f"Invalid log level: {v!r}. Valid: DEBUG, INFO, WARNING, ERROR, CRITICAL"
            raise ValueError(msg)
        return upper

    @field_validator("bancho_bot_username")
    @classmethod
    def _validate_bancho_bot_username(cls, v: str) -> str:
        """BanchoBot usernameの文字数と使用可能文字を検証する.

        Args:
            v (str): environmentから読み込んだBanchoBot username.

        Returns:
            str: 検証済みのusername.

        Raises:
            ValueError: usernameが2から15文字の範囲外、または英数字、space、underscore、
                hyphen以外を含む場合.
        """
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
        """URL list設定をJSON arrayまたはcomma-separated textから復元する.

        Args:
            v (object): Pydanticがvalidatorへ渡した未加工の設定値.

        Returns:
            object: 文字列以外はそのまま、空文字列は空list、JSONまたはcomma-separated
                textは`list[str]`へ変換した値.

        Raises:
            pydantic.ValidationError: JSON arrayとして解釈する値が不正な場合.
        """
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
        """譜面sourceとmirror設定の相互制約を検証する.

        Returns:
            Self: 全fieldの相互制約を検証済みの設定instance.

        Raises:
            ValueError: official source credential、URL、refresh interval、bounded waitの
                いずれかが運用上の制約を満たさない場合.
        """
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
        """譜面file URL templateのplaceholderとURL制約を検証する.

        Args:
            template (str): `{beatmap_id}`を含むURL template.
            field_name (str): validation errorで表示する設定field名.
            environment (str): HTTP URLを許可するか判断する実行環境名.

        Returns:
            None: templateを検証するだけで値を返さないことを示す.

        Raises:
            ValueError: template構文、placeholder、または生成後URLが制約を満たさない場合.
        """
        parsed_fields = AppConfig._parse_beatmap_url_template_fields(
            template,
            field_name=field_name,
        )
        AppConfig._validate_beatmap_url_template_fields(
            parsed_fields,
            field_name=field_name,
        )
        candidate = AppConfig._render_beatmap_url_template_candidate(
            template,
            field_name=field_name,
        )
        AppConfig._validate_beatmap_http_url(
            candidate,
            field_name=field_name,
            environment=environment,
            absolute_url_label="URL template",
        )

    @staticmethod
    def _parse_beatmap_url_template_fields(
        template: str,
        *,
        field_name: str,
    ) -> tuple[_BeatmapUrlTemplateField, ...]:
        """URL templateからplaceholder、conversion、format specificationを抽出する.

        Args:
            template (str): 解析するURL template.
            field_name (str): validation errorで表示する設定field名.

        Returns:
            tuple[_BeatmapUrlTemplateField, ...]: templateに含まれるplaceholder情報.

        Raises:
            ValueError: `string.Formatter`で解析できないtemplateの場合.
        """
        try:
            parsed_template = tuple(Formatter().parse(template))
        except ValueError as exc:
            msg = f"{field_name} must be a valid URL template"
            raise ValueError(msg) from exc

        return tuple(
            (placeholder, conversion, format_spec)
            for _, placeholder, format_spec, conversion in parsed_template
            if placeholder is not None
        )

    @staticmethod
    def _validate_beatmap_url_template_fields(
        parsed_fields: tuple[_BeatmapUrlTemplateField, ...],
        *,
        field_name: str,
    ) -> None:
        """抽出済みURL template fieldがbeatmap ID専用であることを検証する.

        Args:
            parsed_fields (tuple[_BeatmapUrlTemplateField, ...]): templateから抽出した
                placeholder情報.
            field_name (str): validation errorで表示する設定field名.

        Returns:
            None: fieldを検証するだけで値を返さないことを示す.

        Raises:
            ValueError: `{beatmap_id}`がちょうど1個でない、または未対応placeholderを
                含む場合.
        """
        beatmap_id_fields = tuple(
            field for field in parsed_fields if field[0] == _BEATMAP_URL_TEMPLATE_FIELD
        )
        AppConfig._validate_single_beatmap_id_template_field(
            beatmap_id_fields,
            field_name=field_name,
        )

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

    @staticmethod
    def _validate_single_beatmap_id_template_field(
        beatmap_id_fields: tuple[_BeatmapUrlTemplateField, ...],
        *,
        field_name: str,
    ) -> None:
        """譜面ID placeholderが無変換で1個だけ存在することを検証する.

        Args:
            beatmap_id_fields (tuple[_BeatmapUrlTemplateField, ...]): `beatmap_id`だけを
                抽出したplaceholder情報.
            field_name (str): validation errorで表示する設定field名.

        Returns:
            None: placeholderを検証するだけで値を返さないことを示す.

        Raises:
            ValueError: placeholder数が1以外、またはconversion/format specificationを
                指定している場合.
        """
        if len(beatmap_id_fields) != 1:
            msg = f"{field_name} must include exactly one {_BEATMAP_URL_TEMPLATE_TOKEN}"
            raise ValueError(msg)
        _, conversion, format_spec = beatmap_id_fields[0]
        if conversion or format_spec:
            msg = f"{field_name} must use exactly {_BEATMAP_URL_TEMPLATE_TOKEN}"
            raise ValueError(msg)

    @staticmethod
    def _render_beatmap_url_template_candidate(
        template: str,
        *,
        field_name: str,
    ) -> str:
        """検証用beatmap IDをURL templateへ適用して候補URLを生成する.

        Args:
            template (str): `{beatmap_id}`を含む検証済みのURL template.
            field_name (str): validation errorで表示する設定field名.

        Returns:
            str: beatmap ID `1`を適用した候補URL.

        Raises:
            ValueError: templateのformat処理が失敗した場合.

        Notes:
            呼出前に`_validate_beatmap_url_template_fields()`でfieldを検証していることを
            前提とする.
        """
        try:
            return template.format(beatmap_id=1)
        except ValueError as exc:
            msg = f"{field_name} must be a valid URL template"
            raise ValueError(msg) from exc

    @staticmethod
    def _validate_beatmap_http_url(
        value: str,
        *,
        field_name: str,
        environment: str,
        absolute_url_label: str,
    ) -> None:
        """絶対HTTP/HTTPS URLと環境別scheme制約を検証する.

        Args:
            value (str): 検証するURLまたはtemplateから生成した候補URL.
            field_name (str): validation errorで表示する設定field名.
            environment (str): test環境以外でHTTPSを必須化する実行環境名.
            absolute_url_label (str): error messageでURLの用途を示す表示名.

        Returns:
            None: URLを検証するだけで値を返さないことを示す.

        Raises:
            ValueError: URLがabsoluteでない、HTTP/HTTPS以外、またはtest以外でHTTPの場合.
        """
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            msg = f"{field_name} must be an absolute {absolute_url_label}"
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
        """譜面metadata mirrorのbase URLを検証する.

        Args:
            base_url (str): 検証するmetadata mirrorのbase URL.
            field_name (str): validation errorで表示する設定field名.
            environment (str): test環境以外でHTTPSを必須化する実行環境名.

        Returns:
            None: base URLを検証するだけで値を返さないことを示す.

        Raises:
            ValueError: base URLが`_validate_beatmap_http_url()`の制約を満たさない場合.
        """
        AppConfig._validate_beatmap_http_url(
            base_url,
            field_name=field_name,
            environment=environment,
            absolute_url_label="URL",
        )

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="")


class RoutingConfig(BaseSettings):
    """application lifespan開始前に必要なrouting設定を表す.

    Attributes:
        environment (str): 実行環境名. 未指定時はdevelopment.
        domain (str): host-based routingに使用する基本domain.
        model_config (ClassVar[SettingsConfigDict]): 未知の設定を無視してenvironment variableを
            直接読むSettings設定.
    """

    environment: str = "development"
    domain: str = "athena.localhost"

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
    )


def load_config() -> AppConfig:
    """環境変数と環境別`.env` fileから完全なapplication設定を読み込む.

    Returns:
        AppConfig: PostgreSQL、Valkey、runtime設定を検証済みのconfiguration.

    Raises:
        pydantic.ValidationError: 必須設定またはfield間の制約が満たされない場合.

    Notes:
        `ENVIRONMENT`を小文字化して`.env.<environment>`を選び、未指定時はdevelopmentを使う.
    """
    environment = os.environ.get(_ENVIRONMENT_VARIABLE, _DEFAULT_ENVIRONMENT).lower()
    return AppConfig(_env_file=f".env.{environment}")  # pyright: ignore[reportCallIssue]


def load_routing_config() -> RoutingConfig:
    """完全なapplication起動前にrouting設定だけを読み込む.

    Returns:
        RoutingConfig: host-based routingに必要なenvironmentとdomainを含む設定.

    Notes:
        `ENVIRONMENT`を小文字化して`.env.<environment>`を選び、DB/Valkeyの必須設定は
        この段階で検証しない.
    """
    environment = os.environ.get(_ENVIRONMENT_VARIABLE, _DEFAULT_ENVIRONMENT).lower()
    return RoutingConfig(_env_file=f".env.{environment}")  # pyright: ignore[reportCallIssue]
