from __future__ import annotations

from datetime import UTC, datetime

from pydantic import PostgresDsn, RedisDsn

# まだ作成していないモジュールからインポートして、わざとエラーにする (RED 状態を作るため)
from tests.factories.config import make_app_config
from tests.factories.domain import make_channel, make_channel_role_override, make_user

from osu_server.config import AppConfig
from osu_server.domain.channel import Channel, ChannelRoleOverride, ChannelType
from osu_server.domain.user import User


def test_make_channel_creates_with_defaults() -> None:
    channel = make_channel()
    assert isinstance(channel, Channel)
    assert channel.id == 1
    assert channel.name == "#osu"
    assert channel.channel_type == ChannelType.PUBLIC
    assert channel.auto_join is True
    assert isinstance(channel.created_at, datetime)
    assert isinstance(channel.updated_at, datetime)


def test_make_channel_allows_overrides() -> None:
    custom_time = datetime.now(UTC)
    channel = make_channel(
        id=42,
        name="#announcements",
        topic="Official news",
        channel_type=ChannelType.TEMPORARY,
        auto_join=False,
        rate_limit_messages=5,
        rate_limit_window=10,
        created_at=custom_time,
        updated_at=custom_time,
    )
    assert channel.id == 42
    assert channel.name == "#announcements"
    assert channel.topic == "Official news"
    assert channel.channel_type == ChannelType.TEMPORARY
    assert channel.auto_join is False
    assert channel.rate_limit_messages == 5
    assert channel.rate_limit_window == 10
    assert channel.created_at == custom_time
    assert channel.updated_at == custom_time


def test_make_channel_role_override() -> None:
    override = make_channel_role_override(
        channel_id=10,
        role_id=20,
        can_read=False,
        can_write=False,
    )
    assert isinstance(override, ChannelRoleOverride)
    assert override.channel_id == 10
    assert override.role_id == 20
    assert override.can_read is False
    assert override.can_write is False


def test_make_user_creates_with_defaults() -> None:
    user = make_user()
    assert isinstance(user, User)
    assert user.id == 1
    assert user.username == "TestUser"
    assert user.safe_username == "testuser"
    assert isinstance(user.created_at, datetime)


def test_make_user_allows_overrides() -> None:
    custom_time = datetime.now(UTC)
    user = make_user(
        id=99,
        username="Cool Gamer",
        safe_username="cool_gamer",
        email="gamer@example.com",
        password_hash="hashed_pw",
        country="US",
        created_at=custom_time,
        updated_at=custom_time,
    )
    assert user.id == 99
    assert user.username == "Cool Gamer"
    assert user.safe_username == "cool_gamer"
    assert user.email == "gamer@example.com"
    assert user.password_hash == "hashed_pw"
    assert user.country == "US"
    assert user.created_at == custom_time
    assert user.updated_at == custom_time


def test_make_app_config_creates_with_defaults() -> None:
    config = make_app_config()
    assert isinstance(config, AppConfig)
    assert isinstance(config.database_url, PostgresDsn)
    assert isinstance(config.valkey_url, RedisDsn)
    assert config.environment == "development"
    assert config.beatmap_official_sources_enabled is True
    assert config.beatmap_official_api_client_id == "test-client-id"
    assert config.beatmap_official_api_client_secret == "test-client-secret"
    assert config.beatmap_mirror_trust_policy == "untrusted"


def test_make_app_config_allows_overrides() -> None:
    config = make_app_config(
        database_url="postgresql+asyncpg://prod_db:pass@host/prod",
        valkey_url="redis://valkey_host:6379/1",
        environment="production",
        server_port=9000,
        log_level="DEBUG",
        beatmap_community_mirror_url_templates=["https://mirror.example.com/osu/{beatmap_id}"],
    )
    assert str(config.database_url) == "postgresql+asyncpg://prod_db:pass@host/prod"
    assert str(config.valkey_url) == "redis://valkey_host:6379/1"
    assert config.environment == "production"
    assert config.server_port == 9000
    assert config.log_level == "DEBUG"
    assert config.beatmap_community_mirror_url_templates == [
        "https://mirror.example.com/osu/{beatmap_id}"
    ]
