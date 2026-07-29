"""PacketDispatcher の provider registration と stable Bancho public API を検証する."""

import pytest

from osu_server.composition.providers.container import make_app_container
from osu_server.composition.providers.test import make_in_memory_runtime_provider_set
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from tests.factories.config import make_app_config


class TestDispatcherModuleInstance:
    """module-level dispatcher instance の型と singleton 性を検証する."""

    def test_module_level_dispatcher_exists(self) -> None:
        """Dispatch module が PacketDispatcher instance を公開することを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        from osu_server.transports.stable.bancho.dispatch import dispatcher

        assert isinstance(dispatcher, PacketDispatcher)

    def test_module_level_dispatcher_is_singleton_instance(self) -> None:
        """Dispatch module の dispatcher attribute が同一 instance を参照することを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        from osu_server.transports.stable.bancho import dispatch

        assert hasattr(dispatch, "dispatcher")
        assert dispatch.dispatcher is dispatch.dispatcher  # same object


class TestBanchoPublicAPI:
    """stable.bancho package が dispatcher public API を再公開することを検証する."""

    def test_reexports_packet_dispatcher_class(self) -> None:
        """Package が PacketDispatcher class を同じ object として再公開することを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        from osu_server.transports.stable.bancho import PacketDispatcher as ReExported

        assert ReExported is PacketDispatcher

    def test_reexports_dispatcher_instance(self) -> None:
        """Package が module-level dispatcher instance を再公開することを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        from osu_server.transports.stable.bancho import dispatcher as re_exported
        from osu_server.transports.stable.bancho.dispatch import dispatcher

        assert re_exported is dispatcher

    def test_all_includes_dispatcher_names(self) -> None:
        """Package の __all__ が dispatcher public API 名を含むことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        from osu_server.transports.stable import bancho

        assert "PacketDispatcher" in bancho.__all__
        assert "dispatcher" in bancho.__all__


class TestDIRegistration:
    """Dishka app container が registration 済み PacketDispatcher を解決することを検証する."""

    @pytest.mark.asyncio
    async def test_resolve_packet_dispatcher(self) -> None:
        """in-memory app container が PacketDispatcher を解決することを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
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
        """同じ app container の PacketDispatcher が singleton であることを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
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
        """Container が解決した dispatcher に STATUS_CHANGE handler が登録されることを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
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
        """Container が解決した dispatcher に両方の presence handler が登録されることを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
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
