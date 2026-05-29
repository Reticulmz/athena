"""Tests for PacketDispatcher DI registration and bancho public API.

Validates:
- Task 5.1: モジュールレベルの dispatcher インスタンスが存在する
- Task 5.1: PacketDispatcher を DI コンテナにシングルトン登録・resolve できる
- Task 5.1: bancho パッケージから PacketDispatcher/dispatcher を re-export する
"""

from osu_server.infrastructure.di.container import Container
from osu_server.transports.bancho.dispatch import PacketDispatcher


class TestDispatcherModuleInstance:
    """Module-level dispatcher instance exists and is PacketDispatcher."""

    def test_module_level_dispatcher_exists(self) -> None:
        from osu_server.transports.bancho.dispatch import dispatcher

        assert isinstance(dispatcher, PacketDispatcher)

    def test_module_level_dispatcher_is_singleton_instance(self) -> None:
        from osu_server.transports.bancho import dispatch

        assert hasattr(dispatch, "dispatcher")
        assert dispatch.dispatcher is dispatch.dispatcher  # same object


class TestBanchoPublicAPI:
    """bancho/__init__.py re-exports PacketDispatcher and dispatcher."""

    def test_reexports_packet_dispatcher_class(self) -> None:
        from osu_server.transports.bancho import PacketDispatcher as ReExported

        assert ReExported is PacketDispatcher

    def test_reexports_dispatcher_instance(self) -> None:
        from osu_server.transports.bancho import dispatcher as re_exported
        from osu_server.transports.bancho.dispatch import dispatcher

        assert re_exported is dispatcher

    def test_all_includes_dispatcher_names(self) -> None:
        from osu_server.transports import bancho

        assert "PacketDispatcher" in bancho.__all__
        assert "dispatcher" in bancho.__all__


class TestDIRegistration:
    """PacketDispatcher can be registered and resolved via DI Container."""

    async def test_resolve_packet_dispatcher(self) -> None:
        container = Container()
        dp = PacketDispatcher()
        container.register_singleton(PacketDispatcher, lambda: dp)

        resolved = await container.resolve(PacketDispatcher)
        assert resolved is dp

    async def test_resolve_returns_same_singleton(self) -> None:
        container = Container()
        dp = PacketDispatcher()
        container.register_singleton(PacketDispatcher, lambda: dp)

        first = await container.resolve(PacketDispatcher)
        second = await container.resolve(PacketDispatcher)
        assert first is second
