"""Tests for service registry composition — endpoint graph wiring."""

from __future__ import annotations

import pytest

from osu_server.composition.service_registry import register_services
from osu_server.config import AppConfig
from osu_server.infrastructure.di.providers import build_container
from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.endpoint import BanchoEndpoint
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.workflows.login import LoginWorkflow
from osu_server.transports.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)
from osu_server.transports.bancho.workflows.polling import PollingWorkflow


def _make_config(*, environment: str = "test") -> AppConfig:
    return AppConfig.model_validate(
        {
            "database_url": "postgresql://test:test@localhost:5432/test",
            "valkey_url": "redis://localhost:6379/0",
            "environment": environment,
        },
    )


@pytest.mark.asyncio
async def test_register_services_binds_bancho_endpoint_graph() -> None:
    """register_services builds the full endpoint graph without manual wiring.

    Every component in the bancho endpoint graph is resolvable from the
    container, endpoint-internal workflow references are the same instances
    returned by the container, and the polling dispatcher carries the
    C2S handlers registered during composition.
    """
    config = _make_config()
    container = await build_container(config)
    await register_services(container, config)

    endpoint = await container.resolve(BanchoEndpoint)
    login_workflow = await container.resolve(LoginWorkflow)
    polling_workflow = await container.resolve(PollingWorkflow)
    response_builder = await container.resolve(LoginResponseBuilder)
    dispatcher = await container.resolve(PacketDispatcher)

    assert isinstance(endpoint, BanchoEndpoint)
    assert isinstance(login_workflow, LoginWorkflow)
    assert isinstance(polling_workflow, PollingWorkflow)
    assert isinstance(response_builder, LoginResponseBuilder)
    assert isinstance(dispatcher, PacketDispatcher)

    # No manual wiring — endpoint holds container-resolved instances
    assert endpoint._login_workflow is login_workflow  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert endpoint._polling_workflow is polling_workflow  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    # Polling dispatcher is the same instance that received handler registrations
    assert polling_workflow._packet_dispatcher is dispatcher  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert ClientPacketID.SEND_MESSAGE in dispatcher.get_handlers()
    assert ClientPacketID.JOIN_CHANNEL in dispatcher.get_handlers()
