"""Tests for PacketDispatcher provider registration and stable bancho public API."""

import pytest

from osu_server.composition.providers.container import make_app_container
from osu_server.composition.providers.test import make_in_memory_runtime_provider_set
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from tests.factories.config import make_app_config


class TestDispatcherModuleInstance:
    """Module-level dispatcher instance exists and is PacketDispatcher."""

    def test_module_level_dispatcher_exists(self) -> None:
        from osu_server.transports.stable.bancho.dispatch import dispatcher

        assert isinstance(dispatcher, PacketDispatcher)

    def test_module_level_dispatcher_is_singleton_instance(self) -> None:
        from osu_server.transports.stable.bancho import dispatch

        assert hasattr(dispatch, "dispatcher")
        assert dispatch.dispatcher is dispatch.dispatcher  # same object


class TestBanchoPublicAPI:
    """stable/bancho/__init__.py re-exports PacketDispatcher and dispatcher."""

    def test_reexports_packet_dispatcher_class(self) -> None:
        from osu_server.transports.stable.bancho import PacketDispatcher as ReExported

        assert ReExported is PacketDispatcher

    def test_reexports_dispatcher_instance(self) -> None:
        from osu_server.transports.stable.bancho import dispatcher as re_exported
        from osu_server.transports.stable.bancho.dispatch import dispatcher

        assert re_exported is dispatcher

    def test_all_includes_dispatcher_names(self) -> None:
        from osu_server.transports.stable import bancho

        assert "PacketDispatcher" in bancho.__all__
        assert "dispatcher" in bancho.__all__


class TestDIRegistration:
    """PacketDispatcher can be resolved via the Dishka app container."""

    @pytest.mark.asyncio
    async def test_resolve_packet_dispatcher(self) -> None:
        config = make_app_config(environment="test")
        container = make_app_container(
            config,
            overrides=(make_in_memory_runtime_provider_set(),),
        )

        try:
            resolved = await container.get(PacketDispatcher)
            assert isinstance(resolved, PacketDispatcher)
        finally:
            await container.close()

    @pytest.mark.asyncio
    async def test_resolve_returns_same_singleton(self) -> None:
        config = make_app_config(environment="test")
        container = make_app_container(
            config,
            overrides=(make_in_memory_runtime_provider_set(),),
        )

        try:
            first = await container.get(PacketDispatcher)
            second = await container.get(PacketDispatcher)
            assert first is second
        finally:
            await container.close()

    @pytest.mark.asyncio
    async def test_resolved_dispatcher_registers_status_change_handler(self) -> None:
        config = make_app_config(environment="test")
        container = make_app_container(
            config,
            overrides=(make_in_memory_runtime_provider_set(),),
        )

        try:
            dispatcher = await container.get(PacketDispatcher)
            assert ClientPacketID.STATUS_CHANGE in dispatcher.get_handlers()
        finally:
            await container.close()

    @pytest.mark.asyncio
    async def test_resolved_dispatcher_registers_presence_handlers(self) -> None:
        config = make_app_config(environment="test")
        container = make_app_container(
            config,
            overrides=(make_in_memory_runtime_provider_set(),),
        )

        try:
            dispatcher = await container.get(PacketDispatcher)
            handlers = dispatcher.get_handlers()
            assert ClientPacketID.PRESENCE_REQUEST in handlers
            assert ClientPacketID.PRESENCE_REQUEST_ALL in handlers
        finally:
            await container.close()
